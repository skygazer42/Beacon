import json
import os
import re
import time
from pathlib import Path

from django.core.cache import cache


_GATEWAY_SETTINGS_CACHE = {
    "mtime": None,
    "data": {},
}

_DEFAULT_SUSPICIOUS_PATTERNS = [
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"\.\./"),
    re.compile(r"\.\.\\"),
    re.compile(r"%3cscript", re.IGNORECASE),
    re.compile(r"union\s+select", re.IGNORECASE),
    re.compile(r"drop\s+table", re.IGNORECASE),
    re.compile(r"or\s+1\s*=\s*1", re.IGNORECASE),
    re.compile(r"sleep\s*\(", re.IGNORECASE),
    re.compile(r"\x00"),
]


def _repo_root() -> Path:
    """返回仓库根目录。"""
    return Path(__file__).resolve().parents[3]


def _read_config_json() -> dict:
    """读取配置JSON。"""
    path = _repo_root() / "config.json"
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = None

    if _GATEWAY_SETTINGS_CACHE["mtime"] == mtime and isinstance(_GATEWAY_SETTINGS_CACHE.get("data"), dict):
        return dict(_GATEWAY_SETTINGS_CACHE["data"])

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        data = json.loads(path.read_text(encoding="gbk"))
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}
    _GATEWAY_SETTINGS_CACHE["mtime"] = mtime
    _GATEWAY_SETTINGS_CACHE["data"] = dict(data)
    return data


def _env_bool(name: str, default: bool) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10**9) -> int:
    """读取环境变量并转换为整数。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        value = int(default)
    else:
        try:
            value = int(str(raw).strip())
        except Exception:
            value = int(default)
    if value < min_value:
        value = min_value
    if value > max_value:
        value = max_value
    return value


def get_openapi_gateway_settings() -> dict:
    """获取`openapi`网关设置。"""
    data = _read_config_json()
    return {
        "rate_limit_enabled": _env_bool("BEACON_OPEN_API_RATE_LIMIT_ENABLED", bool(data.get("openApiRateLimitEnabled", False))),
        "rate_limit_per_minute": _env_int("BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE", int(data.get("openApiRateLimitPerMinute", 60) or 60), min_value=1, max_value=100000),
        "rate_limit_burst": _env_int("BEACON_OPEN_API_RATE_LIMIT_BURST", int(data.get("openApiRateLimitBurst", 10) or 10), min_value=0, max_value=100000),
        "waf_enabled": _env_bool("BEACON_OPEN_API_WAF_ENABLED", bool(data.get("openApiWafEnabled", False))),
        "waf_max_body_bytes": _env_int("BEACON_OPEN_API_WAF_MAX_BODY_BYTES", int(data.get("openApiWafMaxBodyBytes", 1048576) or 1048576), min_value=1, max_value=1024 * 1024 * 1024),
    }


def _waf_ok() -> dict:
    """判断 WAF 校验是否通过。"""
    return {"ok": True, "status_code": 200, "msg": ""}


def _waf_block(status_code: int, msg: str) -> dict:
    """处理WAF拦截。"""
    return {"ok": False, "status_code": int(status_code), "msg": str(msg)}


def _parse_content_length(request) -> int:
    """解析`content``length`。"""
    try:
        return int(str(getattr(request, "META", {}).get("CONTENT_LENGTH", "0") or "0"))
    except Exception:
        return 0


def _build_path_query_haystack(request) -> str:
    """构建路径查询参数`haystack`。"""
    try:
        path = str(getattr(request, "path_info", "") or "")
    except Exception:
        path = ""
    try:
        query = str(getattr(request, "META", {}).get("QUERY_STRING", "") or "")
    except Exception:
        query = ""
    return f"{path}?{query}"


def _has_suspicious_patterns(haystack: str) -> bool:
    """检查`suspicious``patterns`。"""
    for pattern in _DEFAULT_SUSPICIOUS_PATTERNS:
        try:
            if pattern.search(haystack):
                return True
        except Exception:
            continue
    return False


def check_request_waf(request, settings: dict) -> dict:
    """检查请求WAF。"""
    if not bool((settings or {}).get("waf_enabled")):
        return _waf_ok()

    content_length = _parse_content_length(request)
    max_body_bytes = int((settings or {}).get("waf_max_body_bytes") or 1048576)
    if content_length > max_body_bytes:
        return _waf_block(413, "waf blocked: body too large")

    haystack = _build_path_query_haystack(request)
    if _has_suspicious_patterns(haystack):
        return _waf_block(403, "waf blocked: suspicious request")

    return _waf_ok()


def apply_rate_limit(*, principal: str, rate_limit_per_minute: int, burst_limit: int) -> dict:
    """处理应用`rate``limit`。"""
    limit = max(0, int(rate_limit_per_minute or 0)) + max(0, int(burst_limit or 0))
    if limit <= 0:
        return {"ok": True, "limit": 0, "remaining": 0, "retry_after": 0}

    now = int(time.time())
    window = now // 60
    retry_after = 60 - (now % 60)
    cache_key = f"beacon:openapi:rl:{principal}:{window}"

    current = cache.get(cache_key)
    if current is None:
        cache.set(cache_key, 1, timeout=retry_after + 1)
        current = 1
    else:
        try:
            current = cache.incr(cache_key)
        except Exception:
            current = int(current) + 1
            cache.set(cache_key, current, timeout=retry_after + 1)

    remaining = max(0, limit - int(current))
    if int(current) > limit:
        return {"ok": False, "limit": limit, "remaining": 0, "retry_after": retry_after}
    return {"ok": True, "limit": limit, "remaining": remaining, "retry_after": retry_after}


def build_rate_limit_headers(result: dict) -> dict:
    """构建`rate``limit`请求头。"""
    limit = int((result or {}).get("limit") or 0)
    if limit <= 0:
        return {}
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, int((result or {}).get("remaining") or 0))),
    }
    if not bool((result or {}).get("ok")):
        headers["Retry-After"] = str(max(1, int((result or {}).get("retry_after") or 60)))
    return headers
