# ruff: noqa: F403, F405
# This module historically relies on a large set of globals/helpers from ViewsBase.
from app.views.ViewsBase import *  # NOSONAR
# Admin models are used extensively throughout this file; keep the star import for now.
from app.models import *  # NOSONAR
from django.shortcuts import render
from app.utils.Utils import gen_random_code_s,buildPageLabels
import logging
import hashlib
import re
import json
from datetime import datetime
from django.db import transaction
from django.db.models import Q

from app.utils.AlgorithmRegistry import resolve_algorithm_runtime_config
from app.utils.SafeLog import safe_json_dumps
from app.utils.UploadPath import resolve_upload_url_to_abs_path, split_paired_path


logger = logging.getLogger(__name__)

_DEVICE_SUFFIXES = ["_gpu", "_cpu", "_auto", "_npu", "_trt"]

MSG_CONTROL_NOT_FOUND_CN = "布控数据不存在"
MSG_INVALID_PARAMS_CN = "请求参数不合法"
MSG_METHOD_NOT_SUPPORTED_CN = "请求方法不支持"
MSG_ANALYZER_CANCEL_FAILED_CN = "Analyzer 取消布控失败"
MSG_ALARM_CLEANUP_FAILED_CN = "关联告警清理失败"
MSG_CONTROL_DELETE_NOT_CONFIRMED_CN = "布控数据删除未确认"

DEFAULT_OVERLAY_COLOR = "255,0,0"
DEFAULT_FULL_FRAME_RECOGNITION_REGION = "0,0,1,0,1,1,0,1"
SQL_SELECT_ALL_ALGORITHMS_DESC = "select * from av_algorithm order by id desc"
TEMPLATE_MESSAGE = "app/message.html"
URL_CONTROLS = "/controls"

def _split_algorithm_code(code):
    """拆分算法编码。"""
    if not code:
        return "", "CPU"
    value = str(code)
    lower = value.lower()
    # Support optional numeric suffix for multi-GPU/TRT, e.g. *_gpu1, *_trt0
    for suffix in ("_gpu", "_trt"):
        if lower.endswith(suffix):
            return value[:-len(suffix)], suffix[1:].upper()
        m = re.search(rf"{re.escape(suffix)}(\d+)$", lower)
        if m:
            dev_id = m.group(1)
            return value[: -len(suffix) - len(dev_id)], f"{suffix[1:].upper()}:{dev_id}"

    for suffix in ("_cpu", "_auto", "_npu"):
        if lower.endswith(suffix):
            return value[:-len(suffix)], suffix[1:].upper()
    return value, "CPU"

def _stable_process_index(code: str, mod: int) -> int:
    """返回`stable`进程索引。
    
    Deterministic mapping from a control/flow code to a process index.
    
        Used for "multi-analyzer host" deployments where Admin assigns controls to a fixed process
        without keeping extra state in DB.
    """
    try:
        m = int(mod or 0)
    except Exception:
        m = 0
    if m <= 1:
        return 0
    try:
        value = str(code or "")
        h = hashlib.md5(value.encode("utf-8")).hexdigest()
        return int(h[:8], 16) % m
    except Exception:
        return 0

def _algorithm_code_variants(base_code):
    """处理算法编码`variants`。"""
    if not base_code:
        return []
    return [base_code] + [base_code + suffix for suffix in _DEVICE_SUFFIXES]

def _resolve_algorithm_object_str_list(base_code: str):
    """解析并返回算法`object`字符串列表。"""
    algo = AlgorithmModel.objects.filter(code=str(base_code or "")).first()
    if not algo:
        return []
    return algo.object_str.split(",")


def _split_tracking_algorithm_for_ui(tracking_code: str):
    """拆分`tracking`算法`for``ui`。"""
    tracking_code = str(tracking_code or "").strip()
    if not tracking_code:
        return "", "CPU", ""

    base, dev = _split_algorithm_code(tracking_code)
    dev_raw = str(dev or "CPU")
    if ":" in dev_raw:
        parts = dev_raw.split(":", 1)
        device = parts[0].upper() if parts[0] else "CPU"
        device_id = parts[1] if len(parts) > 1 else ""
        return base, device, device_id

    return base, dev_raw.upper(), ""


def _get_operator(request):
    """获取操作人。"""
    try:
        user = getUser(request)
        if user:
            return user.get("username") or user.get("email") or ""
    except Exception as e:
        logger.debug("_get_operator() error: %s", e)
    return ""

def _save_control_log(control_code, action, result_code, result_msg, operator="", detail=""):
    """保存控制`log`。"""
    try:
        log = ControlLog()
        log.control_code = control_code or ""
        log.action = action
        log.result_code = result_code
        log.result_msg = result_msg or ""
        log.operator = operator or ""
        log.detail = detail or ""
        log.create_time = datetime.now()
        log.save()
    except Exception as e:
        logger.warning(
            "ControlView._save_control_log() error: %s",
            safe_json_dumps(str(e), max_len=512),
        )


def _resolve_stream_context_for_control(control):
    """解析并返回流`context``for`控制。"""
    stream_app = control.stream_app
    stream_name = control.stream_name
    stream_code = stream_name

    stream = Stream.objects.filter(app=stream_app, name=stream_name).first()
    if stream:
        stream_code = stream.code

    return stream_app, stream_name, stream_code


def _resolve_pipeline_mode_object_str(control) -> str:
    """
    Pipeline 模式 3/4：目标列表与匹配以“分类算法”的 object_str 为准。

    返回空字符串表示不覆盖。
    """
    try:
        if not getattr(control, "use_pipeline_mode", False):
            return ""

        try:
            mode = int(getattr(control, "algorithm_pipeline_mode", 1) or 1)
        except Exception:
            mode = 1
        if mode not in (3, 4):
            return ""

        cls_code = str(getattr(control, "classification_algorithm_code", "") or "").strip()
        if not cls_code:
            return ""

        cls_base, _cls_dev = _split_algorithm_code(cls_code)
        cls_algo = AlgorithmModel.objects.filter(code=cls_base).first()
        if not cls_algo:
            return ""

        cls_runtime = resolve_algorithm_runtime_config(cls_algo, control_code=control.code)
        return str(cls_runtime.get("object_str") or getattr(cls_algo, "object_str", "") or "").strip()
    except Exception:
        return ""


def _resolve_control_object_str(control, algorithm, runtime_algorithm):
    # 流程模式 3/4：目标列表与匹配应以“分类算法”的类别集合为准（更符合工业使用习惯）
    """解析并返回控制`object`字符串。"""
    runtime_algorithm = runtime_algorithm or {}
    default_object_str = str(runtime_algorithm.get("object_str") or getattr(algorithm, "object_str", "") or "")
    override = _resolve_pipeline_mode_object_str(control)
    return override or default_object_str


def _resolve_control_basic_api_url(algorithm, runtime_algorithm):
    # 基础算法来源：只有 basic_source=api 时才把 api_url 下发给 Analyzer。
    # 否则会导致“本地模型推理”被 api_url 覆盖，进而跳过模型加载/走错链路。
    """解析并返回控制`basic`APIURL。"""
    api_url = ""
    try:
        if str(runtime_algorithm.get("basic_source") or getattr(algorithm, "basic_source", "model")) == "api":
            api_url = str(runtime_algorithm.get("api_url") or getattr(algorithm, "api_url", "") or "").strip()
    except Exception:
        api_url = ""
    return api_url


def _enforce_algorithm_max_control_count(algorithm, runtime_algorithm):
    # 基础算法布控数量上限检查（0 表示不限）
    """处理`enforce`算法最大值控制统计。"""
    try:
        effective_max_control_count = int(runtime_algorithm.get("max_control_count"))
    except Exception:
        effective_max_control_count = int(getattr(algorithm, "max_control_count", 0) or 0)

    if effective_max_control_count <= 0:
        return True, ""

    # Consider all variants: <base>, <base>_<device...>, <base>__<instanceKey...>
    active_count = Control.objects.filter(state=1).filter(
        Q(algorithm_code=algorithm.code)
        | Q(algorithm_code__startswith=algorithm.code + "_")
        | Q(algorithm_code__startswith=algorithm.code + "__")
    ).count()
    if active_count >= effective_max_control_count:
        return False, f"该算法已达到布控上限({effective_max_control_count})，请先停止部分布控"

    return True, ""


