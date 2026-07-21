import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

import requests


logger = logging.getLogger(__name__)

_ALLOW_KEYS = ("allow", "pass", "ok", "accepted")
_PRECHECK_REQUIRED_FIELDS = ("control_code", "desc")
_PRECHECK_OPTIONAL_FIELD_DEFAULTS = {
    "alarm_type": "",
    "alarm_level": 0,
    "algorithm_code": "",
    "object_code": "",
    "recognition_region": "",
    "stream_code": "",
    "stream_app": "",
    "stream_name": "",
    "stream_url": "",
    "image_path": "",
    "image_abs_path": "",
    "image_base64": "",
    "metadata": None,
}
_PRECHECK_ALLOWED_FIELDS = _PRECHECK_REQUIRED_FIELDS + tuple(_PRECHECK_OPTIONAL_FIELD_DEFAULTS.keys())


def _safe_str_falsy(value: Any) -> str:
    """判断安全字符串是否为空。"""
    if not value:
        return ""
    return str(value)


def _safe_int(value: Any, default: int) -> int:
    """处理安全整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _response_status_code(res) -> int:
    """处理响应状态编码。"""
    try:
        return int(getattr(res, "status_code", 0))
    except Exception:
        return 0


def _parse_bool(value) -> Optional[bool]:
    """解析布尔值。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            return int(value) != 0
        except Exception:
            return bool(value)
    raw = str(value or "").strip().lower()
    if raw in ("1", "true", "yes", "y", "on", "allow", "pass", "ok"):
        return True
    if raw in ("0", "false", "no", "n", "off", "deny", "block"):
        return False
    return None


def _extract_first_allow_flag(payload: Dict[str, Any]) -> Optional[bool]:
    """提取首个允许标记。"""
    for key in _ALLOW_KEYS:
        v = _parse_bool(payload.get(key))
        if v is not None:
            return v
    return None


def _extract_reason_text(*payloads: Any) -> str:
    """提取原因文本。"""
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        reason = str(payload.get("reason") or payload.get("msg") or "").strip()
        if reason:
            return reason
    return ""


def _extract_allow_reason(payload: Any) -> Tuple[Optional[bool], str]:
    """提取允许原因。"""
    if not isinstance(payload, dict):
        return None, ""

    allow = _extract_first_allow_flag(payload)
    if allow is not None:
        return allow, _extract_reason_text(payload)

    result = payload.get("result")
    if isinstance(result, dict):
        allow = _extract_first_allow_flag(result)
        if allow is not None:
            return allow, _extract_reason_text(result, payload)

    data = payload.get("data")
    if isinstance(data, dict):
        allow = _extract_first_allow_flag(data)
        if allow is not None:
            return allow, _extract_reason_text(data, payload)

    return None, ""


def _normalize_image_base64(image_base64: str) -> str:
    """执行归一化图片Base64。"""
    value = str(image_base64 or "").strip()
    if not value:
        return ""
    if "," in value:
        # Strip optional data URL prefix and keep raw base64 payload.
        value = value.split(",", 1)[1].strip()
    return value


def _try_read_file_as_base64(abs_path: str, *, max_bytes: int = 5 * 1024 * 1024) -> str:
    """处理`try`读取文件`as`Base64。"""
    path = str(abs_path or "").strip()
    if not path:
        return ""
    try:
        if not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        if size <= 0:
            return ""
        if size > int(max_bytes):
            logger.warning("AlarmPrecheck read file too large (%s bytes), skip base64: %s", size, path)
            return ""
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        logger.debug("AlarmPrecheck read file error: %s", e)
        return ""


def _precheck_timeout_seconds(config, default: int = 5) -> int:
    """返回预检超时时间秒数。"""
    try:
        timeout = int(getattr(config, "alarmPrecheckTimeoutSeconds", default) or default)
    except Exception:
        timeout = int(default)
    return max(1, min(int(timeout), 60))


def _precheck_image_base64(image_base64: str, image_abs_path: str) -> str:
    """处理预检图片Base64。"""
    img_b64 = _normalize_image_base64(image_base64)
    if img_b64:
        return img_b64
    if image_abs_path:
        return _try_read_file_as_base64(image_abs_path)
    return ""


def _precheck_bool_result(fail_open: bool, *, reason: str) -> Tuple[bool, str]:
    """返回预检布尔值结果。"""
    return (True, reason) if fail_open else (False, reason)


def _precheck_http_status_result(status_code, *, fail_open: bool) -> Tuple[bool, str]:
    """返回预检HTTP状态结果。"""
    return _precheck_bool_result(fail_open, reason=f"precheck http={status_code}")


