from app.models import AlgorithmModel, AlgorithmModelVersion, Control
from app.views.ViewsBase import f_parseGetParams, f_parsePostParams, f_responseJson, g_analyzer, g_config
from django.shortcuts import render, redirect
from django.db import transaction
import os
import time
import base64
import json
import logging
import struct
import requests
from io import BytesIO
from PIL import Image
from app.utils.AlgorithmRegistry import (
    activate_algorithm_version,
    build_algorithm_snapshot,
    create_algorithm_version,
    ensure_algorithm_version_registry,
    rollback_algorithm_version,
    set_algorithm_gray_version,
    snapshots_equal,
)
from app.utils.Utils import buildPageLabels
from app.utils.UploadPath import resolve_upload_url_to_abs_path, split_paired_path

# 模型和动态库上传目录
_UPLOAD_BASE_DIR = getattr(g_config, "uploadDir", "") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static", "upload"
)
UPLOAD_MODEL_DIR = os.path.join(_UPLOAD_BASE_DIR, "models")
UPLOAD_DLL_DIR = os.path.join(_UPLOAD_BASE_DIR, "dlls")

# 确保上传目录存在
os.makedirs(UPLOAD_MODEL_DIR, exist_ok=True)
os.makedirs(UPLOAD_DLL_DIR, exist_ok=True)

PATH_STATIC_UPLOAD = "/static/upload/"
PATH_ALGORITHM_INDEX = "/algorithm/index"
TEMPLATE_MESSAGE = "app/message.html"
MSG_METHOD_NOT_SUPPORTED = "request method not supported"
MSG_ALGORITHM_NOT_FOUND = "算法不存在"
MSG_CODE_REQUIRED = "code is required"
MODEL_EXT_ONNX = ".onnx"
logger = logging.getLogger(__name__)
ALGORITHM_MARKETPLACE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "algorithm_marketplace",
)

# ========== 支持的模型文件格式 ==========
SUPPORTED_MODEL_FORMATS = {
    # ONNX Runtime
    MODEL_EXT_ONNX: 'ONNX模型',
    # PyTorch
    '.pt': 'PyTorch模型',
    '.pth': 'PyTorch模型',
    # TensorRT
    '.engine': 'TensorRT引擎',
    '.trt': 'TensorRT引擎',
    '.plan': 'TensorRT Plan',
    # OpenVINO
    '.xml': 'OpenVINO IR模型（需配套.bin文件）',
    '.bin': 'OpenVINO权重文件（配套.xml文件）',
    # TensorFlow
    '.pb': 'TensorFlow模型',
    # YOLO
    '.weights': 'YOLO权重文件（需配套.cfg文件）',
    '.cfg': 'YOLO配置文件（配套.weights文件）',
    # 其他
    '.tflite': 'TensorFlow Lite模型',
    '.h5': 'Keras H5模型',
    # 国产硬件
    '.rknn': 'RKNN模型',
    '.om': 'Ascend OM模型',
}

# 需要配对的文件格式
PAIRED_FORMATS = {
    '.xml': '.bin',  # OpenVINO IR: .xml需要.bin
    '.weights': '.cfg',  # YOLO: .weights需要.cfg
}

# Analyzer 侧同一算法可能按设备后缀区分不同实例（用于运维展示/统计）
_ANALYZER_DEVICE_SUFFIXES = ["", "_gpu", "_trt", "_auto", "_npu", "_cpu"]
_SUPPORTED_BASIC_ALGORITHM_SUBTYPES = ("detection", "classification", "ocr", "tracking", "speech")
_SUPPORTED_API_V2_BUILTIN_BEHAVIORS = {
    "absence",
    "corruptscreen",
    "crosscount",
    "crossing",
    "crowd",
    "grayscreen",
    "intrusion",
    "loitering",
    "motion",
    "occlusion",
    "super",
    "unattended",
}

def _normalize_encrypt_suffix(suffix: str) -> str:
    """执行归一化加密`suffix`。"""
    value = str(suffix or "").strip()
    if not value:
        return ".enc"
    if value == "." or value == "..":
        return ".enc"
    if not value.startswith("."):
        value = "." + value
    if len(value) > 16:
        return ".enc"
    return value


def _strip_suffix_ci(value: str, suffix: str):
    """处理`strip``suffix``ci`。"""
    if not value or not suffix:
        return value, False
    v = str(value)
    sfx = str(suffix)
    if v.lower().endswith(sfx.lower()):
        return v[: -len(sfx)], True
    return v, False


def _effective_model_ext(filename: str, encrypt_suffix: str):
    """处理`effective`模型`ext`。
    
    Return (effective_ext, is_enc_wrapper) where:
          - "a.engine"      -> (".engine", False)
          - "a.engine.enc"  -> (".engine", True)
    """
    suffix = _normalize_encrypt_suffix(encrypt_suffix)
    stripped, is_enc = _strip_suffix_ci(str(filename or ""), suffix)
    ext = os.path.splitext(stripped)[1].lower()
    return ext, bool(is_enc)


_ENC_V2_MAGIC = b"BENCv2\x00\x00"


def _looks_like_enc_v2_file(abs_path: str) -> bool:
    """处理外观`like``enc``v2`文件。"""
    try:
        with open(abs_path, "rb") as f:
            head = f.read(len(_ENC_V2_MAGIC))
        return head == _ENC_V2_MAGIC
    except Exception:
        return False


def _xor_encrypt_stream(src_abs: str, dst_abs: str, *, key: str, trial_seconds: int = 0, custom_id: str = ""):
    """处理`xor`加密流。"""
    key_bytes = str(key or "").encode("utf-8")
    if not key_bytes:
        raise ValueError("modelEncryptKey is empty")

    try:
        trial = int(trial_seconds or 0)
    except Exception:
        trial = 0
    if trial < 0:
        trial = 0

    cid = str(custom_id or "")
    cid_bytes = cid.encode("utf-8")
    if len(cid_bytes) > 1024:
        cid_bytes = cid_bytes[:1024]

    encrypted_at_ms = int(time.time() * 1000)
    version = 2
    header_size = len(_ENC_V2_MAGIC) + 4 + 4 + 8 + 4 + 4 + len(cid_bytes)

    header_fixed = struct.pack(
        "<IIQII",
        int(version),
        int(header_size),
        int(encrypted_at_ms),
        int(trial),
        int(len(cid_bytes)),
    )

    tmp_abs = dst_abs + ".tmp"
    idx = 0
    klen = len(key_bytes)
    chunk_size = 4 * 1024 * 1024
    try:
        with open(src_abs, "rb") as src, open(tmp_abs, "wb") as dst:
            dst.write(_ENC_V2_MAGIC)
            dst.write(header_fixed)
            if cid_bytes:
                dst.write(cid_bytes)

            while True:
                data = src.read(chunk_size)
                if not data:
                    break
                buf = bytearray(data)
                for i in range(len(buf)):
                    buf[i] ^= key_bytes[(idx + i) % klen]
                idx += len(buf)
                dst.write(buf)
            dst.flush()
        os.replace(tmp_abs, dst_abs)
    finally:
        try:
            if os.path.exists(tmp_abs):
                os.remove(tmp_abs)
        except Exception:
            logger.debug("cleanup temporary encrypted model file failed path=%s", tmp_abs, exc_info=True)


