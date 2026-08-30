import json
import logging
import math
import os
import secrets
import time
from datetime import datetime

from django.shortcuts import render

from app.models import Alarm, Stream
from app.utils.SafeLog import safe_log_text
from app.utils.UploadSecurity import atomic_write_bytes, decode_base64_limited, detect_raster_extension
from app.views.ViewsBase import f_responseJson, g_config
from framework.settings import PROJECT_VERSION


logger = logging.getLogger(__name__)
MAX_CALLBACK_IMAGE_BYTES = 20 * 1024 * 1024
MAX_CALLBACK_DETECTIONS = 1000
MAX_CALLBACK_FRAME_INDEX = (1 << 63) - 1
MAX_CALLBACK_TIMESTAMP = 253402300799

MSG_METHOD_NOT_ALLOWED = "Method not allowed"
def _algo_callback_error(msg: str):
    """处理`algo`回调错误。"""
    return f_responseJson({"code": 0, "msg": str(msg or "")})


def _validate_detection_confidence(idx: int, detection: dict):
    """校验`detection``confidence`。"""
    if "confidence" not in detection:
        return None

    conf = detection.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return f"detections[{idx}].confidence must be a number"
    if not math.isfinite(float(conf)):
        return f"detections[{idx}].confidence must be finite"
    if conf < 0 or conf > 1:
        return f"detections[{idx}].confidence must be between 0 and 1"
    return None


def _validate_detection_bbox(idx: int, detection: dict):
    """校验`detection``bbox`。"""
    if "bbox" not in detection:
        return None

    bbox = detection.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return f"detections[{idx}].bbox must be an array of 4 numbers [x1, y1, x2, y2]"

    for i, val in enumerate(bbox):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return f"detections[{idx}].bbox[{i}] must be a number"
        if not math.isfinite(float(val)):
            return f"detections[{idx}].bbox[{i}] must be finite"

    return None


def _validate_detection_item(idx: int, detection):
    """校验`detection``item`。"""
    if not isinstance(detection, dict):
        return f"detections[{idx}] must be an object"

    if "class_name" not in detection:
        return f"detections[{idx}].class_name is required"
    if not isinstance(detection.get("class_name"), str):
        return f"detections[{idx}].class_name must be a string"
    class_name = detection.get("class_name")
    if not class_name.strip():
        return f"detections[{idx}].class_name is required"
    if len(class_name) > 128:
        return f"detections[{idx}].class_name is too long"
    if any(ord(char) < 32 or ord(char) == 127 for char in class_name):
        return f"detections[{idx}].class_name contains control characters"

    err = _validate_detection_confidence(idx, detection)
    if err:
        return err

    return _validate_detection_bbox(idx, detection)


def _parse_algorithm_callback_payload(data: dict):
    # 必填字段验证
    """解析算法回调载荷。"""
    control_code = data.get("control_code")
    if not control_code:
        return None, "control_code is required"
    if not isinstance(control_code, str) or len(control_code) == 0:
        return None, "control_code must be a non-empty string"
    try:
        from app.utils.Security import validate_control_code

        control_code = validate_control_code(control_code)
    except ValueError:
        return None, "control_code is invalid"

    # 可选字段验证
    frame_index = data.get("frame_index", 0)
    if (
        isinstance(frame_index, bool)
        or not isinstance(frame_index, int)
        or not 0 <= frame_index <= MAX_CALLBACK_FRAME_INDEX
    ):
        return None, "frame_index must be a non-negative integer"

    timestamp = data.get("timestamp", 0)
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not math.isfinite(float(timestamp))
        or not 0 <= timestamp <= MAX_CALLBACK_TIMESTAMP
    ):
        return None, "timestamp must be a non-negative number"

    detections = data.get("detections", [])
    if not isinstance(detections, list):
        return None, "detections must be an array"
    if len(detections) > MAX_CALLBACK_DETECTIONS:
        return None, "detections contains too many items"

    for idx, detection in enumerate(detections):
        err = _validate_detection_item(idx, detection)
        if err:
            return None, err

    trigger_alarm = data.get("trigger_alarm", False)
    if not isinstance(trigger_alarm, bool):
        return None, "trigger_alarm must be a boolean"

    image_base64 = data.get("image_base64", "")
    if not isinstance(image_base64, str):
        return None, "image_base64 must be a string"
    max_encoded = ((MAX_CALLBACK_IMAGE_BYTES + 2) // 3) * 4
    if len(image_base64) > max_encoded + 256:
        return None, "image_base64 is too large"

    return (control_code, frame_index, timestamp, detections, trigger_alarm, image_base64), None



def _build_callback_alarm_desc(detections):
    """构建回调告警`desc`。"""
    class_names = []
    for item in detections or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("class_name") or "").strip()
        if not name:
            continue
        class_names.append(name)

    if not class_names:
        return "developer callback alarm"
    return ", ".join(class_names[:5])


