import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import DatabaseError


EVENT_SCHEMA_V1 = "beacon.event.v1"
EVENT_TYPE_ALARM_CREATED = "alarm.created"


class AlarmOutboxEnqueueError(RuntimeError):
    """Outbox 持久化失败，调用方必须显式处理。"""

    def __init__(self, *, event_id: str, sink_type: str):
        self.event_id = str(event_id or "")
        self.sink_type = str(sink_type or "")
        super().__init__(
            f"alarm outbox enqueue failed: event_id={self.event_id} sink_type={self.sink_type}"
        )


def _is_truthy(value: Any) -> bool:
    """判断`truthy`。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _clean_str(value: Any) -> str:
    """处理清理字符串。"""
    return str(value or "").strip()


def _inject_extra_fields(payload: Dict[str, Any], extra_fields: Dict[str, Any]) -> None:
    # Keep legacy behavior: openAdd historically included extra fields at top-level.
    """返回`inject`额外字段。"""
    for key, value in extra_fields.items():
        if not key:
            continue
        if key in payload:
            continue
        payload[key] = value


def _coerce_int(value: Any, default: int) -> int:
    """处理`coerce`整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _coerce_float(value: Any, default: float) -> float:
    """处理`coerce`浮点数。"""
    try:
        return float(value)
    except Exception:
        return float(default)


def _merge_event_extra_fields(payload: Dict[str, Any], extra: Optional[Dict[str, Any]]) -> None:
    """返回`merge`事件额外字段。"""
    if not isinstance(extra, dict):
        return
    for key, value in extra.items():
        clean_key = str(key or "").strip()
        if not clean_key:
            continue
        payload[clean_key] = value


def _alarm_timestamp(alarm: Any) -> datetime:
    """处理告警`timestamp`。"""
    timestamp = getattr(alarm, "create_time", None)
    if isinstance(timestamp, datetime):
        return timestamp
    return datetime.now()


def _alarm_media_url(upload_dir_www: str, path: str) -> str:
    """返回告警媒体URL。"""
    if not path:
        return ""
    return f"{str(upload_dir_www or '')}{str(path)}"