def _maybe_auto_encrypt_file(abs_path: str, *, url_path: str, key: str, suffix: str, custom_id: str):
    """按需处理自动加密文件。
    
    If abs_path is not already encrypted, encrypt to abs_path+suffix and delete abs_path.
        Returns: (new_abs_path, new_url_path)
    """
    norm_suffix = _normalize_encrypt_suffix(suffix)
    if not abs_path:
        return abs_path, url_path

    already = False
    try:
        already = abs_path.lower().endswith(norm_suffix.lower())
    except Exception:
        already = False
    if not already:
        already = _looks_like_enc_v2_file(abs_path)

    if already:
        return abs_path, url_path

    dst_abs = abs_path + norm_suffix
    dst_url = str(url_path or "") + norm_suffix

    _xor_encrypt_stream(abs_path, dst_abs, key=key, trial_seconds=0, custom_id=custom_id)
    try:
        os.remove(abs_path)
    except Exception:
        logger.debug("remove original model file after encryption failed path=%s", abs_path, exc_info=True)

    return dst_abs, dst_url


def validate_model_file(file, filename):
    """
    验证模型文件格式和大小
    """
    encrypt_suffix = getattr(g_config, "modelEncryptSuffix", ".enc") or ".enc"
    file_ext, _is_enc = _effective_model_ext(filename, encrypt_suffix)

    # 检查扩展名
    if file_ext not in SUPPORTED_MODEL_FORMATS:
        supported_list = ', '.join(SUPPORTED_MODEL_FORMATS.keys())
        raise ValueError(f"不支持的模型文件格式 {file_ext}，支持的格式：{supported_list}")

    # 检查文件大小（最大5GB）
    max_size = 5 * 1024 * 1024 * 1024  # 5GB
    if file.size > max_size:
        size_mb = file.size / (1024 * 1024)
        raise ValueError(f"文件过大 ({size_mb:.1f}MB)，最大支持5GB")

    return file_ext

def save_uploaded_file(file, code, target_dir, *, filename_stem=None, url_subdir=None):
    """
    保存上传的文件
    """
    from app.utils.Security import validate_control_code

    safe_code = validate_control_code(code)
    encrypt_suffix = getattr(g_config, "modelEncryptSuffix", ".enc") or ".enc"
    eff_ext, is_enc = _effective_model_ext(file.name, encrypt_suffix)
    file_ext = eff_ext
    if is_enc:
        file_ext = eff_ext + _normalize_encrypt_suffix(encrypt_suffix)
    stem = str(filename_stem or "").strip()
    if not stem:
        stem = f"{safe_code}_{int(time.time())}"
    filename = f"{stem}{file_ext}"
    file_path = os.path.join(target_dir, filename)

    with open(file_path, 'wb+') as destination:
        for chunk in file.chunks():
            destination.write(chunk)

    # 返回相对路径（URL）
    url_prefix = str(getattr(g_config, "uploadDir_www", PATH_STATIC_UPLOAD) or PATH_STATIC_UPLOAD).strip()
    if not url_prefix.endswith("/"):
        url_prefix = url_prefix + "/"
    if url_subdir:
        sub = str(url_subdir).strip().strip("/\\")
        return f"{url_prefix}{sub}/{filename}"
    return f"{url_prefix}models/{filename}" if target_dir == UPLOAD_MODEL_DIR else f"{url_prefix}dlls/{filename}"
# ========================================

def _algorithm_index_positive_int(raw_value, default: int) -> int:
    """处理算法索引`positive`整数值。"""
    try:
        value = int(raw_value)
    except Exception:
        value = int(default)
    if value < 1:
        return int(default)
    return int(value)


def _algorithm_index_pagination_params(params):
    """处理算法索引`pagination`参数。"""
    page = _algorithm_index_positive_int(params.get('p', 1), 1)
    page_size = _algorithm_index_positive_int(params.get('ps', 10), 10)
    return page, page_size


def _algorithm_index_paginate(queryset, page: int, page_size: int):
    """处理算法索引分页。"""
    from django.core.paginator import Paginator

    paginator = Paginator(queryset, page_size)
    try:
        current_page = paginator.page(page)
    except Exception:
        page = paginator.num_pages
        current_page = paginator.page(page)
    return paginator, current_page, page


def _algorithm_index_analyzer_lookup():
    """处理算法索引分析器查询。"""
    analyzer_state = False
    analyzer_msg = ""
    analyzer_by_code = {}
    try:
        analyzer_state, analyzer_msg, analyzer_items = g_analyzer.algorithm_list()
        if isinstance(analyzer_items, list):
            for item in analyzer_items:
                try:
                    code = str((item or {}).get("code") or "").strip()
                except Exception:
                    code = ""
                if code:
                    analyzer_by_code[code] = item or {}
    except Exception as e:
        analyzer_msg = str(e)
    return analyzer_state, analyzer_msg, analyzer_by_code


def _algorithm_index_device_label(code: str) -> str:
    """处理算法索引设备标签。"""
    lower = str(code or "").lower()
    if lower.endswith("_gpu"):
        return "GPU"
    if lower.endswith("_trt"):
        return "TRT"
    if lower.endswith("_auto"):
        return "AUTO"
    if lower.endswith("_npu"):
        return "NPU"
    return "CPU"


def _algorithm_index_variant_codes(base_code: str):
    """处理算法索引`variant`编码列表。"""
    if not base_code:
        return []
    return [base_code + suffix if suffix else base_code for suffix in _ANALYZER_DEVICE_SUFFIXES]


def _algorithm_index_append_unique(items, value) -> None:
    """处理算法索引追加去重后。"""
    if value not in items:
        items.append(value)


def _algorithm_index_ref_total(ref_total: int, item) -> int:
    """处理算法索引`ref``total`。"""
    try:
        return ref_total + int(item.get("refCount") or 0)
    except Exception:
        return ref_total


def _algorithm_index_preview(preview, item):
    """处理算法索引`preview`。"""
    if preview:
        return preview
    try:
        codes_preview = item.get("controlCodesPreview") or []
    except Exception:
        return preview
    if isinstance(codes_preview, list) and codes_preview:
        return codes_preview
    return preview


def _algorithm_index_analyzer_summary(base_code: str, analyzer_by_code):
    """处理算法索引分析器`summary`。"""
    loaded_variants = []
    loaded_devices = []
    ref_total = 0
    preview = []

    for code in _algorithm_index_variant_codes(base_code):
        item = analyzer_by_code.get(code)
        if not item:
            continue
        loaded_variants.append(code)
        _algorithm_index_append_unique(loaded_devices, _algorithm_index_device_label(code))
        ref_total = _algorithm_index_ref_total(ref_total, item)
        preview = _algorithm_index_preview(preview, item)

    return loaded_variants, loaded_devices, ref_total, preview