def _dedup_keep_order(items):
    """处理`dedup``keep``order`。"""
    uniq = []
    seen = set()
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


_ALGORITHM_SUBTYPES = ("detection", "classification", "tracking", "behavior", "ocr")


def _control_int(value, default: int) -> int:
    """处理控制整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _algorithm_runtime_type(runtime_cfg, algo) -> int:
    """返回算法运行时类型。"""
    return _control_int(runtime_cfg.get("algorithm_type") or getattr(algo, "algorithm_type", 0) or 0, 0)


def _algorithm_runtime_basic_source(runtime_cfg, algo) -> str:
    """处理算法运行时`basic`来源。"""
    return str(runtime_cfg.get("basic_source") or getattr(algo, "basic_source", "model"))


def _algorithm_runtime_subtype(runtime_cfg, algo) -> str:
    """处理算法运行时`subtype`。"""
    subtype = str(runtime_cfg.get("algorithm_subtype") or getattr(algo, "algorithm_subtype", "") or "").strip().lower()
    if subtype in _ALGORITHM_SUBTYPES:
        return subtype
    return ""


def _prewarm_model_spec(algo_type: int, algo_subtype: str, algo, runtime_cfg):
    """处理预热模型`spec`。"""
    if int(algo_type or 0) == 0:
        model_path = str(runtime_cfg.get("model_path") or getattr(algo, "model_path", "") or "").strip()
        if not model_path:
            return "", None
        parts = split_paired_path(model_path)
        model_path = parts[0] if parts else model_path

        class_names = None
        if algo_subtype != "tracking":
            class_names = [
                x.strip()
                for x in str(runtime_cfg.get("object_str") or getattr(algo, "object_str", "") or "").split(",")
                if x.strip()
            ]
        return model_path, class_names

    dll_path = str(runtime_cfg.get("dll_path") or getattr(algo, "dll_path", "") or "").strip()
    if not dll_path:
        return "", None
    return dll_path, None


def _prewarm_model_concurrency(runtime_cfg, algo) -> int:
    """处理预热模型`concurrency`。"""
    concurrency = _control_int(runtime_cfg.get("model_concurrency") or getattr(algo, "model_concurrency", 1) or 1, 1)
    return int(concurrency) if int(concurrency) >= 1 else 1


def _prewarm_instance_code(algo_code: str, runtime_cfg: dict, algo) -> str:
    """构建与 Analyzer 布控侧一致的模型实例键。"""
    precision = str(runtime_cfg.get("model_precision") or getattr(algo, "model_precision", "FP32") or "FP32").upper()
    precision = {"F16": "FP16", "F32": "FP32", "I8": "INT8"}.get(precision, precision)
    if precision not in ("FP32", "FP16", "INT8"):
        precision = "FP32"

    def _dimension(name: str) -> int:
        value = _control_int(runtime_cfg.get(name) or getattr(algo, name, 640) or 640, 640)
        return min(value if value > 0 else 640, 8192)

    width = _dimension("input_width")
    height = _dimension("input_height")
    return f"{algo_code}__{precision}__{width}x{height}"


def _prewarm_algorithm_code(algo_code: str, control_code: str = ""):
    """处理预热算法编码。"""
    base, device = _split_algorithm_code(algo_code)
    if not base:
        return True, ""

    algo = AlgorithmModel.objects.filter(code=base).first()
    if not algo:
        # Unknown code (e.g. bytetrack) -> ignore.
        return True, ""
    runtime_cfg = resolve_algorithm_runtime_config(algo, control_code=control_code)
    algo_subtype = _algorithm_runtime_subtype(runtime_cfg, algo)
    algo_type = _algorithm_runtime_type(runtime_cfg, algo)

    # Basic API inference does not need local warm-load.
    if int(algo_type or 0) == 0 and _algorithm_runtime_basic_source(runtime_cfg, algo) == "api":
        return True, ""

    model_path, class_names = _prewarm_model_spec(algo_type, algo_subtype, algo, runtime_cfg)
    if not model_path:
        # Built-in models may be loaded by Analyzer's preset mapping.
        return True, ""

    abs_path = resolve_upload_url_to_abs_path(
        model_path,
        upload_dir=getattr(g_config, "uploadDir", ""),
        upload_www_prefix=getattr(g_config, "uploadDir_www", "/static/upload/"),
    )
    if not abs_path:
        return False, "无法解析模型文件路径"

    model_concurrency = _prewarm_model_concurrency(runtime_cfg, algo)

    __state, __msg = g_analyzer.algorithm_load(
        code=_prewarm_instance_code(algo_code, runtime_cfg, algo),
        modelPath=abs_path,
        classNames=class_names,
        device=device or "CPU",
        modelConcurrency=model_concurrency,
        algorithmSubtype=algo_subtype or None,
    )

    if (not __state) and ("already loaded" in str(__msg or "").lower()):
        __state = True

    return bool(__state), str(__msg or ("success" if __state else "error"))


def _control_flag(obj, attr: str) -> bool:
    """处理控制标记。"""
    try:
        return bool(getattr(obj, attr, False))
    except Exception:
        return False


def _control_attr_str(obj, attr: str) -> str:
    """处理控制`attr`字符串。"""
    try:
        return str(getattr(obj, attr, "") or "").strip()
    except Exception:
        return ""


def _not_bytetrack(code: str) -> bool:
    """处理`not``bytetrack`。"""
    return str(code or "").strip().lower() != "bytetrack"


_PIPELINE_MODE_PREWARM_SPECS = {
    1: [("behavior_algorithm_code", None)],
    2: [("tracking_algorithm_code", _not_bytetrack), ("behavior_algorithm_code", None)],
    3: [("classification_algorithm_code", None), ("behavior_algorithm_code", None)],
    4: [("classification_algorithm_code", None), ("behavior_algorithm_code", None)],
    7: [("feature_algorithm_code", None)],
    9: [("feature_algorithm_code", None)],
}


def _append_hierarchical_prewarm_codes(warm_codes, control) -> None:
    """追加`hierarchical`预热编码列表。"""
    if not _control_flag(control, "enable_hierarchical_algorithm"):
        return

    sec_code = _control_attr_str(control, "secondary_algorithm_code")
    if not sec_code:
        return

    sec_api = _control_attr_str(control, "secondary_api_url")
    if sec_api:
        return

    warm_codes.append(sec_code)


def _append_pipeline_mode_prewarm_codes(warm_codes, control) -> None:
    """追加`pipeline`模式预热编码列表。"""
    if not _control_flag(control, "use_pipeline_mode"):
        return

    try:
        mode_raw = getattr(control, "algorithm_pipeline_mode", 1) or 1
    except Exception:
        mode_raw = 1
    mode = _control_int(mode_raw, 1)

    for attr, predicate in _PIPELINE_MODE_PREWARM_SPECS.get(int(mode or 0), []):
        code = _control_attr_str(control, attr)
        if not code:
            continue
        if predicate and not predicate(code):
            continue
        warm_codes.append(code)


def _collect_prewarm_codes_for_control(control, algorithm, runtime_algorithm):
    """获取控制的`collect`预热编码列表。"""
    warm_codes = []

    # Base detection algorithm (local model only)
    if _algorithm_runtime_type(runtime_algorithm, algorithm) == 0 and _algorithm_runtime_basic_source(runtime_algorithm, algorithm) != "api":
        warm_codes.append(control.algorithm_code)

    _append_hierarchical_prewarm_codes(warm_codes, control)
    _append_pipeline_mode_prewarm_codes(warm_codes, control)

    return _dedup_keep_order(warm_codes)


def _prewarm_algorithms_for_control(control, algorithm, runtime_algorithm):
    # v4.18: 启动布控前自动预热（动态加载）本地模型/插件，避免“算法未加载/No preset mapping”导致启动失败。
    """获取控制的预热`algorithms`。"""
    try:
        warm_codes = _collect_prewarm_codes_for_control(control, algorithm, runtime_algorithm)
        for item in warm_codes:
            ok, msg = _prewarm_algorithm_code(item, control_code=control.code)
            if not ok:
                return False, f"算法预热失败({item}): {msg}"
    except Exception as e:
        return False, f"算法预热异常: {e}"
    return True, ""


def _control_pipeline_mode_value(control, default: int = 1) -> int:
    """返回控制`pipeline`模式值。"""
    try:
        return int(getattr(control, "algorithm_pipeline_mode", default) or default)
    except Exception:
        return int(default)


def _should_inject_behavior_api_config(control) -> bool:
    """判断`inject``behavior`API配置。"""
    return bool(getattr(control, "use_pipeline_mode", False)) and _control_pipeline_mode_value(control) in (5, 7, 9)


def _load_behavior_config_dict(behavior_config_text: str) -> dict:
    """加载`behavior`配置字典。"""
    try:
        merged = json.loads(behavior_config_text) if str(behavior_config_text or "").strip() else {}
    except Exception:
        return {}
    return merged if isinstance(merged, dict) else {}


def _control_analysis_prompt(control) -> str:
    """处理控制`analysis``prompt`。"""
    try:
        return str(getattr(control, "analysis_prompt", "") or "").strip()
    except Exception:
        return ""


def _apply_behavior_prompt(merged: dict, prompt: str) -> bool:
    """处理应用`behavior``prompt`。"""
    if not prompt:
        return False
    merged["prompt"] = prompt
    merged["promptZh"] = prompt
    return True


def _resolve_behavior_algorithm_binding(control):
    """解析并返回`behavior`算法`binding`。"""
    behavior_code_raw = str(getattr(control, "behavior_algorithm_code", "") or "").strip()
    if not behavior_code_raw:
        return "", None, {}

    behavior_base, _behavior_dev = _split_algorithm_code(behavior_code_raw)
    if not behavior_base:
        return "", None, {}

    behavior_algo = AlgorithmModel.objects.filter(code=behavior_base).first()
    if not behavior_algo:
        return behavior_base, None, {}

    if int(getattr(behavior_algo, "algorithm_type", 0) or 0) not in (1, 2):
        return behavior_base, None, {}

    behavior_runtime = resolve_algorithm_runtime_config(behavior_algo, control_code=control.code)
    return behavior_base, behavior_algo, behavior_runtime


def _resolve_behavior_api_url(current_api_url: str, behavior_runtime: dict, behavior_algo) -> str:
    """解析并返回`behavior`APIURL。"""
    if current_api_url:
        return current_api_url
    return str(behavior_runtime.get("api_url") or getattr(behavior_algo, "api_url", "") or "").strip()


def _resolve_behavior_builtin(behavior_runtime: dict, behavior_algo) -> str:
    """解析并返回`behavior``builtin`。"""
    return str(behavior_runtime.get("builtin_behavior") or getattr(behavior_algo, "builtin_behavior", "") or "").strip()


def _normalize_behavior_api_version(value) -> int:
    """执行归一化`behavior`API版本。"""
    try:
        version = int(value or 1)
    except Exception:
        version = 1
    return version if version in (1, 2, 3) else 1


def _resolve_behavior_api_version(behavior_runtime: dict, behavior_algo) -> int:
    """解析并返回`behavior`API版本。"""
    return _normalize_behavior_api_version(
        behavior_runtime.get("behavior_api_version") or getattr(behavior_algo, "behavior_api_version", 1) or 1
    )


def _apply_behavior_runtime_defaults(merged: dict, *, builtin_behavior: str, pipeline_mode: int, api_version: int) -> bool:
    """处理应用`behavior`运行时`defaults`。"""
    changed = False

    if builtin_behavior and not merged.get("builtinBehavior"):
        merged["builtinBehavior"] = builtin_behavior
        changed = True

    if pipeline_mode != 5:
        return changed

    if "apiVersion" not in merged:
        merged["apiVersion"] = api_version
        changed = True

    if builtin_behavior in ("absence", "unattended") and not merged.get("postprocess"):
        merged["postprocess"] = builtin_behavior
        changed = True

    return changed


def _apply_behavior_algorithm_binding(merged: dict, behavior_base: str) -> bool:
    """处理应用`behavior`算法`binding`。"""
    if not behavior_base:
        return False
    merged.setdefault("behaviorAlgorithmCode", behavior_base)
    return True


def _inject_behavior_api_config_for_control(control):
    # ========== Pipeline Mode 5: 行为算法 APIv2（混合模式）配置注入 ==========
    # 目标：
    # - 用户在算法管理里配置“行为/业务算法” code + api_url + behavior_api_version + builtin_behavior
    # - 布控只需要填写 behavior_algorithm_code（算法编号），无需重复填写 apiVersion/builtinBehavior
    #
    # 兼容：
    # - 用户仍可手工填写 behavior_api_url / behavior_config，本逻辑只做 setdefault，不强制覆盖
    """获取控制的`inject``behavior`API配置。"""
    behavior_api_url = str(getattr(control, "behavior_api_url", "") or "").strip()
    behavior_config_text = str(getattr(control, "behavior_config", "{}") or "{}")
    try:
        if _should_inject_behavior_api_config(control):
            pipeline_mode = _control_pipeline_mode_value(control)
            merged = _load_behavior_config_dict(behavior_config_text)
            changed = _apply_behavior_prompt(merged, _control_analysis_prompt(control))

            behavior_base, behavior_algo, behavior_runtime = _resolve_behavior_algorithm_binding(control)
            if behavior_algo:
                behavior_api_url = _resolve_behavior_api_url(behavior_api_url, behavior_runtime, behavior_algo)
                builtin_behavior = _resolve_behavior_builtin(behavior_runtime, behavior_algo)
                api_version = _resolve_behavior_api_version(behavior_runtime, behavior_algo)
                if _apply_behavior_runtime_defaults(
                    merged,
                    builtin_behavior=builtin_behavior,
                    pipeline_mode=pipeline_mode,
                    api_version=api_version,
                ):
                    changed = True
                if _apply_behavior_algorithm_binding(merged, behavior_base):
                    changed = True

            if changed:
                behavior_config_text = json.dumps(merged, ensure_ascii=False)
    except Exception as e:
        logger.debug("ControlView._start_control() inject behavior api config error: %s", e)

    return behavior_api_url, behavior_config_text


def _start_control(control):
    """启动控制。"""
    if not control:
        return False, MSG_CONTROL_NOT_FOUND_CN

    base_code, _device = _split_algorithm_code(control.algorithm_code)
    stream_app, stream_name, stream_code = _resolve_stream_context_for_control(control)

    algorithm = AlgorithmModel.objects.filter(code=base_code).first()
    if not algorithm:
        return False, "该布控算法不存在"
    runtime_algorithm = resolve_algorithm_runtime_config(algorithm, control_code=control.code)

    object_str = _resolve_control_object_str(control, algorithm, runtime_algorithm)

    api_url = _resolve_control_basic_api_url(algorithm, runtime_algorithm)

    ok, msg = _enforce_algorithm_max_control_count(algorithm, runtime_algorithm)
    if not ok:
        return False, msg

    ok, msg = _prewarm_algorithms_for_control(control, algorithm, runtime_algorithm)
    if not ok:
        return False, msg

    behavior_api_url, behavior_config_text = _inject_behavior_api_config_for_control(control)
    recognition_region = str(getattr(control, "polygon", "") or "").strip()
    if not recognition_region:
        recognition_region = DEFAULT_FULL_FRAME_RECOGNITION_REGION

    __state, __msg = g_analyzer.control_add(
        code=control.code,
        algorithmCode=control.algorithm_code,
        streamCode=stream_code,
        streamApp=stream_app,
        streamName=stream_name,
        streamUrl=g_zlm.get_rtspUrl(control.stream_app, control.stream_name),  # 拉流地址
        pushStream=control.push_stream,
        pushStreamUrl=g_zlm.get_rtspUrl(control.push_stream_app, control.push_stream_name),  # 推流地址
        api_url=api_url,
        object_str=object_str,
        objectCode=control.object_code,
        recognitionRegion=recognition_region,
        minInterval=control.min_interval,
        classThresh=control.class_thresh,
        overlapThresh=control.overlap_thresh,
        alarmVideoType=control.alarm_video_type,
        alarmImageCount=control.alarm_image_count,
        alarmCoverPosition=getattr(control, "alarm_cover_position", "front"),
        alarmCoverCustomIndex=getattr(control, "alarm_cover_custom_index", 0),
        alarmImageDrawMode=getattr(control, "alarm_image_draw_mode", "boxed"),
        # v4.627: 强制逐帧发送报警（谨慎开启：会增加存储/网络压力）
        forceFrameAlarm=getattr(control, "force_frame_alarm", False),
        # ========== 新增参数 ==========
        # 算法推理阈值参数（新的标准命名）
        # 两个阈值字段暂时沿用历史来源
        nmsThresh=control.overlap_thresh,
        confThresh=control.class_thresh,
        # 推流视频质量参数
        pushVideoCodec=control.push_video_codec,
        pushVideoBitrate=control.push_video_bitrate,
        pushVideoFps=control.push_video_fps,
        pushVideoWidth=control.push_video_width,
        pushVideoHeight=control.push_video_height,
        pushVideoGop=control.push_video_gop,
        # 算法模型参数
        modelPrecision=runtime_algorithm.get("model_precision") or getattr(algorithm, "model_precision", "FP32"),
        inputWidth=runtime_algorithm.get("input_width") or getattr(algorithm, "input_width", 640),
        inputHeight=runtime_algorithm.get("input_height") or getattr(algorithm, "input_height", 640),
        modelConcurrency=runtime_algorithm.get("model_concurrency") or getattr(algorithm, "model_concurrency", 1) or 1,
        # 基础算法检测模式参数
        basicAlgoDetectMode=getattr(control, "basic_algo_detect_mode", 0) or 0,
        basicAlgoDetectInterval=getattr(control, "basic_algo_detect_interval", 1) or 1,
        # v4.623: 布控级跳帧解码（1=全帧；N=每 N 帧解码一次）
        decodeStride=getattr(control, "decode_stride", 1) or 1,
        # v4.644: perf tuning knobs (optional)
        pullFrequency=getattr(control, "pull_frequency", 0) or 0,
        psEffectMinFps=getattr(control, "ps_effect_min_fps", 0) or 0,
        # OSD 参数
        osdEnabled=getattr(control, "osd_enabled", False),
        osdText=getattr(control, "osd_text", ""),
        osdPosition=getattr(control, "osd_position", "top-left"),
        osdX=getattr(control, "osd_x", 10),
        osdY=getattr(control, "osd_y", 30),
        osdFontSize=getattr(control, "osd_font_size", 24),
        osdFontColor=getattr(control, "osd_font_color", "255,255,255"),
        osdBgEnabled=getattr(control, "osd_bg_enabled", True),
        osdFontThickness=getattr(control, "osd_font_thickness", 2),
        # OSD 贴图参数
        osdImagePath=getattr(control, "osd_image_path", ""),
        osdImageX=getattr(control, "osd_image_x", 10),
        osdImageY=getattr(control, "osd_image_y", 10),
        osdImageScale=getattr(control, "osd_image_scale", 1.0),
        osdImageAlpha=getattr(control, "osd_image_alpha", 1.0),
        # Algo/FPS overlay coordinates (defaults match Analyzer hardcode)
        osdAlgoX=getattr(control, "osd_algo_x", 20),
        osdAlgoY=getattr(control, "osd_algo_y", 80),
        osdFpsX=getattr(control, "osd_fps_x", 20),
        osdFpsY=getattr(control, "osd_fps_y", 140),
        # ========== 算法流绘制样式（v4.627） ==========
        overlayRegionColor=getattr(control, "overlay_region_color", DEFAULT_OVERLAY_COLOR),
        overlayRegionThickness=getattr(control, "overlay_region_thickness", 4),
        overlayLineColor=getattr(control, "overlay_line_color", DEFAULT_OVERLAY_COLOR),
        overlayLineThickness=getattr(control, "overlay_line_thickness", 4),
        overlayDetectColor=getattr(control, "overlay_detect_color", DEFAULT_OVERLAY_COLOR),
        overlayDetectThickness=getattr(control, "overlay_detect_thickness", 2),
        overlayDetectFontSize=getattr(control, "overlay_detect_font_size", 48),
        # 越线/绘制参数
        drawType=getattr(control, "draw_type", "polygon"),
        lineCoordinates=getattr(control, "line_coordinates", ""),
        lineViolationDirection=getattr(control, "line_violation_direction", "both"),
        enableTracking=getattr(control, "enable_tracking", False),
        # ========== 布控级硬件编解码配额开关（v4.20.1） ==========
        enableHardwareDecode=getattr(control, "enable_hw_decode", False),
        enableHardwareEncode=getattr(control, "enable_hw_encode", False),
        # ========================================
        # ========== 层级算法（二级检测） ==========
        enableHierarchicalAlgorithm=getattr(control, "enable_hierarchical_algorithm", False),
        secondaryAlgorithmCode=getattr(control, "secondary_algorithm_code", ""),
        secondaryApiUrl=getattr(control, "secondary_api_url", ""),
        secondaryConfThresh=getattr(control, "secondary_conf_thresh", 0.25),
        # ========================================
        # ========== 算法流程模式参数 ==========
        usePipelineMode=getattr(control, "use_pipeline_mode", False),
        pipelineMode=getattr(control, "algorithm_pipeline_mode", 1),
        trackingAlgorithmCode=getattr(control, "tracking_algorithm_code", ""),
        trackingConfig=getattr(control, "tracking_config", "{}"),
        classificationAlgorithmCode=getattr(control, "classification_algorithm_code", ""),
        classificationConfig=getattr(control, "classification_config", "{}"),
        featureAlgorithmCode=getattr(control, "feature_algorithm_code", ""),
        featureConfig=getattr(control, "feature_config", "{}"),
        behaviorAlgorithmCode=getattr(control, "behavior_algorithm_code", ""),
        behaviorApiUrl=behavior_api_url,
        behaviorConfig=behavior_config_text,
        # ========================================
    )

    if __state:
        control.state = 1
        control.save()
        return True, "布控成功"

    return False, __msg

def _stop_control(control):
    """停止控制。"""
    if not control:
        return False, MSG_CONTROL_NOT_FOUND_CN

    __state, __msg = g_analyzer.control_cancel(
        code=control.code
    )

    if __state:
        control.state = 0
        control.save()
        return True, "取消布控成功"

    return False, __msg

def _parse_codes(params):
    """解析编码列表。"""
    codes = params.get("codes")
    if isinstance(codes, list):
        raw_codes = codes
    else:
        raw_codes = str(codes or "").split(",")
    return [c.strip() for c in raw_codes if c and str(c).strip()]

ANALYZER_CONTROL_ABSENT_MESSAGE = "there is no such control"


class _ControlDeleteNotConfirmed(RuntimeError):
    pass


def _cancel_control_for_delete(control_code: str) -> tuple[bool, str]:
    """取消 Analyzer 布控，并返回是否可以安全删除本地记录。"""
    try:
        result = g_analyzer.control_cancel(code=control_code)
    except Exception as e:
        logger.warning(
            "Analyzer cancel raised: err=%s",
            safe_json_dumps(str(e), max_len=512),
        )
        return False, MSG_ANALYZER_CANCEL_FAILED_CN

    if not isinstance(result, tuple) or len(result) != 2:
        logger.warning(
            "Analyzer cancel returned malformed result: result=%s",
            safe_json_dumps(result, max_len=512),
        )
        return False, "Analyzer 取消布控响应格式不合法"

    state, message = result
    if not isinstance(state, bool) or not isinstance(message, str):
        logger.warning(
            "Analyzer cancel returned invalid field types: result=%s",
            safe_json_dumps(result, max_len=512),
        )
        return False, "Analyzer 取消布控响应格式不合法"

    if state or message == ANALYZER_CONTROL_ABSENT_MESSAGE:
        return True, message
    logger.warning(
        "Analyzer cancel was not confirmed: detail=%s",
        safe_json_dumps(message, max_len=512),
    )
    return False, MSG_ANALYZER_CANCEL_FAILED_CN


def _remove_control_related_alarms(control_code: str) -> tuple[bool, str]:
    """Delete related alarms in ID order and stop on the first failure."""
    try:
        alarm_ids = list(
            Alarm.objects.filter(control_code=control_code)
            .order_by("id")
            .values_list("id", flat=True)
        )
        removed_count = 0
        for alarm_id in alarm_ids:
            if f_removeAlarmAndStorage(alarm_id=alarm_id) is not True:
                logger.warning("related alarm cleanup failed: alarm_id=%s", alarm_id)
                return False, MSG_ALARM_CLEANUP_FAILED_CN
            removed_count += 1
        if Alarm.objects.filter(control_code=control_code).exists():
            logger.warning("related alarm cleanup left residual rows")
            return False, MSG_ALARM_CLEANUP_FAILED_CN
        return True, f"关联告警清理成功{removed_count}条"
    except Exception as e:
        logger.warning(
            "related alarm cleanup raised: err=%s",
            safe_json_dumps(str(e), max_len=512),
        )
        return False, MSG_ALARM_CLEANUP_FAILED_CN


def _clone_control_fields(src, dst) -> None:
    # 工业化复制：尽量复制所有字段，避免新增字段后忘记同步
    """返回`clone`控制字段。"""
    for field in Control._meta.fields:
        name = field.name
        if name in ("id", "code", "create_time", "last_update_time", "state"):
            continue
        setattr(dst, name, getattr(src, name))


def index(request):
    """渲染默认页面。"""
    context = {}
    params = f_parseGetParams(request)

    # Provide group/search filter UI options (best-effort).
    # Note: Control list is filtered by `stream_app`, which aligns with Stream.app groups.
    try:
        app_choices = list(Stream.objects.values_list("app", flat=True).distinct().order_by("app"))
    except Exception:
        app_choices = []

    filter_stream_app = str(params.get("stream_app") or params.get("app") or "").strip()
    filter_search_text = str(params.get("search_text") or params.get("q") or "").strip()

    context["app_choices"] = app_choices
    context["filter_stream_app"] = filter_stream_app
    context["filter_search_text"] = filter_search_text
    return render(request, 'app/control/index.html', context)


def _parse_control_list_pagination(params):
    """解析控制列表`pagination`。"""
    page = params.get("p", 1)
    page_size = params.get("ps", 10)

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1

    try:
        page_size = int(page_size)
        if page_size < 1:
            page_size = 1
        if page_size > 50:
            page_size = 50
    except (TypeError, ValueError):
        page_size = 10

    return page, page_size


def _parse_control_list_filters(params):
    # Support both OpenAPI params (`search_text`/`stream_app`) and UI params (`q`/`app`).
    """解析控制列表`filters`。"""
    search_text = str(
        (params.get("search_text") if params.get("search_text") is not None else params.get("q")) or ""
    ).strip()
    filter_stream_app = str(
        (params.get("stream_app") if params.get("stream_app") is not None else params.get("app")) or ""
    ).strip()
    if filter_stream_app.lower() in ("all", "*"):
        filter_stream_app = ""
    return search_text, filter_stream_app


def _get_analyzer_process_num():
    """获取分析器进程`num`。"""
    raw_hosts = str(os.environ.get("BEACON_ANALYZER_HOSTS") or "").strip()
    if not raw_hosts:
        return 1
    analyzer_hosts = [h.strip() for h in raw_hosts.split(",") if h and str(h).strip()]
    return int(len(analyzer_hosts)) if analyzer_hosts else 1


def _fetch_online_streams_and_controls():
    """获取在线流列表`and``controls`。"""
    online_streams_dict = {}  # 在线的视频流
    online_controls_dict = {}  # 在线的布控数据

    streams = g_zlm.getMediaList()
    media_server_state = g_zlm.mediaServerState

    for item in streams:
        if item.get("is_online"):
            online_streams_dict[item.get("an")] = item

    analyzer_server_state = False
    if media_server_state:
        __state, __msg, controls = g_analyzer.controls()
        analyzer_server_state = g_analyzer.analyzer_server_state
        for item in controls:
            online_controls_dict[item.get("code")] = item

    return online_streams_dict, online_controls_dict, media_server_state, analyzer_server_state


def _build_db_stream_dict():
    """构建数据库流字典。"""
    db_stream_dict = {}
    db_streams = g_djangoSql.select("select * from av_stream")
    for row in db_streams:
        app_name = "%s_%s" % (row["app"], row["name"])
        db_stream_dict[app_name] = row
    return db_stream_dict


def _build_algorithms_dict():
    """构建`algorithms`字典。"""
    algorithms_dict = {}
    algorithms_data = g_djangoSql.select(SQL_SELECT_ALL_ALGORITHMS_DESC)
    for row in algorithms_data:
        algorithms_dict[row.get("code")] = row
    return algorithms_dict


def _build_control_where_clause(filter_stream_app: str, search_text: str):
    """构建控制`where``clause`。"""
    where_clauses = []
    where_params = []

    if filter_stream_app:
        where_clauses.append("stream_app = %s")
        where_params.append(filter_stream_app)

    if search_text:
        where_clauses.append("(code like %s or stream_name like %s or stream_app like %s or algorithm_code like %s)")
        like = "%%%s%%" % search_text
        where_params.extend([like, like, like, like])

    where_sql = (" where " + " and ".join(where_clauses)) if where_clauses else ""
    return where_sql, where_params


def _fetch_control_count(where_sql: str, where_params):
    """获取控制统计。"""
    count_rows = g_djangoSql.select("select count(id) as count from av_control" + where_sql, where_params)
    return int(count_rows[0]["count"]) if count_rows else 0


def _fetch_control_rows(where_sql: str, where_params, *, page: int, page_size: int):
    """获取控制记录。"""
    skip = (page - 1) * page_size
    return g_djangoSql.select(
        "select * from av_control%s order by id desc limit %d,%d" % (where_sql, skip, page_size),
        where_params,
    )


def _fetch_db_control_code_set():
    """获取数据库控制编码`set`。"""
    rows = g_djangoSql.select("select code from av_control")
    return {r.get("code") for r in rows if r.get("code")}


def _decorate_db_control_row(
    row,
    *,
    db_stream_dict,
    online_streams_dict,
    online_controls_dict,
    algorithms_dict,
    process_num: int,
):
    """返回装饰数据库控制记录。"""
    app_name = "%s_%s" % (row["stream_app"], row["stream_name"])
    row["create_time"] = row["create_time"].strftime("%Y-%m-%d %H:%M")
    d_stream = db_stream_dict.get(app_name)
    row["stream_nickname"] = d_stream["nickname"] if d_stream else row["stream_name"]

    row["stream_active"] = 1 if online_streams_dict.get(app_name) else 0

    base_code, device = _split_algorithm_code(row["algorithm_code"])
    row["algorithm_device"] = device
    algorithm = algorithms_dict.get(base_code)
    if algorithm:
        row["flow_nickname"] = algorithm["name"]
        row["flow_code"] = algorithm["code"]
        row["flow_deploy_process_index"] = _stable_process_index(row.get("code"), process_num)
        row["flow_max_concurrency"] = 0
        row["flow_concurrency_unit_length"] = 0
    else:
        row["flow_nickname"] = 0

    row["last_update_time"] = row["last_update_time"].strftime("%Y/%m/%d %H:%M:%S")
    row["checkFps"] = "0"

    online_control = online_controls_dict.get(row["code"])
    if online_control:
        row["cur_state"] = 1  # 布控中
        row["checkFps"] = "%.2f" % float(online_control.get("checkFps"))
    else:
        row["cur_state"] = 0 if int(row.get("state")) == 0 else 5  # 未布控 / 布控中断

    if row.get("state") != row.get("cur_state"):
        # 数据表中的布控状态和最新布控状态不一致，需要更新至最新状态
        try:
            cur_state = int(row.get("cur_state"))
            control_id = int(row.get("id"))
            sql = "UPDATE av_control SET state=%s WHERE id=%s"
            g_djangoSql.execute(sql, [cur_state, control_id])
        except (ValueError, TypeError) as e:
            logger.warning(
                "更新布控状态失败: %s cur_state=%s id=%s",
                e,
                row.get("cur_state"),
                row.get("id"),
            )


def _decorate_db_control_rows(
    rows,
    *,
    db_stream_dict,
    online_streams_dict,
    online_controls_dict,
    algorithms_dict,
    process_num: int,
):
    """返回装饰数据库控制记录。"""
    data = []
    for row in rows:
        _decorate_db_control_row(
            row,
            db_stream_dict=db_stream_dict,
            online_streams_dict=online_streams_dict,
            online_controls_dict=online_controls_dict,
            algorithms_dict=algorithms_dict,
            process_num=process_num,
        )
        data.append([row])
    return data


def _cancel_orphan_running_controls(online_controls_dict, *, db_control_code_set):
    """处理`cancel``orphan``running``controls`。"""
    for code, control in online_controls_dict.items():
        if code in db_control_code_set:
            continue
        # 布控数据在运行中，但却不存在本地数据表中，该数据为失控数据，需要关闭其运行状态
        logger.warning(
            "api_getControls() orphan running control; canceling code=%s control=%s",
            code,
            safe_json_dumps(control, max_len=1024),
        )
        g_analyzer.control_cancel(code=code)


def _format_control_list_top_msg(*, media_server_state, analyzer_server_state):
    """处理`format`控制列表`top``msg`。"""
    if media_server_state and analyzer_server_state:
        return "<span style='color:green;font-size:14px;'>流媒体运行中，视频分析器运行中</span>"
    if media_server_state and not analyzer_server_state:
        return "<span style='color:green;font-size:14px;'>流媒体运行中</span> <span style='color:red;font-size:14px;'>视频分析器未运行<span>"
    return "<span style='color:red;font-size:14px;'>流媒体未运行，视频分析器未运行<span>"


def _build_page_data(*, page: int, page_size: int, count: int):
    """构建页面数据。"""
    page_num = int(count // page_size)  # 总页数
    if count % page_size > 0:
        page_num += 1
    return {
        "page": page,
        "page_size": page_size,
        "page_num": page_num,
        "count": count,
        "pageLabels": buildPageLabels(page=page, page_num=page_num),
    }


def _build_control_state_stats(where_sql: str, where_params, *, total_count: int):
    """构建控制状态`stats`。"""
    state_counts = {0: 0, 1: 0, 5: 0}
    try:
        rows = g_djangoSql.select(
            "select state, count(id) as cnt from av_control%s group by state" % where_sql,
            where_params,
        )
        for r in rows:
            s = int(r.get("state") or 0)
            c = int(r.get("cnt") or 0)
            state_counts[s] = c
    except Exception:
        logger.debug("load control state counts failed", exc_info=True)

    return {
        "total": total_count,
        "running": state_counts.get(1, 0),
        "stopped": state_counts.get(0, 0),
        "error": state_counts.get(5, 0),
    }


def api_open_index(request):
    """处理 `openIndex` 接口请求。"""
    params = f_parseGetParams(request)
    page, page_size = _parse_control_list_pagination(params)
    search_text, filter_stream_app = _parse_control_list_filters(params)

    process_num = _get_analyzer_process_num()
    online_streams_dict, online_controls_dict, media_server_state, analyzer_server_state = _fetch_online_streams_and_controls()

    db_stream_dict = _build_db_stream_dict()
    algorithms_dict = _build_algorithms_dict()

    where_sql, where_params = _build_control_where_clause(filter_stream_app, search_text)

    count = _fetch_control_count(where_sql, where_params)
    control_rows = _fetch_control_rows(where_sql, where_params, page=page, page_size=page_size)
    db_control_code_set = _fetch_db_control_code_set()

    data = _decorate_db_control_rows(
        control_rows,
        db_stream_dict=db_stream_dict,
        online_streams_dict=online_streams_dict,
        online_controls_dict=online_controls_dict,
        algorithms_dict=algorithms_dict,
        process_num=process_num,
    )

    _cancel_orphan_running_controls(online_controls_dict, db_control_code_set=db_control_code_set)

    top_msg = _format_control_list_top_msg(
        media_server_state=media_server_state, analyzer_server_state=analyzer_server_state
    )

    page_data = _build_page_data(page=page, page_size=page_size, count=count)
    stats = _build_control_state_stats(where_sql, where_params, total_count=count)

    res = {
        "code": 1000,
        "msg": "success",
        "top_msg": top_msg,
        "data": data,
        "pageData": page_data,
        "stats": stats,
    }
    return f_responseJson(res)
api_openIndex = api_open_index  # pragma: no cover - compatibility alias


def add(request):
    """处理新增。"""
    context = {
    }

    streams = g_zlm.getMediaList()


    context["streams"] = streams
    context["algorithms"] = g_djangoSql.select(SQL_SELECT_ALL_ALGORITHMS_DESC)
    context["handle"] = "add"

    context["control"] = {
        "code": gen_random_code_s("control"),
        "min_interval": 180,
        "class_thresh": 0.5,
        "overlap_thresh": 0.5,
        "push_stream": True,
        "push_video_fps": 25,
        "alarm_sound_id": 0,
        "alarm_video_type": "mp4",
        "alarm_image_count": 3,
        "alarm_cover_position": "back",
        "alarm_cover_custom_index": 0,
        "alarm_image_draw_mode": "boxed",
        # 绘制/越线配置
        "draw_type": "polygon",
        "line_coordinates": "",
        "line_violation_direction": "both",
        "enable_tracking": False,
        # OSD 配置
        "osd_enabled": False,
        "osd_text": "",
        "osd_position": "top-left",
        "osd_x": 10,
        "osd_y": 30,
        "osd_font_size": 24,
        "osd_font_color": "255,255,255",
        "osd_bg_enabled": True,
        "osd_image_path": "",
        "osd_image_x": 10,
        "osd_image_y": 10,
        "osd_image_scale": 1.0,
        "osd_image_alpha": 1.0,
        # Algo/FPS overlay coordinates (defaults match Analyzer hardcode)
        "osd_algo_x": 20,
        "osd_algo_y": 80,
        "osd_fps_x": 20,
        "osd_fps_y": 140,
    }
    context["control_algorithm_base"] = ""
    context["control_algorithm_device"] = "CPU"
    context["control_tracking_base"] = ""
    context["control_tracking_device"] = "CPU"
    context["control_tracking_device_id"] = ""

    return render(request, 'app/control/add.html', context)


def edit(request):
    """处理编辑。"""
    context = {}
    params = f_parseGetParams(request)

    code = str(params.get("code") or "").strip()
    if not code:
        return render(
            request,
            TEMPLATE_MESSAGE,
            {"msg": "缺少参数：code（布控编号）", "is_success": False, "redirect_url": URL_CONTROLS},
        )

    control = Control.objects.filter(code=code).first()
    if not control:
        return render(
            request,
            TEMPLATE_MESSAGE,
            {"msg": "该布控不存在或已被删除", "is_success": False, "redirect_url": URL_CONTROLS},
        )

    try:
        base_code, device = _split_algorithm_code(control.algorithm_code)
        old_object_data = _resolve_algorithm_object_str_list(base_code)

        context["algorithms"] = g_djangoSql.select(SQL_SELECT_ALL_ALGORITHMS_DESC)

        context["old_object_data"] = old_object_data
        context["handle"] = "edit"
        context["control"] = control
        context["control_algorithm_base"] = base_code
        context["control_algorithm_device"] = device
        public_host = get_public_host_for_urls(request)
        context["control_stream_flvUrl"] = g_zlm.get_wsMp4Url(control.stream_app, control.stream_name, public_host)

        # tracking algorithm split for UI
        tracking_base, tracking_device, tracking_device_id = _split_tracking_algorithm_for_ui(
            getattr(control, "tracking_algorithm_code", "")
        )
        context["control_tracking_base"] = tracking_base
        context["control_tracking_device"] = tracking_device
        context["control_tracking_device_id"] = tracking_device_id

    except Exception as e:
        logger.warning("ControlView.edit() error: %s", e, exc_info=True)

        return render(
            request,
            TEMPLATE_MESSAGE,
            {"msg": "读取布控数据失败，请稍后重试或联系管理员", "is_success": False, "redirect_url": URL_CONTROLS},
        )

    return render(request, 'app/control/add.html', context)

def api_open_start_control(request):
    """处理 `openStartControl` 接口请求。"""
    code = 0
    msg = "error"

    if request.method == 'POST':
        params = f_parsePostParams(request)

        control_code = params.get("code")

        if control_code:
            try:
                control = Control.objects.get(code=control_code)
                operator = _get_operator(request)

                __state, __msg = _start_control(control)
                msg = __msg
                if __state:
                    code = 1000

                _save_control_log(control_code, "start", code, msg, operator)
            except Exception as e:
                msg = str(e)
                _save_control_log(control_code, "start", 0, msg, _get_operator(request))
                logger.warning("ControlView.api_openStartControl() error: %s", e)

        else:
            msg = MSG_INVALID_PARAMS_CN
    else:
        msg = MSG_METHOD_NOT_SUPPORTED_CN
    res = {
        "code": code,
        "msg": msg
    }
    return f_responseJson(res)
api_openStartControl = api_open_start_control  # pragma: no cover - compatibility alias

def api_open_stop_control(request):
    """处理 `openStopControl` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    control_code = params.get("code")
    if not control_code:
        return f_responseJson({"code": 0, "msg": MSG_INVALID_PARAMS_CN})

    try:
        operator = _get_operator(request)
        control = Control.objects.filter(code=control_code).first()
        if not control:
            msg = "布控数据不能存在！"
            _save_control_log(control_code, "stop", 0, msg, operator)
            return f_responseJson({"code": 0, "msg": msg})

        ok, msg = _stop_control(control)
        code = 1000 if ok else 0
        _save_control_log(control_code, "stop", code, msg, operator)
        return f_responseJson({"code": code, "msg": msg})
    except Exception as e:
        msg = str(e)
        _save_control_log(control_code, "stop", 0, msg, _get_operator(request))
        return f_responseJson({"code": 0, "msg": msg})
