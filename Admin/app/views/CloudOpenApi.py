import logging
import json
import os
from datetime import datetime
from typing import Any, Dict

from django.db import transaction
from django.db import IntegrityError
from django.http import HttpResponse
from django.utils import timezone

from app.utils.DeploymentMode import is_cloud_mode



logger = logging.getLogger(__name__)
def _json_response(payload: Dict[str, Any], *, status: int = 200) -> HttpResponse:
    """返回JSON响应。"""
    return HttpResponse(json.dumps(payload, ensure_ascii=False, default=str), status=status, content_type="application/json")


def _clean_str(value: Any) -> str:
    """处理清理字符串。"""
    return str(value or "").strip()


def _presign_bucket() -> str:
    """处理预签名`bucket`。"""
    return _clean_str(os.environ.get("BEACON_CLOUD_S3_BUCKET", ""))


def _presign_expires_seconds() -> int:
    """返回预签名`expires`秒数。"""
    try:
        expires_in = int(os.environ.get("BEACON_CLOUD_PRESIGN_PUT_EXPIRES_SECONDS", 900) or 900)
    except Exception:
        expires_in = 900
    return max(60, min(3600, expires_in))


def _parse_json_body(request) -> Dict[str, Any]:
    """解析JSON响应体。"""
    try:
        raw = getattr(request, "body", b"") or b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def api_cloud_presign_image(request):
    """处理 `cloud_presign_image` 接口请求。"""
    if not is_cloud_mode():
        return HttpResponse(status=404)
    if request.method != "POST":
        return _json_response({"code": 0, "msg": "method not allowed"}, status=405)

    cluster = getattr(request, "cloud_edge_cluster", None)
    if not cluster:
        return _json_response({"code": 0, "msg": "unauthorized"}, status=401)

    body = _parse_json_body(request)
    event_id = _clean_str(body.get("event_id", ""))
    content_type = _clean_str(body.get("content_type", "")) or "application/octet-stream"
    ext = _clean_str(body.get("ext", "")) or ".jpg"
    if not event_id:
        return _json_response({"code": 0, "msg": "event_id required"}, status=400)

    bucket = _presign_bucket()
    if not bucket:
        return _json_response({"code": 0, "msg": "BEACON_CLOUD_S3_BUCKET missing"}, status=500)

    expires_in = _presign_expires_seconds()

    from app.utils.CloudS3 import build_alarm_image_object_key, presign_put_image

    now = timezone.now()

    # cluster -> project -> tenant
    tenant_id = getattr(getattr(getattr(cluster, "project", None), "tenant", None), "id", None)
    project_id = getattr(getattr(cluster, "project", None), "id", None)
    cluster_id = getattr(cluster, "id", None)
    object_key = build_alarm_image_object_key(
        tenant_id=tenant_id,
        project_id=project_id,
        cluster_id=cluster_id,
        event_id=event_id,
        ext=ext,
        now=now,
    )

    upload = presign_put_image(bucket=bucket, key=object_key, content_type=content_type, expires_in=expires_in)

    return _json_response(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "bucket": bucket,
                "object_key": object_key,
                "upload": {
                    "method": "PUT",
                    "url": upload.get("url"),
                    "headers": upload.get("headers") or {"Content-Type": content_type},
                    "expires_in_seconds": int(upload.get("expires_in_seconds") or expires_in),
                },
            },
        }
    )


def _parse_timestamp(value: Any):
    """解析`timestamp`。"""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            # Python 3.11: fromisoformat supports "YYYY-MM-DDTHH:MM:SS[.ffffff][+HH:MM]"
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt
    try:
        # Project runs with USE_TZ=False; normalize aware values to the active local
        # timezone before stripping tzinfo so SQLite can store them safely.
        return timezone.localtime(dt, timezone.get_current_timezone()).replace(tzinfo=None)
    except Exception:
        try:
            return dt.astimezone(timezone.get_current_timezone()).replace(tzinfo=None)
        except Exception:
            return dt.replace(tzinfo=None)


def _cloud_ingest_require_request(request):
    """处理云端接入需要请求。"""
    if not is_cloud_mode():
        return HttpResponse(status=404), None
    if request.method != "POST":
        return _json_response({"code": 0, "msg": "method not allowed"}, status=405), None

    cluster = getattr(request, "cloud_edge_cluster", None)
    if not cluster:
        return _json_response({"code": 0, "msg": "unauthorized"}, status=401), None
    return None, cluster