def _algorithm_index_apply_analyzer_summary(algorithms, analyzer_by_code) -> None:
    """处理算法索引应用分析器`summary`。"""
    for algo in algorithms:
        try:
            base_code = str(getattr(algo, "code", "") or "").strip()
        except Exception:
            base_code = ""
        loaded_variants, loaded_devices, ref_total, preview = _algorithm_index_analyzer_summary(
            base_code,
            analyzer_by_code,
        )
        try:
            algo.analyzer_loaded_variants = loaded_variants
            algo.analyzer_loaded_devices = loaded_devices
            algo.analyzer_ref_count = ref_total
            algo.analyzer_control_preview = preview
        except Exception:
            logger.debug("annotate algorithm analyzer summary failed algorithm_id=%s", getattr(algo, "id", None), exc_info=True)


def index(request):
    """渲染默认页面。"""
    context = {}
    params = f_parseGetParams(request)
    page, page_size = _algorithm_index_pagination_params(params)

    queryset = AlgorithmModel.objects.all().order_by('-id')
    paginator, current_page, page = _algorithm_index_paginate(queryset, page, page_size)
    data = current_page.object_list

    analyzer_state, analyzer_msg, analyzer_by_code = _algorithm_index_analyzer_lookup()
    _algorithm_index_apply_analyzer_summary(data, analyzer_by_code)

    context["analyzer_state"] = analyzer_state
    context["analyzer_msg"] = analyzer_msg

    page_labels = buildPageLabels(page=page, page_num=paginator.num_pages)
    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": page_labels
    }

    context["data"] = data
    context["pageData"] = page_data
    return render(request, 'app/algorithm/index.html', context)


def api_marketplace(request):
    """处理算法市场列表接口。"""
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    from app.utils.AlgorithmMarketplace import list_algorithm_packages

    data = list_algorithm_packages(ALGORITHM_MARKETPLACE_DIR)
    return f_responseJson({"code": 1000, "msg": "success", "data": data})


def _popup_mode_enabled(params) -> bool:
    """判断`popup`模式是否启用。"""
    value = str(params.get("popup", "") or "").strip().lower()
    return value in ("1", "true", "yes", "on", "y")


def _algorithm_normalize_form_flags(*, algorithm_type: int, algorithm_subtype: str, support_direct_api, behavior_api_version):
    """处理算法归一化表单标记集合。"""
    algorithm_subtype = str(algorithm_subtype or "").strip().lower()
    if algorithm_type in (1, 2):
        algorithm_subtype = "behavior"
    if algorithm_type == 0 and algorithm_subtype not in _SUPPORTED_BASIC_ALGORITHM_SUBTYPES:
        algorithm_subtype = "detection"

    raw_direct = str(support_direct_api or "").strip().lower()
    support_direct_api = raw_direct in ("1", "true", "yes", "y", "on")
    try:
        behavior_api_version = int(behavior_api_version or 1)
    except Exception:
        behavior_api_version = 1
    if behavior_api_version not in (1, 2, 3):
        behavior_api_version = 1
    return algorithm_subtype, support_direct_api, behavior_api_version


def _algorithm_normalize_edit_subtype(*, algorithm_type: int, algorithm_subtype: str, existing_subtype: str) -> str:
    """处理算法归一化编辑`subtype`。"""
    algorithm_subtype = str(algorithm_subtype or "").strip().lower()
    if algorithm_type in (1, 2):
        return "behavior"
    if algorithm_type != 0:
        return algorithm_subtype
    if algorithm_subtype in _SUPPORTED_BASIC_ALGORITHM_SUBTYPES:
        return algorithm_subtype
    existing_subtype = str(existing_subtype or "").strip().lower()
    if existing_subtype in _SUPPORTED_BASIC_ALGORITHM_SUBTYPES:
        return existing_subtype
    return "detection"


def _algorithm_behavior_object_str(*, builtin_behavior: str, api_url: str, object_str: str) -> str:
    """处理算法`behavior``object`字符串。"""
    builtin_behavior = str(builtin_behavior or "").strip()
    if builtin_behavior:
        return builtin_behavior
    if api_url and (not str(object_str or "").strip()):
        return "api"
    return str(object_str or "").strip()


def _algorithm_float_value(raw_value, default: float) -> float:
    """返回算法浮点数值。"""
    try:
        return float(raw_value or default)
    except Exception:
        return float(default)


def _algorithm_parse_form_data(params):
    """返回算法`parse`表单数据。"""
    algorithm_type = int(params.get("algorithm_type", 0))
    algorithm_subtype, support_direct_api, behavior_api_version = _algorithm_normalize_form_flags(
        algorithm_type=algorithm_type,
        algorithm_subtype=params.get("algorithm_subtype", ""),
        support_direct_api=params.get("support_direct_api", ""),
        behavior_api_version=params.get("behavior_api_version", 1),
    )
    return {
        "handle": params.get("handle"),
        "code": params.get("code", "").strip(),
        "name": params.get("name", "").strip(),
        "algorithm_type": algorithm_type,
        "algorithm_subtype": algorithm_subtype,
        "basic_source": params.get("basic_source", "model").strip(),
        "api_url": params.get("api_url", "").strip(),
        "support_direct_api": support_direct_api,
        "behavior_api_version": behavior_api_version,
        "builtin_behavior": params.get("builtin_behavior", "").strip(),
        "object_str": params.get("object_str", "").strip(),
        "max_control_count": int(params.get("max_control_count", 0)),
        "model_concurrency": int(params.get("model_concurrency", 1) or 1),
        "license_package": str(params.get("license_package", "") or "").strip() or "core",
        "remark": params.get("remark", "").strip(),
        "model_precision": str(params.get("model_precision", "") or "").strip().upper() or "FP32",
        "input_width": int(params.get("input_width", 640) or 640),
        "input_height": int(params.get("input_height", 640) or 640),
        "nms_thresh": _algorithm_float_value(params.get("nms_thresh", 0.45), 0.45),
        "conf_thresh": _algorithm_float_value(params.get("conf_thresh", 0.25), 0.25),
    }


def _algorithm_validate_add_request(data):
    """处理算法`validate`新增请求。"""
    from app.utils.Security import validate_control_code

    if data["handle"] != "add":
        raise ValueError("request parameters are incorrect")
    if not data["code"]:
        raise ValueError("code cannot be empty")
    try:
        data["code"] = validate_control_code(data["code"])
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if not data["name"]:
        raise ValueError("name cannot be empty")
    try:
        data["license_package"] = validate_control_code(data["license_package"])
    except Exception as exc:
        raise ValueError("license_package is invalid") from exc
    if AlgorithmModel.objects.filter(code=data["code"]).first():
        raise ValueError("algorithm code already exist")


def _algorithm_validate_edit_request(data):
    """处理算法`validate`编辑请求。"""
    from app.utils.Security import validate_control_code

    if data["handle"] != "edit":
        raise ValueError("request parameters are incorrect")
    if not data["code"]:
        raise ValueError("code cannot be empty")
    if not data["name"]:
        raise ValueError("name cannot be empty")
    try:
        data["license_package"] = validate_control_code(data["license_package"])
    except Exception as exc:
        raise ValueError("license_package is invalid") from exc
    obj = AlgorithmModel.objects.filter(code=data["code"]).first()
    if not obj:
        raise ValueError("the data does not exist")
    return obj