def _save_callback_alarm_image(control_code, image_base64, image_ext="jpg"):
    """保存回调告警图片。"""
    from app.utils.Security import validate_control_code, validate_upload_rel_path, resolve_under_base

    if not image_base64:
        return ""

    control_code = validate_control_code(control_code)
    data_bytes = decode_base64_limited(image_base64, max_bytes=MAX_CALLBACK_IMAGE_BYTES)
    detected_ext = detect_raster_extension(data_bytes[:16])
    requested_ext = str(image_ext or "").strip().lower().lstrip(".")
    if requested_ext not in ("", "jpg", "jpeg") and requested_ext != detected_ext:
        raise ValueError("callback image extension does not match its content")

    day = datetime.now().strftime("%Y%m%d")
    filename = f"img_{time.time_ns()}_{secrets.token_hex(6)}.{detected_ext}"
    rel_path = f"alarm/{control_code}/{day}/{filename}"
    rel_path = validate_upload_rel_path(rel_path, required_prefix="alarm/")
    abs_path = resolve_under_base(g_config.uploadDir, rel_path)
    atomic_write_bytes(
        abs_path,
        data_bytes,
        allowed_root=g_config.uploadDir,
        max_bytes=MAX_CALLBACK_IMAGE_BYTES,
        media_extension=detected_ext,
    )
    return rel_path


def _resolve_stream_context_for_alarm(control):
    """解析并返回流`context``for`告警。"""
    stream = Stream.objects.filter(app=control.stream_app, name=control.stream_name).first()
    if not stream:
        return "", ""
    return str(getattr(stream, "code", "") or ""), str(getattr(stream, "pull_stream_url", "") or "")


def _resolve_upload_abs_path(rel_path: str) -> str:
    """解析并返回上传绝对路径路径。"""
    if not rel_path:
        return ""
    from app.utils.Security import resolve_under_base

    try:
        return resolve_under_base(g_config.uploadDir, rel_path)
    except Exception:
        return ""


def _remove_file_best_effort(filepath: str) -> None:
    """尽力处理`remove`文件。"""
    try:
        if filepath and os.path.isfile(filepath):
            os.remove(filepath)
    except Exception:
        logger.debug("suppressed exception in app/views/DeveloperView.py:174", exc_info=True)


def _allow_store_callback_alarm(
    control,
    *,
    desc: str,
    stream_code: str,
    stream_url: str,
    image_path: str,
    image_base64,
    metadata_obj: dict,
) -> bool:
    """处理允许`store`回调告警。"""
    from app.utils.AlarmPrecheck import should_store_alarm

    image_abs_path = _resolve_upload_abs_path(image_path)
    try:
        allow_store, _ = should_store_alarm(
            g_config,
            control_code=control.code,
            desc=desc,
            alarm_type="developerCallback",
            algorithm_code=control.algorithm_code,
            object_code=control.object_code,
            recognition_region=control.polygon,
            stream_code=stream_code,
            stream_app=control.stream_app,
            stream_name=control.stream_name,
            stream_url=stream_url,
            image_path=image_path,
            image_abs_path=image_abs_path,
            image_base64=image_base64,
            metadata=metadata_obj,
        )
    except Exception:
        return True

    if allow_store:
        return True
    _remove_file_best_effort(image_abs_path)
    return False