def build_alarm_created_event(
    config: Any,
    *,
    legacy_event: str,
    event_source: str,
    timestamp: datetime,
    alarm_id: int,
    control_code: str,
    desc: str,
    image_path: str,
    video_path: str,
    image_url: str,
    video_url: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建告警`created`事件。
    
    Build a unified alarm.created event payload while preserving legacy top-level fields.
    
        Notes:
        - Keep `event` for backward compatibility (e.g. alarm_openAdd / alarm_upload)
        - Add v1 schema fields for industrial integrations
        - Put full business payload under `data`
    """
    event_id = str(uuid.uuid4())
    node_code = _clean_str(getattr(config, "code", ""))

    payload: Dict[str, Any] = {
        # New schema fields
        "schema": EVENT_SCHEMA_V1,
        "event_id": event_id,
        "event_type": EVENT_TYPE_ALARM_CREATED,
        "event_source": _clean_str(event_source),
        "timestamp": timestamp.isoformat(),
        "node_code": node_code,
        # Legacy fields (top-level)
        "event": _clean_str(legacy_event),
        "alarm_id": int(alarm_id or 0),
        "control_code": _clean_str(control_code),
        "desc": _clean_str(desc),
        "image_path": _clean_str(image_path),
        "video_path": _clean_str(video_path),
        "image_url": _clean_str(image_url),
        "video_url": _clean_str(video_url),
    }

    extra_fields: Dict[str, Any] = dict(extra or {})
    _inject_extra_fields(payload, extra_fields)

    data: Dict[str, Any] = {
        "alarm_id": payload["alarm_id"],
        "control_code": payload["control_code"],
        "desc": payload["desc"],
        "image_path": payload["image_path"],
        "video_path": payload["video_path"],
        "image_url": payload["image_url"],
        "video_url": payload["video_url"],
    }
    data.update(extra_fields)
    payload["data"] = data
    return payload


def build_alarm_created_event_for_alarm(
    config: Any,
    *,
    alarm: Any,
    legacy_event: str,
    event_source: str,
    metadata_obj: Optional[Dict[str, Any]] = None,
    extra_images: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建告警`created`事件`for`告警。"""
    metadata_payload = metadata_obj if isinstance(metadata_obj, dict) else {}
    extra_images_payload = [str(item).strip() for item in (extra_images or []) if str(item or "").strip()]
    alarm_level = _coerce_int(getattr(alarm, "alarm_level", 1), 1)
    region_index = _coerce_int(getattr(alarm, "region_index", -1), -1)
    class_thresh = _coerce_float(getattr(alarm, "class_thresh", 0.5), 0.5)
    overlap_thresh = _coerce_float(getattr(alarm, "overlap_thresh", 0.5), 0.5)
    min_interval = _coerce_int(getattr(alarm, "min_interval", 0), 0)

    payload_extra: Dict[str, Any] = {
        "alarm_type": _clean_str(getattr(alarm, "alarm_type", "")),
        "alarm_level": alarm_level,
        "algorithm_code": _clean_str(getattr(alarm, "algorithm_code", "")),
        "object_code": _clean_str(getattr(alarm, "object_code", "")),
        "recognition_region": _clean_str(getattr(alarm, "recognition_region", "")),
        "region_index": region_index,
        "class_thresh": class_thresh,
        "overlap_thresh": overlap_thresh,
        "min_interval": min_interval,
        "stream_code": _clean_str(getattr(alarm, "stream_code", "")),
        "stream_app": _clean_str(getattr(alarm, "stream_app", "")),
        "stream_name": _clean_str(getattr(alarm, "stream_name", "")),
        "stream_url": _clean_str(getattr(alarm, "stream_url", "")),
        "metadata": metadata_payload,
        "extra_images": extra_images_payload,
    }

    _merge_event_extra_fields(payload_extra, extra)

    timestamp = _alarm_timestamp(alarm)

    image_path = _clean_str(getattr(alarm, "image_path", ""))
    video_path = _clean_str(getattr(alarm, "video_path", ""))
    upload_dir_www = _clean_str(getattr(config, "uploadDir_www", ""))

    return build_alarm_created_event(
        config,
        legacy_event=legacy_event,
        event_source=event_source,
        timestamp=timestamp,
        alarm_id=int(getattr(alarm, "id", 0) or 0),
        control_code=_clean_str(getattr(alarm, "control_code", "")),
        desc=_clean_str(getattr(alarm, "desc", "")),
        image_path=image_path,
        video_path=video_path,
        image_url=_alarm_media_url(upload_dir_www, image_path),
        video_url=_alarm_media_url(upload_dir_www, video_path),
        extra=payload_extra,
    )


def _alarm_webhook_sink_enabled(config: Any) -> bool:
    """判断告警Webhook接收端是否启用。"""
    if not bool(getattr(config, "alarmWebhookEnabled", False)):
        return False
    urls = getattr(config, "alarmWebhookUrls", []) or []
    return bool(isinstance(urls, list) and len(urls) > 0)


def _alarm_cloud_sink_enabled(config: Any) -> bool:
    """判断告警云端接收端是否启用。"""
    if not bool(getattr(config, "cloudEnabled", False)):
        return False
    cloud_base_url = str(getattr(config, "cloudBaseUrl", "") or "").strip()
    cloud_edge_token = str(getattr(config, "cloudEdgeToken", "") or "").strip()
    return bool(cloud_base_url and cloud_edge_token)


def get_enabled_alarm_sink_types(config: Any) -> List[str]:
    """获取启用告警接收端`types`。"""
    sinks: List[str] = []
    if _alarm_webhook_sink_enabled(config):
        sinks.append("webhook")
    if _alarm_cloud_sink_enabled(config):
        sinks.append("cloud")
    return sinks


def enqueue_alarm_event_outbox(config: Any, payload: Dict[str, Any], *, alarm_id: int, control_code: str) -> int:
    """处理`enqueue`告警事件`outbox`。
    
    Write outbox records (one per enabled sink).
        Returns number of rows created.
    """
    if not bool(getattr(config, "alarmOutboxEnabled", True)):
        return 0

    event_id = str(payload.get("event_id", "") or "").strip()
    if not event_id:
        return 0

    from app.models import AlarmEventOutbox

    sink_types = get_enabled_alarm_sink_types(config)
    if not sink_types:
        return 0

    payload_json = json.dumps(payload, ensure_ascii=False, default=str)

    created = 0
    for sink_type in sink_types:
        try:
            _row, was_created = AlarmEventOutbox.objects.get_or_create(
                event_id=event_id,
                sink_type=sink_type,
                defaults={
                    "schema": str(payload.get("schema", EVENT_SCHEMA_V1) or EVENT_SCHEMA_V1),
                    "event_type": str(
                        payload.get("event_type", EVENT_TYPE_ALARM_CREATED) or EVENT_TYPE_ALARM_CREATED
                    ),
                    "event_source": str(payload.get("event_source", "") or ""),
                    "alarm_id": int(alarm_id or 0),
                    "control_code": str(control_code or ""),
                    "payload_json": payload_json,
                    "status": "pending",
                },
            )
        except DatabaseError as exc:
            raise AlarmOutboxEnqueueError(event_id=event_id, sink_type=sink_type) from exc
        if was_created:
            created += 1

    return created