def _algorithm_validate_paired_model_file(file_ext: str, paired_file) -> None:
    """处理算法`validate``paired`模型文件。"""
    if file_ext not in PAIRED_FORMATS:
        return
    if not paired_file:
        raise ValueError(f"该模型格式需要配对文件，请同时上传 {PAIRED_FORMATS[file_ext]} 文件")
    paired_ext = validate_model_file(paired_file, paired_file.name)
    expected_ext = PAIRED_FORMATS[file_ext]
    if paired_ext != expected_ext:
        raise ValueError(f"配对文件格式不正确，需要 {expected_ext} 文件，实际为 {paired_ext}")


def _algorithm_encrypt_uploaded_model_urls(*, code: str, model_url: str, paired_url: str):
    """返回算法加密`uploaded`模型URL 列表。"""
    try:
        enc_enabled = bool(getattr(g_config, "modelEncrypt", False))
        enc_key = str(getattr(g_config, "modelEncryptKey", "") or "").strip()
        enc_suffix = getattr(g_config, "modelEncryptSuffix", ".enc") or ".enc"
    except Exception:
        enc_enabled = False
        enc_key = ""
        enc_suffix = ".enc"

    if not (enc_enabled and enc_key):
        return model_url, paired_url

    main_abs = os.path.join(UPLOAD_MODEL_DIR, os.path.basename(model_url))
    _, model_url = _maybe_auto_encrypt_file(
        main_abs,
        url_path=model_url,
        key=enc_key,
        suffix=enc_suffix,
        custom_id=code,
    )
    if not paired_url:
        return model_url, paired_url

    paired_abs = os.path.join(UPLOAD_MODEL_DIR, os.path.basename(paired_url))
    _, paired_url = _maybe_auto_encrypt_file(
        paired_abs,
        url_path=paired_url,
        key=enc_key,
        suffix=enc_suffix,
        custom_id=code,
    )
    return model_url, paired_url


def _algorithm_store_model_artifacts(request, *, code: str, algorithm_subtype: str) -> str:
    """处理算法`store`模型`artifacts`。"""
    model_file = request.FILES.get("model_file")
    paired_file = request.FILES.get("paired_file")
    if not model_file:
        raise ValueError("请选择要上传的模型文件")

    file_ext = validate_model_file(model_file, model_file.name)
    if algorithm_subtype == "tracking" and file_ext not in (MODEL_EXT_ONNX, ".xml"):
        raise ValueError("追踪(Tracking)算法仅支持 .onnx 或 OpenVINO .xml + .bin")

    _algorithm_validate_paired_model_file(file_ext, paired_file)

    filename_stem = f"{code}_{int(time.time())}"
    model_url = save_uploaded_file(
        model_file,
        code,
        UPLOAD_MODEL_DIR,
        filename_stem=filename_stem,
        url_subdir="models",
    )
    paired_url = ""
    if paired_file:
        paired_url = save_uploaded_file(
            paired_file,
            code,
            UPLOAD_MODEL_DIR,
            filename_stem=filename_stem,
            url_subdir="models",
        )

    model_url, paired_url = _algorithm_encrypt_uploaded_model_urls(
        code=code,
        model_url=model_url,
        paired_url=paired_url,
    )
    return f"{model_url}|{paired_url}" if paired_url else model_url


def _algorithm_resolve_basic_artifacts(request, data, *, current_model_path: str = "", require_upload: bool = True) -> str:
    """处理算法`resolve``basic``artifacts`。"""
    if data["algorithm_subtype"] == "tracking" and data["basic_source"] == "api":
        raise ValueError("追踪(Tracking)算法仅支持“本地模型”方式")
    if data["algorithm_subtype"] == "speech" and data["basic_source"] != "api":
        raise ValueError("语音/ASR 算法在 Wave 1 仅支持“API接口”方式")
    if data["basic_source"] == "model":
        model_file = request.FILES.get("model_file")
        paired_file = request.FILES.get("paired_file")
        if paired_file and not model_file:
            raise ValueError("请先选择主模型文件，再上传配对文件")
        if model_file or require_upload:
            return _algorithm_store_model_artifacts(
                request,
                code=data["code"],
                algorithm_subtype=data["algorithm_subtype"],
            )
        return current_model_path
    if data["basic_source"] == "api" and not data["api_url"]:
        raise ValueError("API接口方式必须填写API地址")
    return current_model_path


def _algorithm_resolve_behavior_artifacts(request, data, *, current_dll_path: str = ""):
    """处理算法`resolve``behavior``artifacts`。"""
    dll_path = current_dll_path
    dll_file = request.FILES.get("dll_file")
    if dll_file:
        file_ext = os.path.splitext(dll_file.name)[1].lower()
        if file_ext not in [".dll", ".so", ".dylib"]:
            raise ValueError("不支持的动态库格式，请上传 .dll/.so/.dylib 格式")
        dll_path = save_uploaded_file(dll_file, data["code"], UPLOAD_DLL_DIR, url_subdir="dlls")

    object_str = _algorithm_behavior_object_str(
        builtin_behavior=data["builtin_behavior"],
        api_url=data["api_url"],
        object_str=data["object_str"],
    )
    if data["api_url"] and data["behavior_api_version"] == 2:
        builtin_behavior = data["builtin_behavior"].lower()
        if not builtin_behavior:
            raise ValueError("APIv2 类型必须选择内置行为算法（用于本地后处理）")
        if builtin_behavior not in _SUPPORTED_API_V2_BUILTIN_BEHAVIORS:
            raise ValueError(f"APIv2 不支持内置行为算法：{data['builtin_behavior']}")
    return dll_path, object_str


def _algorithm_add_artifacts(request, data):
    """处理算法新增`artifacts`。"""
    if data["algorithm_type"] == 0:
        return _algorithm_resolve_basic_artifacts(request, data), "", data["object_str"]
    if data["algorithm_type"] in (1, 2):
        dll_path, object_str = _algorithm_resolve_behavior_artifacts(request, data)
        return "", dll_path, object_str
    return "", "", data["object_str"]


def _algorithm_edit_artifacts(request, data, *, current_model_path: str, current_dll_path: str):
    """处理算法编辑`artifacts`。"""
    if data["algorithm_type"] == 0:
        model_path = _algorithm_resolve_basic_artifacts(
            request,
            data,
            current_model_path=current_model_path,
            require_upload=False,
        )
        return model_path, current_dll_path, data["object_str"]
    if data["algorithm_type"] in (1, 2):
        dll_path, object_str = _algorithm_resolve_behavior_artifacts(
            request,
            data,
            current_dll_path=current_dll_path,
        )
        return current_model_path, dll_path, object_str
    return current_model_path, current_dll_path, data["object_str"]


def _algorithm_object_count(object_str: str) -> int:
    """处理算法`object`统计。"""
    return len([item for item in str(object_str or "").split(",") if item])


