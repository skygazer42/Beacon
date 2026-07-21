import ast
import json
import hashlib
import hmac
import logging
import math
import os
import ipaddress
import re
import time
import uuid
from urllib.parse import urlparse
from django.http import HttpResponseRedirect, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

from app.utils.DeploymentMode import is_cloud_mode
from app.utils.UserPermissionRules import is_path_allowed, parse_permissions_json

_OPEN_API_TOKEN_CACHE = {
    "loaded": False,
    "token": ""
}

_IP_POLICY_CACHE = {
    "open_allow_raw": None,
    "open_allow": [],
    "open_deny_raw": None,
    "open_deny": [],
    "admin_allow_raw": None,
    "admin_allow": [],
    "admin_deny_raw": None,
    "admin_deny": [],
}

logger = logging.getLogger(__name__)

_TOTP_REAUTH_CACHE = {
    "prefixes_raw": None,
    "prefixes": [],
}

_LEGACY_API_BLOCK_ALLOWLIST_CACHE = {
    "raw": None,
    "rules": [],
}

_TOTP_REAUTH_UNTIL_SESSION_KEY = "totp_reauth_until"

# Shared string/regex constants used across middleware helpers.
CONTENT_TYPE_HTML = "text/html"
CONTENT_TYPE_JSON = "application/json"
TEMPLATE_MESSAGE_HTML = "app/message.html"
SCOPE_SPLIT_RE = r"[|,;\s]+"
OPEN_OPS_PATH = "open/ops"
OPEN_OPS_PREFIX = "open/ops/"
STREAM_PLAY_AUDIT_EVENT = "stream.play.get"
LEGACY_API_REQUEST_EVENT = "legacy.api.request"
LEGACY_API_BLOCKED_EVENT = "legacy.api.blocked"
LEGACY_API_RESPONSE_HEADER = "X-Beacon-Legacy-Api"
APP_SHELL_MARKER_META_KEY = "HTTP_X_BEACON_APP_SHELL"


def _env_bool(name: str, default: bool = False) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    """读取环境变量并转换为整数。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception:
            value = int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _totp_sensitive_reauth_enabled() -> bool:
    """判断TOTP敏感二次认证是否启用。"""
    return _env_bool("BEACON_TOTP_SENSITIVE_REAUTH_ENABLED", default=False)


def _totp_sensitive_reauth_prefixes():
    """返回TOTP敏感二次认证前缀列表。"""
    raw = str(os.environ.get("BEACON_TOTP_SENSITIVE_REAUTH_PREFIXES", "") or "").strip()
    if raw == _TOTP_REAUTH_CACHE.get("prefixes_raw"):
        return _TOTP_REAUTH_CACHE.get("prefixes") or []

    prefixes = []
    for token in raw.split(","):
        token = str(token or "").strip()
        if not token:
            continue
        prefixes.append(token.lstrip("/"))
    _TOTP_REAUTH_CACHE["prefixes_raw"] = raw
    _TOTP_REAUTH_CACHE["prefixes"] = prefixes
    return prefixes


def _totp_reauth_window_seconds() -> int:
    """返回TOTP二次认证窗口秒数。"""
    return _env_int("BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS", 300, min_value=30, max_value=3600)


def _totp_path_requires_reauth(path: str) -> bool:
    """处理TOTP路径`requires`二次认证。"""
    if not _totp_sensitive_reauth_enabled():
        return False
    prefixes = _totp_sensitive_reauth_prefixes()
    if not prefixes:
        return False
    p = str(path or "").lstrip("/")
    for prefix in prefixes:
        if not prefix:
            continue
        if p == prefix or p.startswith(prefix):
            return True
    return False


def _totp_reauth_deny_response(request, msg: str):
    """返回TOTP二次认证拒绝响应。"""
    accept = str(getattr(request, "META", {}).get("HTTP_ACCEPT", "") or "").lower()
    wants_html = CONTENT_TYPE_HTML in accept
    if wants_html:
        return render(
            request,
            TEMPLATE_MESSAGE_HTML,
            {
                "msg": msg,
                "is_success": False,
                "redirect_url": "/profile",
            },
        )
    return HttpResponse(
        json.dumps({"code": 403, "msg": msg}, ensure_ascii=False),
        content_type=CONTENT_TYPE_JSON,
    )


def _sanitize_trace_id(value: str, *, max_len: int = 128) -> str:
    """清洗链路追踪ID。
    
    Best-effort sanitization for request_id/correlation_id from headers.
    
        Avoid CRLF to prevent header injection and cap length to keep logs safe.
    """
    try:
        s = str(value or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    s = s.replace("\r", "").replace("\n", "")
    # Remove non-printable control chars (e.g. TAB) to keep logs/headers clean.
    s = "".join(ch for ch in s if (ord(ch) >= 32 and ord(ch) != 127))
    # Accept quoted header values commonly produced by proxies/gateways.
    while len(s) >= 2 and ((s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'"))):
        s = s[1:-1].strip()
        if not s:
            return ""
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _trace_id_from_traceparent(value: str) -> str:
    """从`traceparent`获取链路追踪ID。
    
    Extract W3C trace-id from traceparent header.
        Format: version-trace-id-parent-id-flags
    """
    raw = _sanitize_trace_id(value, max_len=256)
    if not raw:
        return ""
    parts = str(raw).split("-")
    if len(parts) < 4:
        return ""
    trace_id = str(parts[1] or "").strip().lower()
    parent_id = str(parts[2] or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        return ""
    if trace_id == ("0" * 32):
        return ""
    if not re.fullmatch(r"[0-9a-f]{16}", parent_id):
        return ""
    if parent_id == ("0" * 16):
        return ""
    return trace_id


def _trace_id_from_b3_traceid(value: str) -> str:
    """从 B3 请求头中提取 trace ID。"""
    raw = _sanitize_trace_id(value, max_len=64).lower()
    if not raw:
        return ""
    if re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{32}", raw) is None:
        return ""
    if set(raw) == {"0"}:
        return ""
    return raw


def _trace_id_from_b3_single(value: str) -> str:
    """从`b3``single`获取链路追踪ID。"""
    raw = _sanitize_trace_id(value, max_len=256)
    if not raw:
        return ""
    token = str(raw).split("-", 1)[0].strip()
    return _trace_id_from_b3_traceid(token)


def _extract_amzn_root_value(raw: str) -> str:
    """提取`amzn`根目录值。"""
    parts = [str(x or "").strip() for x in str(raw or "").split(";") if str(x or "").strip()]
    for item in parts:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        if str(k or "").strip().lower() == "root":
            return _sanitize_trace_id(v, max_len=256)
    return ""


def _trace_id_from_x_amzn_trace_id(value: str) -> str:
    """从`x``amzn`链路追踪ID获取链路追踪ID。"""
    raw = _sanitize_trace_id(value, max_len=256)
    if not raw:
        return ""
    root_val = _extract_amzn_root_value(raw)
    if not root_val:
        return ""

    m = re.fullmatch(r"[0-9a-fA-F]-([0-9a-fA-F]{8})-([0-9a-fA-F]{24})", root_val)
    if not m:
        return ""
    trace_id = (str(m.group(1) or "") + str(m.group(2) or "")).lower()
    if len(trace_id) != 32:
        return ""
    if set(trace_id) == {"0"}:
        return ""
    return trace_id


def _trace_id_from_x_cloud_trace_context(value: str) -> str:
    """从`x`云端链路追踪`context`获取链路追踪ID。"""
    raw = _sanitize_trace_id(value, max_len=256)
    if not raw:
        return ""
    trace_part = str(raw).split("/", 1)[0].strip().lower()
    while len(trace_part) >= 2 and (
        (trace_part.startswith('"') and trace_part.endswith('"'))
        or (trace_part.startswith("'") and trace_part.endswith("'"))
    ):
        trace_part = trace_part[1:-1].strip().lower()
        if not trace_part:
            return ""
    if re.fullmatch(r"[0-9a-f]{32}", trace_part) is None:
        return ""
    if set(trace_part) == {"0"}:
        return ""
    return trace_part


def _get_request_id(request) -> str:
    """获取请求ID。"""
    try:
        meta = getattr(request, "META", {}) or {}
    except Exception:
        meta = {}

    rid = _sanitize_trace_id(meta.get("HTTP_X_REQUEST_ID", ""))
    if not rid:
        rid = _sanitize_trace_id(meta.get("HTTP_X_BEACON_REQUEST_ID", ""))
    if not rid:
        rid = _trace_id_from_traceparent(meta.get("HTTP_TRACEPARENT", ""))
    if not rid:
        rid = _trace_id_from_x_amzn_trace_id(meta.get("HTTP_X_AMZN_TRACE_ID", ""))
    if not rid:
        rid = _trace_id_from_x_cloud_trace_context(meta.get("HTTP_X_CLOUD_TRACE_CONTEXT", ""))
    if not rid:
        rid = _trace_id_from_b3_traceid(meta.get("HTTP_X_B3_TRACEID", ""))
    if not rid:
        rid = _trace_id_from_b3_single(meta.get("HTTP_B3", ""))
    if rid:
        return rid

    # default: generate a new request id.
    try:
        return uuid.uuid4().hex
    except Exception:
        return "unknown"


def _get_correlation_id(request, request_id: str) -> str:
    """获取`correlation`ID。"""
    try:
        meta = getattr(request, "META", {}) or {}
    except Exception:
        meta = {}

    cid = _sanitize_trace_id(meta.get("HTTP_X_CORRELATION_ID", ""))
    if not cid:
        cid = _sanitize_trace_id(meta.get("HTTP_X_BEACON_CORRELATION_ID", ""))
    if not cid:
        cid = _trace_id_from_traceparent(meta.get("HTTP_TRACEPARENT", ""))
    if not cid:
        cid = _trace_id_from_x_amzn_trace_id(meta.get("HTTP_X_AMZN_TRACE_ID", ""))
    if not cid:
        cid = _trace_id_from_x_cloud_trace_context(meta.get("HTTP_X_CLOUD_TRACE_CONTEXT", ""))
    if not cid:
        cid = _trace_id_from_b3_traceid(meta.get("HTTP_X_B3_TRACEID", ""))
    if not cid:
        cid = _trace_id_from_b3_single(meta.get("HTTP_B3", ""))
    if cid:
        return cid
    return str(request_id or "")


def _parse_cidr_csv(raw: str):
    """解析`cidr`CSV。"""
    nets = []
    has_invalid = False
    if not raw:
        return nets, has_invalid
    for token in str(raw).split(","):
        token = str(token or "").strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except Exception:
            has_invalid = True
    return nets, has_invalid


def _get_cached_ip_nets(env_name: str, cache_raw_key: str, cache_nets_key: str):
    """获取`cached`IP`nets`。"""
    raw = str(os.environ.get(env_name, "") or "").strip()
    if raw == _IP_POLICY_CACHE.get(cache_raw_key):
        return (
            _IP_POLICY_CACHE.get(cache_nets_key) or [],
            bool(_IP_POLICY_CACHE.get(f"{cache_nets_key}_has_invalid")),
        )

    nets, has_invalid = _parse_cidr_csv(raw)
    if raw and has_invalid:
        try:
            logger.warning("IP policy contains invalid CIDR entries")
        except Exception:
            logger.debug("suppressed exception in app/middleware.py:362", exc_info=True)
    _IP_POLICY_CACHE[cache_raw_key] = raw
    _IP_POLICY_CACHE[cache_nets_key] = nets
    _IP_POLICY_CACHE[f"{cache_nets_key}_has_invalid"] = has_invalid
    return nets, has_invalid


def _remote_addr(request) -> str:
    """返回请求来源地址。"""
    try:
        meta = getattr(request, "META", {}) or {}
    except Exception:
        meta = {}
    return str(meta.get("REMOTE_ADDR", "") or "").strip()


def _parse_ip_address(ip_str: str):
    """解析IP`address`。"""
    try:
        return ipaddress.ip_address(str(ip_str or "").strip())
    except Exception:
        return None


def _ip_in_any_net_best_effort(ip, nets) -> bool:
    """尽力处理IP`in``any``net`。"""
    if not nets:
        return False
    try:
        for n in nets:
            if ip in n:
                return True
    except Exception:
        return False
    return False


def _ip_policy_allows(ip_str: str, allow_nets, deny_nets) -> bool:
    # Policy disabled: allow all.
    """判断IP策略是否允许。"""
    if not allow_nets and not deny_nets:
        return True

    ip = _parse_ip_address(ip_str)
    if ip is None:
        # When policy is enabled, invalid/empty IP should be rejected.
        return False

    if _ip_in_any_net_best_effort(ip, (deny_nets or [])):
        return False
    if not allow_nets:
        return True
    return _ip_in_any_net_best_effort(ip, allow_nets)


def _open_api_ip_allowed(request) -> bool:
    """判断OpenAPIIP是否允许。"""
    allow_nets, allow_has_invalid = _get_cached_ip_nets("BEACON_OPEN_API_IP_ALLOWLIST", "open_allow_raw", "open_allow")
    deny_nets, deny_has_invalid = _get_cached_ip_nets("BEACON_OPEN_API_IP_DENYLIST", "open_deny_raw", "open_deny")
    if allow_has_invalid or deny_has_invalid:
        return False
    return _ip_policy_allows(_remote_addr(request), allow_nets, deny_nets)


def _admin_ip_allowed(request) -> bool:
    """判断管理员IP是否允许。"""
    allow_nets, allow_has_invalid = _get_cached_ip_nets("BEACON_ADMIN_IP_ALLOWLIST", "admin_allow_raw", "admin_allow")
    deny_nets, deny_has_invalid = _get_cached_ip_nets("BEACON_ADMIN_IP_DENYLIST", "admin_deny_raw", "admin_deny")
    if allow_has_invalid or deny_has_invalid:
        return False
    return _ip_policy_allows(_remote_addr(request), allow_nets, deny_nets)


def _read_json_file(filepath):
    """读取 JSON 配置文件。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="gbk") as f:
            return json.loads(f.read())
    except Exception:
        return {}