api_openStopControl = api_open_stop_control  # pragma: no cover - compatibility alias

def _control_quickset_get_param(params: dict, *names):
    """处理控制快捷设置`get`参数。"""
    for name in names:
        if name in params:
            return True, params.get(name)
    return False, None


def _control_quickset_parse_int_range(raw, *, field_name: str, min_value: int, max_value: int):
    """处理控制快捷设置`parse`整数值`range`。"""
    try:
        value = int(raw)
    except Exception:
        return None, f"{field_name} must be an integer"

    if value < min_value or value > max_value:
        return None, f"{field_name} must be between {min_value} and {max_value}"

    return value, ""


def _control_quickset_apply_params(control, params: dict):
    """处理控制快捷设置应用参数。"""
    changed = {}

    present, raw = _control_quickset_get_param(params, "decode_stride", "decodeStride")
    if present:
        v, err = _control_quickset_parse_int_range(raw, field_name="decode_stride", min_value=1, max_value=100)
        if err:
            return {}, err
        control.decode_stride = v
        changed["decode_stride"] = v

    present, raw = _control_quickset_get_param(params, "alarm_video_type", "alarmVideoType")
    if present:
        v = str(raw or "").strip().lower()
        if v not in ("mp4", "ts", "flv", "none"):
            return {}, "alarm_video_type must be one of: mp4/ts/flv/none"
        control.alarm_video_type = v
        changed["alarm_video_type"] = v

    present, raw = _control_quickset_get_param(params, "alarm_image_count", "alarmImageCount")
    if present:
        v, err = _control_quickset_parse_int_range(raw, field_name="alarm_image_count", min_value=0, max_value=50)
        if err:
            return {}, err
        control.alarm_image_count = v
        changed["alarm_image_count"] = v

    present, raw = _control_quickset_get_param(params, "alarm_image_draw_mode", "alarmImageDrawMode")
    if present:
        v = str(raw or "").strip().lower()
        if v not in ("boxed", "clean", "both"):
            return {}, "alarm_image_draw_mode must be one of: boxed/clean/both"
        control.alarm_image_draw_mode = v
        changed["alarm_image_draw_mode"] = v

    return changed, ""


