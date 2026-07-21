import base64
import binascii
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from django.core.cache import cache
from django.core import signing
from django.db import transaction

from app.models import (
    DigitalHumanAiDiagnosisConfig,
    DigitalHumanAlert,
    DigitalHumanAlertRoute,
    DigitalHumanAlertRouteConfig,
    DigitalHumanCommandResult,
    DigitalHumanCommandTask,
    DigitalHumanDevice,
    DigitalHumanDeviceMetricHistory,
    DigitalHumanHumanLog,
    DigitalHumanJwtAccount,
    SystemConfig,
)
from app.utils.DigitalHumanCrypto import extract_bearer_token, sm4_decrypt_ecb_pkcs7  # gitleaks:allow -- function names, not credentials
from app.utils.Security import resolve_under_base
from app.views.ViewsBase import g_config


DATE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
UPLOAD_PAYLOAD_TIME_FORMAT = "%Y%m%d%H%M%S"

AUTH_PENDING = "PENDING"
AUTH_AUTHORIZED = "AUTHORIZED"
AUTH_DISABLED = "DISABLED"
AUTH_EXPIRED = "EXPIRED"

ALERT_PENDING = "pending"
ALERT_RESOLVED = "resolved"
COMMAND_PENDING = "PENDING"
COMMAND_SUCCESS = "SUCCESS"
COMMAND_FAILED = "FAILED"

OPEN_TOKEN_SALT = "digital-human-open-agent-token"
DEFAULT_REPORT_INTERVAL_SEC = 30
DEFAULT_REPORT_IMAGE_MAX_BYTES = 524288

DEVICE_STALE_MINUTES = 5
UPLOAD_AUTH_WINDOW = timedelta(minutes=5)

RESOURCE_WARNING_THRESHOLD = 80.0
RESOURCE_CRITICAL_THRESHOLD = 90.0
LATENCY_WARNING_THRESHOLD = 200
LATENCY_CRITICAL_THRESHOLD = 500

HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
DATA_URL_RE = re.compile(r"^data:(?P<content_type>[^;,]+)?(?:;charset=[^;,]+)?;base64,(?P<data>.+)$", re.IGNORECASE)
SAFE_SCREENSHOT_CONTENT_TYPES = {
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_REPLAY_LOCK = threading.Lock()
_REPLAY_CACHE = {}
_REPLAY_REDIS_LOCK = threading.Lock()
_REPLAY_REDIS_CLIENT = None
_REPLAY_REDIS_URL = ""
_REPLAY_REDIS_CONFIG = {"expires_at": 0.0, "url": "", "cache_key_prefix": "beacon:digital-human:replay"}

logger = logging.getLogger(__name__)


class DigitalHumanError(RuntimeError):
    def __init__(self, message, *, status_code=400):
        super().__init__(str(message or "数字人监管服务错误"))
        self.status_code = int(status_code or 400)


def _now():
    return datetime.now()


def _format_dt(value):
    if not value:
        return ""
    try:
        return value.strftime(DATE_TIME_FORMAT)
    except Exception:
        return ""


def _parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (DATE_TIME_FORMAT, "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    raise DigitalHumanError("时间格式不合法")


def _parse_report_dt(value):
    text = str(value or "").strip()
    if not text:
        raise DigitalHumanError("缺少 reportTime")
    for fmt in (DATE_TIME_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    raise DigitalHumanError("reportTime 格式不合法")


def _strip_to_none(value):
    text = str(value or "").strip()
    return text or None


def _normalize_text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _boolish(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off", ""):
        return False
    return bool(default)


def _extract_number(value, default=0.0):
    if value is None:
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    matched = NUMBER_RE.search(str(value))
    if not matched:
        return float(default)
    try:
        return float(matched.group(0))
    except Exception:
        return float(default)


def _intish(value, default=0):
    try:
        return int(round(_extract_number(value, default)))
    except Exception:
        return int(default)


def _floatish(value, default=0.0, digits=1):
    number = _extract_number(value, default)
    if digits is None:
        return float(number)
    return round(float(number), digits)


def _parse_object_id(value, field_name="ID"):
    text = str(value or "").strip()
    if not text:
        raise DigitalHumanError(f"{field_name} 不合法")
    try:
        parsed = int(text)
    except Exception as exc:
        raise DigitalHumanError(f"{field_name} 不合法") from exc
    if parsed <= 0:
        raise DigitalHumanError(f"{field_name} 不合法")
    return parsed


def _load_json_text(value, default=None):
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _dump_json_text(value):
    return json.dumps(value or {}, ensure_ascii=False)


def _sha256_hex(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _mask_secret(value, prefix=4, suffix=4):
    text = _normalize_text(value, default="")
    if not text:
        return ""
    if len(text) <= prefix + suffix:
        return "*" * max(len(text), 4)
    return f"{text[:prefix]}****{text[-suffix:]}"


def _mask_route_secret(value):
    return _mask_secret(value, prefix=4, suffix=4)


def _jwt_secret():
    return secrets.token_hex(16)


def _authorization_secret():
    value = (
        str(os.environ.get("BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET") or "").strip()
        or str(os.environ.get("APP_AGENT_AUTHORIZATION_SECRET") or "").strip()
    )
    if not value:
        raise DigitalHumanError("未配置数字人授权密钥", status_code=503)
    return value


def _upload_auth_sm4_secret_key():
    value = (
        str(os.environ.get("BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY") or "").strip()
        or str(os.environ.get("APP_AGENT_UPLOAD_AUTH_SM4_SECRET_KEY") or "").strip()
    )
    if not value:
        raise DigitalHumanError("未配置数字人上报加密密钥", status_code=503)
    return value


def _env_int(name, default):
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _report_default_interval_sec():
    value = _env_int("BEACON_DIGITAL_HUMAN_REPORT_DEFAULT_INTERVAL_SEC", 0)
    if value > 0:
        return value
    value = _env_int("APP_AGENT_REPORT_DEFAULT_INTERVAL_SEC", 0)
    if value > 0:
        return value
    return DEFAULT_REPORT_INTERVAL_SEC


def _report_image_max_bytes():
    value = _env_int("BEACON_DIGITAL_HUMAN_REPORT_IMAGE_MAX_BYTES", 0)
    if value > 0:
        return value
    value = _env_int("APP_AGENT_REPORT_IMAGE_MAX_BYTES", 0)
    if value > 0:
        return value
    return DEFAULT_REPORT_IMAGE_MAX_BYTES


def _replay_redis_settings():
    now_ts = time.time()
    cached = dict(_REPLAY_REDIS_CONFIG)
    if float(cached.get("expires_at") or 0.0) > now_ts:
        return (
            _normalize_text(cached.get("url"), default=""),
            _normalize_text(cached.get("cache_key_prefix"), default="beacon:digital-human:replay"),
        )

    redis_url = (
        str(os.environ.get("BEACON_DIGITAL_HUMAN_REPLAY_REDIS_URL") or "").strip()
        or str(os.environ.get("BEACON_DIGITAL_HUMAN_REDIS_URL") or "").strip()
    )
    cache_key_prefix = (
        str(os.environ.get("BEACON_DIGITAL_HUMAN_REPLAY_CACHE_PREFIX") or "").strip()
        or "beacon:digital-human:replay"
    )

    _REPLAY_REDIS_CONFIG.update(
        {
            "expires_at": now_ts + 30.0,
            "url": redis_url,
            "cache_key_prefix": cache_key_prefix,
        }
    )
    return redis_url, cache_key_prefix


def _get_replay_redis_client():
    global _REPLAY_REDIS_CLIENT, _REPLAY_REDIS_URL

    redis_url, cache_key_prefix = _replay_redis_settings()
    if not redis_url:
        return None, cache_key_prefix

    with _REPLAY_REDIS_LOCK:
        if _REPLAY_REDIS_CLIENT is not None and _REPLAY_REDIS_URL == redis_url:
            return _REPLAY_REDIS_CLIENT, cache_key_prefix
        try:
            import redis
        except ImportError as exc:
            _REPLAY_REDIS_CLIENT = None
            _REPLAY_REDIS_URL = redis_url
            logger.warning("Digital human replay redis dependency unavailable, falling back to cache/local guard: %s", exc)
            return None, cache_key_prefix

        try:
            _REPLAY_REDIS_CLIENT = redis.Redis.from_url(redis_url, decode_responses=True)
            _REPLAY_REDIS_URL = redis_url
        except Exception as exc:
            _REPLAY_REDIS_CLIENT = None
            _REPLAY_REDIS_URL = redis_url
            logger.warning("Digital human replay redis unavailable, falling back to cache/local guard: %s", exc)
        return _REPLAY_REDIS_CLIENT, cache_key_prefix


def _register_local_replay_guard(replay_digest, now=None):
    current = now or _now()
    with _REPLAY_LOCK:
        expired_keys = [key for key, expires_at in _REPLAY_CACHE.items() if expires_at <= current]
        for key in expired_keys:
            _REPLAY_CACHE.pop(key, None)
        if replay_digest in _REPLAY_CACHE:
            raise DigitalHumanError("machineCode重放已拒绝", status_code=401)
        _REPLAY_CACHE[replay_digest] = current + UPLOAD_AUTH_WINDOW


def _reject_upload_replay(payload_text, now=None):
    current = now or _now()
    replay_digest = _sha256_hex(payload_text)
    ttl_seconds = max(1, int(UPLOAD_AUTH_WINDOW.total_seconds()))

    redis_client, cache_key_prefix = _get_replay_redis_client()
    if redis_client is not None:
        try:
            created = redis_client.set(f"{cache_key_prefix}:{replay_digest}", "1", nx=True, ex=ttl_seconds)
            if not created:
                raise DigitalHumanError("machineCode重放已拒绝", status_code=401)
            return
        except DigitalHumanError:
            raise
        except Exception as exc:
            logger.warning("Digital human replay redis write failed, falling back to cache/local guard: %s", exc)

    cache_key = f"beacon:digital-human:replay-cache:{replay_digest}"
    try:
        created = cache.add(cache_key, "1", timeout=ttl_seconds)
        if not created:
            raise DigitalHumanError("machineCode重放已拒绝", status_code=401)
        return
    except DigitalHumanError:
        raise
    except Exception as exc:
        logger.warning("Digital human replay cache add failed, falling back to local guard: %s", exc)

    _register_local_replay_guard(replay_digest, now=current)


def _device_screenshot_proxy_url(device_id):
    return f"/digital-human/device-screenshot?id={int(device_id or 0)}"


def _digital_human_screenshot_bucket():
    return (
        str(os.environ.get("BEACON_DIGITAL_HUMAN_S3_BUCKET") or "").strip()
        or str(os.environ.get("BEACON_CLOUD_S3_BUCKET") or "").strip()
    )


def _normalize_screenshot_content_type(content_type, default="image/jpeg"):
    normalized = _normalize_text(content_type, default=default).lower()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized in SAFE_SCREENSHOT_CONTENT_TYPES:
        return normalized
    return ""


def _guess_image_extension(content_type):
    normalized = _normalize_screenshot_content_type(content_type, default="")
    if normalized:
        return SAFE_SCREENSHOT_CONTENT_TYPES[normalized]
    guessed = mimetypes.guess_extension(str(content_type or "").strip().lower() or "image/jpeg")
    if guessed == ".jpe":
        return ".jpg"
    if guessed:
        return guessed
    return ".jpg"


def _decode_report_image(value):
    raw_text = str(value or "").strip()
    if not raw_text:
        return None

    content_type = "image/jpeg"
    payload_text = raw_text
    matched = DATA_URL_RE.match(raw_text)
    if matched:
        content_type = _normalize_screenshot_content_type(matched.group("content_type"), default="")
        if not content_type:
            logger.warning("Digital human screenshot ignored because content type was not a supported image type")
            return None
        payload_text = str(matched.group("data") or "").strip()
    else:
        content_type = _normalize_screenshot_content_type(content_type, default="image/jpeg") or "image/jpeg"

    payload_text = re.sub(r"\s+", "", payload_text)
    if not payload_text:
        return None

    try:
        image_bytes = base64.b64decode(payload_text, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not image_bytes:
        return None
    return {
        "raw_text": raw_text,
        "content_type": content_type or "image/jpeg",
        "extension": _guess_image_extension(content_type),
        "image_bytes": image_bytes,
    }


def _snapshot_screenshot_artifact(device):
    return {
        "bucket": _normalize_text(getattr(device, "screenshot_object_bucket", ""), default=""),
        "object_key": _normalize_text(getattr(device, "screenshot_object_key", ""), default=""),
        "storage_path": _normalize_text(getattr(device, "screenshot_storage_path", ""), default=""),
    }


def _delete_screenshot_artifact(artifact):
    if not artifact:
        return

    bucket = _normalize_text((artifact or {}).get("bucket"), default="")
    object_key = _normalize_text((artifact or {}).get("object_key"), default="")
    if bucket and object_key:
        from app.utils.CloudS3 import make_s3_client_from_env

        try:
            make_s3_client_from_env().delete_object(Bucket=bucket, Key=object_key)
        except Exception as exc:
            logger.warning("Digital human screenshot cleanup failed for object storage artifact: %s", exc)
        return

    storage_path = _normalize_text((artifact or {}).get("storage_path"), default="")
    if not storage_path:
        return

    upload_root = str(getattr(g_config, "uploadDir", "") or "").strip()
    if not upload_root:
        return
    try:
        abs_path = resolve_under_base(upload_root, storage_path)
    except Exception as exc:
        logger.warning("Digital human screenshot cleanup skipped for invalid local path: %s", exc)
        return

    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception as exc:
        logger.warning("Digital human screenshot cleanup failed for local artifact: %s", exc)
        return

    base_dir = os.path.normcase(os.path.abspath(upload_root))
    current_dir = os.path.dirname(abs_path)
    while current_dir:
        normalized_dir = os.path.normcase(os.path.abspath(current_dir))
        if normalized_dir == base_dir or not normalized_dir.startswith(base_dir):
            break
        try:
            os.rmdir(current_dir)
        except OSError:
            break
        current_dir = os.path.dirname(current_dir)


def _schedule_previous_screenshot_cleanup(device, previous_artifact):
    previous = previous_artifact or {}
    if not (_normalize_text(previous.get("bucket"), default="") and _normalize_text(previous.get("object_key"), default="")) and not _normalize_text(previous.get("storage_path"), default=""):
        return

    current = _snapshot_screenshot_artifact(device)
    if current == previous:
        return
    transaction.on_commit(lambda artifact=dict(previous): _delete_screenshot_artifact(artifact))


def _local_screenshot_rel_path(device, reported_at, extension):
    current = reported_at or _now()
    leaf = f"{current.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{extension}"
    return (
        f"digital-human/screenshots/{current.strftime('%Y/%m/%d')}"
        f"/device_{int(device.id or 0)}/{leaf}"
    )


def _apply_screenshot_storage_metadata(device, *, bucket="", object_key="", storage_path="", content_type="", byte_size=0):
    device.screenshot_object_bucket = _normalize_text(bucket, default="")
    device.screenshot_object_key = _normalize_text(object_key, default="")
    device.screenshot_storage_path = _normalize_text(storage_path, default="")
    device.screenshot_storage_url = _device_screenshot_proxy_url(device.id) if device.id else ""
    device.screenshot_content_type = _normalize_text(content_type, default="")
    device.screenshot_byte_size = max(0, _intish(byte_size, default=0))


def _store_device_screenshot(device, image_value, reported_at):
    parsed = _decode_report_image(image_value)
    if not parsed:
        return False

    previous_artifact = _snapshot_screenshot_artifact(device)
    image_bytes = parsed["image_bytes"]
    if len(image_bytes) > _report_image_max_bytes():
        logger.warning(
            "Digital human screenshot skipped because decoded payload exceeded limit: device_id=%s bytes=%s limit=%s",
            getattr(device, "id", None),
            len(image_bytes),
            _report_image_max_bytes(),
        )
        return False

    content_type = parsed["content_type"]
    extension = parsed["extension"]
    bucket = _digital_human_screenshot_bucket()
    if bucket:
        from app.utils.CloudS3 import build_digital_human_screenshot_object_key, make_s3_client_from_env

        try:
            object_key = build_digital_human_screenshot_object_key(
                device_id=device.id,
                ext=extension,
                now=reported_at or _now(),
            )
            client = make_s3_client_from_env()
            client.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=image_bytes,
                ContentType=content_type,
            )
            _apply_screenshot_storage_metadata(
                device,
                bucket=bucket,
                object_key=object_key,
                storage_path="",
                content_type=content_type,
                byte_size=len(image_bytes),
            )
            device.screenshot_base64 = ""
            _schedule_previous_screenshot_cleanup(device, previous_artifact)
            return True
        except Exception as exc:
            logger.warning("Digital human screenshot object-storage write failed, falling back to local storage: %s", exc)

    try:
        upload_root = str(getattr(g_config, "uploadDir", "") or "").strip()
        if not upload_root:
            raise RuntimeError("uploadDir is not configured")
        rel_path = _local_screenshot_rel_path(device, reported_at, extension)
        abs_path = resolve_under_base(upload_root, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(image_bytes)
        _apply_screenshot_storage_metadata(
            device,
            bucket="",
            object_key="",
            storage_path=rel_path,
            content_type=content_type,
            byte_size=len(image_bytes),
        )
        device.screenshot_base64 = ""
        _schedule_previous_screenshot_cleanup(device, previous_artifact)
        return True
    except Exception as exc:
        logger.warning("Digital human screenshot local persistence failed, using legacy DB fallback: %s", exc)

    device.screenshot_base64 = parsed["raw_text"]
    _apply_screenshot_storage_metadata(device, bucket="", object_key="", storage_path="", content_type=content_type, byte_size=len(image_bytes))
    _schedule_previous_screenshot_cleanup(device, previous_artifact)
    return True


def _ensure_device_codes(device):
    changed_fields = []
    if not device.device_code:
        device.device_code = f"KD-{int(device.id or 0):03d}"
        changed_fields.append("device_code")
    if not device.agent_device_id:
        device.agent_device_id = f"AGENT-{int(device.id or 0):03d}"
        changed_fields.append("agent_device_id")
    if not device.agent_token:
        device.agent_token = secrets.token_urlsafe(18)
        changed_fields.append("agent_token")
    if changed_fields:
        device.save(update_fields=changed_fields)
    return device


def _authorization_message(status):
    if status == AUTH_PENDING:
        return "等待授权"
    if status == AUTH_AUTHORIZED:
        return "已授权"
    if status == AUTH_EXPIRED:
        return "授权已过期"
    if status == AUTH_DISABLED:
        return "未授权"
    return "未知状态"


def _resolve_authorization_status(device, now=None):
    current = now or _now()
    if str(device.authorization_status or "").strip().upper() == AUTH_PENDING and not bool(device.authorization_enabled):
        return AUTH_PENDING
    if not bool(device.authorization_enabled):
        return AUTH_DISABLED
    if device.authorization_valid_until and current > device.authorization_valid_until:
        return AUTH_EXPIRED
    if device.authorization_valid_from and current < device.authorization_valid_from:
        return AUTH_DISABLED
    return AUTH_AUTHORIZED


def _apply_authorization_status(device, now=None, *, persist=False):
    status = _resolve_authorization_status(device, now=now)
    if persist and status != device.authorization_status:
        device.authorization_status = status
        device.save(update_fields=["authorization_status"])
    return status


def _device_is_stale(device, now=None):
    current = now or _now()
    if not device.last_report_time:
        return True
    return current - device.last_report_time > timedelta(minutes=DEVICE_STALE_MINUTES)


def _route_config_row():
    config = DigitalHumanAlertRouteConfig.objects.order_by("id").first()
    if config is None:
        config = DigitalHumanAlertRouteConfig.objects.create(enabled=False)
    return config


def _active_route_rows():
    return list(DigitalHumanAlertRoute.objects.all().order_by("-is_default_route", "id"))


def _resolve_route_for_region(region):
    config = _route_config_row()
    if not config.enabled:
        return config, None
    normalized_region = _normalize_text(region, default="")
    active_routes = [item for item in _active_route_rows() if item.active]
    for route in active_routes:
        if route.region and route.region == normalized_region:
            return config, route
    for route in active_routes:
        if route.is_default_route:
            return config, route
    return config, None


def _append_alert_timeline(alert, action, detail, event_time):
    timeline = list(_load_json_text(alert.timeline_json, default=[] ) or [])
    timeline.append(
        {
            "time": _format_dt(event_time),
            "action": _normalize_text(action, default="事件"),
            "detail": _normalize_text(detail, default=""),
        }
    )
    alert.timeline_json = _dump_json_text(timeline[-20:])


def _candidate_chat_completion_urls(base_url):
    trimmed = _normalize_text(base_url, default="").rstrip("/")
    if not trimmed:
        return []
    if trimmed.endswith("/chat/completions"):
        return [trimmed]
    candidates = [
        f"{trimmed}/chat/completions",
        f"{trimmed}/v1/chat/completions",
    ]
    deduped = []
    seen = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def _coerce_ai_text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text_part = _normalize_text(item.get("text"), default="")
            if text_part:
                parts.append(text_part)
                continue
            if isinstance(item.get("text"), dict):
                nested = _normalize_text(item["text"].get("value"), default="")
                if nested:
                    parts.append(nested)
        return "\n".join([part for part in parts if part]).strip()
    if isinstance(value, dict):
        text_part = _normalize_text(value.get("text"), default="")
        if text_part:
            return text_part
        if isinstance(value.get("text"), dict):
            return _normalize_text(value["text"].get("value"), default="")
    return ""


def _extract_ai_completion_text(payload_json):
    if not isinstance(payload_json, dict):
        return ""
    choices = payload_json.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0] or {}
        if isinstance(first_choice, dict):
            message = first_choice.get("message") or {}
            if isinstance(message, dict):
                text = _coerce_ai_text(message.get("content"))
                if text:
                    return text
            text = _coerce_ai_text(first_choice.get("text"))
            if text:
                return text
    output = payload_json.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            parts.append(_coerce_ai_text(item.get("content")))
        text = "\n".join([part for part in parts if part]).strip()
        if text:
            return text
    return _normalize_text(payload_json.get("output_text"), default="")


def _call_ai_diagnosis(config, *, system_prompt, user_prompt):
    if not _is_ai_config_complete(config):
        return "skipped", "", ""

    connect_timeout = max(1, _intish(config.connect_timeout_ms, default=10000)) / 1000.0
    read_timeout = max(1, _intish(config.read_timeout_ms, default=60000)) / 1000.0
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    request_body = {
        "model": _normalize_text(config.model, default=""),
        "temperature": _floatish(config.temperature, default=0.2, digits=None),
        "messages": [
            {"role": "system", "content": _normalize_text(system_prompt, default="你是数字人监管平台的运维诊断助手。")},
            {"role": "user", "content": _normalize_text(user_prompt, default="请给出诊断建议。")},
        ],
    }

    errors = []
    for url in _candidate_chat_completion_urls(config.base_url):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=request_body,
                timeout=(connect_timeout, read_timeout),
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        if int(response.status_code or 0) >= 400:
            errors.append(f"{url}: http {int(response.status_code or 0)} {response.text[:200]}")
            continue

        try:
            payload_json = response.json()
        except Exception as exc:
            errors.append(f"{url}: invalid json ({exc})")
            continue

        text = _extract_ai_completion_text(payload_json)
        if text:
            return "success", text[:4000], ""
        errors.append(f"{url}: empty completion")

    return "failed", "", "; ".join(errors)[:1000] or "AI 诊断请求失败"


def _alert_diagnosis_for_candidate(candidate):
    config = DigitalHumanAiDiagnosisConfig.objects.order_by("id").first()
    if not _is_ai_config_complete(config):
        return "skipped", "", ""
    system_prompt = _normalize_text(
        getattr(config, "alert_system_prompt", ""),
        default="你是数字人监管平台的运维诊断助手。请根据告警信息给出简洁、可执行的排障建议。",
    )
    user_prompt = "\n".join(
        [
            "请分析以下数字人终端告警，并输出 2-4 句中文诊断建议：",
            f"告警类型: {_normalize_text(candidate.get('alertType'), default='unknown')}",
            f"告警标题: {_normalize_text(candidate.get('title'), default='')}",
            f"告警模块: {_normalize_text(candidate.get('module'), default='')}",
            f"严重等级: {_normalize_text(candidate.get('level'), default='warning')}",
            f"告警描述: {_normalize_text(candidate.get('description'), default='')}",
        ]
    )
    return _call_ai_diagnosis(config, system_prompt=system_prompt, user_prompt=user_prompt)


def _build_alert_candidates(device, now=None):
    current = now or _now()
    candidates = []
    status = _resolve_authorization_status(device, now=current)
    if status == AUTH_AUTHORIZED and _device_is_stale(device, now=current):
        candidates.append(
            {
                "alertType": "device_offline",
                "title": "终端离线",
                "description": "设备超过 5 分钟未上报，建议检查网络连通和进程存活。",
                "module": "终端状态",
                "level": "critical",
            }
        )

    if status != AUTH_AUTHORIZED:
        return candidates

    if not bool(device.peripheral_cam):
        candidates.append(
            {
                "alertType": "camera_offline",
                "title": "摄像头离线",
                "description": "摄像头状态异常，数字人视频采集可能不可用。",
                "module": "摄像头",
                "level": "warning",
            }
        )
    if not bool(device.peripheral_mic):
        candidates.append(
            {
                "alertType": "mic_offline",
                "title": "麦克风异常",
                "description": "麦克风状态异常，数字人语音交互可能受影响。",
                "module": "音频设备",
                "level": "warning",
            }
        )
    if device.service_stream is False:
        candidates.append(
            {
                "alertType": "stream_service_down",
                "title": "推流服务异常",
                "description": "推流服务状态异常，欢迎词播报或直播链路可能中断。",
                "module": "推流服务",
                "level": "critical",
            }
        )
    if device.service_llm is False:
        candidates.append(
            {
                "alertType": "llm_service_down",
                "title": "LLM 服务异常",
                "description": "本地大模型服务不可用，诊断与交互能力可能退化。",
                "module": "LLM 服务",
                "level": "warning",
            }
        )
    if device.cpu_usage >= RESOURCE_CRITICAL_THRESHOLD:
        candidates.append(
            {
                "alertType": "cpu_high",
                "title": "CPU 占用过高",
                "description": f"设备 CPU 使用率达到 {int(device.cpu_usage)}%，建议检查热点进程。",
                "module": "系统资源",
                "level": "critical",
            }
        )
    elif device.cpu_usage >= RESOURCE_WARNING_THRESHOLD:
        candidates.append(
            {
                "alertType": "cpu_high",
                "title": "CPU 占用偏高",
                "description": f"设备 CPU 使用率达到 {int(device.cpu_usage)}%，建议关注负载变化。",
                "module": "系统资源",
                "level": "warning",
            }
        )
    if device.memory_usage >= RESOURCE_CRITICAL_THRESHOLD:
        candidates.append(
            {
                "alertType": "memory_high",
                "title": "内存占用过高",
                "description": f"设备内存使用率达到 {int(device.memory_usage)}%，建议检查模型缓存和并发任务。",
                "module": "系统资源",
                "level": "critical",
            }
        )
    elif device.memory_usage >= RESOURCE_WARNING_THRESHOLD:
        candidates.append(
            {
                "alertType": "memory_high",
                "title": "内存占用偏高",
                "description": f"设备内存使用率达到 {int(device.memory_usage)}%，建议关注近期波动。",
                "module": "系统资源",
                "level": "warning",
            }
        )
    if device.disk_usage >= RESOURCE_CRITICAL_THRESHOLD:
        candidates.append(
            {
                "alertType": "disk_high",
                "title": "磁盘占用过高",
                "description": f"设备磁盘使用率达到 {int(device.disk_usage)}%，建议清理日志与缓存。",
                "module": "系统资源",
                "level": "critical",
            }
        )
    elif device.disk_usage >= RESOURCE_WARNING_THRESHOLD:
        candidates.append(
            {
                "alertType": "disk_high",
                "title": "磁盘占用偏高",
                "description": f"设备磁盘使用率达到 {int(device.disk_usage)}%，建议关注剩余空间。",
                "module": "系统资源",
                "level": "warning",
            }
        )
    if device.net_latency_ms >= LATENCY_CRITICAL_THRESHOLD:
        candidates.append(
            {
                "alertType": "network_latency_high",
                "title": "网络延迟严重",
                "description": f"终端延迟达到 {int(device.net_latency_ms)} ms，可能影响数字人实时交互。",
                "module": "网络链路",
                "level": "critical",
            }
        )
    elif device.net_latency_ms >= LATENCY_WARNING_THRESHOLD:
        candidates.append(
            {
                "alertType": "network_latency_high",
                "title": "网络延迟偏高",
                "description": f"终端延迟达到 {int(device.net_latency_ms)} ms，建议检查链路质量。",
                "module": "网络链路",
                "level": "warning",
            }
        )
    return candidates


def _build_dingtalk_webhook_url(webhook, secret):
    parsed = urlsplit(_normalize_text(webhook, default=""))
    if not parsed.scheme or not parsed.netloc:
        return ""
    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if secret:
        timestamp = str(int(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        signature = base64.b64encode(
            hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        query_pairs["timestamp"] = timestamp
        query_pairs["sign"] = signature
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_pairs), parsed.fragment))


def _build_dingtalk_alert_message(alert):
    device = getattr(alert, "device", None)
    lines = [
        "【数字人告警】",
        f"设备: {_normalize_text(device.display_name if device else '', default='未命名设备')}",
        f"编号: {_normalize_text(device.device_code if device else '', default='--')}",
        f"区域: {_normalize_text(device.region if device else '', default='--')}",
        f"级别: {_normalize_text(alert.level, default='warning')}",
        f"模块: {_normalize_text(alert.alert_module_text, default='未分类')}",
        f"标题: {_normalize_text(alert.title, default='未命名告警')}",
        f"详情: {_normalize_text(alert.description, default='暂无描述')}",
        f"发生时间: {_format_dt(alert.first_occurred_at or alert.last_occurred_at or _now())}",
    ]
    return "\n".join(lines).strip()


def _send_dingtalk_alert_notification(alert, route, now=None):
    current = now or _now()
    webhook = _normalize_text(getattr(route, "webhook", ""), default="")
    target_url = _build_dingtalk_webhook_url(webhook, _normalize_text(getattr(route, "secret", ""), default=""))
    preview = _build_dingtalk_alert_message(alert)
    if not target_url:
        alert.dingtalk_push_status = "failed"
        alert.dingtalk_message_preview = preview[:500]
        alert.dingtalk_error = "钉钉 webhook 未配置或格式不合法"
        alert.dingtalk_push_time = current
        _append_alert_timeline(alert, "钉钉推送失败", alert.dingtalk_error, current)
        return

    owner_phone = _normalize_text(getattr(route, "owner_phone", ""), default="")
    payload = {
        "msgtype": "text",
        "text": {"content": preview},
        "at": {"atMobiles": [owner_phone] if owner_phone else [], "isAtAll": False},
    }
    try:
        response = requests.post(target_url, json=payload, timeout=(3.0, 8.0))
    except Exception as exc:
        alert.dingtalk_push_status = "failed"
        alert.dingtalk_message_preview = preview[:500]
        alert.dingtalk_error = f"钉钉推送异常: {exc}"
        alert.dingtalk_push_time = current
        _append_alert_timeline(alert, "钉钉推送失败", alert.dingtalk_error, current)
        return

    body_json = None
    try:
        body_json = response.json()
    except Exception:
        body_json = None

    errcode = None
    errmsg = ""
    if isinstance(body_json, dict):
        errcode = body_json.get("errcode")
        errmsg = _normalize_text(body_json.get("errmsg"), default="")

    if 200 <= int(response.status_code or 0) < 300 and (errcode in (None, 0, "0")):
        alert.dingtalk_push_status = "success"
        alert.dingtalk_message_preview = preview[:500]
        alert.dingtalk_error = ""
        alert.dingtalk_push_time = current
        _append_alert_timeline(alert, "钉钉推送成功", f"已推送至 {_normalize_text(route.region, default='默认路由')}", current)
        return

    error_message = errmsg or _normalize_text(response.text, default="钉钉返回异常")[:200]
    alert.dingtalk_push_status = "failed"
    alert.dingtalk_message_preview = preview[:500]
    alert.dingtalk_error = f"http {int(response.status_code or 0)}: {error_message}".strip()
    alert.dingtalk_push_time = current
    _append_alert_timeline(alert, "钉钉推送失败", alert.dingtalk_error, current)


def _finalize_alert_diagnosis_and_delivery(
    alert,
    candidate,
    config,
    route,
    *,
    now=None,
    run_diagnosis=False,
    run_delivery=False,
):
    current = now or _now()
    changed_fields = []
    if run_diagnosis:
        diagnosis_status, diagnosis_text, diagnosis_error = _alert_diagnosis_for_candidate(candidate)
        alert.diagnosis_status = diagnosis_status
        alert.diagnosis_text = diagnosis_text
        alert.diagnosis_error = diagnosis_error
        changed_fields.extend(["diagnosis_status", "diagnosis_text", "diagnosis_error"])
    if run_delivery and config.enabled and route is not None:
        _send_dingtalk_alert_notification(alert, route, now=current)
        changed_fields.extend(
            [
                "dingtalk_push_status",
                "dingtalk_message_preview",
                "dingtalk_error",
                "dingtalk_push_time",
                "timeline_json",
            ]
        )
    if changed_fields:
        alert.save(update_fields=list(dict.fromkeys(changed_fields + ["update_time"])))


def _sync_alerts_for_device(device, now=None):
    current = now or _now()
    desired = {item["alertType"]: item for item in _build_alert_candidates(device, now=current)}
    existing_rows = list(DigitalHumanAlert.objects.filter(device=device, status=ALERT_PENDING))
    existing_map = {row.alert_type: row for row in existing_rows}

    for alert_type, candidate in desired.items():
        config, route = _resolve_route_for_region(device.region)
        if alert_type in existing_map:
            row = existing_map[alert_type]
            previous_signature = (
                _normalize_text(row.title, default=""),
                _normalize_text(row.description, default=""),
                _normalize_text(row.alert_module_text, default=""),
                _normalize_text(row.level, default="warning"),
            )
            previous_diagnosis_status = _normalize_text(row.diagnosis_status, default="")
            previous_delivery = {
                "status": _normalize_text(row.dingtalk_push_status, default=""),
                "route": _normalize_text(row.dingtalk_route_region, default=""),
                "owner_name": _normalize_text(row.dingtalk_owner_name, default=""),
                "owner_phone": _normalize_text(row.dingtalk_owner_phone, default=""),
            }
            row.title = candidate["title"]
            row.description = candidate["description"]
            row.alert_module_text = candidate["module"]
            row.level = candidate["level"]
            row.last_occurred_at = current
            next_signature = (
                _normalize_text(row.title, default=""),
                _normalize_text(row.description, default=""),
                _normalize_text(row.alert_module_text, default=""),
                _normalize_text(row.level, default="warning"),
            )
            route_changed = {
                "route": _normalize_text(route.region if route else "", default=""),
                "owner_name": _normalize_text(route.owner_name if route else "", default=""),
                "owner_phone": _normalize_text(route.owner_phone if route else "", default=""),
            } != {
                "route": previous_delivery["route"],
                "owner_name": previous_delivery["owner_name"],
                "owner_phone": previous_delivery["owner_phone"],
            }
            should_refresh_diagnosis = previous_signature != next_signature or previous_diagnosis_status in (
                "",
                "skipped",
                "failed",
            )
            should_send_delivery = previous_delivery["status"] in ("", "pending", "not_configured", "no_route")
            if previous_delivery["status"] == "failed" and route_changed:
                should_send_delivery = True
            _apply_route_state(
                row,
                config,
                route,
                keep_terminal_status=not should_send_delivery,
            )
            row.save()
            _finalize_alert_diagnosis_and_delivery(
                row,
                candidate,
                config,
                route,
                now=current,
                run_diagnosis=should_refresh_diagnosis,
                run_delivery=should_send_delivery and row.dingtalk_push_status == "pending",
            )
            continue

        row = DigitalHumanAlert(
            device=device,
            alert_type=alert_type,
            title=candidate["title"],
            description=candidate["description"],
            alert_module_text=candidate["module"],
            level=candidate["level"],
            status=ALERT_PENDING,
            diagnosis_status="skipped",
            diagnosis_text="",
            diagnosis_error="",
            first_occurred_at=current,
            last_occurred_at=current,
        )
        _apply_route_state(row, config, route, keep_terminal_status=False)
        row.save()
        _append_alert_timeline(row, "告警创建", candidate["description"], current)
        row.save(update_fields=["timeline_json"])
        _finalize_alert_diagnosis_and_delivery(
            row,
            candidate,
            config,
            route,
            now=current,
            run_diagnosis=True,
            run_delivery=row.dingtalk_push_status == "pending",
        )

    for row in existing_rows:
        if row.alert_type in desired:
            continue
        row.status = ALERT_RESOLVED
        row.resolved_at = current
        row.last_occurred_at = current
        _append_alert_timeline(row, "自动恢复", "设备最新上报已恢复正常。", current)
        row.save(update_fields=["status", "resolved_at", "last_occurred_at", "timeline_json"])


def _apply_route_state(alert, config, route, *, keep_terminal_status=False):
    if not config.enabled:
        alert.dingtalk_push_status = "not_configured"
        alert.dingtalk_route_region = ""
        alert.dingtalk_owner_name = ""
        alert.dingtalk_owner_phone = ""
        alert.dingtalk_message_preview = ""
        alert.dingtalk_error = ""
        alert.dingtalk_push_time = None
        return
    if route is None:
        alert.dingtalk_push_status = "no_route"
        alert.dingtalk_route_region = ""
        alert.dingtalk_owner_name = ""
        alert.dingtalk_owner_phone = ""
        alert.dingtalk_message_preview = "当前告警未命中活跃推送路由。"
        alert.dingtalk_error = ""
        alert.dingtalk_push_time = None
        return

    previous_status = _normalize_text(alert.dingtalk_push_status, default="")
    alert.dingtalk_route_region = route.region
    alert.dingtalk_owner_name = route.owner_name
    alert.dingtalk_owner_phone = route.owner_phone
    if keep_terminal_status and previous_status in ("success", "failed"):
        return
    alert.dingtalk_push_status = "pending"
    alert.dingtalk_message_preview = ""
    alert.dingtalk_error = ""
    alert.dingtalk_push_time = None


def refresh_runtime_state():
    current = _now()
    for device in DigitalHumanDevice.objects.all().order_by("id"):
        _ensure_device_codes(device)
        _apply_authorization_status(device, now=current, persist=True)
        _sync_alerts_for_device(device, now=current)


def _device_status(device, pending_alerts=None, now=None):
    current = now or _now()
    if _resolve_authorization_status(device, now=current) != AUTH_AUTHORIZED:
        return "offline"
    if _device_is_stale(device, now=current):
        return "offline"
    alerts = list(pending_alerts or [])
    if any(item.level == "critical" for item in alerts):
        return "error"
    if alerts:
        return "warning"
    return "online"


def _serialize_delivery(alert):
    status = _normalize_text(alert.dingtalk_push_status, default="")
    if status == "success":
        return {
            "routeLabel": _normalize_text(alert.dingtalk_route_region, default="已命中"),
            "ownerName": _normalize_text(alert.dingtalk_owner_name, default=""),
            "ownerPhone": _normalize_text(alert.dingtalk_owner_phone, default=""),
            "statusLabel": "已推送",
            "statusTone": "success",
            "note": _normalize_text(alert.dingtalk_message_preview, default="消息已成功推送"),
        }
    if status == "failed":
        return {
            "routeLabel": _normalize_text(alert.dingtalk_route_region, default="已命中"),
            "ownerName": _normalize_text(alert.dingtalk_owner_name, default=""),
            "ownerPhone": _normalize_text(alert.dingtalk_owner_phone, default=""),
            "statusLabel": "推送失败",
            "statusTone": "error",
            "note": _normalize_text(alert.dingtalk_error, default="请检查路由配置"),
        }
    if status == "no_route":
        return {
            "routeLabel": "未命中",
            "ownerName": "",
            "ownerPhone": "",
            "statusLabel": "未命中",
            "statusTone": "warning",
            "note": "当前告警未匹配到区域路由或兜底路由",
        }
    if status == "not_configured":
        return {
            "routeLabel": "未启用",
            "ownerName": "",
            "ownerPhone": "",
            "statusLabel": "未启用",
            "statusTone": "default",
            "note": "当前未启用钉钉自动推送",
        }
    if status == "pending":
        return {
            "routeLabel": _normalize_text(alert.dingtalk_route_region, default="已命中"),
            "ownerName": _normalize_text(alert.dingtalk_owner_name, default=""),
            "ownerPhone": _normalize_text(alert.dingtalk_owner_phone, default=""),
            "statusLabel": "待发送",
            "statusTone": "processing",
            "note": _normalize_text(alert.dingtalk_message_preview, default="已命中路由，等待推送"),
        }
    return {
        "routeLabel": _normalize_text(alert.dingtalk_route_region, default="--"),
        "ownerName": _normalize_text(alert.dingtalk_owner_name, default=""),
        "ownerPhone": _normalize_text(alert.dingtalk_owner_phone, default=""),
        "statusLabel": "待接入",
        "statusTone": "default",
        "note": _normalize_text(alert.dingtalk_message_preview, default="当前告警暂无推送状态记录"),
    }


def _serialize_alert(alert):
    device = alert.device
    return {
        "id": alert.id,
        "title": _normalize_text(alert.title, default="未命名告警"),
        "description": _normalize_text(alert.description, default="暂无描述"),
        "deviceId": device.id if device else None,
        "deviceCode": _normalize_text(device.device_code if device else "", default=""),
        "deviceName": _normalize_text(device.display_name if device else "", default="--"),
        "region": _normalize_text(device.region if device else "", default="--"),
        "module": _normalize_text(alert.alert_module_text, default="未分类"),
        "level": _normalize_text(alert.level, default="warning"),
        "status": _normalize_text(alert.status, default=ALERT_PENDING),
        "diagnosisStatus": _normalize_text(alert.diagnosis_status, default="skipped"),
        "firstOccurredAt": _format_dt(alert.first_occurred_at),
        "lastOccurredAt": _format_dt(alert.resolved_at or alert.last_occurred_at or alert.first_occurred_at),
        "delivery": _serialize_delivery(alert),
    }


def _serialize_alert_detail(alert):
    payload = _serialize_alert(alert)
    timeline = list(_load_json_text(alert.timeline_json, default=[] ) or [])
    if not timeline:
        timeline = [
            {
                "time": _format_dt(alert.first_occurred_at),
                "action": "告警创建",
                "detail": _normalize_text(alert.description, default="告警已产生"),
            }
        ]
    payload.update(
        {
            "diagnosisText": _normalize_text(alert.diagnosis_text, default="暂无诊断结果"),
            "diagnosisStatus": _normalize_text(alert.diagnosis_status, default="skipped"),
            "diagnosisError": _normalize_text(alert.diagnosis_error, default="") or None,
            "timeline": timeline,
        }
    )
    return payload


def _serialize_device(device, pending_alerts=None, now=None):
    current = now or _now()
    alerts = list(pending_alerts or [])
    screenshot_url = _normalize_text(getattr(device, "screenshot_storage_url", ""), default="")
    if not screenshot_url and (
        _normalize_text(getattr(device, "screenshot_storage_path", ""), default="")
        or (
            _normalize_text(getattr(device, "screenshot_object_bucket", ""), default="")
            and _normalize_text(getattr(device, "screenshot_object_key", ""), default="")
        )
        or _normalize_text(getattr(device, "screenshot_base64", ""), default="")
    ):
        screenshot_url = _device_screenshot_proxy_url(device.id)
    return {
        "id": device.id,
        "deviceCode": _normalize_text(device.device_code, default=""),
        "name": _normalize_text(device.display_name or device.computer_name, default="未命名设备"),
        "region": _normalize_text(device.region, default="--"),
        "status": _device_status(device, pending_alerts=alerts, now=current),
        "netLatency": _intish(device.net_latency_ms),
        "cpu": _intish(device.cpu_usage),
        "mem": _intish(device.memory_usage),
        "gpu": _intish(device.gpu_usage),
        "disk": _intish(device.disk_usage),
        "bandwidth": _normalize_text(device.bandwidth_text, default="--"),
        "peripherals": {
            "cam": bool(device.peripheral_cam),
            "mic": bool(device.peripheral_mic),
        },
        "services": {
            "stream": device.service_stream,
            "llm": device.service_llm,
        },
        "lastReportAt": _format_dt(device.last_report_time),
        "activeWindowTitle": _normalize_text(device.active_window_title, default="--"),
        "activeWindowProcess": _normalize_text(device.active_window_process, default="--"),
        "computerName": _normalize_text(device.computer_name, default="--"),
        "screenshotUrl": screenshot_url or None,
        "alertWindow": {
            "enabled": bool(device.alert_window_enabled),
            "weekdays": list(_load_json_text(device.alert_window_weekdays_json, default=[] ) or []),
            "startTime": _normalize_text(device.alert_window_start_time, default=""),
            "endTime": _normalize_text(device.alert_window_end_time, default=""),
        },
    }


def _serialize_route(route):
    return {
        "id": route.id,
        "region": _normalize_text(route.region, default=""),
        "webhook": _mask_route_secret(route.webhook),
        "secret": _mask_route_secret(route.secret),
        "ownerName": _normalize_text(route.owner_name, default=""),
        "ownerPhone": _normalize_text(route.owner_phone, default=""),
        "active": bool(route.active),
        "defaultRoute": bool(route.is_default_route),
    }


def _routing_snapshot():
    config = _route_config_row()
    return {
        "enabled": bool(config.enabled),
        "routes": [_serialize_route(route) for route in _active_route_rows()],
    }


def _serialize_metric_day(days):
    today = _now().date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _online_count_for_day(day):
    return len(
        {
            row.device_id
            for row in DigitalHumanDeviceMetricHistory.objects.filter(reported_at__date=day)
            if str(row.status or "").strip().lower() == "online"
        }
    )


def get_dashboard_payload():
    refresh_runtime_state()
    current = _now()
    pending_alerts = list(DigitalHumanAlert.objects.filter(status=ALERT_PENDING).select_related("device"))
    alerts_by_device = defaultdict(list)
    for alert in pending_alerts:
        alerts_by_device[alert.device_id].append(alert)
    devices = [
        _serialize_device(device, pending_alerts=alerts_by_device.get(device.id, []), now=current)
        for device in DigitalHumanDevice.objects.all().order_by("id")
    ]
    all_alerts = list(DigitalHumanAlert.objects.all().order_by("-last_occurred_at").select_related("device"))
    alert_rows = [_serialize_alert(alert) for alert in all_alerts]
    days = _serialize_metric_day(7)
    trend_rows = []
    for day in days:
        daily_alerts = [
            alert for alert in all_alerts if alert.first_occurred_at and alert.first_occurred_at.date() == day
        ]
        trend_rows.append(
            {
                "label": day.strftime("%m-%d"),
                "online": _online_count_for_day(day),
                "alerts": len(daily_alerts),
                "critical": len([item for item in daily_alerts if item.level == "critical"]),
            }
        )

    total = len(devices)
    online = len([item for item in devices if item["status"] == "online"])
    offline = len([item for item in devices if item["status"] == "offline"])
    warning = len([item for item in devices if item["status"] == "warning"])
    error = len([item for item in devices if item["status"] == "error"])
    resolved_alerts = [alert for alert in alert_rows if alert["status"] == ALERT_RESOLVED]
    pending_alert_rows = [alert for alert in alert_rows if alert["status"] == ALERT_PENDING]
    critical_alerts = [alert for alert in pending_alert_rows if alert["level"] == "critical"]
    warning_alerts = [alert for alert in pending_alert_rows if alert["level"] == "warning"]
    diagnosis_done = len(
        [alert for alert in alert_rows if str(alert.get("diagnosisStatus") or "").strip().lower() == "success"]
    )
    online_rate = round((online / total) * 100.0, 1) if total else 0.0
    resolved_rate = round((len(resolved_alerts) / len(alert_rows)) * 100.0, 1) if alert_rows else 0.0

    load_rows = []
    for device in devices:
        metric_pairs = [
            ("CPU", device["cpu"], "%"),
            ("内存", device["mem"], "%"),
            ("GPU", device["gpu"], "%"),
            ("磁盘", device["disk"], "%"),
            ("延迟", device["netLatency"], "ms"),
        ]
        metric_type, metric_value, metric_unit = max(metric_pairs, key=lambda item: item[1])
        load_rows.append(
            {
                "id": device["id"],
                "name": f'{device["name"]} ({device["deviceCode"]})' if device["deviceCode"] else device["name"],
                "deviceCode": metric_type,
                "region": metric_unit,
                "maxLoad": _intish(metric_value),
            }
        )
    load_rows.sort(key=lambda item: item["maxLoad"], reverse=True)

    routing = _routing_snapshot()
    return {
        "generatedAt": _format_dt(current),
        "kpis": [
            {
                "title": "终端总数",
                "value": total,
                "suffix": "台",
                "color": "#2563eb",
                "metaItems": [{"label": "在线", "value": online}, {"label": "离线", "value": offline}],
            },
            {
                "title": "平均在线率",
                "value": online_rate,
                "suffix": "%",
                "color": "#16a34a",
                "metaItems": [{"label": "告警中", "value": warning + error}, {"label": "稳定", "value": online}],
            },
            {
                "title": "待处理告警",
                "value": len(pending_alert_rows),
                "suffix": "条",
                "color": "#f97316",
                "metaItems": [
                    {"label": "严重", "value": len(critical_alerts)},
                    {"label": "警告", "value": len(warning_alerts)},
                ],
            },
            {
                "title": "闭环处置率",
                "value": resolved_rate,
                "suffix": "%",
                "color": "#7c3aed",
                "metaItems": [
                    {"label": "已解决", "value": len(resolved_alerts)},
                    {"label": "诊断完成", "value": diagnosis_done},
                ],
            },
        ],
        "trendRows": trend_rows,
        "topLoads": load_rows[:5],
        "alertFeed": alert_rows[:5],
        "routingHealth": {
            "enabled": bool(routing["enabled"]),
            "activeRoutes": len([item for item in routing["routes"] if item["active"]]),
        },
    }


def list_devices():
    refresh_runtime_state()
    current = _now()
    pending_alerts = list(DigitalHumanAlert.objects.filter(status=ALERT_PENDING))
    alerts_by_device = defaultdict(list)
    for alert in pending_alerts:
        alerts_by_device[alert.device_id].append(alert)
    rows = [
        _serialize_device(device, pending_alerts=alerts_by_device.get(device.id, []), now=current)
        for device in DigitalHumanDevice.objects.all().order_by("id")
    ]
    return rows


def get_device_screenshot_descriptor(device_id):
    device = DigitalHumanDevice.objects.filter(id=_parse_object_id(device_id, "deviceId")).first()
    if not device:
        raise DigitalHumanError("设备不存在", status_code=404)
    if _normalize_text(device.screenshot_object_bucket, default="") and _normalize_text(device.screenshot_object_key, default=""):
        return {
            "storage": "s3",
            "bucket": _normalize_text(device.screenshot_object_bucket, default=""),
            "object_key": _normalize_text(device.screenshot_object_key, default=""),
            "content_type": _normalize_text(device.screenshot_content_type, default="application/octet-stream"),
        }
    if _normalize_text(device.screenshot_storage_path, default=""):
        upload_root = str(getattr(g_config, "uploadDir", "") or "").strip()
        if not upload_root:
            raise DigitalHumanError("截图不存在", status_code=404)
        try:
            abs_path = resolve_under_base(upload_root, device.screenshot_storage_path)
        except Exception as exc:
            raise DigitalHumanError(f"截图路径无效: {exc}", status_code=404) from exc
        if not os.path.isfile(abs_path):
            raise DigitalHumanError("截图不存在", status_code=404)
        return {
            "storage": "local",
            "path": abs_path,
            "content_type": _normalize_text(device.screenshot_content_type, default="application/octet-stream"),
        }
    parsed = _decode_report_image(device.screenshot_base64)
    if parsed:
        return {
            "storage": "inline",
            "image_bytes": parsed["image_bytes"],
            "content_type": parsed["content_type"],
        }
    raise DigitalHumanError("截图不存在", status_code=404)


def update_device_window(device_id, payload):
    device = DigitalHumanDevice.objects.filter(id=_parse_object_id(device_id, "deviceId")).first()
    if not device:
        raise DigitalHumanError("设备不存在")
    device.alert_window_enabled = _boolish(payload.get("enabled"))
    device.alert_window_weekdays_json = _dump_json_text(list(payload.get("weekdays") or []))
    device.alert_window_start_time = _normalize_text(payload.get("startTime"), default="")
    device.alert_window_end_time = _normalize_text(payload.get("endTime"), default="")
    device.save(
        update_fields=[
            "alert_window_enabled",
            "alert_window_weekdays_json",
            "alert_window_start_time",
            "alert_window_end_time",
        ]
    )
    return _serialize_device(device, pending_alerts=list(DigitalHumanAlert.objects.filter(device=device, status=ALERT_PENDING)))


def list_alerts():
    refresh_runtime_state()
    return [
        _serialize_alert(alert)
        for alert in DigitalHumanAlert.objects.all().order_by("-last_occurred_at", "-id").select_related("device")
    ]


def get_alert_detail(alert_id):
    alert = DigitalHumanAlert.objects.filter(id=_parse_object_id(alert_id, "告警 ID")).select_related("device").first()
    if not alert:
        raise DigitalHumanError("告警不存在")
    return _serialize_alert_detail(alert)


def resolve_alert(alert_id):
    alert = DigitalHumanAlert.objects.filter(id=_parse_object_id(alert_id, "告警 ID")).select_related("device").first()
    if not alert:
        raise DigitalHumanError("告警不存在")
    current = _now()
    alert.status = ALERT_RESOLVED
    alert.resolved_at = current
    alert.last_occurred_at = current
    _append_alert_timeline(alert, "人工复核", "Beacon 数字人监管页已完成闭环处置。", current)
    alert.save(update_fields=["status", "resolved_at", "last_occurred_at", "timeline_json"])
    return _serialize_alert_detail(alert)


def get_alert_routing_snapshot():
    return _routing_snapshot()


def save_alert_routing_enabled(enabled):
    config = _route_config_row()
    config.enabled = _boolish(enabled, default=config.enabled)
    config.save(update_fields=["enabled", "update_time"])
    return _routing_snapshot()


def create_alert_route(payload):
    route = DigitalHumanAlertRoute.objects.create(
        region=_normalize_text(payload.get("region"), default=""),
        webhook=_normalize_text(payload.get("webhook"), default=""),
        secret=_normalize_text(payload.get("secret"), default=""),
        owner_name=_normalize_text(payload.get("ownerName"), default=""),
        owner_phone=_normalize_text(payload.get("ownerPhone"), default=""),
        active=_boolish(payload.get("active"), default=True),
        is_default_route=_boolish(payload.get("defaultRoute"), default=False),
    )
    if route.is_default_route:
        DigitalHumanAlertRoute.objects.exclude(id=route.id).update(is_default_route=False)
    return _serialize_route(route)


def update_alert_route(route_id, payload):
    route = DigitalHumanAlertRoute.objects.filter(id=_parse_object_id(route_id, "路由 ID")).first()
    if not route:
        raise DigitalHumanError("路由不存在")
    route.region = _normalize_text(payload.get("region"), default=route.region)
    if _strip_to_none(payload.get("webhook")) is not None:
        route.webhook = _normalize_text(payload.get("webhook"), default="")
    if _strip_to_none(payload.get("secret")) is not None:
        route.secret = _normalize_text(payload.get("secret"), default="")
    route.owner_name = _normalize_text(payload.get("ownerName"), default=route.owner_name)
    route.owner_phone = _normalize_text(payload.get("ownerPhone"), default=route.owner_phone)
    route.active = _boolish(payload.get("active"), default=route.active)
    route.is_default_route = _boolish(payload.get("defaultRoute"), default=route.is_default_route)
    route.save()
    if route.is_default_route:
        DigitalHumanAlertRoute.objects.exclude(id=route.id).update(is_default_route=False)
    return _serialize_route(route)


def delete_alert_route(route_id):
    route = DigitalHumanAlertRoute.objects.filter(id=_parse_object_id(route_id, "路由 ID")).first()
    if not route:
        raise DigitalHumanError("路由不存在")
    route.delete()
    return {}


def _log_diagnosis_for_row(log_row):
    level = _normalize_text(log_row.level, default="INFO")
    if level.upper() == "INFO":
        return "skipped", "INFO 级别日志无需 AI 分析。", ""
    config = DigitalHumanAiDiagnosisConfig.objects.order_by("id").first()
    if not _is_ai_config_complete(config):
        return "skipped", "", ""
    system_prompt = _normalize_text(
        getattr(config, "log_system_prompt", ""),
        default="你是数字人监管平台的日志诊断助手。请根据日志上下文输出简洁、可执行的中文排障建议。",
    )
    user_prompt = "\n".join(
        [
            "请分析以下数字人终端日志，并给出 2-4 句中文诊断建议：",
            f"设备: {_normalize_text(log_row.device.display_name or log_row.device.computer_name, default='未命名设备')}",
            f"设备编号: {_normalize_text(log_row.device.device_code, default='')}",
            f"区域: {_normalize_text(log_row.device.region, default='')}",
            f"日志时间: {_format_dt(log_row.time)}",
            f"日志等级: {_normalize_text(log_row.level, default='INFO')}",
            f"日志模块: {_normalize_text(log_row.module, default='unknown')}",
            f"日志内容: {_normalize_text(log_row.message, default='')}",
        ]
    )
    return _call_ai_diagnosis(config, system_prompt=system_prompt, user_prompt=user_prompt)


def _serialize_log(log_row):
    return {
        "id": str(log_row.id),
        "time": _format_dt(log_row.time),
        "deviceId": _normalize_text(log_row.device.agent_device_id, default=""),
        "deviceName": _normalize_text(log_row.device.display_name or log_row.device.computer_name, default="--"),
        "level": _normalize_text(log_row.level, default="INFO"),
        "module": _normalize_text(log_row.module, default="--"),
        "message": _normalize_text(log_row.message, default="暂无日志内容"),
        "diagnosisStatus": _normalize_text(log_row.diagnosis_status, default="skipped"),
        "diagnosisText": _normalize_text(log_row.diagnosis_text, default="") or None,
        "diagnosisError": _normalize_text(log_row.diagnosis_error, default="") or None,
        "traceId": str(log_row.id),
        "structured": {
            "source": "beacon-digital-human",
            "note": "Beacon 本地日志结构化上下文仍为最小实现。",
        },
    }


def list_monitor_logs(filters):
    refresh_runtime_state()
    params = filters or {}
    rows = list(DigitalHumanHumanLog.objects.select_related("device").all().order_by("-time", "-id"))
    keyword = _normalize_text(params.get("keyword"), default="").lower()
    level = _normalize_text(params.get("level"), default="")
    module = _normalize_text(params.get("module"), default="")
    start = _parse_dt(params.get("start")) if _strip_to_none(params.get("start")) else None
    end = _parse_dt(params.get("end")) if _strip_to_none(params.get("end")) else None
    filtered = []
    for row in rows:
        if keyword:
            haystack = " ".join(
                [
                    _normalize_text(row.message, default=""),
                    _normalize_text(row.module, default=""),
                    _normalize_text(row.device.display_name, default=""),
                ]
            ).lower()
            if keyword not in haystack:
                continue
        if level and _normalize_text(row.level, default="").upper() != level.upper():
            continue
        if module and _normalize_text(row.module, default="") != module:
            continue
        if start and row.time < start:
            continue
        if end and row.time > end:
            continue
        filtered.append(_serialize_log(row))
    return filtered


def get_monitor_log_node_status():
    latest = DigitalHumanHumanLog.objects.order_by("-time").first()
    if latest is None:
        return {"status": "offline", "label": "暂无上报", "lastReceivedAt": None}
    current = _now()
    delta = current - latest.time
    if delta > timedelta(minutes=5):
        return {"status": "offline", "label": "上报中断", "lastReceivedAt": _format_dt(latest.time)}
    if delta > timedelta(minutes=1):
        return {"status": "warning", "label": "轻微延迟", "lastReceivedAt": _format_dt(latest.time)}
    return {"status": "healthy", "label": "运行正常", "lastReceivedAt": _format_dt(latest.time)}


def reanalyze_monitor_log(log_id):
    log_row = DigitalHumanHumanLog.objects.select_related("device").filter(id=_parse_object_id(log_id, "日志 ID")).first()
    if not log_row:
        raise DigitalHumanError("日志不存在")
    status, text, error = _log_diagnosis_for_row(log_row)
    log_row.diagnosis_status = status
    log_row.diagnosis_error = error
    log_row.diagnosis_text = text
    log_row.save(update_fields=["diagnosis_status", "diagnosis_error", "diagnosis_text"])
    return {
        "id": str(log_row.id),
        "diagnosisStatus": log_row.diagnosis_status,
        "diagnosisText": log_row.diagnosis_text or None,
        "diagnosisError": log_row.diagnosis_error or None,
    }


def get_ops_report(range_key):
    refresh_runtime_state()
    days = {"today": 1, "7days": 7, "30days": 30}.get(str(range_key or "").strip(), 7)
    current = _now()
    start = current - timedelta(days=days - 1)
    history_rows = list(DigitalHumanDeviceMetricHistory.objects.filter(reported_at__gte=start).order_by("reported_at"))
    alert_rows = list(DigitalHumanAlert.objects.filter(first_occurred_at__gte=start).select_related("device"))
    resolved_rows = [row for row in alert_rows if row.resolved_at]
    trend_days = _serialize_metric_day(days)
    trend_rows = []
    for day in trend_days:
        day_history = [row for row in history_rows if row.reported_at.date() == day]
        online_devices = {row.device_id for row in day_history if str(row.status).lower() == "online"}
        total_devices = max(DigitalHumanDevice.objects.count(), 1)
        day_alerts = [row for row in alert_rows if row.first_occurred_at and row.first_occurred_at.date() == day]
        day_repairs = [row for row in resolved_rows if row.resolved_at and row.resolved_at.date() == day]
        trend_rows.append(
            {
                "label": day.strftime("%m-%d"),
                "alerts": len(day_alerts),
                "repairs": len(day_repairs),
                "onlineRate": round((len(online_devices) / total_devices) * 100.0, 1),
            }
        )

    total_devices = max(DigitalHumanDevice.objects.count(), 1)
    recent_devices = list(DigitalHumanDevice.objects.all())
    avg_latency = round(
        sum([_floatish(device.net_latency_ms, default=0, digits=None) for device in recent_devices]) / len(recent_devices),
        1,
    ) if recent_devices else 0.0
    mttr_minutes = round(
        sum(
            [
                max((row.resolved_at - row.first_occurred_at).total_seconds() / 60.0, 0.0)
                for row in resolved_rows
                if row.first_occurred_at and row.resolved_at
            ]
        ) / len(resolved_rows),
        1,
    ) if resolved_rows else 0.0
    module_distribution_counter = Counter([_normalize_text(row.alert_module_text, default="未分类") for row in alert_rows])

    focus_device_counter = Counter()
    focus_device_modules = defaultdict(Counter)
    for row in alert_rows:
        if row.device_id:
            focus_device_counter[row.device_id] += 1
            focus_device_modules[row.device_id][_normalize_text(row.alert_module_text, default="未分类")] += 1

    focus_devices = []
    for device_id, fault_count in focus_device_counter.most_common(5):
        device = next((item for item in recent_devices if item.id == device_id), None)
        if device is None:
            continue
        device_history = [row for row in history_rows if row.device_id == device_id]
        online_points = len([row for row in device_history if str(row.status or "").lower() == "online"])
        sla = round((online_points / len(device_history)) * 100.0, 1) if device_history else 0.0
        focus_devices.append(
            {
                "deviceId": device.id,
                "deviceCode": _normalize_text(device.device_code, default=""),
                "deviceName": _normalize_text(device.display_name or device.computer_name, default="--"),
                "region": _normalize_text(device.region, default="--"),
                "faultCount": fault_count,
                "sla": sla,
                "primaryModule": focus_device_modules[device_id].most_common(1)[0][0],
            }
        )

    return {
        "rangeKey": str(range_key or "7days"),
        "generatedAt": _format_dt(current),
        "kpis": {
            "globalSla": trend_rows[-1]["onlineRate"] if trend_rows else 0.0,
            "mttrMinutes": mttr_minutes,
            "alertCount": len(alert_rows),
            "autoRepairRate": round((len(resolved_rows) / len(alert_rows)) * 100.0, 1) if alert_rows else 0.0,
            "avgLlmLatency": avg_latency,
        },
        "trendRows": trend_rows,
        "moduleDistribution": [{"name": name, "value": value} for name, value in module_distribution_counter.items()],
        "focusDevices": focus_devices,
    }


def _is_ai_config_complete(config):
    return bool(
        config
        and bool(config.enabled)
        and _strip_to_none(config.base_url)
        and _strip_to_none(config.api_key)
        and _strip_to_none(config.model)
    )


def get_ops_ai_insight(range_key):
    report = get_ops_report(range_key)
    config = DigitalHumanAiDiagnosisConfig.objects.order_by("id").first()
    if not _is_ai_config_complete(config):
        return {"status": "skipped", "text": None, "error": None, "generatedAt": report["generatedAt"]}
    system_prompt = _normalize_text(
        getattr(config, "alert_system_prompt", ""),
        default="你是数字人监管平台的运维分析助手。请输出简洁、可执行、偏运营视角的中文洞察。",
    )
    user_prompt = "\n".join(
        [
            "请基于以下数字人运维报告输出 3-5 句中文洞察，包含风险判断和优先建议：",
            f"时间范围: {_normalize_text(report.get('rangeKey'), default='7days')}",
            f"告警总量: {_intish((report.get('kpis') or {}).get('alertCount'), default=0)}",
            f"整体 SLA: {_floatish((report.get('kpis') or {}).get('globalSla'), default=0.0, digits=None)}%",
            f"平均修复时长: {_floatish((report.get('kpis') or {}).get('mttrMinutes'), default=0.0, digits=None)} 分钟",
            f"自动修复率: {_floatish((report.get('kpis') or {}).get('autoRepairRate'), default=0.0, digits=None)}%",
            f"平均 LLM 延迟: {_floatish((report.get('kpis') or {}).get('avgLlmLatency'), default=0.0, digits=None)} ms",
            f"模块分布: {json.dumps(report.get('moduleDistribution') or [], ensure_ascii=False)}",
            f"重点设备: {json.dumps((report.get('focusDevices') or [])[:3], ensure_ascii=False)}",
            f"近期趋势: {json.dumps((report.get('trendRows') or [])[-5:], ensure_ascii=False)}",
        ]
    )
    status, text, error = _call_ai_diagnosis(config, system_prompt=system_prompt, user_prompt=user_prompt)
    return {
        "status": status,
        "text": text or None,
        "error": error or None,
        "generatedAt": report["generatedAt"],
    }


def list_jwt_accounts():
    return [
        {
            "accountUuid": row.account_uuid,
            "projectName": _normalize_text(row.project_name, default=""),
            "tenantName": _normalize_text(row.tenant_name, default=""),
            "tokenTtlMinutes": int(row.token_ttl_minutes or 0),
            "enabled": bool(row.enabled),
            "secretMask": _normalize_text(row.secret_mask, default=""),
            "lastTokenIssuedAt": _format_dt(row.last_token_issued_at),
            "createdAt": _format_dt(row.create_time),
        }
        for row in DigitalHumanJwtAccount.objects.all().order_by("-create_time", "-id")
    ]


def create_jwt_account(payload):
    tenant_name = _normalize_text(payload.get("tenantName"), default="")
    if not tenant_name:
        raise DigitalHumanError("缺少 tenantName")
    if DigitalHumanJwtAccount.objects.filter(tenant_name=tenant_name).exists():
        raise DigitalHumanError("租户名已存在")
    token_ttl_minutes = max(1, _intish(payload.get("tokenTtlMinutes"), default=30))
    secret = _jwt_secret()
    row = DigitalHumanJwtAccount.objects.create(
        account_uuid=str(uuid.uuid4()),
        project_name=_normalize_text(payload.get("projectName"), default=""),
        tenant_name=tenant_name,
        secret_hash=_sha256_hex(secret),
        secret_mask=_mask_secret(secret, prefix=2, suffix=2),
        token_ttl_minutes=token_ttl_minutes,
        credential_version=1,
        enabled=True,
    )
    return {
        "account": {
            "accountUuid": row.account_uuid,
            "projectName": row.project_name,
            "tenantName": row.tenant_name,
            "tokenTtlMinutes": row.token_ttl_minutes,
            "enabled": row.enabled,
            "secretMask": row.secret_mask,
            "lastTokenIssuedAt": _format_dt(row.last_token_issued_at),
            "createdAt": _format_dt(row.create_time),
        },
        "secretReveal": {
            "accountUuid": row.account_uuid,
            "secret": secret,
            "secretMask": row.secret_mask,
            "tenantName": row.tenant_name,
        },
    }


def rotate_jwt_account_secret(account_uuid):
    row = DigitalHumanJwtAccount.objects.filter(account_uuid=_normalize_text(account_uuid, default="")).first()
    if not row:
        raise DigitalHumanError("JWT 账户不存在")
    secret = _jwt_secret()
    row.secret_hash = _sha256_hex(secret)
    row.secret_mask = _mask_secret(secret, prefix=2, suffix=2)
    row.credential_version = int(row.credential_version or 0) + 1
    row.save(update_fields=["secret_hash", "secret_mask", "credential_version", "update_time"])
    return {"accountUuid": row.account_uuid, "secret": secret, "secretMask": row.secret_mask}


def update_jwt_account_status(account_uuid, enabled):
    row = DigitalHumanJwtAccount.objects.filter(account_uuid=_normalize_text(account_uuid, default="")).first()
    if not row:
        raise DigitalHumanError("JWT 账户不存在")
    row.enabled = _boolish(enabled, default=row.enabled)
    row.save(update_fields=["enabled", "update_time"])
    return {
        "accountUuid": row.account_uuid,
        "projectName": row.project_name,
        "tenantName": row.tenant_name,
        "tokenTtlMinutes": row.token_ttl_minutes,
        "enabled": row.enabled,
        "secretMask": row.secret_mask,
        "lastTokenIssuedAt": _format_dt(row.last_token_issued_at),
        "createdAt": _format_dt(row.create_time),
    }


def delete_jwt_account(account_uuid):
    row = DigitalHumanJwtAccount.objects.filter(account_uuid=_normalize_text(account_uuid, default="")).first()
    if not row:
        raise DigitalHumanError("JWT 账户不存在")
    row.delete()
    return {}


def list_device_authorizations(filters):
    refresh_runtime_state()
    params = filters or {}
    region = _normalize_text(params.get("region"), default="")
    display_name = _normalize_text(params.get("displayName"), default="")
    mac = _normalize_text(params.get("mac"), default="")
    rows = []
    for device in DigitalHumanDevice.objects.all().order_by("-create_time", "-id"):
        _ensure_device_codes(device)
        if region and region not in _normalize_text(device.region, default=""):
            continue
        if display_name and display_name not in _normalize_text(device.display_name or device.computer_name, default=""):
            continue
        if mac and mac.lower() not in _normalize_text(device.machine_mac or device.mac_address, default="").lower():
            continue
        rows.append(_serialize_device_authorization(device))
    return rows


def _serialize_device_authorization(device):
    return {
        "id": device.id,
        "deviceId": _normalize_text(device.agent_device_id, default=""),
        "displayName": _normalize_text(device.display_name or device.computer_name, default=""),
        "region": _normalize_text(device.region, default=""),
        "mac": _normalize_text(device.machine_mac or device.mac_address, default=""),
        "cpu": _normalize_text(device.processor, default=""),
        "tenantName": _normalize_text(device.tenant_name, default=""),
        "registeredByJwtAccountUuid": _normalize_text(device.registered_by_jwt_account_uuid, default=""),
        "registeredByJwtTenantName": _normalize_text(device.registered_by_jwt_tenant_name, default=""),
        "authorizationStatus": _apply_authorization_status(device, persist=True),
        "enabled": bool(device.authorization_enabled),
        "createdAt": _format_dt(device.create_time),
        "validFrom": _format_dt(device.authorization_valid_from),
        "validUntil": _format_dt(device.authorization_valid_until),
    }


def get_device_authorization_detail(device_id):
    device = DigitalHumanDevice.objects.filter(id=_parse_object_id(device_id, "设备授权 ID")).first()
    if not device:
        raise DigitalHumanError("设备授权不存在")
    payload = _serialize_device_authorization(device)
    payload.update(
        {
            "rustdeskId": _normalize_text(device.rustdesk_id, default=""),
            "rustdeskPassword": _normalize_text(device.rustdesk_password, default=""),
            "agentToken": _normalize_text(device.agent_token, default=""),
        }
    )
    return payload


def update_device_authorization(device_id, payload):
    device = DigitalHumanDevice.objects.filter(id=_parse_object_id(device_id, "设备授权 ID")).first()
    if not device:
        raise DigitalHumanError("设备授权不存在")
    device.authorization_enabled = _boolish(payload.get("enabled"), default=device.authorization_enabled)
    device.display_name = _normalize_text(payload.get("displayName"), default=device.display_name)
    device.region = _normalize_text(payload.get("region"), default=device.region)
    device.rustdesk_id = _normalize_text(payload.get("rustdeskId"), default=device.rustdesk_id)
    device.rustdesk_password = _normalize_text(payload.get("rustdeskPassword"), default=device.rustdesk_password)
    device.authorization_valid_from = _parse_dt(payload.get("validFrom")) if _strip_to_none(payload.get("validFrom")) else None
    device.authorization_valid_until = _parse_dt(payload.get("validUntil")) if _strip_to_none(payload.get("validUntil")) else None
    device.authorization_status = _resolve_authorization_status(device)
    device.save()
    return get_device_authorization_detail(device.id)


def delete_device_authorization(device_id):
    device = DigitalHumanDevice.objects.filter(id=_parse_object_id(device_id, "设备授权 ID")).first()
    if not device:
        raise DigitalHumanError("设备授权不存在")
    device.delete()
    return {}


def _ai_config_row():
    row = DigitalHumanAiDiagnosisConfig.objects.order_by("id").first()
    if row is None:
        row = DigitalHumanAiDiagnosisConfig.objects.create(
            enabled=False,
            base_url="",
            api_key="",
            model="",
            temperature=0.2,
            alert_system_prompt="",
            log_system_prompt="",
            connect_timeout_ms=10000,
            read_timeout_ms=60000,
        )
    return row


def _serialize_ai_config(row):
    return {
        "id": row.id,
        "enabled": bool(row.enabled),
        "baseUrl": _normalize_text(row.base_url, default=""),
        "apiKeyMasked": _mask_secret(row.api_key, prefix=4, suffix=4),
        "apiKeyConfigured": bool(_strip_to_none(row.api_key)),
        "model": _normalize_text(row.model, default=""),
        "temperature": _floatish(row.temperature, default=0.2, digits=None),
        "alertSystemPrompt": _normalize_text(row.alert_system_prompt, default=""),
        "logSystemPrompt": _normalize_text(row.log_system_prompt, default=""),
        "connectTimeoutMs": int(row.connect_timeout_ms or 10000),
        "readTimeoutMs": int(row.read_timeout_ms or 60000),
    }


def get_ai_diagnosis_config():
    return _serialize_ai_config(_ai_config_row())


def save_ai_diagnosis_config(payload):
    row = _ai_config_row()
    row.enabled = _boolish(payload.get("enabled"))
    row.base_url = _normalize_text(payload.get("baseUrl"), default="")
    row.model = _normalize_text(payload.get("model"), default="")
    row.temperature = _floatish(payload.get("temperature"), default=0.2, digits=None)
    row.alert_system_prompt = _normalize_text(payload.get("alertSystemPrompt"), default="")
    row.log_system_prompt = _normalize_text(payload.get("logSystemPrompt"), default="")
    row.connect_timeout_ms = max(1000, _intish(payload.get("connectTimeoutMs"), default=10000))
    row.read_timeout_ms = max(1000, _intish(payload.get("readTimeoutMs"), default=60000))
    incoming_api_key = _strip_to_none(payload.get("apiKey"))
    if incoming_api_key is not None:
        row.api_key = incoming_api_key
    row.save()
    return _serialize_ai_config(row)


def _candidate_model_urls(base_url):
    trimmed = _normalize_text(base_url, default="").rstrip("/")
    if not trimmed:
        return []
    if trimmed.endswith("/models"):
        return [trimmed]
    if trimmed.endswith("/v1"):
        return [trimmed + "/models"]
    return [trimmed + "/models", trimmed + "/v1/models"]


def test_ai_diagnosis_connection(payload):
    saved = _ai_config_row()
    base_url = _normalize_text(payload.get("baseUrl"), default=_normalize_text(saved.base_url, default=""))
    api_key = _normalize_text(payload.get("apiKey"), default=_normalize_text(saved.api_key, default=""))
    if not base_url:
        return {"success": False, "message": "连接测试失败: 缺少 baseUrl", "reply": ""}
    if not api_key:
        return {"success": False, "message": "连接测试失败: 缺少 apiKey", "reply": ""}
    connect_timeout = max(1, _intish(payload.get("connectTimeoutMs"), default=10000)) / 1000.0
    read_timeout = max(1, _intish(payload.get("readTimeoutMs"), default=60000)) / 1000.0
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    for url in _candidate_model_urls(base_url):
        try:
            response = requests.get(url, headers=headers, timeout=(connect_timeout, read_timeout))
            if response.status_code >= 400:
                continue
            try:
                payload_json = response.json()
            except Exception:
                payload_json = None
            reply = ""
            if isinstance(payload_json, dict) and isinstance(payload_json.get("data"), list) and payload_json["data"]:
                first = payload_json["data"][0]
                reply = _normalize_text(first.get("id") if isinstance(first, dict) else first, default="")
            if not reply:
                reply = _normalize_text(response.text, default="连接测试成功")[:200]
            return {"success": True, "message": "连接测试成功", "reply": reply}
        except Exception:
            continue
    return {"success": False, "message": "连接测试失败: 无法访问模型列表接口", "reply": ""}


def _sign_open_agent_token(payload):
    return signing.dumps(payload, salt=OPEN_TOKEN_SALT, compress=True)


def _load_open_agent_token(token, *, max_age=None):
    try:
        return signing.loads(token, salt=OPEN_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise DigitalHumanError("jwtToken已过期", status_code=401) from exc
    except signing.BadSignature as exc:
        raise DigitalHumanError("jwtToken无效", status_code=401) from exc


def issue_open_agent_token(payload):
    tenant_name = _normalize_text(payload.get("tenantName"), default="")
    secret = _normalize_text(payload.get("secret"), default="")
    account = DigitalHumanJwtAccount.objects.filter(tenant_name=tenant_name).first()
    if not account or account.secret_hash != _sha256_hex(secret):
        raise DigitalHumanError("租户名或密钥错误", status_code=401)
    if not account.enabled:
        raise DigitalHumanError("JWT账户已停用", status_code=403)
    token = _sign_open_agent_token(
        {
            "accountUuid": account.account_uuid,
            "tenantName": account.tenant_name,
            "credentialVersion": int(account.credential_version or 0),
        }
    )
    account.last_token_issued_at = _now()
    account.save(update_fields=["last_token_issued_at", "update_time"])
    expires_in_seconds = int(account.token_ttl_minutes or 30) * 60
    return {
        "token": token,
        "tokenType": "Bearer",
        "expiresInSeconds": expires_in_seconds,
        "expiresAt": _format_dt(account.last_token_issued_at + timedelta(seconds=expires_in_seconds)),
    }


def _validate_open_agent_token(authorization):
    token = extract_bearer_token(authorization)
    if not token:
        raise DigitalHumanError("缺少jwtToken", status_code=401)
    unsigned = _load_open_agent_token(token)
    account_uuid = _normalize_text(unsigned.get("accountUuid"), default="")
    account = DigitalHumanJwtAccount.objects.filter(account_uuid=account_uuid).first()
    if not account:
        raise DigitalHumanError("jwtToken无效", status_code=401)
    if not account.enabled:
        raise DigitalHumanError("JWT账户已停用", status_code=403)
    _load_open_agent_token(token, max_age=int(account.token_ttl_minutes or 30) * 60)
    if int(unsigned.get("credentialVersion") or 0) != int(account.credential_version or 0):
        raise DigitalHumanError("jwtToken无效", status_code=401)
    if _normalize_text(unsigned.get("tenantName"), default="") != account.tenant_name:
        raise DigitalHumanError("jwtToken无效", status_code=401)
    return account


def _generate_machine_code(os_name, machine_mac, tenant_name):
    if not os_name or not machine_mac or not tenant_name:
        raise DigitalHumanError("machineCode校验失败")
    payload = f"{os_name}*{machine_mac}*{tenant_name}"
    return hashlib.sha256((_authorization_secret() + payload).encode("utf-8")).hexdigest()


def _resolve_machine_code_from_authorization(authorization):
    token = extract_bearer_token(authorization)
    if not token:
        raise DigitalHumanError("缺少machineCode", status_code=401)
    if HEX_64_RE.match(token):
        return token.lower()
    secret_key = _upload_auth_sm4_secret_key()
    try:
        payload = sm4_decrypt_ecb_pkcs7(token, secret_key)
    except Exception as exc:
        raise DigitalHumanError("machineCode解密失败", status_code=401) from exc
    parts = payload.split("*", 1)
    if len(parts) != 2 or not HEX_64_RE.match(parts[0]):
        raise DigitalHumanError("machineCode格式不合法", status_code=401)
    try:
        payload_time = datetime.strptime(parts[1].strip(), UPLOAD_PAYLOAD_TIME_FORMAT)
    except Exception as exc:
        raise DigitalHumanError("machineCode时间戳格式不合法", status_code=401) from exc
    current = _now()
    if abs(current - payload_time) > UPLOAD_AUTH_WINDOW:
        raise DigitalHumanError("machineCode已过期", status_code=401)
    _reject_upload_replay(payload, now=current)
    return parts[0].lower()


def _resolve_report_device(authorization):
    machine_code = _resolve_machine_code_from_authorization(authorization)
    device = DigitalHumanDevice.objects.filter(machine_code=machine_code).first()
    if not device:
        raise DigitalHumanError("设备未授权", status_code=403)
    status = _apply_authorization_status(device, persist=True)
    if status == AUTH_EXPIRED:
        raise DigitalHumanError("授权已过期", status_code=403)
    if status != AUTH_AUTHORIZED:
        raise DigitalHumanError("设备未授权", status_code=403)
    return device


def _resolve_open_device_for_account(account, device_id):
    parsed_device_id = _parse_object_id(device_id, "deviceId")
    device = DigitalHumanDevice.objects.filter(id=parsed_device_id).first()
    if not device:
        raise DigitalHumanError("设备不存在", status_code=404)
    if _normalize_text(device.registered_by_jwt_account_uuid, default="") != account.account_uuid:
        raise DigitalHumanError("设备不属于当前租户", status_code=403)
    status = _apply_authorization_status(device, persist=True)
    if status == AUTH_EXPIRED:
        raise DigitalHumanError("授权已过期", status_code=403)
    if status != AUTH_AUTHORIZED:
        raise DigitalHumanError("设备未授权", status_code=403)
    return device


def _latest_config_version_for_device(device):
    latest_values = [getattr(device, "update_time", None)]
    route_config = DigitalHumanAlertRouteConfig.objects.order_by("-update_time", "-id").first()
    ai_config = DigitalHumanAiDiagnosisConfig.objects.order_by("-update_time", "-id").first()
    if route_config is not None:
        latest_values.append(getattr(route_config, "update_time", None))
    if ai_config is not None:
        latest_values.append(getattr(ai_config, "update_time", None))
    latest_dt = max([value for value in latest_values if value is not None], default=None)
    if latest_dt is None:
        latest_dt = _now()
    return f"v{latest_dt.strftime('%Y%m%d.%H%M%S')}"


@transaction.atomic
def register_open_agent(authorization, payload):
    account = _validate_open_agent_token(authorization)
    machine_code = _normalize_text(payload.get("machineCode"), default="").lower()
    machine_mac = _normalize_text(payload.get("machineMac"), default="")
    tenant_name = _normalize_text(payload.get("tenantName"), default="")
    os_name = _normalize_text(payload.get("osName"), default="")
    effective_tenant_name = _normalize_text(account.tenant_name, default="")
    if not HEX_64_RE.match(machine_code):
        raise DigitalHumanError("machineCode格式不合法")
    if tenant_name and tenant_name != effective_tenant_name:
        logger.warning(
            "Digital human register payload tenant mismatched JWT tenant; using JWT tenant: account_uuid=%s payload_tenant=%s jwt_tenant=%s",
            account.account_uuid,
            tenant_name,
            effective_tenant_name,
        )
    matched_tenant_name = ""
    expected_machine_code = _generate_machine_code(os_name, machine_mac, effective_tenant_name).lower()
    if machine_code == expected_machine_code:
        matched_tenant_name = effective_tenant_name
    elif tenant_name and tenant_name != effective_tenant_name:
        legacy_machine_code = _generate_machine_code(os_name, machine_mac, tenant_name).lower()
        if machine_code == legacy_machine_code:
            matched_tenant_name = tenant_name
            logger.warning(
                "Digital human register accepted legacy machineCode derived from payload tenant: account_uuid=%s payload_tenant=%s jwt_tenant=%s",
                account.account_uuid,
                tenant_name,
                effective_tenant_name,
            )
    if not matched_tenant_name:
        raise DigitalHumanError("machineCode校验失败")

    device = DigitalHumanDevice.objects.filter(machine_code=machine_code).first()
    if device is None:
        device = DigitalHumanDevice.objects.create(
            machine_code=machine_code,
            machine_mac=machine_mac,
            tenant_name=effective_tenant_name,
            registered_by_jwt_account_uuid=account.account_uuid,
            registered_by_jwt_tenant_name=account.tenant_name,
            authorization_enabled=False,
            authorization_status=AUTH_PENDING,
            display_name="",
            os_name=os_name,
        )
    device.machine_mac = machine_mac
    device.tenant_name = effective_tenant_name
    device.registered_by_jwt_account_uuid = account.account_uuid
    device.registered_by_jwt_tenant_name = effective_tenant_name
    device.os_name = os_name
    device.save()
    _ensure_device_codes(device)
    status = _apply_authorization_status(device, persist=True)
    return {
        "deviceId": device.id,
        "deviceCode": device.device_code,
        "serverTime": _format_dt(_now()),
        "nextReportIntervalSec": _report_default_interval_sec(),
        "authorizationStatus": status,
        "authorizationMessage": _authorization_message(status),
    }


def get_open_agent_latest_config(authorization, device_id):
    account = _validate_open_agent_token(authorization)
    device = _resolve_open_device_for_account(account, device_id)
    return {
        "deviceId": device.id,
        "latestConfigVersion": _latest_config_version_for_device(device),
        "config": {
            "reportIntervalSec": _report_default_interval_sec(),
            "imageMaxBytes": _report_image_max_bytes(),
        },
    }


def pull_open_agent_commands(authorization, device_id):
    account = _validate_open_agent_token(authorization)
    device = _resolve_open_device_for_account(account, device_id)
    commands = []
    pending_rows = list(
        DigitalHumanCommandTask.objects.filter(device=device, status=COMMAND_PENDING)
        .order_by("create_time", "id")
    )
    for row in pending_rows:
        commands.append(
            {
                "commandId": row.id,
                "commandType": _normalize_text(row.command_type, default=""),
                "commandPayload": _normalize_text(row.command_payload, default="{}"),
                "createdAt": _format_dt(row.create_time),
            }
        )
    return {
        "deviceId": device.id,
        "pendingCount": len(commands),
        "commands": commands,
    }


@transaction.atomic
def submit_open_agent_command_result(authorization, payload):
    account = _validate_open_agent_token(authorization)
    device = _resolve_open_device_for_account(account, payload.get("deviceId"))
    command_id = _parse_object_id(payload.get("commandId"), "commandId")
    success = _boolish(payload.get("success"))
    task = DigitalHumanCommandTask.objects.filter(id=command_id).select_related("device").first()
    if task is None:
        raise DigitalHumanError("命令不存在", status_code=404)
    if int(task.device_id or 0) != int(device.id):
        raise DigitalHumanError("命令不属于当前设备", status_code=403)
    task.status = COMMAND_SUCCESS if success else COMMAND_FAILED
    task.save(update_fields=["status", "update_time"])
    DigitalHumanCommandResult.objects.create(
        command_task=task,
        success=success,
        result_message=_normalize_text(payload.get("resultMessage"), default=""),
        result_payload=str(payload.get("resultPayload") or ""),
    )
    return None


def _parse_active_window(value):
    parsed = _load_json_text(value, default=None)
    if isinstance(parsed, dict):
        return (
            _normalize_text(parsed.get("title"), default=""),
            _normalize_text(parsed.get("process") or parsed.get("processName"), default=""),
        )
    text = _normalize_text(value, default="")
    return text, ""


def _parse_network_status(value):
    parsed = _load_json_text(value, default=None)
    if isinstance(parsed, dict):
        return {
            "latency": _intish(
                parsed.get("latencyMs")
                or parsed.get("latency")
                or parsed.get("pingMs")
                or parsed.get("delayMs")
            ),
            "bandwidth": _normalize_text(parsed.get("bandwidth") or parsed.get("netSpeed"), default=""),
        }
    text = _normalize_text(value, default="")
    return {"latency": _intish(text), "bandwidth": ""}


def _parse_service_status(value):
    parsed = _load_json_text(value, default=None)
    if isinstance(parsed, dict):
        return {
            "stream": parsed.get("stream") if isinstance(parsed.get("stream"), bool) else _boolish(parsed.get("stream"), default=True),
            "llm": parsed.get("llm") if isinstance(parsed.get("llm"), bool) else _boolish(parsed.get("llm"), default=True),
        }
    text = _normalize_text(value, default="").lower()
    if not text:
        return {"stream": None, "llm": None}
    stream = None if "stream" not in text else ("down" not in text and "false" not in text and "0" not in text)
    llm = None if "llm" not in text else ("down" not in text and "false" not in text and "0" not in text)
    return {"stream": stream, "llm": llm}


def _parse_hardware_devices(value):
    parsed = _load_json_text(value, default=None)
    if isinstance(parsed, dict):
        return {
            "cam": parsed.get("cam")
            if isinstance(parsed.get("cam"), bool)
            else parsed.get("camera")
            if isinstance(parsed.get("camera"), bool)
            else parsed.get("cameraOnline")
            if isinstance(parsed.get("cameraOnline"), bool)
            else parsed.get("videoCapture")
            if isinstance(parsed.get("videoCapture"), bool)
            else None,
            "mic": parsed.get("mic")
            if isinstance(parsed.get("mic"), bool)
            else parsed.get("microphone")
            if isinstance(parsed.get("microphone"), bool)
            else parsed.get("microphoneOnline")
            if isinstance(parsed.get("microphoneOnline"), bool)
            else parsed.get("audioCapture")
            if isinstance(parsed.get("audioCapture"), bool)
            else None,
        }
    text = _normalize_text(value, default="").lower()
    if not text:
        return {"cam": None, "mic": None}
    return {
        "cam": True if ("camera" in text or "cam" in text) else None,
        "mic": True if ("mic" in text or "microphone" in text) else None,
    }


@transaction.atomic
def receive_open_agent_report(authorization, payload):
    device = _resolve_report_device(authorization)
    reported_at = _parse_report_dt(payload.get("reportTime"))
    active_window_title, active_window_process = _parse_active_window(payload.get("activeWindow"))
    network_status = _parse_network_status(payload.get("networkStatus"))
    services = _parse_service_status(payload.get("serviceStatus"))
    hardware = _parse_hardware_devices(payload.get("hardwareDevices"))

    device.computer_name = _normalize_text(payload.get("computerName"), default=device.computer_name)
    device.mac_address = _normalize_text(payload.get("macAddress"), default=device.mac_address)
    device.machine_mac = _normalize_text(payload.get("macAddress"), default=device.machine_mac or device.mac_address)
    device.os_name = _normalize_text(payload.get("osName"), default=device.os_name)
    device.os_version = _normalize_text(payload.get("osVersion"), default=device.os_version)
    device.os_user = _normalize_text(payload.get("osUser"), default=device.os_user)
    device.processor = _normalize_text(payload.get("processor"), default=device.processor)
    device.processor_architecture = _normalize_text(
        payload.get("processorArchitecture"),
        default=device.processor_architecture,
    )
    device.local_ip = _normalize_text(payload.get("localIp"), default=device.local_ip)
    device.system_uptime = _normalize_text(payload.get("systemUptime"), default=device.system_uptime)
    device.cpu_usage = _floatish(payload.get("cpuUsage"), default=device.cpu_usage, digits=None)
    device.gpu_usage = _floatish(payload.get("gpuUsage"), default=device.gpu_usage, digits=None)
    device.memory_usage = _floatish(payload.get("memoryUsage"), default=device.memory_usage, digits=None)
    device.disk_usage = _floatish(payload.get("diskUsage"), default=device.disk_usage, digits=None)
    device.net_latency_ms = _intish(network_status.get("latency"), default=device.net_latency_ms)
    device.bandwidth_text = _normalize_text(payload.get("netSpeed") or network_status.get("bandwidth"), default="")
    device.network_status_json = _dump_json_text(_load_json_text(payload.get("networkStatus"), default={"raw": payload.get("networkStatus")}))
    device.service_status_json = _dump_json_text(_load_json_text(payload.get("serviceStatus"), default={"raw": payload.get("serviceStatus")}))
    device.hardware_devices_json = _dump_json_text(_load_json_text(payload.get("hardwareDevices"), default={"raw": payload.get("hardwareDevices")}))
    device.remote_monitor_json = _dump_json_text(_load_json_text(payload.get("remoteMonitor"), default={"raw": payload.get("remoteMonitor")}))
    device.active_window_title = active_window_title
    device.active_window_process = active_window_process
    if _strip_to_none(payload.get("image")):
        _store_device_screenshot(device, payload.get("image"), reported_at)
    if hardware.get("cam") is not None:
        device.peripheral_cam = bool(hardware.get("cam"))
    if hardware.get("mic") is not None:
        device.peripheral_mic = bool(hardware.get("mic"))
    if services.get("stream") is not None:
        device.service_stream = services.get("stream")
    if services.get("llm") is not None:
        device.service_llm = services.get("llm")
    device.last_report_time = reported_at
    device.last_online_time = reported_at
    device.save()

    DigitalHumanDeviceMetricHistory.objects.create(
        device=device,
        reported_at=reported_at,
        status="online",
        cpu_usage=device.cpu_usage,
        gpu_usage=device.gpu_usage,
        memory_usage=device.memory_usage,
        disk_usage=device.disk_usage,
        net_latency_ms=device.net_latency_ms,
    )
    _sync_alerts_for_device(device, now=reported_at)
    return {
        "reportId": f"dh-report-{device.id}-{reported_at.strftime('%Y%m%d%H%M%S')}",
        "deviceId": device.id,
        "serverTime": _format_dt(_now()),
        "nextReportIntervalSec": _report_default_interval_sec(),
        "latestConfigVersion": _latest_config_version_for_device(device),
        "pendingCommandCount": 0,
    }


@transaction.atomic
def receive_open_human_report(authorization, payload):
    device = _resolve_report_device(authorization)
    if payload.get("deviceId") is not None and _parse_object_id(payload.get("deviceId"), "deviceId") != int(device.id):
        raise DigitalHumanError("设备不匹配", status_code=403)
    log_row = DigitalHumanHumanLog(
        device=device,
        time=_parse_dt(payload.get("time")) or _now(),
        level=_normalize_text(payload.get("level"), default="INFO"),
        module=_normalize_text(payload.get("module"), default="unknown"),
        message=_normalize_text(payload.get("message"), default=""),
        diagnosis_status="",
        diagnosis_text="",
        diagnosis_error="",
        structured_json=_dump_json_text({}),
    )
    log_row.diagnosis_status, log_row.diagnosis_text, log_row.diagnosis_error = _log_diagnosis_for_row(log_row)
    log_row.save()
    return {"logId": str(log_row.id), "serverTime": _format_dt(_now())}