def _cloud_ingest_parse_event_body(body: Dict[str, Any]):
    """返回云端接入`parse`事件响应体。"""
    schema = _clean_str(body.get("schema", ""))
    event_id = _clean_str(body.get("event_id", ""))
    if schema != "beacon.event.v1":
        return None, _json_response({"code": 0, "msg": "invalid schema"}, status=400)
    if not event_id:
        return None, _json_response({"code": 0, "msg": "event_id required"}, status=400)

    cloud_image = body.get("cloud_image") or {}
    if not isinstance(cloud_image, dict):
        cloud_image = {}

    return (
        {
            "event_id": event_id,
            "event_type": _clean_str(body.get("event_type", "")) or "alarm.created",
            "event_source": _clean_str(body.get("event_source", "")),
            "timestamp": _parse_timestamp(body.get("timestamp")),
            "node_code": _clean_str(body.get("node_code", "")),
            "control_code": _clean_str(body.get("control_code", "")),
            "desc": _clean_str(body.get("desc", "")),
            "image_bucket": _clean_str(cloud_image.get("bucket", "")),
            "image_key": _clean_str(cloud_image.get("key", "")),
            "image_content_type": _clean_str(cloud_image.get("content_type", "")),
        },
        None,
    )


def _cloud_ingest_allowed_image_prefix(cluster) -> str:
    """返回云端接入`allowed`图片前缀。"""
    tenant_id = getattr(getattr(getattr(cluster, "project", None), "tenant", None), "id", None)
    project_id = getattr(getattr(cluster, "project", None), "id", None)
    cluster_id = getattr(cluster, "id", None)
    return f"tenant_{tenant_id}/project_{project_id}/cluster_{cluster_id}/"


def _cloud_ingest_validate_image_key(image_key: str, allowed_prefix: str):
    """返回云端接入`validate`图片键。"""
    if image_key and not str(image_key).startswith(str(allowed_prefix)):
        return _json_response({"code": 0, "msg": "cloud_image.key not allowed"}, status=400)
    return None


def _cloud_ingest_store_event(*, cluster, event: Dict[str, Any], body: Dict[str, Any], now):
    """处理云端接入`store`事件。"""
    from app.models import CloudAlarmEvent

    try:
        with transaction.atomic():
            CloudAlarmEvent.objects.create(
                edge_cluster=cluster,
                event_id=event.get("event_id", ""),
                event_type=event.get("event_type", ""),
                event_source=event.get("event_source", ""),
                timestamp=event.get("timestamp"),
                node_code=event.get("node_code", ""),
                control_code=event.get("control_code", ""),
                desc=event.get("desc", ""),
                payload_json=json.dumps(body, ensure_ascii=False, default=str),
                image_bucket=event.get("image_bucket", ""),
                image_key=event.get("image_key", ""),
                image_content_type=event.get("image_content_type", ""),
                received_at=now,
            )
    except IntegrityError:
        # idempotent success: (edge_cluster, event_id) already exists
        return None
    except Exception as e:
        return _json_response({"code": 0, "msg": f"db error: {e}"}, status=500)
    return None


def _cloud_ingest_touch_cluster_best_effort(cluster, now) -> None:
    """尽力处理云端接入刷新集群。"""
    try:
        cluster.last_seen_at = now
        cluster.save(update_fields=["last_seen_at"])
    except Exception:
        logger.debug("suppressed exception in app/views/CloudOpenApi.py:233", exc_info=True)


def api_cloud_ingest_alarm_created(request):
    """处理 `cloud_ingest_alarm_created` 接口请求。"""
    resp, cluster = _cloud_ingest_require_request(request)
    if resp:
        return resp

    body = _parse_json_body(request)
    event, err = _cloud_ingest_parse_event_body(body)
    if err:
        return err

    allowed_prefix = _cloud_ingest_allowed_image_prefix(cluster)
    err = _cloud_ingest_validate_image_key(str(event.get("image_key") or ""), allowed_prefix)
    if err:
        return err

    now = timezone.now()
    err = _cloud_ingest_store_event(cluster=cluster, event=event, body=body, now=now)
    if err:
        return err

    _cloud_ingest_touch_cluster_best_effort(cluster, now)
    return _json_response({"code": 1000, "msg": "success"})