def _control_quickset_want_restart(params: dict) -> bool:
    """处理控制快捷设置`want`重启。"""
    restart = str(params.get("restart") or "0").strip()
    return restart in ("1", "true", "yes", "y", "on")


def _control_quickset_restart_if_needed(control, want_restart: bool):
    """处理控制快捷设置重启`if``needed`。"""
    if not want_restart:
        return ""

    try:
        running = int(getattr(control, "state", 0) or 0) == 1
    except Exception:
        running = False

    if not running:
        return ""

    try:
        _stop_ok, _stop_msg = _stop_control(control)
        if not _stop_ok:
            return f"已保存但重启停止失败: {_stop_msg}"
        _start_ok, _start_msg = _start_control(control)
        if not _start_ok:
            return f"已保存但重启启动失败: {_start_msg}"
        return ""
    except Exception as e:
        return f"已保存但重启异常: {e}"


def _control_quickset_save_log(control_code: str, *, operator: str, changed: dict):
    """处理控制快捷设置`save``log`。"""
    try:
        _save_control_log(
            control_code,
            "quick_set",
            1000,
            "success",
            operator=operator,
            detail=json.dumps(changed, ensure_ascii=False),
        )
    except Exception:
        logger.debug("save control quick-set log failed control_code=%s", control_code, exc_info=True)