def _algorithm_apply_form_data(obj, data, *, model_path: str, dll_path: str, object_str: str) -> None:
    """返回算法应用表单数据。"""
    model_precision = data["model_precision"] if data["model_precision"] in ("FP32", "FP16", "INT8") else "FP32"
    input_width = data["input_width"] if data["input_width"] > 0 else 640
    input_height = data["input_height"] if data["input_height"] > 0 else 640
    nms_thresh = data["nms_thresh"] if 0.0 <= float(data["nms_thresh"]) <= 1.0 else 0.45
    conf_thresh = data["conf_thresh"] if 0.0 <= float(data["conf_thresh"]) <= 1.0 else 0.25

    obj.name = data["name"]
    obj.algorithm_type = data["algorithm_type"]
    obj.algorithm_subtype = data["algorithm_subtype"] if data["algorithm_subtype"] else str(getattr(obj, "algorithm_subtype", "") or "detection")
    obj.basic_source = data["basic_source"]
    obj.api_url = data["api_url"]
    obj.support_direct_api = bool(data["support_direct_api"]) if data["algorithm_type"] in (1, 2) else False
    obj.behavior_api_version = int(data["behavior_api_version"] or 1) if data["algorithm_type"] in (1, 2) else 1
    obj.model_path = model_path
    obj.dll_path = dll_path
    obj.builtin_behavior = data["builtin_behavior"]
    obj.object_count = _algorithm_object_count(object_str)
    obj.object_str = object_str
    obj.max_control_count = data["max_control_count"]
    obj.model_concurrency = data["model_concurrency"] if data["model_concurrency"] > 0 else 1
    obj.model_precision = model_precision
    obj.input_width = input_width
    obj.input_height = input_height
    obj.nms_thresh = float(nms_thresh)
    obj.conf_thresh = float(conf_thresh)
    obj.license_package = data["license_package"]
    obj.remark = data["remark"]


def _algorithm_persist_added_algorithm(data, *, model_path: str, dll_path: str, object_str: str) -> None:
    """处理算法`persist``added`算法。"""
    with transaction.atomic():
        obj = AlgorithmModel()
        obj.sort = 0
        obj.code = data["code"]
        obj.state = 0
        _algorithm_apply_form_data(
            obj,
            data,
            model_path=model_path,
            dll_path=dll_path,
            object_str=object_str,
        )
        obj.save()
        create_algorithm_version(obj, note="initial", make_current=True)


def _algorithm_form_message_redirect(*, is_success: bool, popup_mode: bool, failure_path: str) -> str:
    """处理算法表单`message``redirect`。"""
    if is_success:
        return PATH_ALGORITHM_INDEX
    if popup_mode:
        separator = "&" if "?" in failure_path else "?"
        return failure_path + separator + "popup=1"
    return failure_path


def _algorithm_form_context(*, handle: str, popup_mode: bool, obj):
    """处理算法表单`context`。"""
    return {
        "handle": handle,
        "popup_mode": popup_mode,
        "obj": obj,
        "algorithm_types": AlgorithmModel.ALGORITHM_TYPE_CHOICES,
        "basic_sources": AlgorithmModel.BASIC_SOURCE_CHOICES,
        "builtin_behaviors": AlgorithmModel.BEHAVIOR_BUILTIN_CHOICES,
        "algorithm_subtypes": AlgorithmModel.ALGORITHM_SUBTYPE_CHOICES,
        "model_precisions": AlgorithmModel.MODEL_PRECISION_CHOICES,
        "license_packages": [
            {"code": "core", "name": "core（核心）"},
            {"code": "ppe", "name": "ppe（劳保/PPE）"},
            {"code": "behavior_pro", "name": "behavior_pro（行为增强）"},
        ],
    }


def _algorithm_sync_edit_versions(obj, *, before_snapshot, had_versions: bool) -> None:
    """处理算法`sync`编辑`versions`。"""
    after_snapshot = build_algorithm_snapshot(obj)
    if not had_versions:
        if snapshots_equal(before_snapshot, after_snapshot):
            create_algorithm_version(obj, snapshot=after_snapshot, note="bootstrap", make_current=True)
            return
        create_algorithm_version(obj, snapshot=before_snapshot, note="legacy-baseline", make_current=False)
        create_algorithm_version(obj, snapshot=after_snapshot, note="edited", make_current=True)
        return
    if not snapshots_equal(before_snapshot, after_snapshot):
        create_algorithm_version(obj, snapshot=after_snapshot, note="edited", make_current=True)
        return
    ensure_algorithm_version_registry(obj, note="edit-bootstrap")


def _algorithm_persist_edited_algorithm(obj, data, *, model_path: str, dll_path: str, object_str: str) -> None:
    """处理算法`persist``edited`算法。"""
    before_snapshot = build_algorithm_snapshot(obj)
    had_versions = AlgorithmModelVersion.objects.filter(algorithm=obj).exists()

    with transaction.atomic():
        _algorithm_apply_form_data(
            obj,
            data,
            model_path=model_path,
            dll_path=dll_path,
            object_str=object_str,
        )
        obj.save()
        _algorithm_sync_edit_versions(
            obj,
            before_snapshot=before_snapshot,
            had_versions=had_versions,
        )


def _algorithm_add_post_response(request):
    """返回算法新增`post`响应。"""
    params = f_parsePostParams(request)
    popup_mode = _popup_mode_enabled(params)
    data = _algorithm_parse_form_data(params)
    is_success = False
    msg = "未知错误"

    try:
        _algorithm_validate_add_request(data)
        model_path, dll_path, object_str = _algorithm_add_artifacts(request, data)
        _algorithm_persist_added_algorithm(
            data,
            model_path=model_path,
            dll_path=dll_path,
            object_str=object_str,
        )
        msg = "添加成功"
        is_success = True
    except Exception as exc:
        msg = str(exc)

    redirect_url = _algorithm_form_message_redirect(
        is_success=is_success,
        popup_mode=popup_mode,
        failure_path="/algorithm/add",
    )
    return render(
        request,
        TEMPLATE_MESSAGE,
        {"msg": msg, "is_success": is_success, "redirect_url": redirect_url},
    )


def _algorithm_add_get_response(request):
    """返回算法新增`get`响应。"""
    params = f_parseGetParams(request)
    popup_mode = _popup_mode_enabled(params)
    context = _algorithm_form_context(
        handle="add",
        popup_mode=popup_mode,
        obj={
            "sort": 0,
            "algorithm_type": 0,
            "basic_source": "model",
            "algorithm_subtype": "detection",
            "max_control_count": 0,
            "license_package": "core",
        },
    )
    return render(request, "app/algorithm/add.html", context)


def add(request):
    """处理新增。"""
    if request.method == "POST":
        return _algorithm_add_post_response(request)
    return _algorithm_add_get_response(request)