def _emit_alarm_created_event(
    control,
    *,
    alarm,
    desc: str,
    now_date,
    image_path: str,
    metadata_obj: dict,
    detections,
) -> None:
    """处理`emit`告警`created`事件。"""
    from app.utils.AlarmEventBus import (
        AlarmOutboxEnqueueError,
        build_alarm_created_event,
        enqueue_alarm_event_outbox,
    )
    from app.utils.BackgroundServices import get_alarm_sink_dispatcher

    payload = build_alarm_created_event(
        g_config,
        legacy_event="alarm_algorithmCallback",
        event_source="algorithmCallback",
        timestamp=now_date,
        alarm_id=alarm.id,
        control_code=control.code,
        desc=desc,
        image_path=image_path,
        video_path="",
        image_url=(g_config.uploadDir_www + image_path) if image_path else "",
        video_url="",
        extra={
            "algorithm_code": alarm.algorithm_code,
            "object_code": alarm.object_code,
            "recognition_region": alarm.recognition_region,
            "class_thresh": alarm.class_thresh,
            "overlap_thresh": alarm.overlap_thresh,
            "min_interval": alarm.min_interval,
            "stream_code": alarm.stream_code,
            "stream_app": alarm.stream_app,
            "stream_name": alarm.stream_name,
            "stream_url": alarm.stream_url,
            "metadata": metadata_obj,
            "detections": detections,
        },
    )
    try:
        if getattr(g_config, "alarmOutboxEnabled", True):
            enqueue_alarm_event_outbox(g_config, payload, alarm_id=alarm.id, control_code=control.code)
            return
    except AlarmOutboxEnqueueError:
        event_id = safe_log_text(payload.get("event_id", ""), max_len=128)
        control_code = safe_log_text(control.code, max_len=128)
        logger.exception(
            "Alarm outbox enqueue failed event_id=%r alarm_id=%s control_code=%r",
            event_id,
            alarm.id,
            control_code,
            extra={"alarm_event_id": event_id, "alarm_id": alarm.id, "control_code": control_code},
        )
        raise
    except Exception:
        return

    dispatcher = get_alarm_sink_dispatcher()
    if dispatcher:
        dispatcher.enqueue(payload)


def _create_callback_alarm(control, *, frame_index, timestamp, detections, image_base64):
    """创建回调告警。"""
    stream_code, stream_url = _resolve_stream_context_for_alarm(control)

    desc = _build_callback_alarm_desc(detections)
    metadata_obj = {
        "event_source": "developer.algorithmCallback",
        "frame_index": frame_index,
        "timestamp": timestamp,
        "detections": detections,
    }

    image_path = _save_callback_alarm_image(control.code, image_base64, image_ext="jpg")
    if not _allow_store_callback_alarm(
        control,
        desc=desc,
        stream_code=stream_code,
        stream_url=stream_url,
        image_path=image_path,
        image_base64=image_base64,
        metadata_obj=metadata_obj,
    ):
        return None

    now_date = datetime.now()
    alarm = Alarm()
    alarm.sort = 0
    alarm.control_code = control.code
    alarm.desc = desc
    alarm.detail_desc = desc
    alarm.alarm_type = "developerCallback"
    alarm.alarm_level = 1
    alarm.algorithm_code = control.algorithm_code
    alarm.object_code = control.object_code
    alarm.recognition_region = control.polygon
    alarm.class_thresh = control.class_thresh
    alarm.overlap_thresh = control.overlap_thresh
    alarm.min_interval = control.min_interval
    alarm.stream_code = stream_code
    alarm.stream_app = control.stream_app
    alarm.stream_name = control.stream_name
    alarm.stream_url = stream_url
    alarm.image_path = image_path
    alarm.metadata = json.dumps(metadata_obj, ensure_ascii=False)
    alarm.create_time = now_date
    alarm.state = 0
    alarm.save()

    _emit_alarm_created_event(
        control,
        alarm=alarm,
        desc=desc,
        now_date=now_date,
        image_path=image_path,
        metadata_obj=metadata_obj,
        detections=detections,
    )

    return alarm


def index(request):
    """开发者文档首页"""
    try:
        api_base_url = request.build_absolute_uri("/").rstrip("/")
    except Exception:
        api_base_url = "//%s" % request.get_host()
    context = {
        "api_base_url": api_base_url,
        "version": PROJECT_VERSION,
    }
    return render(request, 'app/developer/index.html', context)