def _get_repo_root():
    # Admin/app/middleware.py -> Admin/app -> Admin -> repo root
    """获取仓库根目录。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_open_api_token():
    """获取OpenAPI令牌。"""
    env_token = str(os.environ.get("BEACON_OPEN_API_TOKEN", "") or "").strip()
    if env_token:
        return env_token

    if _OPEN_API_TOKEN_CACHE.get("loaded"):
        return _OPEN_API_TOKEN_CACHE.get("token", "") or ""

    token = ""
    try:
        config_path = os.path.join(_get_repo_root(), "config.json")
        data = _read_json_file(config_path)
        token = str(data.get("openApiToken", "") or "").strip()
    except Exception:
        token = ""

    _OPEN_API_TOKEN_CACHE["loaded"] = True
    _OPEN_API_TOKEN_CACHE["token"] = token
    return token


def _is_loopback_ip(value):
    """判断`loopback`IP。"""
    if not value:
        return False
    ip = str(value).strip()
    if ip == "::1" or ip == "127.0.0.1":
        return True
    if ip.startswith("127."):
        return True
    return False


def _is_loopback_host(value: str) -> bool:
    """判断`loopback`主机。"""
    s = str(value or "").strip().lower()
    if not s:
        return False
    if s == "localhost":
        return True
    return _is_loopback_ip(s)


def _is_loopback_url(value: str) -> bool:
    """判断`loopback`URL。"""
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").strip()
    except Exception:
        host = ""
    return _is_loopback_host(host)


def _loopback_open_api_allows_unsafe_without_token(request) -> bool:
    """返回`loopback`OpenAPI允许非安全`without`令牌。
    
    In dev/POC mode when OpenAPI token is not configured, loopback requests are
        allowed for backward compatibility. For unsafe methods (POST/PUT/PATCH/DELETE),
        we still want to block cross-site browser CSRF attempts.
    
        Machine clients (Analyzer/curl) typically do not send Origin/Sec-Fetch headers.
        Browsers do, so we can reject obvious cross-site requests without breaking
        local machine-to-machine integrations.
    """
    try:
        meta = getattr(request, "META", {}) or {}
    except Exception:
        meta = {}

    origin = str(meta.get("HTTP_ORIGIN", "") or "").strip()
    if origin:
        return _is_loopback_url(origin)

    sec_fetch_site = str(meta.get("HTTP_SEC_FETCH_SITE", "") or "").strip().lower()
    if sec_fetch_site and sec_fetch_site not in ("none", "same-origin"):
        return False

    referer = str(meta.get("HTTP_REFERER", "") or "").strip()
    if referer:
        return _is_loopback_url(referer)

    return True


def _require_open_api_token():
    """返回需要OpenAPI令牌。"""
    raw = str(os.environ.get("BEACON_REQUIRE_OPEN_API_TOKEN", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _open_api_token_max_length() -> int:
    """处理OpenAPI令牌最大值`length`。"""
    return _env_int("BEACON_OPEN_API_TOKEN_MAX_LENGTH", 2048, min_value=64, max_value=16384)


def _contains_control_chars(value: str) -> bool:
    """处理`contains`控制字符。"""
    raw = str(value or "")
    return any((ord(ch) < 32 or ord(ch) == 127) for ch in raw)


def _unwrap_matching_quotes(value: str) -> str:
    """处理`unwrap``matching``quotes`。"""
    s = str(value or "").strip()
    while len(s) >= 2 and ((s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'"))):
        s = s[1:-1].strip()
        if not s:
            return ""
    return s


def _extract_quoted_token_prefix(value: str):
    """提取带引号令牌前缀。"""
    s = str(value or "")
    if not s.startswith(('"', "'")):
        return None
    quote = s[0]
    end = s.find(quote, 1)
    if end <= 1:
        return None

    token = s[1:end].strip()
    tail = str(s[end + 1 :]).strip()
    if not tail:
        return token
    if tail.startswith((",", ";")):
        return token
    return None


def _strip_auth_param_tail(value: str) -> str:
    """处理`strip`认证参数`tail`。"""
    s = str(value or "")
    for sep in (",", ";"):
        idx = s.find(sep)
        if idx > 0:
            return s[:idx].strip()
    return s


def _strip_auth_param_key_value(value: str) -> str:
    """返回`strip`认证参数键值。"""
    s = str(value or "")
    if "=" not in s:
        return s
    k, v = s.split("=", 1)
    key = str(k or "").strip().lower()
    if key in ("token", "apikey", "api_key", "key", "access_token", "access-token", "credential"):
        return str(v or "").strip()
    return s


def _strip_token_quotes(value: str) -> str:
    """处理`strip`令牌`quotes`。"""
    raw = str(value or "")
    if _contains_control_chars(raw):
        return ""
    s = raw.strip()
    if not s:
        return ""

    # Handle '"token",k=v' / "'token';k=v" style auth params.
    quoted = _extract_quoted_token_prefix(s)
    if quoted is not None:
        return quoted

    # Handle 'token,k=v' / 'token;k=v' style auth params.
    s = _strip_auth_param_tail(s)

    # Handle auth-param style token expression: token=<value>.
    s = _strip_auth_param_key_value(s)
    return _unwrap_matching_quotes(s)


def _request_meta(request) -> dict:
    """处理请求元数据。"""
    try:
        return getattr(request, "META", {}) or {}
    except Exception:
        return {}


def _first_open_api_token_from_headers(meta: dict, max_len: int) -> str:
    """从请求头中提取首个 OpenAPI 令牌。"""
    for header_name in ("HTTP_X_BEACON_TOKEN", "HTTP_X_API_KEY", "HTTP_X_AUTH_TOKEN", "HTTP_X_TOKEN"):
        got = _strip_token_quotes(meta.get(header_name, ""))
        if not got:
            continue
        if len(got) > max_len:
            # Ignore pathological values and continue scanning fallback aliases.
            continue
        return got
    return ""


def _split_authorization_header(value: str):
    """拆分认证请求头。"""
    auth = str(value or "")
    parts = auth.split(None, 1)
    if len(parts) >= 2:
        return parts[0], parts[1]
    if "=" in auth:
        return auth.split("=", 1)
    if ":" in auth:
        return auth.split(":", 1)
    if ";" in auth:
        return auth.split(";", 1)
    return "", ""


def _strip_auth_token_part_prefix(value: str) -> str:
    """返回`strip`认证令牌`part`前缀。"""
    token_part = str(value or "").strip()
    if token_part.startswith("="):
        token_part = token_part[1:].strip()
    if token_part.startswith((":", ";")):
        token_part = token_part[1:].strip()
    return token_part


def _normalize_auth_scheme(value: str) -> str:
    """执行归一化认证`scheme`。"""
    return str(value or "").strip().lower().rstrip("=;:")


def _get_presented_open_api_token(request) -> str:
    """获取`presented`OpenAPI令牌。
    
    Extract OpenAPI token from request headers (best-effort).
    
        Supported:
        - X-Beacon-Token: <token> (legacy)
        - Authorization: Bearer <token> (industrial tooling)
    """
    meta = _request_meta(request)
    max_len = _open_api_token_max_length()
    got = _first_open_api_token_from_headers(meta, max_len)
    if got:
        return got

    auth = str(meta.get("HTTP_AUTHORIZATION", "") or "").strip()
    if not auth:
        return ""
    auth = _unwrap_matching_quotes(auth)
    if not auth:
        return ""

    scheme_raw, token_part = _split_authorization_header(auth)
    token_part = _strip_auth_token_part_prefix(token_part)
    scheme = _normalize_auth_scheme(scheme_raw)
    if scheme not in ("bearer", "apikey", "token"):
        return ""
    got = _strip_token_quotes(token_part or "")
    if len(got) > max_len:
        return ""
    return got


def _hash_api_key_token(token: str) -> str:
    """返回哈希API键令牌。"""
    pepper = str(os.environ.get("BEACON_API_KEY_PEPPER", "") or "")
    raw = (pepper + str(token or "")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _api_key_scope_enabled(value) -> bool:
    """处理 `key_scope_enabled` 接口请求。"""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return not math.isclose(float(value), 0.0, abs_tol=1e-9)
    return _unwrap_matching_quotes(value).lower() in ("1", "true", "yes", "y", "on")


def _api_key_scope_literal(value: str):
    """处理 `key_scope_literal` 接口请求。"""
    text = _unwrap_matching_quotes(value)
    if not text:
        return None
    if not (
        (text.startswith("[") and text.endswith("]"))
        or (text.startswith("{") and text.endswith("}"))
        or (text.startswith("(") and text.endswith(")"))
    ):
        return None
    candidates = [text]
    if '\\"' in text:
        candidates.append(text.replace('\\"', '"'))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    try:
        return ast.literal_eval(text)
    except Exception:
        return None


def _api_key_scope_enabled_keys(payload: dict) -> list:
    """处理 `key_scope_enabled_keys` 接口请求。"""
    return [key for key, value in payload.items() if _api_key_scope_enabled(value)]


def _api_key_scope_mapping_candidate(payload: dict):
    """处理 `key_scope_mapping_candidate` 接口请求。"""
    if not isinstance(payload, dict):
        return None
    if "scopes" in payload:
        return payload.get("scopes")
    if "scope" in payload:
        return payload.get("scope")
    for key, value in payload.items():
        lowered = str(key or "").strip().lower()
        if lowered in ("scopes", "scope"):
            return value
    return None


def _api_key_scope_csv_tokens(value: str) -> list:
    """处理 `key_scope_csv_tokens` 接口请求。"""
    text = str(value or "").strip()
    csv_text = _unwrap_matching_quotes(text) or text
    return [token for token in re.split(SCOPE_SPLIT_RE, csv_text) if str(token or "").strip()]


def _api_key_scope_tokens_from_candidate(candidate) -> list:
    """处理 `key_scope_tokens_from_candidate` 接口请求。"""
    if isinstance(candidate, list):
        return list(candidate)
    if isinstance(candidate, dict):
        return _api_key_scope_enabled_keys(candidate)
    if isinstance(candidate, str):
        parsed = _api_key_scope_literal(candidate)
        if isinstance(parsed, (tuple, set)):
            parsed = list(parsed)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return _api_key_scope_enabled_keys(parsed)
        return _api_key_scope_csv_tokens(candidate)
    return []


def _api_key_scope_tokens(loaded) -> list:
    """处理 `key_scope_tokens` 接口请求。"""
    if isinstance(loaded, list):
        return list(loaded)
    if isinstance(loaded, dict):
        candidate = _api_key_scope_mapping_candidate(loaded)
        if candidate is not None:
            return _api_key_scope_tokens_from_candidate(candidate)
        return _api_key_scope_enabled_keys(loaded)
    if isinstance(loaded, str):
        parsed = _api_key_scope_literal(loaded)
        if isinstance(parsed, (tuple, set)):
            parsed = list(parsed)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            candidate = _api_key_scope_mapping_candidate(parsed)
            if candidate is not None:
                return _api_key_scope_tokens_from_candidate(candidate)
            return _api_key_scope_enabled_keys(parsed)
        return _api_key_scope_csv_tokens(loaded)
    return []


def _api_key_scope_parts(raw: str) -> list:
    """处理 `key_scope_parts` 接口请求。"""
    probe = _unwrap_matching_quotes(raw)
    if (
        (probe.startswith("{") and probe.endswith("}"))
        or (probe.startswith("[") and probe.endswith("]"))
        or (probe.startswith("(") and probe.endswith(")"))
    ):
        return [raw]
    if ("|" in raw) or ("," in raw) or (";" in raw) or bool(re.search(r"\s", raw)):
        return [part for part in re.split(SCOPE_SPLIT_RE, raw) if str(part or "").strip()]
    return [raw]


def _normalize_api_key_scope_token(value: str) -> str:
    """执行归一化API键作用域令牌。"""
    token = _unwrap_matching_quotes(str(value or "").strip().lower())
    return token.strip().strip('"').strip("'").strip()


def _parse_api_key_scopes(row) -> list:
    """解析API键`scopes`。"""
    raw_scopes = str(getattr(row, "scopes_json", "") or "").strip()
    if not raw_scopes:
        return []
    try:
        loaded = json.loads(raw_scopes)
    except Exception:
        loaded = raw_scopes
    tokens = _api_key_scope_tokens(loaded)
    if not tokens:
        return []

    out = []
    for token in tokens:
        raw = str(token or "").strip()
        if not raw:
            continue
        for part in _api_key_scope_parts(raw):
            normalized = _normalize_api_key_scope_token(part)
            if not normalized or normalized in out:
                continue
            out.append(normalized)
    return out


def _get_db_api_key_row(request):
    """获取数据库API键记录。"""
    token = _get_presented_open_api_token(request)
    if not token:
        return None

    from django.utils import timezone
    from django.db.models import Q
    from app.models import ApiKey

    try:
        now = timezone.now()
        token_hash = _hash_api_key_token(token)
        return (
            ApiKey.objects.filter(token_hash=token_hash, enabled=True, revoked_at__isnull=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .first()
        )
    except Exception:
        return None


def _db_api_key_authorized(request, required_scope: str = "") -> bool:
    """处理数据库API键`authorized`。
    
    DB-managed API keys (optional).
    
        This is a backward-compatible extension to the legacy single-token auth:
        - It allows multiple keys to authorize OpenAPI/Ops endpoints.
        - Keys are stored hashed in DB (no plaintext token storage).
    """
    row = _get_db_api_key_row(request)
    if not row:
        return False

    scope = str(required_scope or "").strip().lower()
    if not scope:
        return True

    scopes = _parse_api_key_scopes(row)
    if "*" in scopes:
        return True
    return scope in scopes


def _open_api_ok_context(*, source: str, principal: str, rate_limit_per_minute: int = 0, burst_limit: int = 0, api_key_row=None) -> dict:
    """处理OpenAPI通过`context`。"""
    return {
        "ok": True,
        "source": str(source or "").strip() or "unknown",
        "principal": str(principal or "").strip() or "unknown",
        "rate_limit_per_minute": int(rate_limit_per_minute or 0),
        "burst_limit": int(burst_limit or 0),
        "api_key_row": api_key_row,
    }


def _open_api_legacy_token_context(request) -> dict:
    """处理OpenAPI旧版令牌`context`。"""
    return _open_api_ok_context(
        source="legacy_token",
        principal="legacy:" + str(_remote_addr(request) or "unknown"),
        rate_limit_per_minute=0,
        burst_limit=0,
        api_key_row=None,
    )


def _open_api_api_key_context(row) -> dict:
    """处理OpenAPIAPI键`context`。"""
    return _open_api_ok_context(
        source="api_key",
        principal="api_key:" + str(getattr(row, "id", 0) or 0),
        rate_limit_per_minute=int(getattr(row, "rate_limit_per_minute", 0) or 0),
        burst_limit=int(getattr(row, "burst_limit", 0) or 0),
        api_key_row=row,
    )


def _open_api_loopback_context(request) -> dict:
    """处理OpenAPI`loopback``context`。"""
    return _open_api_ok_context(
        source="loopback",
        principal="loopback:" + str(_remote_addr(request) or "unknown"),
        rate_limit_per_minute=0,
        burst_limit=0,
        api_key_row=None,
    )


def _api_key_row_authorized_for_scope(row, scope: str) -> bool:
    """处理 `key_row_authorized_for_scope` 接口请求。"""
    scope = str(scope or "").strip().lower()
    if not scope:
        return True
    scopes = _parse_api_key_scopes(row)
    if "*" in scopes:
        return True
    return scope in scopes


def _unsafe_method(request) -> bool:
    """处理非安全`method`。"""
    try:
        method = str(getattr(request, "method", "") or "").strip().upper()
    except Exception:
        method = ""
    if not method:
        return False
    return method not in ("GET", "HEAD", "OPTIONS")


def _open_api_auth_context(request, required_scope: str) -> dict:
    """处理OpenAPI认证`context`。"""
    expected = _get_open_api_token()
    presented = _get_presented_open_api_token(request)
    scope = str(required_scope or "").strip().lower()

    if expected:
        if presented and hmac.compare_digest(str(presented), str(expected)):
            return _open_api_legacy_token_context(request)
        row = _get_db_api_key_row(request)
        if row and _api_key_row_authorized_for_scope(row, scope):
            return _open_api_api_key_context(row)
        return {"ok": False}

    row = _get_db_api_key_row(request)
    if row and _api_key_row_authorized_for_scope(row, scope):
        return _open_api_api_key_context(row)

    if _require_open_api_token():
        return {"ok": False}

    if _is_loopback_ip(request.META.get("REMOTE_ADDR")):
        # Backward-compatible dev/POC behavior: allow loopback requests even when
        # no OpenAPI token is configured. For unsafe methods, mitigate browser CSRF
        # by rejecting obvious cross-site requests (Origin/Sec-Fetch).
        if _unsafe_method(request) and (not _loopback_open_api_allows_unsafe_without_token(request)):
            return {"ok": False}
        return _open_api_loopback_context(request)
    return {"ok": False}


def _screen_login_required() -> bool:
    """处理`screen`登录`required`。
    
    Whether /screen/index (big screen page) requires a logged-in web session.
    
        This is intentionally *not* tied to OpenAPI token: the screen page is a UI page.
        Industrial deployments may want to embed or show it on a wall display without login.
    """
    from app.utils.SystemConfigHelper import get_bool

    try:
        return bool(get_bool("screenLoginRequired", default=True))
    except Exception:
        return True


def _open_api_authorized_for_scope(request, required_scope: str) -> bool:
    """获取作用域的OpenAPI`authorized`。
    
    Authorize an OpenAPI/Ops request for a required scope.
    
        Scope mapping is enforced for DB-managed ApiKey rows.
        Legacy single token (BEACON_OPEN_API_TOKEN/config.json openApiToken) is treated
        as full-scope for backward compatibility.
    """
    return bool(_open_api_auth_context(request, required_scope).get("ok"))


def _open_api_authorized(request) -> bool:
    # Backward-compatible wrapper: treat as OpenAPI scope.
    """处理OpenAPI`authorized`。"""
    return _open_api_authorized_for_scope(request, "openapi")


def _is_open_api_path(path):
    """判断OpenAPI路径。"""
    if path == "api/app-shell" or path.startswith("api/app-shell/"):
        return False
    return path.startswith((
        "open",
        "alarm/open",
        "control/open",
        "algorithm/open",
        "stream/open",
        "api",
        "onvif/api",
    ))


def _is_digital_human_runtime_open_path(path: str) -> bool:
    """判断数字人 runtime 自鉴权开放路径。"""
    if not path:
        return False
    return path in (
        "open/agent/token",
        "open/agent/register",
        "open/agent/report",
        "open/agent/config/latest",
        "open/agent/commands/pull",
        "open/agent/commands/result",
        "open/human/report",
    )


def _is_machine_open_api_path(path):
    """判断`machine`OpenAPI路径。
    
    OpenAPI paths intended for machine-to-machine integration.
    
        These should never be implicitly authorized by a logged-in web session.
    """
    return path.startswith((
        "open",
        "alarm/open",
        "control/open",
        "algorithm/open",
        "stream/open",
    ))

def _is_ops_standard_path(path):
    """判断运维`standard`路径。
    
    Standard ops endpoints that should NOT require a logged-in web session.
    
        These endpoints are intended for k8s probes / Prometheus scrapes, but still
        must be protected by the same OpenAPI token policy to avoid accidental
        exposure on public networks.
    """
    if not path:
        return False
    return path in ("healthz", "readyz", "metrics")


def _gateway_json_response(*, status: int, msg: str, headers: dict | None = None):
    # OpenAPI-style error body schema:
    # - HTTP status carries the transport-level status (401/403/429/503...)
    # - JSON body keeps the legacy `code=0` error convention for compatibility
    #   with existing clients/tests that treat non-1000 as failure.
    """返回网关JSON响应。"""
    body_code = 1000 if int(status) < 400 else 0
    resp = HttpResponse(
        json.dumps({"code": int(body_code), "msg": str(msg or "")}, ensure_ascii=False),
        status=int(status),
        content_type=CONTENT_TYPE_JSON,
    )
    for key, value in (headers or {}).items():
        try:
            resp[str(key)] = str(value)
        except Exception:
            continue
    return resp


def _enforce_openapi_gateway(request, *, required_scope: str) -> HttpResponse | None:
    """处理`enforce``openapi`网关。
    
    Enforce OpenAPI/Ops auth + WAF + rate limiting for a request.
    
        Returns:
        - `None` if the request is allowed to proceed.
        - an `HttpResponse` if the request must be blocked.
    """
    auth = _open_api_auth_context(request, required_scope)
    if not auth.get("ok"):
        return _gateway_json_response(status=401, msg="unauthorized")

    from app.utils.OpenApiGateway import (
        apply_rate_limit,
        build_rate_limit_headers,
        check_request_waf,
        get_openapi_gateway_settings,
    )

    gateway_settings = get_openapi_gateway_settings()
    waf = check_request_waf(request, gateway_settings)
    if not waf.get("ok"):
        return _gateway_json_response(
            status=int(waf.get("status_code") or 403),
            msg=str(waf.get("msg") or "waf blocked"),
        )

    if gateway_settings.get("rate_limit_enabled"):
        rate = apply_rate_limit(
            principal=str(auth.get("principal") or "unknown"),
            rate_limit_per_minute=int(auth.get("rate_limit_per_minute") or gateway_settings.get("rate_limit_per_minute") or 0),
            burst_limit=int(auth.get("burst_limit") or gateway_settings.get("rate_limit_burst") or 0),
        )
        headers = build_rate_limit_headers(rate)
        setattr(request, "beacon_openapi_gateway_headers", headers)
        if not rate.get("ok"):
            return _gateway_json_response(status=429, msg="rate limit exceeded", headers=headers)

    return None


def _build_ops_audit_event_type(path: str, method: str) -> str:
    """构建运维审计事件类型。
    
    Build a short OpsAuditLog.event_type (<= 50 chars).
    
        Examples:
          - stream/setAutoStartConfig + POST -> stream.setAutoStartConfig.post
          - user/api/addUser + POST -> user.addUser.post
    """
    try:
        p = str(path or "").lstrip("/")
    except Exception:
        p = ""
    try:
        m = str(method or "").strip().lower() or "unknown"
    except Exception:
        m = "unknown"

    segs = [s for s in p.split("/") if s]
    if not segs:
        return ("web." + m)[:50]

    module = segs[0]
    action = ""
    if len(segs) >= 2:
        if segs[1] == "api" and len(segs) >= 3:
            action = segs[2]
        else:
            action = segs[1]

    base = module
    if action:
        base = f"{module}.{action}"
    return f"{base}.{m}"[:50]


def _build_security_audit_event_type(path: str, status_code: int) -> str:
    """构建`security`审计事件类型。"""
    p = str(path or "").lstrip("/")
    try:
        status = int(status_code or 0)
    except Exception:
        status = 0

    if p.startswith(("login", "getVerifyCode")):
        return "security.login_ip_block"
    if status == 401:
        return "openapi.auth.unauthorized"
    if status == 403:
        return "openapi.auth.forbidden"
    if status == 429:
        return "openapi.auth.rate_limited"
    return "openapi.auth.error"


def _build_security_audit_reason(path: str, status_code: int) -> str:
    """构建`security`审计原因。"""
    p = str(path or "").lstrip("/")
    try:
        status = int(status_code or 0)
    except Exception:
        status = 0

    if p.startswith(("login", "getVerifyCode")):
        return "ip_policy"
    if status == 401:
        return "token_missing_or_invalid"
    if status == 403:
        return "policy_or_scope_denied"
    if status == 429:
        return "rate_limited"
    return "gateway_or_backend_error"


def _apply_gateway_response_headers(request, response) -> None:
    """处理应用网关响应请求头。"""
    try:
        for key, value in (getattr(request, "beacon_openapi_gateway_headers", {}) or {}).items():
            response[str(key)] = str(value)
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1232", exc_info=True)


def _apply_trace_response_headers(request, response) -> None:
    """处理应用链路追踪响应请求头。"""
    try:
        rid = str(getattr(request, "beacon_request_id", "") or "").strip()
        cid = str(getattr(request, "beacon_correlation_id", "") or "").strip()
        if rid:
            response["X-Request-Id"] = rid
        if cid:
            response["X-Correlation-Id"] = cid
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1245", exc_info=True)


def _is_app_shell_client_request(request) -> bool:
    """判断`app``shell``client`请求。"""
    try:
        meta = _request_meta(request)
        raw = str(meta.get(APP_SHELL_MARKER_META_KEY, "") or "").strip().lower()
    except Exception:
        return False
    return raw in ("1", "true", "yes", "y", "on")


def _legacy_api_block_for_app_shell_enabled() -> bool:
    """判断旧版API拦截`for``app``shell`是否启用。"""
    return _env_bool("BEACON_BLOCK_LEGACY_API_FOR_APP_SHELL", default=False)


def _legacy_api_allowlist_rule_from_token(token: str):
    """Parse one legacy API allowlist token into a rule tuple."""
    item = str(token or "").strip().lstrip("/")
    if not item:
        return None
    if item.endswith("*"):
        prefix = item[:-1].rstrip("/")
        return ("prefix", prefix) if prefix else None
    if item.endswith("/"):
        prefix = item.rstrip("/")
        return ("prefix", prefix) if prefix else None
    return ("exact", item)


def _legacy_api_block_allowlist_rules():
    """处理旧版API拦截允许列表规则。"""
    raw = str(os.environ.get("BEACON_BLOCK_LEGACY_API_ALLOWLIST", "") or "").strip()
    if raw == _LEGACY_API_BLOCK_ALLOWLIST_CACHE.get("raw"):
        return _LEGACY_API_BLOCK_ALLOWLIST_CACHE.get("rules") or []

    rules = []
    for token in raw.split(","):
        rule = _legacy_api_allowlist_rule_from_token(token)
        if rule:
            rules.append(rule)

    _LEGACY_API_BLOCK_ALLOWLIST_CACHE["raw"] = raw
    _LEGACY_API_BLOCK_ALLOWLIST_CACHE["rules"] = rules
    return rules


def _legacy_api_block_allowlisted(path: str) -> bool:
    """判断旧版API拦截是否命中允许列表。"""
    normalized = str(path or "").strip().lstrip("/")
    if not normalized:
        return False

    for rule_type, value in _legacy_api_block_allowlist_rules():
        if not value:
            continue
        if rule_type == "exact" and normalized == value:
            return True
        if rule_type == "prefix" and (normalized == value or normalized.startswith(str(value) + "/")):
            return True
    return False


def _is_legacy_api_path(path: str) -> bool:
    """判断旧版API路径。"""
    normalized = str(path or "").strip().lstrip("/")
    if not normalized:
        return False
    if normalized.startswith("api/app-shell/"):
        return False
    return normalized.startswith(
        (
            "api/",
            "open/",
            "stream/",
            "control/",
            "alarm/",
            "algorithm/",
            "pipeline/",
            "recording/",
            "user/api/",
            "ops/",
            "onvif/api/",
            "developer/",
        )
    )


def _legacy_api_block_response(request, path: str):
    """返回旧版API拦截响应。"""
    if not _legacy_api_block_for_app_shell_enabled():
        return None
    if not _is_app_shell_client_request(request):
        return None
    if not _is_legacy_api_path(path):
        return None
    if _legacy_api_block_allowlisted(path):
        return None

    setattr(request, "beacon_legacy_api_blocked", True)
    _log_security_event(
        LEGACY_API_BLOCKED_EVENT,
        str(path or ""),
        "app-shell",
        _remote_addr(request),
        410,
        str(getattr(request, "beacon_request_id", "") or ""),
        str(getattr(request, "beacon_correlation_id", "") or ""),
    )

    response = HttpResponse(
        json.dumps({"code": 0, "msg": "legacy api blocked for app-shell client"}, ensure_ascii=False),
        status=410,
        content_type=CONTENT_TYPE_JSON,
    )
    response[LEGACY_API_RESPONSE_HEADER] = "1"
    return response


def _apply_legacy_api_observability(request, response) -> None:
    """处理应用旧版API`observability`。"""
    try:
        if bool(getattr(request, "beacon_legacy_api_blocked", False)):
            return
        if not _is_app_shell_client_request(request):
            return
        path = _audit_request_path(request)
        if not _is_legacy_api_path(path):
            return

        response[LEGACY_API_RESPONSE_HEADER] = "1"
        _log_security_event(
            LEGACY_API_REQUEST_EVENT,
            str(path or ""),
            "app-shell",
            _audit_source_ip(request),
            int(getattr(response, "status_code", 0) or 0),
            str(getattr(request, "beacon_request_id", "") or ""),
            str(getattr(request, "beacon_correlation_id", "") or ""),
        )
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1388", exc_info=True)


def _audit_request_path(request) -> str:
    """返回审计请求路径。"""
    try:
        return request.path_info.lstrip("/")
    except Exception:
        return ""


def _audit_session_user(request):
    """处理审计会话用户。"""
    session = getattr(request, "session", None)
    try:
        if session and "user" in session:
            return session.get("user") or {}
    except Exception:
        return None
    return None


def _audit_request_method(request) -> str:
    """处理审计请求`method`。"""
    return str(getattr(request, "method", "") or "").strip().upper()


def _audit_operator(session_user) -> str:
    """处理审计操作人。"""
    if not isinstance(session_user, dict) or not session_user:
        return ""
    return str(session_user.get("username") or session_user.get("name") or "").strip()


def _audit_source_ip(request) -> str:
    """处理审计来源IP。"""
    return str(getattr(request, "META", {}).get("REMOTE_ADDR", "") or "").strip()


def _audit_detail_base(path: str, method: str, response) -> dict:
    """处理审计详情基础。"""
    return {
        "path": path,
        "method": method,
        "status_code": int(getattr(response, "status_code", 0) or 0),
    }


def _audit_attach_user_agent(detail: dict, request) -> None:
    """处理审计附加用户代理。"""
    try:
        ua = str(getattr(request, "META", {}).get("HTTP_USER_AGENT", "") or "").strip()
    except Exception:
        ua = ""
    if ua:
        detail["user_agent"] = ua


def _audit_attach_trace_ids(detail: dict, request):
    """返回审计附加链路追踪`ids`。"""
    try:
        rid = str(getattr(request, "beacon_request_id", "") or "").strip()
        cid = str(getattr(request, "beacon_correlation_id", "") or "").strip()
    except Exception:
        return "", ""
    if rid:
        detail["request_id"] = rid
    if cid:
        detail["correlation_id"] = cid
    return rid, cid


def _audit_response_outcome(detail: dict, response):
    """处理审计响应`outcome`。"""
    content_type = ""
    try:
        content_type = str(response.get("Content-Type", "") or "").lower()
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1466", exc_info=True)
    if CONTENT_TYPE_JSON not in content_type:
        return int(getattr(response, "status_code", 0) or 0) < 400, ""
    try:
        raw = getattr(response, "content", b"")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(str(raw or "").strip() or "{}")
        if isinstance(payload, dict):
            code = payload.get("code")
            msg = payload.get("msg")
            detail["code"] = code
            if msg is not None:
                detail["msg"] = str(msg)
            ok = bool(code == 1000)
            return ok, "" if ok or not msg else str(msg)
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1483", exc_info=True)
    return int(getattr(response, "status_code", 0) or 0) < 400, ""


def _write_ops_audit_row(event_type: str, operator: str, *, ok: bool, source_ip: str, error_message: str, detail: dict) -> None:
    """写入运维审计记录。"""
    from app.models import OpsAuditLog

    OpsAuditLog.objects.create(
        event_type=str(event_type or "").strip()[:50],
        ok=bool(ok),
        operator=str(operator or "").strip()[:100],
        source_ip=source_ip,
        error_message=error_message,
        detail_json=json.dumps(detail, ensure_ascii=False),
    )


def _is_machine_open_path(path: str) -> bool:
    """判断`machine`开放路径。"""
    return bool(
        _is_open_api_path(path)
        or _is_ops_standard_path(path)
        or path == OPEN_OPS_PATH
        or path.startswith(OPEN_OPS_PREFIX)
    )


def _is_login_entry_path(path: str) -> bool:
    """判断登录条目路径。"""
    return bool(path.startswith(("login", "getVerifyCode")))


def _log_security_event(event_type: str, reason: str, operator: str, source_ip: str, status_code: int, rid: str, cid: str) -> None:
    """记录`security`事件。"""
    try:
        logger.warning(
            "security event_type=%s reason=%s operator=%s ip=%s status=%s rid=%s cid=%s",
            event_type,
            reason,
            operator or "-",
            source_ip or "-",
            status_code,
            rid or "-",
            cid or "-",
        )
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1530", exc_info=True)


def _log_audit_event(event_type: str, ok: bool, operator: str, source_ip: str, status_code: int, rid: str, cid: str) -> None:
    """记录审计事件。"""
    try:
        logger.info(
            "audit event_type=%s ok=%s operator=%s ip=%s status=%s rid=%s cid=%s",
            event_type,
            "1" if ok else "0",
            operator or "-",
            source_ip or "-",
            status_code,
            rid or "-",
            cid or "-",
        )
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1547", exc_info=True)


def _read_audit_event(path: str, request):
    """读取审计事件。"""
    if path == "config/api/logs/export" or path == "api/app-shell/config/action/logs/export":
        return "config.logs.export.get", None
    if (
        path == "ops/audit/export"
        or path == "open/ops/audit/export"
        or path == "api/app-shell/ops/action/audit/export"
    ):
        return "ops.audit.export.get", None
    if path == "open/ops/diagnostics/export" or path == "api/app-shell/ops/action/diagnostics/export":
        return "ops.diagnostics.export.get", None
    if path.startswith("open/fileService/"):
        return "fileService.download.get", {"type": "file", "rel_path": path[len("open/fileService/") :]}
    if path != "stream/getPlayUrl" and path != "api/app-shell/stream/action/getPlayUrl":
        return "", None
    return STREAM_PLAY_AUDIT_EVENT, _stream_play_audit_resource(request)


def _stream_play_audit_resource(request):
    """处理流播放审计`resource`。"""
    try:
        app = str(getattr(request, "GET", {}).get("app", "") or "").strip()
        name = str(getattr(request, "GET", {}).get("name", "") or "").strip()
    except Exception:
        return None
    if app and name:
        return {"type": "stream", "app": app, "name": name}
    return None


def _attach_request_trace_ids(request) -> None:
    """附加请求链路追踪`ids`。"""
    try:
        rid = _get_request_id(request)
        cid = _get_correlation_id(request, rid)
        setattr(request, "beacon_request_id", rid)
        setattr(request, "beacon_correlation_id", cid)
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1589", exc_info=True)


def _session_gateway_scope_for_path(path: str) -> str:
    """获取路径的会话网关作用域。"""
    if _is_digital_human_runtime_open_path(path):
        return ""
    if _is_ops_standard_path(path) or path == OPEN_OPS_PATH or path.startswith(OPEN_OPS_PREFIX):
        return "ops"
    if _is_machine_open_api_path(path):
        return "openapi"
    return ""


def _public_gateway_scope_for_path(path: str) -> str:
    """获取路径的公共网关作用域。"""
    if _is_digital_human_runtime_open_path(path):
        return ""
    if _is_ops_standard_path(path) or path == OPEN_OPS_PATH or path.startswith(OPEN_OPS_PREFIX):
        return "ops"
    if _is_open_api_path(path):
        return "openapi"
    return ""


def _is_public_sessionless_path(path: str, *, screen_login_required: bool) -> bool:
    """判断公共`sessionless`路径。"""
    if _is_login_entry_path(path):
        return True
    if _is_digital_human_runtime_open_path(path):
        return True
    if screen_login_required:
        return False
    if path == "screen/index" or path.startswith("screen/index"):
        return True
    return path in ("stream/getOnline", "stream/getPlayUrl")


def _ip_policy_response(request, path: str):
    """返回IP策略响应。"""
    try:
        if _public_gateway_scope_for_path(path):
            if not _open_api_ip_allowed(request):
                return HttpResponse(
                    json.dumps({"code": 403, "msg": "forbidden"}, ensure_ascii=False),
                    status=403,
                    content_type=CONTENT_TYPE_JSON,
                )
        if _is_login_entry_path(path) and (not _admin_ip_allowed(request)):
            return HttpResponse("forbidden", status=403, content_type="text/plain")
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1634", exc_info=True)
    return None


def _should_block_edge_open_cloud(path: str) -> bool:
    """判断拦截边缘开放云端。"""
    return (not is_cloud_mode()) and (path == "open/cloud" or path.startswith("open/cloud/"))


def _is_cloud_edge_api_path(path: str) -> bool:
    """判断云端边缘API路径。"""
    return is_cloud_mode() and (path == "open/cloud/v1" or path.startswith("open/cloud/v1/"))


def _cloud_edge_request_response(request):
    """返回云端边缘请求响应。"""
    from app.utils.CloudEdgeAuth import authenticate_edge_request

    auth = authenticate_edge_request(request)
    if not bool(auth.get("ok")):
        try:
            status_code = int(auth.get("status_code") or 401)
        except Exception:
            status_code = 401
        return HttpResponse(
            json.dumps({"code": 0, "msg": str(auth.get("error") or "unauthorized")}),
            status=status_code,
            content_type=CONTENT_TYPE_JSON,
        )

    setattr(request, "cloud_edge_cluster", auth.get("cluster"))
    return None


def _has_session_user(request) -> bool:
    """检查会话用户。"""
    session = getattr(request, "session", None)
    try:
        return bool(session and "user" in session)
    except Exception:
        return False


def _authenticated_login_redirect_response(path: str):
    """返回已认证登录`redirect`响应。"""
    if path.startswith("login"):
        return HttpResponseRedirect("/")
    return None


def _authenticated_gateway_response(request, path: str):
    """返回已认证网关响应。"""
    scope = _session_gateway_scope_for_path(path)
    if not scope:
        return None
    try:
        return _enforce_openapi_gateway(request, required_scope=scope)
    except Exception:
        return _gateway_json_response(status=503, msg="gateway error")


def _session_user_id(session_user) -> int:
    """返回会话中的用户 ID。"""
    try:
        return int((session_user or {}).get("id") or 0)
    except Exception:
        return 0


def _totp_reauth_response(request, path: str):
    # Only skip machine-to-machine OpenAPI/ops probe paths.
    # App-shell `/api/app-shell/*` endpoints should still be protectable
    # via `BEACON_TOTP_SENSITIVE_REAUTH_PREFIXES`.
    """返回TOTP二次认证响应。"""
    if _is_machine_open_api_path(path) or _is_ops_standard_path(path) or (not _totp_path_requires_reauth(path)):
        return None

    session_user = _audit_session_user(request) or {}
    user_id = _session_user_id(session_user)
    if user_id <= 0:
        return None

    from app.models import UserTotpCredential

    has_totp = UserTotpCredential.objects.filter(user_id=user_id, enabled=True).exists()
    if not has_totp:
        return None

    try:
        until_ts = int(request.session.get(_TOTP_REAUTH_UNTIL_SESSION_KEY) or 0)
    except Exception:
        until_ts = 0
    now_ts = int(time.time())
    if until_ts > now_ts:
        return None

    win = _totp_reauth_window_seconds()
    return _totp_reauth_deny_response(
        request,
        f"TOTP re-auth is missing or expired (window: {win}s). Please complete re-auth on the profile page and retry.",
    )


def _permission_message_response(request, msg: str, *, status: int | None = None):
    """返回权限`message`响应。"""
    accept = str(getattr(request, "META", {}).get("HTTP_ACCEPT", "") or "").lower()
    wants_html = CONTENT_TYPE_HTML in accept
    template_ctx = {
        "msg": msg,
        "is_success": False,
        "redirect_url": "/",
    }
    if wants_html:
        if status is None:
            return render(request, TEMPLATE_MESSAGE_HTML, template_ctx)
        return render(request, TEMPLATE_MESSAGE_HTML, template_ctx, status=status)

    return JsonResponse(
        {"code": 403, "msg": msg},
        status=status or 200,
        json_dumps_params={"ensure_ascii": False},
    )


def _permission_response(request, path: str):
    # Only skip machine OpenAPI/ops probe paths.
    # App-shell `/api/app-shell/*` endpoints must keep user-permission checks.
    """返回权限响应。"""
    if _is_machine_open_api_path(path) or _is_ops_standard_path(path):
        return None

    from django.contrib.auth.models import User
    from app.models import UserPermission

    try:
        session_user = _audit_session_user(request) or {}
        user_id = _session_user_id(session_user)
        db_user = User.objects.filter(id=user_id).first() if user_id > 0 else None
        if db_user and (db_user.is_staff or db_user.is_superuser):
            return None

        if is_path_allowed({}, path) is None:
            return None

        perm_obj = UserPermission.objects.filter(user_id=user_id).first() if user_id > 0 else None
        parsed, perms = parse_permissions_json(getattr(perm_obj, "permissions_json", "") if perm_obj else "")
        if parsed is None:
            return None
        if parsed is False:
            return _permission_message_response(request, "权限配置无效，请联系管理员")
        if is_path_allowed(perms, path):
            return None
        return _permission_message_response(request, "权限不足：当前账号无访问该模块的权限")
    except Exception:
        logger.exception("permission check failed (fail-closed): path=%s", path)
        return _permission_message_response(request, "权限系统异常，请联系管理员", status=403)


def _authenticated_request_response(request, path: str):
    """返回已认证请求响应。"""
    login_redirect = _authenticated_login_redirect_response(path)
    if login_redirect is not None:
        return login_redirect

    gateway_response = _authenticated_gateway_response(request, path)
    if gateway_response is not None:
        return gateway_response

    try:
        totp_response = _totp_reauth_response(request, path)
        if totp_response is not None:
            return totp_response
    except Exception:
        logger.debug("suppressed exception in app/middleware.py:1809", exc_info=True)

    return _permission_response(request, path)


def _unauthenticated_request_response(request, path: str):
    """返回未认证请求响应。"""
    if _is_public_sessionless_path(path, screen_login_required=_screen_login_required()):
        return None

    if path == "api/app-shell" or path.startswith("api/app-shell/"):
        return _gateway_json_response(status=401, msg="unauthorized")

    scope = _public_gateway_scope_for_path(path)
    if not scope:
        return HttpResponseRedirect("/login")

    resp = _enforce_openapi_gateway(request, required_scope=scope)
    if resp is not None:
        return resp
    return None


def _response_audit_action(path: str, method: str, *, has_session_user: bool, status_code: int, read_event: str) -> str:
    """处理响应审计动作。"""
    is_machine_open_path = _is_machine_open_path(path)
    is_login_entry = _is_login_entry_path(path)
    if (not has_session_user) and status_code >= 400 and (is_machine_open_path or is_login_entry):
        return "security"
    if is_login_entry:
        return "skip"
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        if has_session_user and not (_is_open_api_path(path) or _is_ops_standard_path(path)):
            return "mutating"
        return "skip"
    if method == "GET" and read_event:
        return "read"
    return "skip"


def _build_response_audit_context(request, response):
    """构建响应审计`context`。"""
    path = _audit_request_path(request)
    if not path or path.startswith("static") or path.startswith("logout"):
        return None

    session_user = _audit_session_user(request)
    method = _audit_request_method(request)
    operator = _audit_operator(session_user)
    source_ip = _audit_source_ip(request)
    detail = _audit_detail_base(path, method, response)
    _audit_attach_user_agent(detail, request)
    rid, cid = _audit_attach_trace_ids(detail, request)
    ok, error_message = _audit_response_outcome(detail, response)
    status_code = int(detail.get("status_code") or 0)
    read_event, resource = _read_audit_event(path, request) if method == "GET" else ("", None)
    action = _response_audit_action(
        path,
        method,
        has_session_user=bool(session_user),
        status_code=status_code,
        read_event=read_event,
    )
    return {
        "action": action,
        "cid": cid,
        "detail": detail,
        "error_message": error_message,
        "method": method,
        "ok": ok,
        "operator": operator,
        "path": path,
        "read_event": read_event,
        "resource": resource,
        "rid": rid,
        "session_user": session_user,
        "source_ip": source_ip,
        "status_code": status_code,
    }


def _write_security_audit_from_context(ctx: dict) -> None:
    """写入`security`审计`from``context`。"""
    path = str(ctx.get("path") or "")
    status_code = int(ctx.get("status_code") or 0)
    detail = ctx.get("detail") or {}
    evt = _build_security_audit_event_type(path, status_code)
    reason = _build_security_audit_reason(path, status_code)
    detail["security_event_type"] = evt
    detail["security_reason"] = reason
    source_ip = str(ctx.get("source_ip") or "")
    op = "openapi" if _is_machine_open_path(path) else ""
    _write_ops_audit_row(
        evt,
        op,
        ok=bool(ctx.get("ok")),
        source_ip=source_ip,
        error_message=str(ctx.get("error_message") or ""),
        detail=detail,
    )
    _log_security_event(
        evt,
        reason,
        op,
        source_ip,
        status_code,
        str(ctx.get("rid") or ""),
        str(ctx.get("cid") or ""),
    )


def _write_mutating_audit_from_context(ctx: dict) -> None:
    """写入`mutating`审计`from``context`。"""
    path = str(ctx.get("path") or "")
    method = str(ctx.get("method") or "")
    detail = ctx.get("detail") or {}
    source_ip = str(ctx.get("source_ip") or "")
    event_type = _build_ops_audit_event_type(path, method)
    _write_ops_audit_row(
        event_type,
        str(ctx.get("operator") or ""),
        ok=bool(ctx.get("ok")),
        source_ip=source_ip,
        error_message=str(ctx.get("error_message") or ""),
        detail=detail,
    )
    _log_audit_event(
        event_type,
        bool(ctx.get("ok")),
        str(ctx.get("operator") or ""),
        source_ip,
        int(ctx.get("status_code") or 0),
        str(ctx.get("rid") or ""),
        str(ctx.get("cid") or ""),
    )


def _write_read_audit_from_context(ctx: dict) -> None:
    """写入读取审计`from``context`。"""
    detail = ctx.get("detail") or {}
    resource = ctx.get("resource")
    if resource is not None:
        detail["resource"] = resource

    source_ip = str(ctx.get("source_ip") or "")
    session_user = ctx.get("session_user")
    operator = str(ctx.get("operator") or "") if session_user else "openapi"
    event_type = str(ctx.get("read_event") or "")
    _write_ops_audit_row(
        event_type,
        operator,
        ok=bool(ctx.get("ok")),
        source_ip=source_ip,
        error_message=str(ctx.get("error_message") or ""),
        detail=detail,
    )
    _log_audit_event(
        event_type,
        bool(ctx.get("ok")),
        operator,
        source_ip,
        int(ctx.get("status_code") or 0),
        str(ctx.get("rid") or ""),
        str(ctx.get("cid") or ""),
    )


def _dispatch_response_audit(ctx: dict) -> None:
    """分发响应审计。"""
    action = str(ctx.get("action") or "")
    if action == "security":
        _write_security_audit_from_context(ctx)
        return
    if action == "mutating":
        _write_mutating_audit_from_context(ctx)
        return
    if action == "read":
        _write_read_audit_from_context(ctx)


class OpenApiCsrfBypassMiddleware(MiddlewareMixin):
    """
    Allow open API requests WITHOUT a logged-in web session to bypass CSRF checks.

    This keeps machine-to-machine calls working (e.g. Analyzer -> Admin /alarm/openAdd)
    while enabling CsrfViewMiddleware to protect session-based web UI actions.
    """

    def process_request(self, request):
        """处理请求阶段逻辑。"""
        try:
            path = request.path_info.lstrip('/')
        except Exception:
            return None

        if not _is_open_api_path(path):
            return None

        try:
            if request.session and request.session.get("user"):
                return None
        except Exception:
            logger.debug("suppressed exception in app/middleware.py:2008", exc_info=True)

        setattr(request, "_dont_enforce_csrf_checks", True)
        return None


class SimpleMiddleware(MiddlewareMixin):
    def process_request(self, request):
        """处理请求阶段逻辑。"""
        _attach_request_trace_ids(request)
        path = _audit_request_path(request)

        legacy_block_response = _legacy_api_block_response(request, path)
        if legacy_block_response is not None:
            return legacy_block_response

        ip_policy_response = _ip_policy_response(request, path)
        if ip_policy_response is not None:
            return ip_policy_response

        if _should_block_edge_open_cloud(path):
            return HttpResponse(status=404)

        if _is_cloud_edge_api_path(path):
            return _cloud_edge_request_response(request)

        if _has_session_user(request):
            return _authenticated_request_response(request, path)

        return _unauthenticated_request_response(request, path)

    def process_response(self, request, response):
        """处理响应阶段逻辑。"""
        _apply_gateway_response_headers(request, response)
        _apply_trace_response_headers(request, response)
        _apply_legacy_api_observability(request, response)
        try:
            audit_ctx = _build_response_audit_context(request, response)
            if audit_ctx is not None:
                _dispatch_response_audit(audit_ctx)
        except Exception:
            logger.debug("suppressed exception in app/middleware.py:2049", exc_info=True)

        return response


def _is_truthy_env(name: str) -> bool:
    """判断`truthy`环境变量。"""
    raw = os.environ.get(name)
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_csv(name: str):
    """读取环境变量并拆分为列表。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