def _algorithm_edit_post_response(request):
    """返回算法编辑`post`响应。"""
    params = f_parsePostParams(request)
    popup_mode = _popup_mode_enabled(params)
    data = _algorithm_parse_form_data(params)
    is_success = False
    msg = "未知错误"

    try:
        obj = _algorithm_validate_edit_request(data)
        data["algorithm_subtype"] = _algorithm_normalize_edit_subtype(
            algorithm_type=data["algorithm_type"],
            algorithm_subtype=data["algorithm_subtype"],
            existing_subtype=getattr(obj, "algorithm_subtype", ""),
        )
        model_path, dll_path, object_str = _algorithm_edit_artifacts(
            request,
            data,
            current_model_path=str(getattr(obj, "model_path", "") or ""),
            current_dll_path=str(getattr(obj, "dll_path", "") or ""),
        )
        _algorithm_persist_edited_algorithm(
            obj,
            data,
            model_path=model_path,
            dll_path=dll_path,
            object_str=object_str,
        )
        msg = "编辑成功"
        is_success = True
    except Exception as exc:
        msg = str(exc)

    redirect_url = _algorithm_form_message_redirect(
        is_success=is_success,
        popup_mode=popup_mode,
        failure_path=f"/algorithm/edit?code={data['code']}",
    )
    return render(
        request,
        TEMPLATE_MESSAGE,
        {"msg": msg, "is_success": is_success, "redirect_url": redirect_url},
    )


def _algorithm_edit_get_response(request):
    """返回算法编辑`get`响应。"""
    params = f_parseGetParams(request)
    popup_mode = _popup_mode_enabled(params)
    code = params.get("code")
    if not code:
        return redirect(PATH_ALGORITHM_INDEX)

    obj = AlgorithmModel.objects.filter(code=code).first()
    if not obj:
        return render(
            request,
            TEMPLATE_MESSAGE,
            {"msg": "该算法不存在", "is_success": False, "redirect_url": PATH_ALGORITHM_INDEX},
        )
    return render(
        request,
        "app/algorithm/add.html",
        _algorithm_form_context(handle="edit", popup_mode=popup_mode, obj=obj),
    )


def edit(request):
    """处理编辑。"""
    if request.method == "POST":
        return _algorithm_edit_post_response(request)
    return _algorithm_edit_get_response(request)


def versions(request):
    """处理`versions`。"""
    params = f_parseGetParams(request)
    code = str(params.get("code") or "").strip()
    if not code:
        return redirect(PATH_ALGORITHM_INDEX)

    obj = AlgorithmModel.objects.filter(code=code).first()
    if not obj:
        return render(request, TEMPLATE_MESSAGE, {"msg": "该算法不存在", "is_success": False, "redirect_url": PATH_ALGORITHM_INDEX})

    ensure_algorithm_version_registry(obj, note="versions-bootstrap")
    version_rows = list(AlgorithmModelVersion.objects.filter(algorithm=obj).order_by("-version_no", "-id"))
    for row in version_rows:
        gray_codes = str(getattr(row, "gray_control_codes", "") or "").strip()
        row.gray_control_code_list = [x for x in gray_codes.split(",") if x]

    context = {
        "obj": obj,
        "versions": version_rows,
        "current_version": next((x for x in version_rows if getattr(x, "is_current", False)), None),
        "gray_version": next((x for x in version_rows if getattr(x, "is_gray", False)), None),
    }
    return render(request, "app/algorithm/versions.html", context)


def api_open_version_activate(request):
    """处理 `openVersionActivate` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or "").strip()
    version_id = str(params.get("version_id") or "").strip()
    if not code or not version_id:
        return f_responseJson({"code": 0, "msg": "code and version_id are required"})

    algo = AlgorithmModel.objects.filter(code=code).first()
    if not algo:
        return f_responseJson({"code": 0, "msg": MSG_ALGORITHM_NOT_FOUND})

    ensure_algorithm_version_registry(algo, note="activate-bootstrap")
    version = AlgorithmModelVersion.objects.filter(algorithm=algo, id=version_id).first()
    if not version:
        return f_responseJson({"code": 0, "msg": "版本不存在"})

    version = activate_algorithm_version(version)
    return f_responseJson({"code": 1000, "msg": f"已切换到 {version.version_name}"})
api_openVersionActivate = api_open_version_activate  # pragma: no cover - compatibility alias


def api_open_version_rollback(request):
    """处理 `openVersionRollback` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or "").strip()
    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    algo = AlgorithmModel.objects.filter(code=code).first()
    if not algo:
        return f_responseJson({"code": 0, "msg": MSG_ALGORITHM_NOT_FOUND})

    version = rollback_algorithm_version(algo)
    if not version:
        return f_responseJson({"code": 0, "msg": "没有可回滚版本"})
    return f_responseJson({"code": 1000, "msg": f"已回滚到 {version.version_name}"})
api_openVersionRollback = api_open_version_rollback  # pragma: no cover - compatibility alias