def api_open_quick_set(request):
    '''
    Web/UI + OpenAPI: 布控快捷设置（轻量 patch）

    POST /control/openQuickSet
    Payload (JSON or form):
      - code (required)
      - decode_stride (optional, int >=1)
      - alarm_video_type (optional, mp4/ts/flv/none)
      - alarm_image_count (optional, int >=0)
      - alarm_image_draw_mode (optional, boxed/clean/both)
      - restart (optional, 0/1): when 1 and control is running, restart control to apply.
    '''
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    control_code = str(params.get("code") or params.get("controlCode") or "").strip()
    if not control_code:
        return f_responseJson({"code": 0, "msg": MSG_INVALID_PARAMS_CN})

    control = Control.objects.filter(code=control_code).first()
    if not control:
        return f_responseJson({"code": 0, "msg": "布控不存在"})

    changed, err = _control_quickset_apply_params(control, params)
    if err:
        return f_responseJson({"code": 0, "msg": err})
    if not changed:
        return f_responseJson({"code": 0, "msg": "no changes"})

    control.save()

    restart_error = _control_quickset_restart_if_needed(control, _control_quickset_want_restart(params))
    if restart_error:
        return f_responseJson({"code": 0, "msg": restart_error})

    _control_quickset_save_log(control_code, operator=_get_operator(request), changed=changed)
    return f_responseJson({"code": 1000, "msg": "success", "changed": changed})