def _precheck_invalid_response_result(*, fail_open: bool) -> Tuple[bool, str]:
    """返回预检无效响应结果。"""
    return _precheck_bool_result(fail_open, reason="precheck invalid response")


def _precheck_exception_result(err: Exception, *, fail_open: bool) -> Tuple[bool, str]:
    """返回预检`exception`结果。"""
    return _precheck_bool_result(fail_open, reason=f"precheck error: {err}")


def _precheck_response_body(res) -> Dict[str, Any]:
    """返回预检响应体。"""
    try:
        body = res.json()
        return body if isinstance(body, dict) else {"raw": str(body)}
    except Exception:
        return {"raw": (getattr(res, "text", "") or "").strip()}


def _normalize_should_store_alarm_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """执行归一化`should``store`告警参数。"""
    unexpected = sorted(str(key) for key in kwargs.keys() if key not in _PRECHECK_ALLOWED_FIELDS)
    if unexpected:
        if len(unexpected) == 1:
            raise TypeError(f"should_store_alarm() got unexpected keyword argument '{unexpected[0]}'")
        names = ", ".join(f"'{name}'" for name in unexpected)
        raise TypeError(f"should_store_alarm() got unexpected keyword arguments: {names}")

    missing = [name for name in _PRECHECK_REQUIRED_FIELDS if name not in kwargs]
    if missing:
        if len(missing) == 1:
            raise TypeError(f"should_store_alarm() missing 1 required keyword-only argument: '{missing[0]}'")
        names = ", ".join(f"'{name}'" for name in missing[:-1]) + f" and '{missing[-1]}'"
        raise TypeError(f"should_store_alarm() missing {len(missing)} required keyword-only arguments: {names}")

    normalized = {name: kwargs[name] for name in _PRECHECK_REQUIRED_FIELDS}
    for name, default in _PRECHECK_OPTIONAL_FIELD_DEFAULTS.items():
        normalized[name] = kwargs.get(name, default)
    return normalized


def should_store_alarm(config, **kwargs) -> Tuple[bool, str]:
    """判断`store`告警。
    
    Large-model "precheck" hook before persisting alarms.
    
        Returns: (allow_store, reason)
    
        Config keys (best-effort, default-safe):
        - alarmPrecheckEnabled: bool (default False)
        - alarmPrecheckUrl: str (required when enabled)
        - alarmPrecheckTimeoutSeconds: int (default 5)
        - alarmPrecheckFailOpen: bool (default True)
    """
    normalized = _normalize_should_store_alarm_kwargs(kwargs)
    enabled = bool(getattr(config, "alarmPrecheckEnabled", False))
    url = _safe_str_falsy(getattr(config, "alarmPrecheckUrl", "")).strip()
    if not enabled:
        return True, ""
    if not url:
        return True, ""

    fail_open = bool(getattr(config, "alarmPrecheckFailOpen", True))
    timeout = _precheck_timeout_seconds(config, 5)
    img_b64 = _precheck_image_base64(normalized["image_base64"], normalized["image_abs_path"])

    metadata_payload: Dict[str, Any] = normalized["metadata"] if isinstance(normalized["metadata"], dict) else {}
    payload = {
        "nodeCode": _safe_str_falsy(getattr(config, "code", "")),
        "controlCode": _safe_str_falsy(normalized["control_code"]),
        "desc": _safe_str_falsy(normalized["desc"]),
        "alarmType": _safe_str_falsy(normalized["alarm_type"]),
        "alarmLevel": _safe_int(normalized["alarm_level"], 0),
        "algorithmCode": _safe_str_falsy(normalized["algorithm_code"]),
        "objectCode": _safe_str_falsy(normalized["object_code"]),
        "recognitionRegion": _safe_str_falsy(normalized["recognition_region"]),
        "streamCode": _safe_str_falsy(normalized["stream_code"]),
        "streamApp": _safe_str_falsy(normalized["stream_app"]),
        "streamName": _safe_str_falsy(normalized["stream_name"]),
        "streamUrl": _safe_str_falsy(normalized["stream_url"]),
        "imagePath": _safe_str_falsy(normalized["image_path"]),
        "imageBase64": img_b64,
        "metadata": metadata_payload,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Beacon-Alarm-Precheck/1.0",
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except Exception as e:
        return _precheck_exception_result(e, fail_open=fail_open)

    if _response_status_code(res) != 200:
        return _precheck_http_status_result(getattr(res, "status_code", ""), fail_open=fail_open)

    body = _precheck_response_body(res)
    allow, reason = _extract_allow_reason(body)
    if allow is None:
        return _precheck_invalid_response_result(fail_open=fail_open)
    if allow:
        return True, reason
    return False, reason if reason else "blocked"