class IframeEmbedMiddleware(MiddlewareMixin):
    """
    工业交付：可配置允许后台管理页面被 iframe 嵌入，例如集群平台或大屏系统。

    默认保持 X-Frame-Options=DENY；仅当 BEACON_IFRAME_EMBED_ENABLED=1 时放开。

    Env:
      - BEACON_IFRAME_EMBED_ENABLED=1
      - BEACON_IFRAME_EMBED_ALLOWED_ORIGINS=https://a.example.com,https://b.example.com
        未配置 allowlist 时仅允许同源嵌入（frame-ancestors 'self'）。
    """

    def process_response(self, request, response):
        """处理响应阶段逻辑。"""
        try:
            if not _is_truthy_env("BEACON_IFRAME_EMBED_ENABLED"):
                return response

            # Remove X-Frame-Options set by Django's XFrameOptionsMiddleware.
            try:
                if response.has_header("X-Frame-Options"):
                    del response["X-Frame-Options"]
            except Exception:
                logger.debug("suppressed exception in app/middleware.py:2093", exc_info=True)

            allowed = _env_csv("BEACON_IFRAME_EMBED_ALLOWED_ORIGINS")
            if allowed:
                frame_ancestors = " ".join(["'self'"] + allowed)
            else:
                frame_ancestors = "'self'"

            desired = f"frame-ancestors {frame_ancestors}"

            # Merge with existing CSP (if any): remove any existing frame-ancestors directive.
            existing = str(response.get("Content-Security-Policy", "") or "").strip()
            if existing:
                parts = [p.strip() for p in existing.split(";") if p.strip()]
                parts = [p for p in parts if not p.lower().startswith("frame-ancestors ")]
                parts.append(desired)
                response["Content-Security-Policy"] = "; ".join(parts) + ";"
            else:
                response["Content-Security-Policy"] = desired + ";"

            return response
        except Exception:
            return response