api_openQuickSet = api_open_quick_set  # pragma: no cover - compatibility alias


def api_open_del(request):
    """处理 `openDel` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "请求方法不合法！"})

    params = f_parsePostParams(request)
    control_code = params.get("code")
    if not control_code:
        return f_responseJson({"code": 0, "msg": "删除布控请求参数不完整！"})

    code = 0
    msg = "error"
    try:
        control = Control.objects.get(code=control_code)
        cancel_ok, _cancel_msg = _cancel_control_for_delete(control_code)
        if not cancel_ok:
            msg = "删除失败：无法确认视频分析器已取消布控"
        else:
            try:
                cleanup_result = _remove_control_related_alarms(control_code)
            except Exception as e:
                logger.warning(
                    "related alarm cleanup escaped unexpectedly: err=%s",
                    safe_json_dumps(str(e), max_len=512),
                )
                cleanup_result = (False, MSG_ALARM_CLEANUP_FAILED_CN)
            if (
                not isinstance(cleanup_result, tuple)
                or len(cleanup_result) != 2
                or not isinstance(cleanup_result[0], bool)
                or not isinstance(cleanup_result[1], str)
            ):
                cleanup_ok, _cleanup_msg = False, "关联告警清理响应格式不合法"
                logger.warning("related alarm cleanup returned malformed result")
            else:
                cleanup_ok, _cleanup_msg = cleanup_result

            if not cleanup_ok:
                msg = f"删除失败：{MSG_ALARM_CLEANUP_FAILED_CN}"
            else:
                try:
                    control_pk = control.pk
                    with transaction.atomic():
                        deleted_count, _deleted_objects = control.delete()
                        if (
                            deleted_count <= 0
                            or Control.objects.filter(id=control_pk).exists()
                        ):
                            raise _ControlDeleteNotConfirmed(
                                "control row deletion was not confirmed"
                            )
                    code = 1000
                    msg = "删除成功"
                except Exception as e:
                    msg = f"删除失败：{MSG_CONTROL_DELETE_NOT_CONFIRMED_CN}"
                    logger.warning(
                        "control row delete failed: err=%s",
                        safe_json_dumps(str(e), max_len=512),
                    )
    except Control.DoesNotExist:
        msg = "删除失败：布控不存在"
    except Exception as e:
        msg = "删除失败：内部操作异常"
        logger.warning(
            "control delete request failed: err=%s",
            safe_json_dumps(str(e), max_len=512),
        )

    _save_control_log(control_code, "delete", code, msg, _get_operator(request))
    return f_responseJson({"code": code, "msg": msg})
api_openDel = api_open_del  # pragma: no cover - compatibility alias

def _batch_control_try_apply(control_code: str, op_fn):
    """处理批量控制`try`应用。"""
    try:
        control = Control.objects.filter(code=control_code).first()
        if not control:
            return False, MSG_CONTROL_NOT_FOUND_CN
        return op_fn(control)
    except Exception as e:
        return False, str(e)


def _batch_control_execute(codes: list, *, operator: str, op_fn, log_action: str):
    """处理批量控制执行。"""
    results = []
    success_count = 0
    fail_count = 0

    for control_code in codes:
        __state, __msg = _batch_control_try_apply(control_code, op_fn)
        item_code = 1000 if __state else 0
        if __state:
            success_count += 1
        else:
            fail_count += 1

        _save_control_log(control_code, log_action, item_code, __msg, operator)
        results.append(
            {
                "code": control_code,
                "result_code": item_code,
                "msg": __msg,
            }
        )

    return results, success_count, fail_count


def _batch_control_status(success_count: int, fail_count: int, *, success_template: str, fail_template: str):
    """返回批量控制状态。"""
    if success_count > 0:
        return 1000, success_template % (success_count, fail_count)
    return 0, fail_template % fail_count


def api_open_batch_start(request):
    """处理 `openBatchStart` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN, "results": []})

    params = f_parsePostParams(request)
    codes = _parse_codes(params)
    if not codes:
        return f_responseJson({"code": 0, "msg": "请至少选择一条布控", "results": []})

    operator = _get_operator(request)
    results, success_count, fail_count = _batch_control_execute(
        codes,
        operator=operator,
        op_fn=_start_control,
        log_action="batch_start",
    )
    code, msg = _batch_control_status(
        success_count,
        fail_count,
        success_template="批量布控完成，成功%d条，失败%d条",
        fail_template="批量布控失败，失败%d条",
    )
    return f_responseJson({"code": code, "msg": msg, "results": results})