def api_open_version_gray(request):
    """处理 `openVersionGray` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or "").strip()
    version_id = str(params.get("version_id") or "").strip()
    gray_control_codes = str(params.get("gray_control_codes") or "").strip()
    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    algo = AlgorithmModel.objects.filter(code=code).first()
    if not algo:
        return f_responseJson({"code": 0, "msg": MSG_ALGORITHM_NOT_FOUND})

    ensure_algorithm_version_registry(algo, note="gray-bootstrap")
    version = None
    if version_id:
        version = AlgorithmModelVersion.objects.filter(algorithm=algo, id=version_id).first()
        if not version:
            return f_responseJson({"code": 0, "msg": "版本不存在"})

    try:
        version = set_algorithm_gray_version(algo, version=version, gray_control_codes=gray_control_codes)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    if not version:
        return f_responseJson({"code": 1000, "msg": "已清空灰度版本"})
    return f_responseJson({"code": 1000, "msg": f"已设置灰度版本 {version.version_name}"})
api_openVersionGray = api_open_version_gray  # pragma: no cover - compatibility alias


def api_open_del(request):
    """处理 `openDel` 接口请求。"""
    ret = False
    if request.method == 'POST':
        params = f_parsePostParams(request)
        code = params.get("code")
        controls = Control.objects.filter(algorithm_code=code)

        if len(controls) == 0:
            obj = AlgorithmModel.objects.filter(code=code)
            if len(obj) > 0:
                obj = obj[0]
                if obj.delete():
                    ret = True
                    msg = "success"
                else:
                    msg = "failed to delete model"
            else:
                msg = "the data does not exist"
        else:
            msg = "有%d条布控在使用该算法，无法删除"%len(controls)

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": 1000 if ret else 0,
        "msg": msg
    }
    return f_responseJson(res)
api_openDel = api_open_del  # pragma: no cover - compatibility alias


_ANALYZER_DEVICE_SUFFIX_MAP = {
    "CPU": "",
    "GPU": "_gpu",
    "TRT": "_trt",
    "AUTO": "_auto",
    "NPU": "_npu",
}
_SUPPORTED_ANALYZER_SUBTYPES = ("detection", "classification", "tracking", "behavior", "ocr")


def _algorithm_normalize_analyzer_subtype(algorithm_subtype: str, default: str = "") -> str:
    """处理算法归一化分析器`subtype`。"""
    algorithm_subtype = str(algorithm_subtype or "").strip().lower()
    if algorithm_subtype in _SUPPORTED_ANALYZER_SUBTYPES:
        return algorithm_subtype
    default = str(default or "").strip().lower()
    if default in _SUPPORTED_ANALYZER_SUBTYPES:
        return default
    return ""


def _algorithm_analyzer_code(code: str, device: str) -> str:
    """处理算法分析器编码。"""
    analyzer_code = str(code or "").strip()
    suffix = _ANALYZER_DEVICE_SUFFIX_MAP.get(str(device or "CPU").strip().upper(), "")
    if suffix and not analyzer_code.lower().endswith(suffix):
        return f"{analyzer_code}{suffix}"
    return analyzer_code


def _algorithm_resolve_analyzer_abs_path(model_path: str) -> str:
    """返回算法`resolve`分析器绝对路径路径。"""
    abs_path = resolve_upload_url_to_abs_path(
        model_path,
        upload_dir=getattr(g_config, "uploadDir", ""),
        upload_www_prefix=getattr(g_config, "uploadDir_www", PATH_STATIC_UPLOAD),
    )
    if not abs_path:
        raise ValueError("无法解析模型文件路径")
    return abs_path


def _algorithm_model_class_names(algo) -> list:
    """处理算法模型`class``names`。"""
    class_names = [x.strip() for x in str(getattr(algo, "object_str", "") or "").split(",") if x.strip()]
    if not class_names:
        raise ValueError("请先在算法里配置检测目标（object_str）")
    return class_names


def _algorithm_resolve_analyzer_load_source(algo, *, default_subtype: str = ""):
    """处理算法`resolve`分析器`load`来源。"""
    algo_type = int(getattr(algo, "algorithm_type", 0) or 0)
    algo_subtype = _algorithm_normalize_analyzer_subtype(
        getattr(algo, "algorithm_subtype", ""),
        default=default_subtype,
    )

    if algo_type == 0 and getattr(algo, "basic_source", "model") == "api":
        raise ValueError("该基础算法为 API 推理，无需预热加载")

    if algo_type == 0:
        model_path = str(getattr(algo, "model_path", "") or "").strip()
        if not model_path:
            raise ValueError("该算法未配置模型文件")
        parts = split_paired_path(model_path)
        model_path = parts[0] if parts else model_path
        class_names = None if algo_subtype == "tracking" else _algorithm_model_class_names(algo)
        return algo_subtype, _algorithm_resolve_analyzer_abs_path(model_path), class_names

    dll_path = str(getattr(algo, "dll_path", "") or "").strip()
    if not dll_path:
        raise ValueError("该行为算法未配置动态库（dll/so/dylib）")
    return algo_subtype, _algorithm_resolve_analyzer_abs_path(dll_path), None


def _algorithm_runtime_device_info():
    """返回算法运行时设备信息。"""
    try:
        info_state, _, info = g_analyzer.device_info(timeout_seconds=2)
    except Exception:
        return False, {}
    if not (info_state and isinstance(info, dict) and int(info.get("code") or 0) == 1000):
        return False, {}
    return True, info


def _algorithm_onnx_runtime_device_error(*, device: str, providers) -> str:
    """处理算法`onnx`运行时设备错误。"""
    try:
        providers = [str(p) for p in providers]
    except Exception:
        providers = []
    provider_set = {p for p in providers if p}
    if device == "GPU" and "CUDAExecutionProvider" not in provider_set:
        return "当前 Analyzer 不支持 GPU：CUDAExecutionProvider not available（onnxProviders=%s）" % (
            ",".join(sorted(provider_set)) or "-"
        )
    if device == "TRT" and "TensorrtExecutionProvider" not in provider_set:
        return "当前 Analyzer 不支持 TRT：TensorrtExecutionProvider not available（onnxProviders=%s）" % (
            ",".join(sorted(provider_set)) or "-"
        )
    if device not in ("CPU", "AUTO", "GPU", "TRT"):
        return "当前 Analyzer 不支持 ONNX Runtime 设备：%s" % device
    return ""


def _algorithm_openvino_device_error(*, device: str, devices) -> str:
    """处理算法`openvino`设备错误。"""
    try:
        devices = [str(d) for d in devices]
    except Exception:
        devices = []
    target = str(device or "").strip().upper()
    if target == "CPU":
        return ""
    for device_name in devices:
        normalized = str(device_name or "").strip().upper()
        if normalized == target or normalized.startswith(target + "."):
            return ""
    return "当前 Analyzer 不支持 OpenVINO 设备：%s（openvinoDevices=%s）" % (
        str(device or "").strip() or "-",
        ",".join([x for x in devices if x]) or "-",
    )


def _algorithm_runtime_device_support_error(*, abs_path: str, device: str) -> str:
    """处理算法运行时设备`support`错误。"""
    device = str(device or "CPU").strip().upper()
    if device == "CPU":
        return ""

    try:
        encrypt_suffix = getattr(g_config, "modelEncryptSuffix", ".enc") or ".enc"
    except Exception:
        encrypt_suffix = ".enc"
    model_ext, _is_enc = _effective_model_ext(abs_path, encrypt_suffix)
    if model_ext not in (MODEL_EXT_ONNX, ".xml"):
        return ""

    info_state, info = _algorithm_runtime_device_info()
    if not info_state:
        return ""
    if model_ext == MODEL_EXT_ONNX:
        return _algorithm_onnx_runtime_device_error(device=device, providers=info.get("onnxProviders") or [])
    return _algorithm_openvino_device_error(device=device, devices=info.get("openvinoDevices") or [])


def _algorithm_model_concurrency(algo) -> int:
    """处理算法模型`concurrency`。"""
    model_concurrency = int(getattr(algo, "model_concurrency", 1) or 1)
    if model_concurrency < 1:
        model_concurrency = 1
    return model_concurrency


def _algorithm_analyzer_result(*, state, msg, success_text: str, success_if_contains: str) -> dict:
    """返回算法分析器结果。"""
    state = bool(state)
    if (not state) and success_if_contains and success_if_contains in str(msg or "").lower():
        state = True
    return {"code": 1000 if state else 0, "msg": str(msg or (success_text if state else "error"))}


def _algorithm_image_dimension_error(width: int, height: int, max_edge: int = 4096) -> str:
    """处理算法图片`dimension`错误。"""
    if width > max_edge or height > max_edge:
        return f"图片分辨率过大：{width}x{height}，请使用不超过 {max_edge}px 的图片"
    return ""


def _algorithm_test_infer_api_payload(*, code: str, image_b64: str, algo) -> dict:
    """返回算法`test`推理API载荷。"""
    return {
        "image_base64": image_b64,
        "nodeCode": "admin",
        "controlCode": "test",
        "streamCode": "test",
        "streamApp": "test",
        "streamName": "test",
        "flowCode": code,
        "algorithmCode": code,
        "modelClassNames": str(getattr(algo, "object_str", "") or "").strip(),
        "detectClassNames": str(getattr(algo, "object_str", "") or "").strip(),
        "polygonType": 3,
        "polygon": "0,0,1,0,1,1,0,1",
        "algorithmParams": {
            "confThresh": float(getattr(algo, "conf_thresh", 0.25) or 0.25),
            "nmsThresh": float(getattr(algo, "nms_thresh", 0.45) or 0.45),
            "modelConcurrency": int(getattr(algo, "model_concurrency", 1) or 1),
            "inputWidth": int(getattr(algo, "input_width", 640) or 640),
            "inputHeight": int(getattr(algo, "input_height", 640) or 640),
            "modelPrecision": str(getattr(algo, "model_precision", "FP32") or "FP32"),
        },
        "extensions": {"source": "admin_test"},
    }


def _algorithm_test_infer_image_bytes(image_file) -> bytes:
    """返回算法`test`推理图片字节数。"""
    try:
        return image_file.read()
    except Exception:
        return b""


def _algorithm_test_infer_image_error(image_bytes: bytes) -> str:
    """处理算法`test`推理图片错误。"""
    if not image_bytes:
        return "image is empty"
    try:
        with Image.open(BytesIO(image_bytes)) as image_obj:
            width, height = image_obj.size
    except Exception:
        return ""
    return _algorithm_image_dimension_error(width, height)


def _algorithm_test_infer_api_response(*, code: str, image_b64: str, algo):
    """返回算法`test`推理API响应。"""
    api_url = str(getattr(algo, "api_url", "") or "").strip()
    if not api_url:
        return f_responseJson({"code": 0, "msg": "api_url is required"})

    payload = _algorithm_test_infer_api_payload(code=code, image_b64=image_b64, algo=algo)
    try:
        response = requests.post(
            api_url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload, ensure_ascii=False),
            timeout=(2, 10),
        )
    except Exception as exc:
        return f_responseJson({"code": 0, "msg": str(exc)})

    if not response.status_code:
        return f_responseJson({"code": 0, "msg": "request failed"})

    try:
        api_data = response.json()
    except Exception:
        return f_responseJson({"code": 0, "msg": "invalid api response"})

    ok = bool(api_data.get("code") == 1000)
    return f_responseJson({"code": 1000 if ok else 0, "msg": api_data.get("msg", ""), "data": api_data})


def _algorithm_test_infer_local_response(*, code: str, device: str, image_b64: str, algo):
    """返回算法`test`推理`local`响应。"""
    try:
        algo_subtype, abs_path, class_names = _algorithm_resolve_analyzer_load_source(
            algo,
            default_subtype="detection",
        )
    except ValueError as exc:
        return f_responseJson({"code": 0, "msg": str(exc)})

    device_error = _algorithm_runtime_device_support_error(abs_path=abs_path, device=device)
    if device_error:
        return f_responseJson({"code": 0, "msg": device_error})

    analyzer_code = _algorithm_analyzer_code(code, device)
    load_state, load_msg = g_analyzer.algorithm_load(
        code=analyzer_code,
        modelPath=abs_path,
        classNames=class_names,
        device=device or "CPU",
        modelConcurrency=_algorithm_model_concurrency(algo),
        algorithmSubtype=algo_subtype or None,
    )
    load_result = _algorithm_analyzer_result(
        state=load_state,
        msg=load_msg,
        success_text="success",
        success_if_contains="already loaded",
    )
    if load_result["code"] != 1000:
        return f_responseJson({"code": 0, "msg": str(load_result["msg"] or "load failed")})

    test_state, test_msg, test_data = g_analyzer.algorithm_test_infer(
        analyzer_code,
        image_b64,
        confThresh=float(getattr(algo, "conf_thresh", 0.25) or 0.25),
        nmsThresh=float(getattr(algo, "nms_thresh", 0.45) or 0.45),
        timeout_seconds=30,
    )
    if not test_state:
        return f_responseJson({"code": 0, "msg": str(test_msg or "infer failed")})
    return f_responseJson({"code": 1000, "msg": "success", "data": test_data})


def api_open_analyzer_load(request):
    """
    运维：把某个算法（本地模型/插件）预热到 Analyzer（动态加载）。
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or "").strip()
    device = str(params.get("device") or "CPU").strip().upper()

    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    algo = AlgorithmModel.objects.filter(code=code).first()
    if not algo:
        return f_responseJson({"code": 0, "msg": MSG_ALGORITHM_NOT_FOUND})

    try:
        algo_subtype, abs_path, class_names = _algorithm_resolve_analyzer_load_source(algo)
    except ValueError as exc:
        return f_responseJson({"code": 0, "msg": str(exc)})

    device_error = _algorithm_runtime_device_support_error(abs_path=abs_path, device=device)
    if device_error:
        return f_responseJson({"code": 0, "msg": device_error})

    state, msg = g_analyzer.algorithm_load(
        code=_algorithm_analyzer_code(code, device),
        modelPath=abs_path,
        classNames=class_names,
        device=device or "CPU",
        modelConcurrency=_algorithm_model_concurrency(algo),
        algorithmSubtype=algo_subtype or None,
    )
    return f_responseJson(
        _algorithm_analyzer_result(
            state=state,
            msg=msg,
            success_text="success",
            success_if_contains="already loaded",
        )
    )
