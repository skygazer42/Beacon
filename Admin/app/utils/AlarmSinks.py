import base64
import hashlib
import hmac
import json
import os
from typing import Any, Dict

import requests


def _json_bytes(event: Dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def _clamp_timeout_seconds(value, default: int, *, min_value: int = 1, max_value: int = 30) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = int(default)
    return max(min_value, min(max_value, timeout))


def publish_alarm_event(config, event: Dict[str, Any]) -> Dict[str, bool]:
    return {
        sink: bool(publish_alarm_event_to_sink(config, sink, event).get("ok"))
        for sink in ("webhook", "cloud")
    }


def publish_alarm_event_to_sink(config, sink_type: str, event: Dict[str, Any]) -> Dict[str, Any]:
    sink = str(sink_type or "").strip().lower()
    if sink == "webhook":
        return _publish_webhook(config, event)
    if sink == "cloud":
        return _publish_cloud(config, event)
    return {"ok": False, "retriable": False, "http_status": 0, "error": "unknown sink"}


def _publish_webhook(config, event: Dict[str, Any]) -> Dict[str, Any]:
    """处理发布Webhook。"""
    enabled = bool(getattr(config, "alarmWebhookEnabled", False))
    urls = getattr(config, "alarmWebhookUrls", []) or []
    if not enabled or not isinstance(urls, list) or not urls:
        return {"ok": False, "retriable": True, "http_status": 0, "error": "webhook disabled or urls missing"}

    secret = str(getattr(config, "alarmWebhookSecret", "") or "").strip()
    timeout = _clamp_timeout_seconds(getattr(config, "alarmWebhookTimeoutSeconds", 5), 5, min_value=1, max_value=30)
    body = _json_bytes(event)
    headers = _build_webhook_headers(config, event, body, secret=secret)

    last_status = 0
    attempted_count = 0
    for url in urls:
        url = str(url or "").strip()
        if not url:
            continue
        attempted_count += 1
        result, status = _post_webhook_url(url, headers=headers, body=body, timeout=timeout)
        last_status = int(status or 0)
        if result is not None:
            return result

    if attempted_count == 0:
        return {"ok": False, "retriable": True, "http_status": 0, "error": "webhook urls missing"}

    return {"ok": True, "retriable": False, "http_status": last_status or 200, "error": ""}


def _build_webhook_headers(config, event: Dict[str, Any], body: bytes, *, secret: str = "") -> Dict[str, str]:
    """构建Webhook请求头。"""
    event_id = str(event.get("event_id", "") or "")
    schema = str(event.get("schema", "") or "")
    headers: Dict[str, str] = {
        "User-Agent": "beacon-alarm-webhook",
        "Content-Type": "application/json",
    }
    if event_id:
        headers["X-Beacon-Event-Id"] = event_id
    if schema:
        headers["X-Beacon-Schema"] = schema

    if not secret:
        secret = str(getattr(config, "alarmWebhookSecret", "") or "").strip()
    if secret:
        sig = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("ascii")
        headers["X-Beacon-Signature"] = f"sha256={sig}"
    return headers


def _webhook_response_content_str(res) -> str:
    """处理Webhook响应`content`字符串。"""
    try:
        content = getattr(res, "content", b"") or b""
        return content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _webhook_http_error_result(status: int, content_str: str) -> Dict[str, Any]:
    """返回WebhookHTTP错误结果。"""
    error = f"webhook http {int(status)}: {content_str}".strip()
    if status == 429 or status >= 500:
        return {"ok": False, "retriable": True, "http_status": status, "error": error}
    if 400 <= status < 500:
        return {"ok": False, "retriable": False, "http_status": status, "error": error}
    return {"ok": False, "retriable": True, "http_status": status, "error": error}


def _post_webhook_url(url: str, *, headers: Dict[str, str], body: bytes, timeout: int):
    """发送WebhookURL。"""
    try:
        res = requests.post(url=url, headers=headers, data=body, timeout=timeout)
    except Exception as e:
        return {"ok": False, "retriable": True, "http_status": 0, "error": f"webhook error: {e}"}, 0

    status = int(getattr(res, "status_code", 0) or 0)
    if 200 <= status < 300:
        return None, status
    return _webhook_http_error_result(status, _webhook_response_content_str(res)), status




def _is_truthy(value: Any) -> bool:
    """判断`truthy`。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _safe_res_text(res) -> str:
    """处理安全`res`文本。"""
    try:
        content = getattr(res, "content", b"") or b""
        if isinstance(content, str):
            return content
        return content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _http_failure(status_code: int, text: str) -> Dict[str, Any]:
    """处理HTTP`failure`。"""
    code = int(status_code or 0)
    msg = str(text or "").strip()
    if code == 429 or code >= 500:
        return {"ok": False, "retriable": True, "http_status": code, "error": msg}
    if 400 <= code < 500:
        return {"ok": False, "retriable": False, "http_status": code, "error": msg}
    return {"ok": False, "retriable": True, "http_status": code, "error": msg}


def _cloud_timeouts(config) -> Dict[str, int]:
    """处理云端`timeouts`。"""
    return {
        "upload_timeout": _clamp_timeout_seconds(getattr(config, "cloudUploadTimeoutSeconds", 10), 10, max_value=60),
        "ingest_timeout": _clamp_timeout_seconds(getattr(config, "cloudIngestTimeoutSeconds", 5), 5, max_value=60),
    }


def _cloud_post(base_url: str, token: str, *, path: str, payload: Dict[str, Any], timeout: int):
    """处理云端`post`。"""
    url = f"{base_url}{path}"
    headers = {
        "User-Agent": "beacon-edge-cloud-sink",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    return requests.post(url=url, headers=headers, json=payload, timeout=timeout)


def _cloud_api_success_payload(res) -> Dict[str, Any]:
    """返回云端API成功状态载荷。"""
    status_code = int(getattr(res, "status_code", 0) or 0)
    if not (200 <= status_code < 300):
        return {"ok": False, "error_result": _http_failure(status_code, _safe_res_text(res))}

    try:
        body = res.json()
    except Exception:
        body = {}
    if int((body or {}).get("code") or 0) != 1000:
        return {
            "ok": False,
            "error_result": {"ok": False, "retriable": False, "http_status": status_code, "error": str(body)},
        }
    return {"ok": True, "status_code": status_code, "body": body}


def _cloud_content_type(image_abs: str) -> Dict[str, str]:
    """返回云端`content`类型。"""
    ext = os.path.splitext(image_abs)[1].lower() or ".jpg"
    if ext in (".jpg", ".jpeg"):
        content_type = "image/jpeg"
    elif ext == ".png":
        content_type = "image/png"
    else:
        content_type = "application/octet-stream"
    return {"ext": ext, "content_type": content_type}


def _resolve_cloud_image_context(config, event: Dict[str, Any]) -> Dict[str, Any]:
    """解析并返回云端图片`context`。"""
    image_path = str(event.get("image_path", "") or "").strip()
    if not image_path:
        return {"ok": True, "needs_upload": False}

    from app.utils.Security import resolve_under_base

    try:
        upload_dir = str(getattr(config, "uploadDir", "") or "").strip()
        image_abs = resolve_under_base(upload_dir, image_path)
    except Exception as e:
        return {"ok": False, "error_result": {"ok": False, "retriable": False, "http_status": 0, "error": f"invalid image_path: {e}"}}

    if not os.path.exists(image_abs):
        return {"ok": False, "error_result": {"ok": False, "retriable": False, "http_status": 0, "error": "image file missing"}}

    file_info = _cloud_content_type(image_abs)
    return {
        "ok": True,
        "needs_upload": True,
        "image_abs": image_abs,
        "ext": file_info["ext"],
        "content_type": file_info["content_type"],
    }


def _cloud_ingest(base_url: str, token: str, *, ingest_timeout: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """处理云端接入。"""
    try:
        res = _cloud_post(
            base_url,
            token,
            path="/open/cloud/v1/events/alarm-created",
            payload=payload,
            timeout=ingest_timeout,
        )
    except Exception as e:
        return {"ok": False, "retriable": True, "http_status": 0, "error": f"cloud ingest error: {e}"}

    parsed = _cloud_api_success_payload(res)
    if not parsed["ok"]:
        return parsed["error_result"]
    return {"ok": True, "retriable": False, "http_status": int(parsed["status_code"] or 0), "error": ""}


def _cloud_presign_image(base_url: str, token: str, *, ingest_timeout: int, event_id: str, content_type: str, ext: str) -> Dict[str, Any]:
    """处理云端预签名图片。"""
    try:
        res = _cloud_post(
            base_url,
            token,
            path="/open/cloud/v1/presign/image",
            payload={"event_id": event_id, "content_type": content_type, "ext": ext},
            timeout=ingest_timeout,
        )
    except Exception as e:
        return {"ok": False, "error_result": {"ok": False, "retriable": True, "http_status": 0, "error": f"cloud presign error: {e}"}}

    parsed = _cloud_api_success_payload(res)
    if not parsed["ok"]:
        return parsed["error_result"]

    data = (parsed["body"] or {}).get("data") or {}
    bucket = str(data.get("bucket", "") or "").strip()
    object_key = str(data.get("object_key", "") or "").strip()
    upload = data.get("upload") or {}
    upload_url = str((upload or {}).get("url", "") or "").strip()
    upload_headers = (upload or {}).get("headers") or {"Content-Type": content_type}
    if not bucket or not object_key or not upload_url:
        return {
            "ok": False,
            "error_result": {
                "ok": False,
                "retriable": False,
                "http_status": int(parsed["status_code"] or 0),
                "error": "invalid presign response",
            },
        }
    return {
        "ok": True,
        "bucket": bucket,
        "object_key": object_key,
        "upload_url": upload_url,
        "upload_headers": upload_headers,
    }


def _cloud_upload_image(*, image_abs: str, upload_url: str, upload_headers, upload_timeout: int) -> Dict[str, Any]:
    """处理云端上传图片。"""
    try:
        with open(image_abs, "rb") as f:
            put_res = requests.put(url=upload_url, data=f, headers=upload_headers, timeout=upload_timeout)
    except Exception as e:
        return {"ok": False, "error_result": {"ok": False, "retriable": True, "http_status": 0, "error": f"cloud upload error: {e}"}}

    put_status = int(getattr(put_res, "status_code", 0) or 0)
    if not (200 <= put_status < 300):
        return {"ok": False, "error_result": _http_failure(put_status, _safe_res_text(put_res))}
    return {"ok": True}


def _cloud_ingest_payload(event: Dict[str, Any], *, bucket: str, object_key: str, content_type: str) -> Dict[str, Any]:
    """返回云端接入载荷。"""
    ingest_payload = dict(event)
    ingest_payload["cloud_image"] = {"bucket": bucket, "key": object_key, "content_type": content_type}
    return ingest_payload


def _publish_cloud(config, event: Dict[str, Any]) -> Dict[str, Any]:
    """处理发布云端。
    
    Edge -> Cloud sink (Cloud SaaS v1):
        1) presign PUT from cloud
        2) PUT upload image to object storage
        3) ingest event to cloud (idempotent on (edge_cluster_id, event_id))
    """
    enabled = bool(getattr(config, "cloudEnabled", False))
    base_url = str(getattr(config, "cloudBaseUrl", "") or "").strip().rstrip("/")
    token = str(getattr(config, "cloudEdgeToken", "") or "").strip()

    if not enabled or not base_url or not token:
        return {"ok": False, "retriable": True, "http_status": 0, "error": "cloud disabled or not configured"}

    timeouts = _cloud_timeouts(config)
    upload_timeout = timeouts["upload_timeout"]
    ingest_timeout = timeouts["ingest_timeout"]

    event_id = str(event.get("event_id", "") or "").strip()
    if not event_id:
        return {"ok": False, "retriable": False, "http_status": 0, "error": "event_id missing"}

    image_context = _resolve_cloud_image_context(config, event)
    if not image_context["ok"]:
        return image_context["error_result"]
    if not image_context["needs_upload"]:
        return _cloud_ingest(base_url, token, ingest_timeout=ingest_timeout, payload=dict(event))

    presign = _cloud_presign_image(
        base_url,
        token,
        ingest_timeout=ingest_timeout,
        event_id=event_id,
        content_type=image_context["content_type"],
        ext=image_context["ext"],
    )
    if not presign["ok"]:
        return presign["error_result"]

    upload_result = _cloud_upload_image(
        image_abs=image_context["image_abs"],
        upload_url=presign["upload_url"],
        upload_headers=presign["upload_headers"],
        upload_timeout=upload_timeout,
    )
    if not upload_result["ok"]:
        return upload_result["error_result"]

    return _cloud_ingest(
        base_url,
        token,
        ingest_timeout=ingest_timeout,
        payload=_cloud_ingest_payload(
            event,
            bucket=presign["bucket"],
            object_key=presign["object_key"],
            content_type=image_context["content_type"],
        ),
    )