api_openBatchStart = api_open_batch_start  # pragma: no cover - compatibility alias

def api_open_batch_stop(request):
    """处理 `openBatchStop` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN, "results": []})

    params = f_parsePostParams(request)
    codes = _parse_codes(params)
    if not codes:
        return f_responseJson({"code": 0, "msg": "请至少选择一条布控", "results": []})

    operator = _get_operator(request)
    results, success_count, fail_count = _batch_control_execute(
        codes,
        operator=operator,
        op_fn=_stop_control,
        log_action="batch_stop",
    )
    code, msg = _batch_control_status(
        success_count,
        fail_count,
        success_template="批量停止完成，成功%d条，失败%d条",
        fail_template="批量停止失败，失败%d条",
    )
    return f_responseJson({"code": code, "msg": msg, "results": results})
api_openBatchStop = api_open_batch_stop  # pragma: no cover - compatibility alias

def api_open_copy(request):
    """处理 `openCopy` 接口请求。"""
    code = 0
    msg = "error"
    new_code = ""

    if request.method != 'POST':
        return f_responseJson({"code": code, "msg": "请求方法不合法", "new_code": new_code})

    params = f_parsePostParams(request)
    control_code = params.get("code")
    operator = _get_operator(request)

    if not control_code:
        return f_responseJson({"code": code, "msg": "请求参数不完整", "new_code": new_code})

    try:
        control = Control.objects.get(code=control_code)
        new_code = gen_random_code_s("control")

        new_control = Control()
        _clone_control_fields(control, new_control)

        user = getUser(request) or {}
        new_control.user_id = user.get("id") or control.user_id
        new_control.code = new_code
        new_control.push_stream_name = new_code
        new_control.state = 0
        new_control.create_time = datetime.now()
        new_control.last_update_time = datetime.now()
        new_control.save()

        if new_control.id:
            code = 1000
            msg = "复制成功"
        else:
            msg = "复制失败"

        _save_control_log(new_code, "copy", code, msg, operator, detail="from=%s" % control_code)
    except Exception as e:
        msg = str(e)
        _save_control_log(control_code, "copy", 0, msg, operator)

    res = {
        "code": code,
        "msg": msg,
        "new_code": new_code
    }
    return f_responseJson(res)
api_openCopy = api_open_copy  # pragma: no cover - compatibility alias


def api_open_batch_copy_to_streams(request):
    """处理 `openBatchCopyToStreams` 接口请求。"""
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    src_code = (params.get("src_code") or params.get("code") or "").strip()
    stream_codes = params.get("stream_codes") or params.get("codes") or ""
    only_offline = str(params.get("only_offline", "1")).strip()  # 默认仅离线（未转发）

    stream_codes_list = _batch_copy_stream_codes_list(stream_codes)

    if not src_code:
        return f_responseJson({"code": 0, "msg": "缺少源布控编号(src_code)"})
    if not stream_codes_list:
        return f_responseJson({"code": 0, "msg": "请至少选择一条摄像头"})

    src = Control.objects.filter(code=src_code).first()
    if not src:
        return f_responseJson({"code": 0, "msg": "源布控不存在"})

    operator = _get_operator(request)
    user = getUser(request) or {}
    results = []

    for stream_code in stream_codes_list:
        results.append(
            _batch_copy_control_to_stream(
                src=src,
                src_code=src_code,
                stream_code=stream_code,
                only_offline=only_offline,
                operator=operator,
                user=user,
            )
        )

    success_count = sum(1 for item in results if int(item.get("result_code") or 0) == 1000)
    fail_count = len(results) - success_count

    if success_count > 0:
        code = 1000
        msg = "批量复制完成：成功%d条，失败%d条" % (success_count, fail_count)
    else:
        code = 0
        msg = "批量复制失败：失败%d条" % fail_count

    return f_responseJson({"code": code, "msg": msg, "results": results})
api_openBatchCopyToStreams = api_open_batch_copy_to_streams  # pragma: no cover - compatibility alias


def _batch_copy_stream_codes_list(stream_codes):
    """返回批量`copy`流编码列表列表。"""
    if isinstance(stream_codes, list):
        raw = stream_codes
    else:
        raw = str(stream_codes or "").split(",")
    return [c.strip() for c in raw if c and str(c).strip()]


def _batch_copy_result(stream_code: str, result_code: int, msg: str, *, new_code: str = ""):
    """返回批量`copy`结果。"""
    payload = {"stream_code": str(stream_code or "").strip(), "result_code": int(result_code), "msg": str(msg or "")}
    new_code_token = str(new_code or "").strip()
    if new_code_token:
        payload["new_code"] = new_code_token
    return payload


def _batch_copy_control_to_stream(*, src, src_code: str, stream_code: str, only_offline: str, operator: str, user: dict):
    """处理批量`copy`控制`to`流。"""
    stream_code = str(stream_code or "").strip()
    try:
        if not stream_code:
            return _batch_copy_result(stream_code, 0, "摄像头编号为空")

        stream = Stream.objects.filter(code=stream_code).first()
        if not stream:
            return _batch_copy_result(stream_code, 0, "摄像头不存在")

        if only_offline == "1" and int(getattr(stream, "forward_state", 0) or 0) == 1:
            return _batch_copy_result(stream_code, 0, "该摄像头正在转发，已跳过")

        new_code = gen_random_code_s("control")
        new_control = Control()
        _clone_control_fields(src, new_control)

        new_control.user_id = user.get("id") or src.user_id
        new_control.code = new_code
        new_control.stream_app = stream.app
        new_control.stream_name = stream.name
        new_control.stream_video = src.stream_video or "video"
        new_control.stream_audio = src.stream_audio or "audio"
        new_control.push_stream_name = new_code
        new_control.state = 0
        new_control.create_time = datetime.now()
        new_control.last_update_time = datetime.now()
        new_control.save()

        if not new_control.id:
            return _batch_copy_result(stream_code, 0, "复制失败")

        _save_control_log(new_code, "batch_copy", 1000, "复制成功", operator, detail="from=%s stream=%s" % (src_code, stream_code))
        return _batch_copy_result(stream_code, 1000, "复制成功", new_code=new_code)
    except Exception as e:
        return _batch_copy_result(stream_code, 0, str(e))