api_openAnalyzerLoad = api_open_analyzer_load  # pragma: no cover - compatibility alias


def api_open_analyzer_unload(request):
    """
    运维：从 Analyzer 卸载算法（动态卸载，refCount=0 才允许）。
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or "").strip()
    device = str(params.get("device") or "CPU").strip().upper()

    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    state, msg = g_analyzer.algorithm_unload(_algorithm_analyzer_code(code, device))
    return f_responseJson(
        _algorithm_analyzer_result(
            state=state,
            msg=msg,
            success_text="success",
            success_if_contains="not found",
        )
    )
api_openAnalyzerUnload = api_open_analyzer_unload  # pragma: no cover - compatibility alias


def api_open_test_infer(request):
    """
    v4.18: 后台算法接入验收 - 上传图片做一次推理测试
    - 基础算法 + basic_source=api：直接调用外部 api_url（协议 v2）
    - 本地模型/插件：先确保 Analyzer 已加载，再调用 Analyzer /api/algorithm/testInfer
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    code = str(request.POST.get("code") or "").strip()
    device = str(request.POST.get("device") or "CPU").strip().upper()
    image_file = request.FILES.get("image")

    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})
    if not image_file:
        return f_responseJson({"code": 0, "msg": "image is required"})

    algo = AlgorithmModel.objects.filter(code=code).first()
    if not algo:
        return f_responseJson({"code": 0, "msg": MSG_ALGORITHM_NOT_FOUND})

    image_bytes = _algorithm_test_infer_image_bytes(image_file)
    image_error = _algorithm_test_infer_image_error(image_bytes)
    if image_error:
        return f_responseJson({"code": 0, "msg": image_error})

    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    # ======== API 算法（直接调用外部服务）========
    is_basic_api = (getattr(algo, "algorithm_type", 0) == 0 and getattr(algo, "basic_source", "model") == "api")
    if is_basic_api:
        return _algorithm_test_infer_api_response(code=code, image_b64=image_b64, algo=algo)

    return _algorithm_test_infer_local_response(code=code, device=device, image_b64=image_b64, algo=algo)
api_openTestInfer = api_open_test_infer  # pragma: no cover - compatibility alias