def api_algorithm_callback(request):
    """
    算法回调接口 - 接收算法处理结果
    用于二次开发时，算法处理完成后回调此接口上报检测结果

    请求参数 (POST JSON):
    {
        "control_code": "布控编号",
        "frame_index": 帧序号,
        "timestamp": 时间戳,
        "detections": [
            {
                "class_name": "目标类别",
                "confidence": 置信度,
                "bbox": [x1, y1, x2, y2],
                "extra": {}
            }
        ],
        "image_base64": "检测图片base64(可选)",
        "trigger_alarm": true/false
    }
    """
    if request.method != 'POST':
        return _algo_callback_error(MSG_METHOD_NOT_ALLOWED)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _algo_callback_error("Invalid JSON format")
    except Exception as e:
        logger.exception("algorithm callback parse failed error_type=%s", type(e).__name__)
        return _algo_callback_error("处理失败")

    parsed, err = _parse_algorithm_callback_payload(data if isinstance(data, dict) else {})
    if err:
        return _algo_callback_error(err)

    control_code, frame_index, timestamp, detections, trigger_alarm, image_base64 = parsed

    from app.models import Control

    try:
        control = Control.objects.filter(code=control_code).first()
        if not control:
            return _algo_callback_error(f"Control '{control_code}' not found")

        logger.debug(
            "[算法回调] control=%r frame=%r detections=%s alarm=%r",
            safe_log_text(control_code, max_len=64),
            int(frame_index),
            len(detections),
            bool(trigger_alarm),
        )

        if trigger_alarm:
            _create_callback_alarm(
                control,
                frame_index=frame_index,
                timestamp=timestamp,
                detections=detections,
                image_base64=image_base64,
            )

        return f_responseJson({"code": 1000, "msg": "success"})

    except Exception as e:
        logger.exception("algorithm callback failed error_type=%s", type(e).__name__)
        return _algo_callback_error("处理失败")
api_algorithmCallback = api_algorithm_callback  # pragma: no cover - compatibility alias


def api_get_stream_info(request):
    """
    获取视频流信息接口 - 供二次开发获取当前布控的视频流
    """
    code = 0
    msg = "error"
    data = []

    if request.method == 'GET':
        from app.models import Control, Stream

        try:
            controls = Control.objects.filter(state=1)  # 获取布控中的任务

            for control in controls:
                stream = Stream.objects.filter(
                    app=control.stream_app,
                    name=control.stream_name
                ).first()

                if stream:
                    data.append({
                        "control_code": control.code,
                        "stream_code": stream.code,
                        "stream_app": stream.app,
                        "stream_name": stream.name,
                        "rtsp_url": stream.pull_stream_url,
                        "algorithm_code": control.algorithm_code,
                        "object_code": control.object_code,
                        "polygon": control.polygon,
                        "min_interval": control.min_interval,
                        "class_thresh": control.class_thresh,
                        "overlap_thresh": control.overlap_thresh
                    })

            code = 1000
            msg = "success"

        except Exception as exc:
            logger.warning("developer stream info failed error_type=%s", type(exc).__name__)
            msg = "获取失败"

    else:
        msg = MSG_METHOD_NOT_ALLOWED

    return f_responseJson({"code": code, "msg": msg, "data": data})
api_getStreamInfo = api_get_stream_info  # pragma: no cover - compatibility alias


def api_get_algorithm_info(request):
    """
    获取算法信息接口 - 供二次开发获取算法配置
    """
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED, "data": []})

    def _serialize_algorithm_info(alg):
        """返回`serialize`算法信息。"""
        type_names = {
            0: "基础算法",
            1: "行为算法",
            2: "业务算法",
        }
        try:
            algo_type = int(getattr(alg, "algorithm_type", 0) or 0)
        except Exception:
            algo_type = 0
        return {
            "code": getattr(alg, "code", ""),
            "name": getattr(alg, "name", ""),
            "type": getattr(alg, "algorithm_type", 0),
            "type_name": type_names.get(algo_type, "未知类型"),
            "api_url": getattr(alg, "api_url", ""),
            "support_direct_api": bool(getattr(alg, "support_direct_api", False)),
            "behavior_api_version": int(getattr(alg, "behavior_api_version", 1) or 1),
            "model_path": getattr(alg, "model_path", ""),
            "dll_path": getattr(alg, "dll_path", ""),
            "builtin_behavior": getattr(alg, "builtin_behavior", ""),
            "object_str": getattr(alg, "object_str", ""),
            "object_count": getattr(alg, "object_count", 0),
        }

    from app.models import AlgorithmModel

    try:
        algorithms = AlgorithmModel.objects.filter(state__gte=0)
        data = [_serialize_algorithm_info(alg) for alg in algorithms]
        return f_responseJson({"code": 1000, "msg": "success", "data": data})
    except Exception as exc:
        logger.warning("developer algorithm info failed error_type=%s", type(exc).__name__)
        return f_responseJson({"code": 0, "msg": "获取失败", "data": []})
api_getAlgorithmInfo = api_get_algorithm_info  # pragma: no cover - compatibility alias
