import json
import os
import time

from app.models import UserTotpCredential
from app.views.ViewsBase import f_parsePostParams, f_responseJson, g_config, g_session_key_user
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from datetime import datetime, timedelta
import ipaddress
import logging
import re
import secrets
import unicodedata
import urllib.parse

from app.utils.SystemConfigHelper import get_bool
from app.utils.Utils import validate_email, gen_random_code_s
from app.utils.PermissionCoerce import coerce_permission_bool
from app.utils.PasswordPolicy import validate_password
from app.utils.UserPermissionRules import PERMISSION_KEYS
from app.utils import Totp, TotpRecovery, LdapAuth, OidcAuth


_VERIFY_CODE_SESSION_KEY_PREFIX = "verify_code_"
_OIDC_STATE_SESSION_KEY = "oidc_state"
_OIDC_NONCE_SESSION_KEY = "oidc_nonce"
_OIDC_ID_TOKEN_SESSION_KEY = "oidc_id_token"
_OIDC_PROVIDER_SESSION_KEY = "oidc_provider"

PATH_LOGIN = "/login"
CONTENT_TYPE_TEXT_PLAIN = "text/plain"
MSG_TOTP_INVALID = "TOTP 验证码错误"

logger = logging.getLogger(__name__)


def _sanitize_oidc_provider_id(raw) -> str:
    """清洗OIDC提供方ID。"""
    try:
        v = str(raw or "").strip()
    except Exception:
        v = ""
    while len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
        v = v[1:-1].strip()
    if not v:
        return ""
    if len(v) > 64:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_.-]+", v):
        return v
    return ""


def _sanitize_oidc_error(raw) -> str:
    """清洗OIDC错误。"""
    try:
        v = str(raw or "").strip()
    except Exception:
        v = ""
    while len(v) >= 2 and ((v.startswith(""") and v.endswith(""")) or (v.startswith("'") and v.endswith("'"))):
        v = v[1:-1].strip()
    if not v:
        return ""
    if len(v) > 64:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_.-]+", v):
        return v
    return ""


def _is_login_captcha_enabled() -> bool:
    """判断`is`登录`captcha`是否启用。
    
    Whether the login captcha is enabled.
    
        Precedence:
          1) SystemConfig (DB) key: loginCaptchaEnabled
          2) config.json/env (g_config.loginCaptchaEnabled)
          3) default: False (backward compatible)
    """
    try:
        default_enabled = bool(getattr(g_config, "loginCaptchaEnabled", False))
    except Exception:
        default_enabled = False
    try:
        return bool(get_bool("loginCaptchaEnabled", default=default_enabled))
    except Exception:
        return default_enabled


def _generate_captcha_code(length: int = 4) -> str:
    """生成`captcha`编码。"""
    digits = "0123456789"
    length = int(length or 4)
    if length < 1:
        length = 4
    if length > 8:
        length = 8
    return "".join(secrets.choice(digits) for _ in range(length))


def _build_captcha_svg(code: str, *, width: int = 90, height: int = 34) -> str:
    """构建`captcha``svg`。"""
    safe = str(code or "").strip()
    if not safe:
        safe = "0000"
    # Keep it dependency-free (no Pillow). SVG is a valid <img> source.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" viewBox="0 0 {int(width)} {int(height)}">
  <rect x="0" y="0" width="{int(width)}" height="{int(height)}" rx="4" ry="4" fill="#f8fafc" stroke="#cbd5e1" />
  <text x="50%" y="58%" text-anchor="middle" dominant-baseline="middle"
        font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace"
        font-size="18" font-weight="700" letter-spacing="2" fill="#0f172a">{safe}</text>
</svg>
"""


def _normalize_login_identifier(raw) -> str:
    """执行归一化登录`identifier`。"""
    try:
        s = str(raw or "")
    except Exception:
        s = ""
    try:
        s = unicodedata.normalize("NFKC", s)
    except Exception:
        s = str(s or "")
    s = s.strip()
    if not s:
        return ""
    # LoginLockout.username max_length=150
    return s[:150]


def _build_login_lockout_key(raw_identifier, *, user=None) -> str:
    """构建登录锁定键。
    
    Build a canonical lockout key to reduce alias/case bypass:
        - known local user => user:<id>
        - email input      => email:<lower>
        - username input   => name:<lower>
    """
    try:
        user_id = int(getattr(user, "id", 0) or 0)
    except Exception:
        user_id = 0
    if user_id > 0:
        return f"user:{user_id}"[:150]

    ident = _normalize_login_identifier(raw_identifier)
    if not ident:
        return ""
    if validate_email(ident):
        return f"email:{ident.lower()}"[:150]
    return f"name:{ident.lower()}"[:150]


def _resolve_local_user_for_lockout(raw_identifier):
    """解析并返回`local`用户`for`锁定。
    
    Best-effort local user resolve for lockout key canonicalization.
        Uses case-insensitive fallback to reduce case-variant bypass.
    """
    ident = _normalize_login_identifier(raw_identifier)
    if not ident:
        return None
    try:
        if validate_email(ident):
            return User.objects.filter(email__iexact=ident).first()
        user = User.objects.filter(username=ident).first()
        if user:
            return user
        return User.objects.filter(username__iexact=ident).first()
    except Exception:
        return None


def _login_lockout_trust_xff() -> bool:
    """处理登录锁定`trust``xff`。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _login_lockout_xff_max_hops() -> int:
    """处理登录锁定`xff`最大值`hops`。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS", "") or "").strip()
    if not raw:
        return 8
    try:
        value = int(raw)
    except Exception:
        value = 8
    if value < 1:
        value = 1
    if value > 64:
        value = 64
    return int(value)


def _login_lockout_forwarded_max_hops() -> int:
    """处理登录锁定`forwarded`最大值`hops`。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_FORWARDED_MAX_HOPS", "") or "").strip()
    if not raw:
        return 8
    try:
        value = int(raw)
    except Exception:
        value = 8
    if value < 1:
        value = 1
    if value > 64:
        value = 64
    return int(value)


def _login_lockout_trust_forwarded() -> bool:
    """处理登录锁定`trust``forwarded`。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_TRUST_FORWARDED", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _login_lockout_trust_x_real_ip() -> bool:
    """处理登录锁定`trust``x``real`IP。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _login_lockout_clear_all_ips_on_success() -> bool:
    """处理登录锁定清理全部`ips``on`成功状态。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_CLEAR_ALL_IPS_ON_SUCCESS", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _login_lockout_retention_seconds() -> int:
    """返回登录锁定`retention`秒数。"""
    raw = str(os.environ.get("BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS", "") or "").strip()
    if not raw:
        return 30 * 24 * 3600
    try:
        value = int(raw)
    except Exception:
        value = 30 * 24 * 3600
    if value < 3600:
        value = 3600
    if value > 365 * 24 * 3600:
        value = 365 * 24 * 3600
    return int(value)


def _cleanup_stale_login_lockout_rows(*, lockout_key: str, source_ip: str, now_ts):
    """清理`stale`登录锁定记录。
    
    Best-effort GC for stale lockout rows to keep table size bounded.
    """
    if not lockout_key or not source_ip or now_ts is None:
        return
    from django.db.models import Q
    from app.models import LoginLockout

    try:
        cutoff = now_ts - timedelta(seconds=_login_lockout_retention_seconds())
        (
            LoginLockout.objects.filter(username=str(lockout_key), source_ip=str(source_ip))
            .filter(Q(locked_until__isnull=True) | Q(locked_until__lte=now_ts))
            .filter(last_failure_at__lt=cutoff)
            .delete()
        )
    except Exception:
        logger.debug("login lockout cleanup failed key=%s ip=%s", lockout_key, source_ip, exc_info=True)


def _strip_wrapping_quotes(raw_value) -> str:
    """处理`strip``wrapping``quotes`。"""
    value = _proxy_header_text(raw_value)
    while len(value) >= 2 and (
        (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))
    ):
        value = value[1:-1].strip()
        if not value:
            return ""
    return value


def _proxy_header_text(raw_value, *, strip: bool = True) -> str:
    """处理代理请求头文本。"""
    try:
        value = str(raw_value or "")
    except Exception:
        return ""
    return value.strip() if strip else value


def _proxy_ip_without_bracketed_port(value: str) -> str:
    """返回代理IP`without``bracketed`端口。"""
    if not value.startswith("["):
        return value
    end = value.find("]")
    if end <= 1:
        return value
    return value[1:end].strip()


def _proxy_ip_without_ipv4_port(value: str) -> str:
    """返回代理IP`without``ipv4`端口。"""
    if value.count(":") != 1 or "." not in value:
        return value
    host, port = value.rsplit(":", 1)
    if host and port.isdigit():
        return host.strip()
    return value


def _proxy_ip_without_zone_id(value: str) -> str:
    """返回代理IP`without``zone`ID。"""
    if "%" in value and ":" in value:
        return value.split("%", 1)[0].strip()
    return value


def _normalize_proxy_ip_candidate(raw_value) -> str:
    """执行归一化代理IP`candidate`。"""
    value = _proxy_header_text(raw_value).replace("\r", "").replace("\n", "")
    if not value or len(value) > 256:
        return ""
    value = _strip_wrapping_quotes(value)
    if not value:
        return ""
    value = _proxy_ip_without_bracketed_port(value)
    value = _proxy_ip_without_ipv4_port(value)
    return _proxy_ip_without_zone_id(value)


def _valid_proxy_ip_or_empty(raw_value) -> str:
    """处理`valid`代理IP`or`空。"""
    value = _normalize_proxy_ip_candidate(raw_value)
    if not value:
        return ""
    try:
        return str(ipaddress.ip_address(value))
    except Exception:
        return ""


def _append_proxy_header_part(parts: list, token: list) -> list:
    """追加代理请求头`part`。"""
    part = "".join(token).strip()
    if part:
        parts.append(part)
    return []


def _consume_quoted_proxy_header_char(ch: str, token: list, quote: str, escaped: bool):
    """处理`consume`带引号代理请求头`char`。"""
    token.append(ch)
    if escaped:
        return quote, False
    if ch == "\\":
        return quote, True
    if ch == quote:
        return "", False
    return quote, False


def _consume_unquoted_proxy_header_char(ch: str, token: list, parts: list):
    """处理`consume``unquoted`代理请求头`char`。"""
    if ch in ('"', "'"):
        token.append(ch)
        return ch, False, token
    if ch == ",":
        return "", False, _append_proxy_header_part(parts, token)
    token.append(ch)
    return "", False, token


def _split_proxy_header_list(raw_value) -> list:
    """拆分代理请求头列表。"""
    value = _proxy_header_text(raw_value, strip=False)
    if not value:
        return []

    parts = []
    token = []
    quote = ""
    escaped = False
    for ch in value:
        if quote:
            quote, escaped = _consume_quoted_proxy_header_char(ch, token, quote, escaped)
            continue
        quote, escaped, token = _consume_unquoted_proxy_header_char(ch, token, parts)

    _append_proxy_header_part(parts, token)
    return parts


def _truncated_valid_proxy_ip(raw_value) -> str:
    """处理`truncated``valid`代理IP。"""
    valid_ip = _valid_proxy_ip_or_empty(raw_value)
    if not valid_ip:
        return ""
    return valid_ip[:64]


def _forwarded_for_field_ip(field) -> str:
    """获取`field`IP的`forwarded`。"""
    kv = _proxy_header_text(field)
    if not kv or "=" not in kv:
        return ""
    key, value = kv.split("=", 1)
    if _proxy_header_text(key).lower() != "for":
        return ""
    return _truncated_valid_proxy_ip(value)


def _forwarded_for_ip(raw_forwarded: str, *, max_hops: int) -> str:
    """获取IP的`forwarded`。"""
    for idx, hop in enumerate(_split_proxy_header_list(raw_forwarded)):
        if idx >= max_hops:
            break
        for field in str(hop or "").split(";"):
            valid_for = _forwarded_for_field_ip(field)
            if valid_for:
                return valid_for
    return ""


def _xff_ip(raw_xff: str, *, max_hops: int) -> str:
    """处理`xff`IP。"""
    for idx, token in enumerate(_split_proxy_header_list(raw_xff)):
        if idx >= max_hops:
            break
        valid_ip = _valid_proxy_ip_or_empty(token)
        if valid_ip:
            return valid_ip[:64]
    return ""


def _request_meta_or_empty(request) -> dict:
    """处理请求元数据`or`空。"""
    try:
        return getattr(request, "META", {}) or {}
    except Exception:
        return {}


def _x_real_ip_source(meta: dict) -> str:
    """处理`x``real`IP来源。"""
    if not _login_lockout_trust_x_real_ip():
        return ""
    return _truncated_valid_proxy_ip(meta.get("HTTP_X_REAL_IP", ""))


def _forwarded_source_ip(meta: dict) -> str:
    """处理`forwarded`来源IP。"""
    if not _login_lockout_trust_forwarded():
        return ""
    raw_fwd = _proxy_header_text(meta.get("HTTP_FORWARDED", ""))
    if not raw_fwd:
        return ""
    return _forwarded_for_ip(raw_fwd, max_hops=_login_lockout_forwarded_max_hops())


def _xff_source_ip(meta: dict) -> str:
    """处理`xff`来源IP。"""
    if not _login_lockout_trust_xff():
        return ""
    raw_xff = _proxy_header_text(meta.get("HTTP_X_FORWARDED_FOR", ""))
    if not raw_xff:
        return ""
    return _xff_ip(raw_xff, max_hops=_login_lockout_xff_max_hops())


def _first_nonempty_value(*values) -> str:
    """返回首个非空值。"""
    for value in values:
        if value:
            return value
    return ""


def _get_login_lockout_source_ip(request) -> str:
    """获取登录锁定来源IP。
    
    Source IP used by login lockout policy.
    
        Default: REMOTE_ADDR
        Optional (proxy deployments): first X-Forwarded-For when explicitly enabled.
    """
    meta = _request_meta_or_empty(request)
    source_ip = _first_nonempty_value(
        _x_real_ip_source(meta),
        _forwarded_source_ip(meta),
        _xff_source_ip(meta),
    )
    if source_ip:
        return source_ip

    valid_remote = _truncated_valid_proxy_ip(meta.get("REMOTE_ADDR", ""))
    if valid_remote:
        return valid_remote
    return _proxy_header_text(meta.get("REMOTE_ADDR", ""))[:64]


def _write_login_security_audit_event(
    request,
    *,
    event_type: str,
    username: str = "",
    error_message: str = "",
    detail_extra: dict | None = None,
):
    """写入登录`security`审计事件。"""
    from app.models import OpsAuditLog

    try:
        detail = {
            "path": "login",
            "method": str(getattr(request, "method", "") or "").upper(),
            "status_code": 200,
            "username": _normalize_login_identifier(username),
        }
        if isinstance(detail_extra, dict):
            detail.update(detail_extra)

        OpsAuditLog.objects.create(
            event_type=str(event_type or "").strip()[:50],
            ok=False,
            operator=str(_normalize_login_identifier(username) or "").strip()[:100],
            source_ip=_get_login_lockout_source_ip(request),
            error_message=str(error_message or "")[:1000],
            detail_json=json.dumps(detail, ensure_ascii=False),
        )
    except Exception:
        logger.debug("login audit failure event write failed username=%s", username, exc_info=True)


def web_get_verify_code(request):
    """处理 Web `get``Verify`编码 页面。
    
    GET /getVerifyCode?action=login
        Returns an image captcha and stores the code in session.
    """
    action = str(request.GET.get("action") or "login").strip().lower() or "login"
    code = _generate_captcha_code(4)
    try:
        request.session[f"{_VERIFY_CODE_SESSION_KEY_PREFIX}{action}"] = str(code).strip().lower()
        request.session.modified = True
    except Exception:
        logger.debug("captcha session write failed action=%s", action, exc_info=True)

    svg = _build_captcha_svg(code)
    resp = HttpResponse(svg, content_type="image/svg+xml")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    return resp
web_getVerifyCode = web_get_verify_code  # pragma: no cover - compatibility alias


def _is_multisite_open_alarm(alarm) -> bool:
    """判断多站点开放告警。"""
    status = str(getattr(alarm, "workflow_status", "") or "new").strip().lower() or "new"
    return status not in ("closed", "false_positive")


def _multisite_init_site_map(streams):
    """处理多站点`init``site``map`。"""
    site_map = {}
    code_to_site = {}
    for stream in streams:
        site_name = str(getattr(stream, "app", "") or "").strip() or "default"
        entry = site_map.setdefault(
            site_name,
            {
                "name": site_name,
                "stream_count": 0,
                "alarm_count": 0,
                "open_alarm_count": 0,
                "closed_alarm_count": 0,
                "recent_events": [],
            },
        )
        entry["stream_count"] += 1
        stream_code = str(getattr(stream, "code", "") or "").strip()
        if stream_code:
            code_to_site[stream_code] = site_name
    return site_map, code_to_site


def _multisite_add_alarm_event(entry, alarm) -> None:
    """处理多站点新增告警事件。"""
    entry["alarm_count"] += 1
    if _is_multisite_open_alarm(alarm):
        entry["open_alarm_count"] += 1
    else:
        entry["closed_alarm_count"] += 1

    if len(entry["recent_events"]) >= 3:
        return
    entry["recent_events"].append(
        {
            "id": int(alarm.id),
            "desc": str(getattr(alarm, "desc", "") or "").strip() or "未命名事件",
            "workflow_status": str(getattr(alarm, "workflow_status", "") or "new"),
            "detail_url": f"/alarm/detail?id={alarm.id}",
        }
    )


def _multisite_apply_alarm_stats(site_map, code_to_site) -> None:
    """处理多站点应用告警`stats`。"""
    if not code_to_site:
        return
    from app.models import Alarm

    for alarm in Alarm.objects.filter(stream_code__in=list(code_to_site.keys())).order_by("-id"):
        stream_code = str(getattr(alarm, "stream_code", "") or "").strip()
        site_name = code_to_site.get(stream_code)
        if not site_name:
            continue
        _multisite_add_alarm_event(site_map[site_name], alarm)


def _multisite_workflow_meta(raw_status: str) -> dict:
    """处理多站点`workflow`元数据。"""
    status = str(raw_status or "new").strip().lower() or "new"
    mapping = {
        "new": {"label": "待处置", "tone": "critical"},
        "acknowledged": {"label": "处理中", "tone": "warning"},
        "reviewing": {"label": "复核中", "tone": "accent"},
        "closed": {"label": "已闭环", "tone": "stable"},
        "resolved": {"label": "已解决", "tone": "stable"},
    }
    if status in mapping:
        return mapping[status]
    return {"label": status.replace("_", " ").title(), "tone": "muted"}


def _multisite_finalize_site_entry(entry: dict) -> dict:
    """处理多站点完成`site`条目。"""
    stream_count = int(entry.get("stream_count") or 0)
    alarm_count = int(entry.get("alarm_count") or 0)
    open_alarm_count = int(entry.get("open_alarm_count") or 0)
    closed_alarm_count = int(entry.get("closed_alarm_count") or 0)
    recent_events = list(entry.get("recent_events") or [])

    closure_rate = int(round((closed_alarm_count * 100.0) / alarm_count)) if alarm_count > 0 else 100
    incident_density = int(round((open_alarm_count * 100.0) / stream_count)) if stream_count > 0 else 0

    if open_alarm_count > 0:
        status_tone = "critical" if open_alarm_count >= 2 else "warning"
        status_label = f"{open_alarm_count} 起待处置"
        status_note = "优先关注"
    elif alarm_count > 0:
        status_tone = "stable"
        status_label = "已闭环"
        status_note = f"{closed_alarm_count} 起已完成"
    else:
        status_tone = "muted"
        status_label = "无异常"
        status_note = "当前稳定"

    entry["closure_rate"] = closure_rate
    entry["incident_density"] = incident_density
    entry["status_tone"] = status_tone
    entry["status_label"] = status_label
    entry["status_note"] = status_note
    entry["recent_events"] = [
        {
            **item,
            "workflow_label": _multisite_workflow_meta(item.get("workflow_status")).get("label", "事件更新"),
        }
        for item in recent_events
    ]
    return entry


def _multisite_build_priority_events(site_cards) -> list:
    """处理多站点构建`priority``events`。"""
    priority_events = []
    for site in site_cards:
        site_name = str(site.get("name") or "").strip() or "default"
        for item in site.get("recent_events") or []:
            workflow_meta = _multisite_workflow_meta(item.get("workflow_status"))
            priority_events.append(
                {
                    "id": int(item.get("id") or 0),
                    "site_name": site_name,
                    "desc": str(item.get("desc") or "").strip() or "未命名事件",
                    "detail_url": item.get("detail_url") or "#",
                    "workflow_label": workflow_meta["label"],
                    "workflow_tone": workflow_meta["tone"],
                }
            )
    priority_events.sort(key=lambda item: (-int(item.get("id") or 0), str(item.get("site_name") or "")))
    return priority_events[:8]


def _multisite_build_dashboard_totals(site_cards) -> dict:
    """处理多站点构建`dashboard``totals`。"""
    site_count = len(site_cards)
    stream_count = sum(int(item.get("stream_count") or 0) for item in site_cards)
    alarm_count = sum(int(item.get("alarm_count") or 0) for item in site_cards)
    open_alarm_count = sum(int(item.get("open_alarm_count") or 0) for item in site_cards)
    closed_alarm_count = sum(int(item.get("closed_alarm_count") or 0) for item in site_cards)
    healthy_site_count = sum(1 for item in site_cards if int(item.get("open_alarm_count") or 0) == 0)
    at_risk_site_count = max(0, site_count - healthy_site_count)
    closure_rate = int(round((closed_alarm_count * 100.0) / alarm_count)) if alarm_count > 0 else 100
    return {
        "site_count": site_count,
        "stream_count": stream_count,
        "alarm_count": alarm_count,
        "open_alarm_count": open_alarm_count,
        "closed_alarm_count": closed_alarm_count,
        "healthy_site_count": healthy_site_count,
        "at_risk_site_count": at_risk_site_count,
        "closure_rate": closure_rate,
    }


def _build_multisite_overview_context():
    """构建多站点`overview``context`。"""
    from app.models import Stream

    streams = list(Stream.objects.all().order_by("app", "sort", "id"))
    site_map, code_to_site = _multisite_init_site_map(streams)
    _multisite_apply_alarm_stats(site_map, code_to_site)

    site_cards = [_multisite_finalize_site_entry(site_map[name]) for name in sorted(site_map.keys())]
    top_unhealthy_sites = sorted(
        site_cards,
        key=lambda item: (-int(item.get("open_alarm_count") or 0), -int(item.get("alarm_count") or 0), str(item.get("name") or "")),
    )[:5]
    return {
        "site_cards": site_cards,
        "top_unhealthy_sites": top_unhealthy_sites,
        "priority_events": _multisite_build_priority_events(site_cards),
        "dashboard_totals": _multisite_build_dashboard_totals(site_cards),
        "has_sites": bool(site_cards),
    }


def web_index(request):
    """渲染 Web 首页。"""
    context = {}
    context.update(_build_multisite_overview_context())

    return render(request, 'app/web_index.html', context)

def web_oidc_start(request):
    """处理 Web OIDC起始 页面。
    
    GET /login/oidc/start
        Redirect to the configured OIDC authorization endpoint.
    """
    if not bool(getattr(OidcAuth, "is_enabled")()):
        return redirect(PATH_LOGIN)

    raw_provider_id = str(request.GET.get("provider") or "").strip()
    provider_id = _sanitize_oidc_provider_id(raw_provider_id)
    if raw_provider_id and (not provider_id):
        return HttpResponse("oidc provider invalid", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    if not provider_id:
        try:
            provider_id = _sanitize_oidc_provider_id(getattr(OidcAuth, "get_default_provider_id")() or "")
        except Exception:
            provider_id = ""

    state = gen_random_code_s("oidc_state_")
    nonce = gen_random_code_s("oidc_nonce_")
    request.session[_OIDC_STATE_SESSION_KEY] = state
    request.session[_OIDC_NONCE_SESSION_KEY] = nonce
    request.session[_OIDC_PROVIDER_SESSION_KEY] = provider_id
    request.session.modified = True

    redirect_uri = request.build_absolute_uri(_web_oidc_callback_path(provider_id))
    url = getattr(OidcAuth, "build_authorize_url")(redirect_uri=redirect_uri, state=state, nonce=nonce, provider_id=provider_id)
    if not str(url or "").strip():
        return HttpResponse("oidc config missing", status=500, content_type=CONTENT_TYPE_TEXT_PLAIN)
    return redirect(url)


def _web_oidc_session_string(request, key: str) -> str:
    """处理 Web OIDC会话字符串 页面。"""
    try:
        return str(request.session.get(key) or "").strip()
    except Exception:
        return ""


def _web_oidc_pop_session_key(request, key: str) -> None:
    """处理 Web OIDC`pop`会话键 页面。"""
    try:
        del request.session[key]
    except Exception:
        logger.debug("OIDC session key pop failed key=%s", key, exc_info=True)


def _web_oidc_callback_initial_response(raw_provider_id: str, provider_id: str, error: str):
    """处理 Web OIDC回调`initial`响应 页面。"""
    if raw_provider_id and (not provider_id):
        return HttpResponse("oidc provider invalid", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    if not error:
        return None
    safe_error = _sanitize_oidc_error(error)
    if safe_error:
        return HttpResponse(f"oidc error: {safe_error}", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    return HttpResponse("oidc error", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)


def _web_oidc_callback_provider_id(request, provider_id: str):
    """处理 Web OIDC回调提供方ID 页面。"""
    expected_provider = _sanitize_oidc_provider_id(_web_oidc_session_string(request, _OIDC_PROVIDER_SESSION_KEY))
    if expected_provider and provider_id and provider_id != expected_provider:
        return "", HttpResponse("oidc provider mismatch", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    if provider_id:
        return provider_id, None
    if expected_provider:
        return expected_provider, None
    try:
        provider_id = _sanitize_oidc_provider_id(getattr(OidcAuth, "get_default_provider_id")() or "")
    except Exception:
        provider_id = ""
    return provider_id, None


def _web_oidc_callback_validate_state(request, state: str):
    """处理 Web OIDC回调`validate`状态 页面。"""
    expected = _web_oidc_session_string(request, _OIDC_STATE_SESSION_KEY)
    if not expected or not state or state != expected:
        return HttpResponse("oidc state mismatch", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    _web_oidc_pop_session_key(request, _OIDC_STATE_SESSION_KEY)
    _web_oidc_pop_session_key(request, _OIDC_PROVIDER_SESSION_KEY)
    return None


def _web_oidc_callback_path(provider_id: str) -> str:
    """处理 Web OIDC回调路径 页面。"""
    callback_path = "/login/oidc/callback"
    if not provider_id:
        return callback_path
    return f"{callback_path}?provider={urllib.parse.quote(provider_id)}"


def _web_oidc_token_exchange_failed_response(token_data):
    """处理 Web OIDC令牌`exchange``failed`响应 页面。"""
    reason = ""
    if isinstance(token_data, dict):
        reason = str(token_data.get("reason") or "")
    return HttpResponse(f"oidc token exchange failed: {reason}", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)


def _web_oidc_exchange_code(request, code: str, provider_id: str):
    """处理 Web OIDC`exchange`编码 页面。"""
    redirect_uri = request.build_absolute_uri(_web_oidc_callback_path(provider_id))
    ok, token_data = getattr(OidcAuth, "exchange_code")(code=code, redirect_uri=redirect_uri, provider_id=provider_id)
    if not ok:
        return {}, _web_oidc_token_exchange_failed_response(token_data)
    return token_data if isinstance(token_data, dict) else {}, None


def _web_oidc_invalid_id_token_response(verified):
    """处理 Web OIDC无效ID令牌响应 页面。"""
    reason = ""
    if isinstance(verified, dict):
        reason = str(verified.get("reason") or "")
    return HttpResponse(f"oidc invalid id_token: {reason}", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)


def _web_oidc_claims_from_id_token(id_token: str, *, expected_nonce: str, provider_id: str):
    """处理 Web OIDC`claims``from`ID令牌 页面。"""
    if not id_token:
        return {}, None
    ok, verified = getattr(OidcAuth, "verify_and_parse_id_token")(id_token, expected_nonce=expected_nonce, provider_id=provider_id)
    if not ok:
        return {}, _web_oidc_invalid_id_token_response(verified)
    return verified if isinstance(verified, dict) else {}, None


def _web_oidc_has_claim_value(value) -> bool:
    """处理 Web OIDC`has`声明值 页面。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(str(value).strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _web_oidc_merge_claims(claims, userinfo, *, prefer_userinfo: bool):
    """处理 Web OIDC`merge``claims` 页面。"""
    primary = dict(claims or {}) if prefer_userinfo else dict(userinfo or {})
    secondary = dict(userinfo or {}) if prefer_userinfo else dict(claims or {})
    merged = dict(primary)
    for key, value in secondary.items():
        if _web_oidc_has_claim_value(value):
            merged[key] = value
    return merged


def _web_oidc_enrich_claims_with_userinfo(claims, *, access_token: str, provider_id: str):
    """处理 Web OIDC`enrich``claims``with`userinfo 页面。"""
    try:
        userinfo_enabled = bool(getattr(OidcAuth, "is_userinfo_enabled_for_provider")(provider_id))
    except Exception:
        userinfo_enabled = False
    if not (userinfo_enabled and access_token):
        return claims
    ok_ui, ui = getattr(OidcAuth, "fetch_userinfo")(access_token=access_token, provider_id=provider_id)
    if not (ok_ui and isinstance(ui, dict)):
        return claims
    try:
        prefer_userinfo = bool(getattr(OidcAuth, "is_userinfo_preferred_for_provider")(provider_id))
    except Exception:
        prefer_userinfo = True
    return _web_oidc_merge_claims(claims, ui, prefer_userinfo=prefer_userinfo)


def _web_oidc_claims_from_tokens(request, *, id_token: str, access_token: str, provider_id: str):
    """处理 Web OIDC`claims``from``tokens` 页面。"""
    expected_nonce = _web_oidc_session_string(request, _OIDC_NONCE_SESSION_KEY)
    _web_oidc_pop_session_key(request, _OIDC_NONCE_SESSION_KEY)
    claims, response = _web_oidc_claims_from_id_token(id_token, expected_nonce=expected_nonce, provider_id=provider_id)
    if response is not None:
        return {}, response
    return _web_oidc_enrich_claims_with_userinfo(claims, access_token=access_token, provider_id=provider_id), None


def _web_oidc_user_info_from_claims(claims):
    """处理 Web OIDC用户信息`from``claims` 页面。"""
    user_info = getattr(OidcAuth, "extract_user_from_claims")(claims)
    username = str((user_info or {}).get("username") or "").strip()
    email = str((user_info or {}).get("email") or "").strip()
    sub = str((user_info or {}).get("sub") or "").strip()
    if not username:
        return {}, HttpResponse("oidc user missing username", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    if not sub:
        return {}, HttpResponse("oidc user missing sub", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)
    return {"username": username, "email": email, "sub": sub}, None


def _web_oidc_groups_from_claims(claims):
    """处理 Web OIDC`groups``from``claims` 页面。"""
    try:
        groups = getattr(OidcAuth, "extract_groups_from_claims")(claims)
        return groups if isinstance(groups, list) else []
    except Exception:
        return []


def _web_oidc_group_set(groups):
    """处理 Web OIDC分组`set` 页面。"""
    return {str(group or "").strip().lower() for group in (groups or []) if str(group or "").strip()}


def _web_oidc_required_groups_response(provider_id: str, groups):
    """处理 Web OIDC`required``groups`响应 页面。"""
    try:
        required_groups = set(getattr(OidcAuth, "get_required_groups")(provider_id))
    except Exception:
        required_groups = set()
    if not required_groups:
        return None
    if _web_oidc_group_set(groups) & required_groups:
        return None
    return HttpResponse("oidc required group missing", status=403, content_type=CONTENT_TYPE_TEXT_PLAIN)


def _web_oidc_effective_provider_id(provider_id: str) -> str:
    """处理 Web OIDC`effective`提供方ID 页面。"""
    return str(provider_id or "").strip() or "default"


def _web_oidc_account_link_mode(provider_id: str) -> str:
    """处理 Web OIDC`account``link`模式 页面。"""
    try:
        link_mode = str(getattr(OidcAuth, "get_account_link_mode")(provider_id) or "auto").strip().lower()
    except Exception:
        link_mode = "auto"
    if link_mode not in ("auto", "username", "email", "create", "deny"):
        return "auto"
    return link_mode


def _web_oidc_identity_record(effective_provider_id: str, sub: str):
    """处理 Web OIDC`identity``record` 页面。"""
    from app.models import UserOidcIdentity

    try:
        return UserOidcIdentity.objects.select_related("user").filter(
            provider_id=effective_provider_id,
            subject=sub,
        ).first()
    except Exception:
        return None


def _web_oidc_find_linked_user(*, username: str, email: str, link_mode: str):
    """处理 Web OIDC`find``linked`用户 页面。"""
    if link_mode in ("auto", "username") and username:
        user = User.objects.filter(username=username).first()
        if user:
            return user
        user = User.objects.filter(username__iexact=username).first()
        if user:
            return user
    if link_mode in ("auto", "email") and email:
        return User.objects.filter(email__iexact=email).first()
    return None


def _web_oidc_make_unique_username(base: str, *, sub: str, suffix_hint: str = "") -> str:
    """处理 Web OIDC生成去重后`username` 页面。"""
    raw_base = _normalize_login_identifier(base)
    if raw_base:
        raw_base = re.sub(r"[^A-Za-z0-9_.@+-]", "_", raw_base)
        raw_base = re.sub(r"_+", "_", raw_base).strip("_")
    if not raw_base:
        raw_base = f"oidc_{sub[:12]}"
    max_len = 150
    raw_base = raw_base[:max_len]
    if not User.objects.filter(username=raw_base).exists():
        return raw_base
    suffix_hint = str(suffix_hint or "").strip()
    candidate_base = raw_base
    if suffix_hint:
        trimmed = candidate_base[: max_len - (len(suffix_hint) + 1)]
        candidate = f"{trimmed}_{suffix_hint}"
        if not User.objects.filter(username=candidate).exists():
            return candidate
        candidate_base = candidate
    for index in range(2, 1000):
        suffix = str(index)
        trimmed = candidate_base[: max_len - (len(suffix) + 1)]
        candidate = f"{trimmed}_{suffix}"
        if not User.objects.filter(username=candidate).exists():
            return candidate
    rnd = gen_random_code_s("u_")[-8:]
    trimmed = candidate_base[: max_len - (len(rnd) + 1)]
    return f"{trimmed}_{rnd}"


def _web_oidc_create_user(*, username: str, email: str, sub: str, link_mode: str, effective_provider_id: str):
    """处理 Web OIDC`create`用户 页面。"""
    local_username = _web_oidc_make_unique_username(
        username,
        sub=sub,
        suffix_hint=effective_provider_id if link_mode == "create" else "",
    )
    return User.objects.create_user(
        username=local_username,
        password=gen_random_code_s("oidc_pw_"),
        email=email,
    )


def _web_oidc_resolve_user(*, provider_id: str, username: str, email: str, sub: str):
    """处理 Web OIDC`resolve`用户 页面。"""
    effective_provider_id = _web_oidc_effective_provider_id(provider_id)
    link_mode = _web_oidc_account_link_mode(provider_id)
    identity = _web_oidc_identity_record(effective_provider_id, sub)
    user = getattr(identity, "user", None) if identity else None
    if not user:
        if link_mode == "deny":
            return None, effective_provider_id, identity, HttpResponse("oidc user not provisioned", status=403, content_type=CONTENT_TYPE_TEXT_PLAIN)
        user = _web_oidc_find_linked_user(username=username, email=email, link_mode=link_mode)
    if not user:
        user = _web_oidc_create_user(
            username=username,
            email=email,
            sub=sub,
            link_mode=link_mode,
            effective_provider_id=effective_provider_id,
        )
    return user, effective_provider_id, identity, None


def _web_oidc_ensure_identity(identity, *, user, effective_provider_id: str, sub: str, email: str):
    """处理 Web OIDC`ensure``identity` 页面。"""
    if identity:
        return identity
    from app.models import UserOidcIdentity

    try:
        return UserOidcIdentity.objects.create(
            user=user,
            provider_id=effective_provider_id,
            subject=sub,
            email=email,
        )
    except Exception:
        return identity


def _web_oidc_sync_user_email(user, email: str) -> None:
    """处理 Web OIDC`sync`用户邮箱 页面。"""
    if not email:
        return
    current = str(getattr(user, "email", "") or "").strip().lower()
    if current == str(email).lower():
        return
    try:
        user.email = email
        user.save(update_fields=["email"])
    except Exception:
        logger.debug("OIDC user email sync failed user_id=%s", getattr(user, "id", None), exc_info=True)


def _web_oidc_role_targets(provider_id: str, groups):
    """处理 Web OIDC`role`目标 页面。"""
    try:
        staff_groups = set(getattr(OidcAuth, "get_staff_groups")(provider_id))
    except Exception:
        staff_groups = set()
    try:
        superuser_groups = set(getattr(OidcAuth, "get_superuser_groups")(provider_id))
    except Exception:
        superuser_groups = set()
    if not (staff_groups or superuser_groups):
        return None
    group_set = _web_oidc_group_set(groups)
    desired_superuser = bool(group_set & superuser_groups) if superuser_groups else False
    desired_staff = bool(group_set & staff_groups) if staff_groups else False
    return bool(desired_staff or desired_superuser), bool(desired_superuser)


def _web_oidc_sync_flags_enabled(provider_id: str) -> bool:
    """处理 Web OIDC`sync`标记集合启用 页面。"""
    try:
        return bool(getattr(OidcAuth, "sync_user_flags_enabled")(provider_id))
    except Exception:
        return True


def _web_oidc_changed_user_flags(user, *, desired_staff: bool, desired_superuser: bool, sync_flags: bool):
    """处理 Web OIDC`changed`用户标记集合 页面。"""
    changed_fields = []
    if sync_flags:
        if bool(getattr(user, "is_superuser", False)) != bool(desired_superuser):
            user.is_superuser = bool(desired_superuser)
            changed_fields.append("is_superuser")
        if bool(getattr(user, "is_staff", False)) != bool(desired_staff):
            user.is_staff = bool(desired_staff)
            changed_fields.append("is_staff")
        return changed_fields
    if desired_superuser and (not bool(getattr(user, "is_superuser", False))):
        user.is_superuser = True
        changed_fields.append("is_superuser")
    if desired_staff and (not bool(getattr(user, "is_staff", False))):
        user.is_staff = True
        changed_fields.append("is_staff")
    if bool(getattr(user, "is_superuser", False)) and (not bool(getattr(user, "is_staff", False))):
        user.is_staff = True
        changed_fields.append("is_staff")
    return changed_fields


def _web_oidc_apply_group_flags(user, *, groups, provider_id: str) -> None:
    """处理 Web OIDC应用分组标记集合 页面。"""
    role_targets = _web_oidc_role_targets(provider_id, groups)
    if not role_targets:
        return
    desired_staff, desired_superuser = role_targets
    changed_fields = _web_oidc_changed_user_flags(
        user,
        desired_staff=desired_staff,
        desired_superuser=desired_superuser,
        sync_flags=_web_oidc_sync_flags_enabled(provider_id),
    )
    if not changed_fields:
        return
    try:
        user.save(update_fields=list(set(changed_fields)))
    except Exception:
        user.save()


def _web_oidc_allowed_permission_keys():
    """处理 Web OIDC`allowed`权限键列表 页面。"""
    return set(PERMISSION_KEYS or [])


def _web_oidc_filtered_permissions(derived_perms):
    """处理 Web OIDC`filtered``permissions` 页面。"""
    if not derived_perms:
        return {}
    allowed_keys = _web_oidc_allowed_permission_keys()
    if not allowed_keys:
        return {}
    canonical_by_lower = {str(key).lower(): str(key) for key in allowed_keys}
    return {
        canonical_by_lower.get(str(key).lower()): coerce_permission_bool(value)
        for key, value in (derived_perms or {}).items()
        if str(key).lower() in canonical_by_lower
    }


def _web_oidc_permissions_for_groups(groups, *, provider_id: str):
    """处理 Web OIDC`permissions``for``groups` 页面。"""
    try:
        derived_perms = getattr(OidcAuth, "build_permissions_from_groups")(groups, provider_id=provider_id)
        derived_perms = derived_perms if isinstance(derived_perms, dict) else {}
    except Exception:
        derived_perms = {}
    try:
        sync_perms = bool(getattr(OidcAuth, "sync_user_permissions_enabled")(provider_id))
    except Exception:
        sync_perms = False
    return _web_oidc_filtered_permissions(derived_perms), sync_perms


def _web_oidc_should_apply_permissions(derived_perms, sync_perms: bool) -> bool:
    """处理 Web OIDC`should`应用`permissions` 页面。"""
    return bool(derived_perms) or (sync_perms and isinstance(derived_perms, dict))


def _web_oidc_apply_permissions(user, *, groups, provider_id: str) -> None:
    """处理 Web OIDC应用`permissions` 页面。"""
    derived_perms, sync_perms = _web_oidc_permissions_for_groups(groups, provider_id=provider_id)
    if not _web_oidc_should_apply_permissions(derived_perms, sync_perms):
        return
    from app.models import UserPermission

    try:
        perm_obj = UserPermission.objects.filter(user=user).first()
        raw = str(getattr(perm_obj, "permissions_json", "") or "").strip() if perm_obj else ""
        if sync_perms or (not perm_obj) or (not raw):
            if not perm_obj:
                perm_obj = UserPermission(user=user)
            perm_obj.permissions_json = json.dumps(derived_perms, ensure_ascii=False)
            perm_obj.save()
    except Exception:
        logger.debug("OIDC user permission sync failed user_id=%s", getattr(user, "id", None), exc_info=True)


def _web_oidc_finalize_login(request, user, *, id_token: str = "", provider_id: str = ""):
    """处理 Web OIDC完成登录 页面。"""
    user.last_login = datetime.now()
    try:
        user.save(update_fields=["last_login"])
    except Exception:
        user.save()
    try:
        request.session.flush()
    except Exception:
        try:
            request.session.cycle_key()
        except Exception:
            logger.debug("OIDC session cycle fallback failed user_id=%s", getattr(user, "id", None), exc_info=True)
    request.session[g_session_key_user] = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if getattr(user, "last_login", None) else "",
    }
    if id_token:
        request.session[_OIDC_ID_TOKEN_SESSION_KEY] = id_token
    if provider_id:
        request.session[_OIDC_PROVIDER_SESSION_KEY] = provider_id
    request.session.modified = True
    return redirect("/")


def _web_oidc_callback_request_context(request):
    """处理 Web OIDC回调请求`context` 页面。"""
    code = str(request.GET.get("code") or "").strip()
    state = str(request.GET.get("state") or "").strip()
    error = str(request.GET.get("error") or "").strip()
    raw_provider_id = str(request.GET.get("provider") or "").strip()
    provider_id = _sanitize_oidc_provider_id(raw_provider_id)

    response = _web_oidc_callback_initial_response(raw_provider_id, provider_id, error)
    if response is not None:
        return {}, response

    provider_id, response = _web_oidc_callback_provider_id(request, provider_id)
    if response is not None:
        return {}, response

    response = _web_oidc_callback_validate_state(request, state)
    if response is not None:
        return {}, response
    if not code:
        return {}, HttpResponse("oidc code missing", status=400, content_type=CONTENT_TYPE_TEXT_PLAIN)

    return {"code": code, "provider_id": provider_id}, None


def _web_oidc_callback_token_context(request, *, code: str, provider_id: str):
    """处理 Web OIDC回调令牌`context` 页面。"""
    token_data, response = _web_oidc_exchange_code(request, code, provider_id)
    if response is not None:
        return {}, response

    id_token = str(token_data.get("id_token") or "").strip()
    access_token = str(token_data.get("access_token") or "").strip()
    claims, response = _web_oidc_claims_from_tokens(
        request,
        id_token=id_token,
        access_token=access_token,
        provider_id=provider_id,
    )
    if response is not None:
        return {}, response

    return {"id_token": id_token, "claims": claims}, None


def _web_oidc_callback_user_context(*, provider_id: str, claims):
    """处理 Web OIDC回调用户`context` 页面。"""
    user_info, response = _web_oidc_user_info_from_claims(claims)
    if response is not None:
        return {}, response

    groups = _web_oidc_groups_from_claims(claims)
    response = _web_oidc_required_groups_response(provider_id, groups)
    if response is not None:
        return {}, response

    user, effective_provider_id, identity, response = _web_oidc_resolve_user(
        provider_id=provider_id,
        username=user_info["username"],
        email=user_info["email"],
        sub=user_info["sub"],
    )
    if response is not None:
        return {}, response

    _web_oidc_ensure_identity(
        identity,
        user=user,
        effective_provider_id=effective_provider_id,
        sub=user_info["sub"],
        email=user_info["email"],
    )
    _web_oidc_sync_user_email(user, user_info["email"])
    if not bool(getattr(user, "is_active", True)):
        return {}, HttpResponse("account disabled", status=403, content_type=CONTENT_TYPE_TEXT_PLAIN)

    return {"user": user, "groups": groups}, None


def web_oidc_callback(request):
    """处理 Web OIDC回调 页面。
    
    GET /login/oidc/callback
        Exchange authorization code for tokens and log user in.
    """
    if not bool(getattr(OidcAuth, "is_enabled")()):
        return redirect(PATH_LOGIN)

    request_context, response = _web_oidc_callback_request_context(request)
    if response is not None:
        return response
    provider_id = request_context["provider_id"]

    token_context, response = _web_oidc_callback_token_context(
        request,
        code=request_context["code"],
        provider_id=provider_id,
    )
    if response is not None:
        return response
    id_token = token_context["id_token"]

    user_context, response = _web_oidc_callback_user_context(
        provider_id=provider_id,
        claims=token_context["claims"],
    )
    if response is not None:
        return response
    _web_oidc_apply_group_flags(user_context["user"], groups=user_context["groups"], provider_id=provider_id)
    _web_oidc_apply_permissions(user_context["user"], groups=user_context["groups"], provider_id=provider_id)
    return _web_oidc_finalize_login(request, user_context["user"], id_token=id_token, provider_id=provider_id)


def _web_profile_user_from_session(session_user):
    """处理 Web profile用户`from`会话 页面。"""
    try:
        return User.objects.get(id=session_user.get("id"))
    except User.DoesNotExist:
        return None


def _web_profile_totp_credential(user, *, enabled=None):
    """处理 Web profileTOTP`credential` 页面。"""
    if not user:
        return None
    filters = {"user": user}
    if enabled is not None:
        filters["enabled"] = bool(enabled)
    return UserTotpCredential.objects.filter(**filters).first()


def _web_profile_delete_recovery_codes(user) -> None:
    """处理 Web profile`delete``recovery`编码列表 页面。"""
    from app.models import UserTotpRecoveryCode

    try:
        UserTotpRecoveryCode.objects.filter(user=user).delete()
    except Exception:
        logger.debug("delete TOTP recovery codes failed user_id=%s", getattr(user, "id", None), exc_info=True)


def _web_profile_recovery_unused_count(user) -> int:
    """处理 Web profile`recovery``unused`统计 页面。"""
    from app.models import UserTotpRecoveryCode

    try:
        return int(UserTotpRecoveryCode.objects.filter(user=user, used_at__isnull=True).count()) if user else 0
    except Exception:
        return 0


def _web_profile_reauth_window_seconds() -> int:
    """处理 Web profile二次认证窗口秒数 页面。"""
    return _env_int_clamped(
        "BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS",
        300,
        min_value=30,
        max_value=3600,
    )


def _web_profile_mark_totp_reauthed(request) -> None:
    """处理 Web profile`mark`TOTP`reauthed` 页面。"""
    try:
        request.session["totp_reauth_until"] = int(time.time()) + int(_web_profile_reauth_window_seconds())
        request.session.modified = True
    except Exception:
        logger.debug("mark TOTP reauth session failed", exc_info=True)


def _web_profile_handle_totp_generate(*, user, context):
    """处理 Web profile`handle`TOTP`generate` 页面。"""
    cred = _web_profile_totp_credential(user)
    if not cred:
        cred = UserTotpCredential(user=user)
    cred.secret_base32 = Totp.generate_totp_secret()
    cred.enabled = False
    cred.save()
    _web_profile_delete_recovery_codes(user)
    context["top_msg"] = "TOTP 密钥已生成，请在认证器中添加后再输入验证码启用。"


def _web_profile_handle_totp_enable(*, user, params, context):
    """处理 Web profile`handle`TOTP`enable` 页面。"""
    totp_code = str(params.get("totp_code") or "").strip()
    cred = _web_profile_totp_credential(user)
    if not cred or not str(getattr(cred, "secret_base32", "") or "").strip():
        context["top_msg"] = "请先生成 TOTP 密钥"
        return
    if not Totp.verify_totp(str(getattr(cred, "secret_base32", "")), totp_code):
        context["top_msg"] = MSG_TOTP_INVALID
        return
    cred.enabled = True
    cred.save(update_fields=["enabled", "update_time"])
    context["top_msg"] = "TOTP 二次验证已启用"


def _web_profile_handle_totp_disable(*, user, params, context):
    """处理 Web profile`handle`TOTP`disable` 页面。"""
    totp_code = str(params.get("totp_code") or "").strip()
    cred = _web_profile_totp_credential(user)
    if not cred or not bool(getattr(cred, "enabled", False)):
        context["top_msg"] = "TOTP 未启用"
        return
    if not Totp.verify_totp(str(getattr(cred, "secret_base32", "")), totp_code):
        context["top_msg"] = MSG_TOTP_INVALID
        return
    cred.enabled = False
    cred.save(update_fields=["enabled", "update_time"])
    _web_profile_delete_recovery_codes(user)
    context["top_msg"] = "TOTP 二次验证已停用"


def _web_profile_handle_totp_recovery_generate(*, user, context):
    """处理 Web profile`handle`TOTP`recovery``generate` 页面。"""
    cred = _web_profile_totp_credential(user, enabled=True)
    if not cred:
        context["top_msg"] = "请先启用 TOTP"
        return
    try:
        codes = getattr(TotpRecovery, "replace_recovery_codes_for_user")(user, count=10)
    except Exception:
        codes = []
    if codes:
        context["totp_recovery_codes"] = codes
        context["top_msg"] = "恢复码已生成，请妥善保存（仅展示一次）。"
        return
    context["top_msg"] = "恢复码生成失败"


def _web_profile_handle_totp_reauth(*, request, user, params, context):
    """处理 Web profile`handle`TOTP二次认证 页面。"""
    totp_code = str(params.get("totp_code") or "").strip()
    cred = _web_profile_totp_credential(user, enabled=True)
    if not cred:
        context["top_msg"] = "请先启用 TOTP"
        return
    if not totp_code:
        context["top_msg"] = "TOTP 验证码不能为空"
        return
    if not Totp.verify_totp(str(getattr(cred, "secret_base32", "")), totp_code):
        context["top_msg"] = MSG_TOTP_INVALID
        return
    _web_profile_mark_totp_reauthed(request)
    context["top_msg"] = "敏感操作二次确认已通过"


def _web_profile_handle_save_profile(*, user, params, context):
    """处理 Web profile`handle``save`profile 页面。"""
    email = params.get("email")
    old_password = params.get("old_password")
    new_password = params.get("new_password")
    ok_pw, pw_msg = validate_password(new_password, user=user)
    if not ok_pw:
        context["top_msg"] = pw_msg
        return
    if len(str(new_password or "")) > 128:
        context["top_msg"] = "新密码长度过长"
        return
    if user and user.check_password(old_password):
        user.set_password(new_password)  # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password -- validated above
        user.email = email
        user.save()
        context["top_msg"] = "修改成功"
        return
    context["top_msg"] = "原密码验证失败"


def _web_profile_handle_post(request, session_user, context):
    """处理 Web profile`handle``post` 页面。"""
    params = f_parsePostParams(request)
    action = str(params.get("action") or "save_profile").strip()
    user = _web_profile_user_from_session(session_user)
    if not user:
        return redirect(PATH_LOGIN)
    if action == "totp_generate":
        _web_profile_handle_totp_generate(user=user, context=context)
    elif action == "totp_enable":
        _web_profile_handle_totp_enable(user=user, params=params, context=context)
    elif action == "totp_disable":
        _web_profile_handle_totp_disable(user=user, params=params, context=context)
    elif action == "totp_recovery_generate":
        _web_profile_handle_totp_recovery_generate(user=user, context=context)
    elif action == "totp_reauth":
        _web_profile_handle_totp_reauth(request=request, user=user, params=params, context=context)
    else:
        _web_profile_handle_save_profile(user=user, params=params, context=context)
    return None


def _web_profile_fill_context(context, session_user) -> None:
    """处理 Web profile`fill``context` 页面。"""
    context["user"] = session_user
    profile_user = _web_profile_user_from_session(session_user)
    totp_cred = _web_profile_totp_credential(profile_user)
    totp_secret = str(getattr(totp_cred, "secret_base32", "") or "").strip() if totp_cred else ""
    context["totp_enabled"] = bool(getattr(totp_cred, "enabled", False)) if totp_cred else False
    context["totp_secret"] = totp_secret
    context["totp_otpauth_uri"] = Totp.build_otpauth_uri(
        totp_secret,
        account_name=str(getattr(profile_user, "username", "") or ""),
        issuer=str(getattr(g_config, "title", "Beacon") or "Beacon"),
    ) if totp_secret and profile_user else ""
    context["totp_recovery_unused_count"] = _web_profile_recovery_unused_count(profile_user)


def web_profile(request):
    """渲染 Web 个人资料页面。"""
    context = {

    }
    session_user = request.session.get(g_session_key_user)
    if not session_user:
        return redirect(PATH_LOGIN)

    if request.method == 'POST':
        response = _web_profile_handle_post(request, session_user, context)
        if response is not None:
            return response

    _web_profile_fill_context(context, session_user)

    return render(request, 'app/web_profile.html', context)

def web_logout(request):
    """处理 Web 退出登录请求。"""
    oidc_logout_url = ""
    try:
        id_token_hint = str(request.session.get(_OIDC_ID_TOKEN_SESSION_KEY) or "").strip()
    except Exception:
        id_token_hint = ""
    try:
        provider_id = str(request.session.get(_OIDC_PROVIDER_SESSION_KEY) or "").strip()
    except Exception:
        provider_id = ""

    if id_token_hint:
        try:
            if bool(getattr(OidcAuth, "is_enabled")()):
                post_logout_redirect_uri = request.build_absolute_uri(PATH_LOGIN)
                oidc_logout_url = getattr(OidcAuth, "build_end_session_url")(
                    id_token_hint=id_token_hint,
                    post_logout_redirect_uri=post_logout_redirect_uri,
                    provider_id=provider_id,
                )
        except Exception:
            oidc_logout_url = ""

    try:
        request.session.flush()
    except Exception:
        if g_session_key_user in request.session:
            del request.session[g_session_key_user]

    if str(oidc_logout_url or "").strip():
        return redirect(oidc_logout_url)
    return redirect(PATH_LOGIN)


_ENV_TRUTHY_VALUES = ("1", "true", "yes", "y", "on")


def _env_truthy(name: str) -> bool:
    """处理环境变量`truthy`。"""
    raw = str(os.environ.get(name, "") or "").strip().lower()
    return raw in _ENV_TRUTHY_VALUES


def _unique_nonempty_strs(values):
    """处理去重后非空`strs`。"""
    out = []
    for value in values or []:
        s = str(value or "").strip()
        if not s or s in out:
            continue
        out.append(s)
    return out


def _web_login_context() -> dict:
    """处理 Web 登录`context` 页面。"""
    context = {}
    captcha_enabled = _is_login_captcha_enabled()
    context["captcha_enabled"] = captcha_enabled
    try:
        context["oidc_enabled"] = bool(getattr(OidcAuth, "is_enabled")())
    except Exception:
        context["oidc_enabled"] = False
    return context


def _web_login_validate_captcha_or_response(request, verify_code: str, *, captcha_enabled: bool):
    """处理 Web 登录`validate``captcha``or`响应 页面。"""
    if not captcha_enabled:
        return None
    expected = str(request.session.get(f"{_VERIFY_CODE_SESSION_KEY_PREFIX}login") or "").strip()
    if not verify_code:
        return f_responseJson({"code": 0, "msg": "验证码不能为空"})
    if not expected:
        return f_responseJson({"code": 0, "msg": "验证码已过期，请刷新"})
    if verify_code.strip().lower() != expected.strip().lower():
        return f_responseJson({"code": 0, "msg": "验证码错误"})
    try:
        del request.session[f"{_VERIFY_CODE_SESSION_KEY_PREFIX}login"]
    except Exception:
        logger.debug("login captcha session cleanup failed", exc_info=True)
    return None


def _web_login_lockout_precheck(request, lockout_identifier: str):
    """处理 Web 登录锁定预检 页面。"""
    lockout_identifier = _normalize_login_identifier(lockout_identifier)
    state = {
        "enabled": False,
        "identifier": lockout_identifier,
        "source_ip": _get_login_lockout_source_ip(request),
        "key": "",
        "key_input": "",
        "legacy_key": lockout_identifier[:150] if lockout_identifier else "",
        "user_hint": None,
        "row": None,
        "now_ts": None,
    }

    lockout_enabled = _env_truthy("BEACON_LOGIN_LOCKOUT_ENABLED")
    if not lockout_enabled or not lockout_identifier:
        return state, None
    state["enabled"] = True

    from django.utils import timezone
    from app.models import LoginLockout

    try:
        now_ts = timezone.now()
        state["now_ts"] = now_ts
        state["user_hint"] = _resolve_local_user_for_lockout(lockout_identifier)
        state["key"] = _build_login_lockout_key(lockout_identifier, user=state["user_hint"])
        state["key_input"] = _build_login_lockout_key(lockout_identifier, user=None)

        keys = _unique_nonempty_strs([state["key"], state["key_input"], state["legacy_key"]])
        for k in keys:
            _cleanup_stale_login_lockout_rows(lockout_key=k, source_ip=state["source_ip"], now_ts=now_ts)

        row = (
            LoginLockout.objects.filter(
                username__in=keys,
                source_ip=state["source_ip"],
                locked_until__gt=now_ts,
            )
            .order_by("-locked_until")
            .first()
        ) if keys else None
        state["row"] = row

        if row and getattr(row, "locked_until", None) and row.locked_until > now_ts:
            _write_login_security_audit_event(
                request,
                event_type="security.login_lockout.blocked",
                username=lockout_identifier,
                error_message="account locked",
                detail_extra={
                    "lockout_key": str(getattr(row, "username", "") or ""),
                    "locked_until": str(getattr(row, "locked_until", "") or ""),
                },
            )
            return state, f_responseJson({"code": 0, "msg": "账号已锁定，请稍后重试"})
    except Exception:
        state["row"] = None
        state["now_ts"] = None

    return state, None


def _web_login_lookup_user(username: str):
    """处理 Web 登录查询用户 页面。"""
    username = _normalize_login_identifier(username)
    user = None
    not_found_msg = "用户名未注册"
    looks_like_email = bool(validate_email(username) or ("@" in str(username or "")))
    if looks_like_email:
        try:
            user = User.objects.filter(email__iexact=username).first()
        except Exception:
            user = None
        not_found_msg = "邮箱未注册"
    else:
        try:
            user = User.objects.filter(username=username).first()
            if not user:
                user = User.objects.filter(username__iexact=username).first()
        except Exception:
            user = None
    return user, not_found_msg


def _web_login_local_password_ok(user, password) -> bool:
    """处理 Web 登录`local``password`通过 页面。"""
    return bool(user and user.check_password(password))


def _web_login_ldap_enabled() -> bool:
    """处理 Web 登录LDAP启用 页面。"""
    try:
        return bool(getattr(LdapAuth, "is_enabled")())
    except Exception:
        return False


def _web_login_ldap_authenticate(username: str, password: str):
    """处理 Web 登录LDAP`authenticate` 页面。"""
    try:
        return getattr(LdapAuth, "authenticate")(str(username or ""), str(password or ""))
    except Exception:
        return False, {}


def _web_login_ldap_identity(info, username: str):
    """处理 Web 登录LDAP`identity` 页面。"""
    info = info if isinstance(info, dict) else {}
    provision_username = str(info.get("username") or username or "").strip()
    provision_email = str(info.get("email") or "").strip()
    return provision_username, provision_email


def _web_login_find_existing_user_for_ldap(provision_username: str, provision_email: str):
    """处理 Web 登录`find`现有用户`for`LDAP 页面。"""
    user = None
    if provision_username:
        try:
            user = User.objects.filter(username=provision_username).first()
        except Exception:
            user = None
        if not user:
            try:
                user = User.objects.filter(username__iexact=provision_username).first()
            except Exception:
                user = None

    if (not user) and provision_email:
        try:
            user = User.objects.filter(email__iexact=provision_email).first()
        except Exception:
            user = None

    return user


def _web_login_provision_user_if_missing(user, *, provision_username: str, provision_email: str):
    """处理 Web 登录`provision`用户`if``missing` 页面。"""
    if user or not provision_username:
        return user
    return User.objects.create_user(
        username=provision_username,
        password=gen_random_code_s(24),
        email=provision_email,
    )


def _web_login_sync_email_best_effort(user, provision_email: str) -> None:
    """尽力处理 Web 登录`sync`邮箱 页面。"""
    if not user or not provision_email:
        return
    if str(getattr(user, "email", "") or "").strip().lower() == str(provision_email).lower():
        return
    try:
        user.email = provision_email
        user.save(update_fields=["email"])
    except Exception:
        logger.debug("login provision email sync failed user_id=%s", getattr(user, "id", None), exc_info=True)


def _web_login_try_ldap_fallback(username: str, password: str, user):
    """处理 Web 登录`try`LDAP回退值 页面。"""
    if not _web_login_ldap_enabled():
        return user, False
    if not str(username or "").strip() or not str(password or "").strip():
        return user, False

    ok, info = _web_login_ldap_authenticate(username, password)
    if not ok:
        return user, False

    provision_username, provision_email = _web_login_ldap_identity(info, username)
    if not user:
        user = _web_login_find_existing_user_for_ldap(provision_username, provision_email)
        user = _web_login_provision_user_if_missing(
            user,
            provision_username=provision_username,
            provision_email=provision_email,
        )

    _web_login_sync_email_best_effort(user, provision_email)
    return user, bool(user)


def _web_login_authenticate_user(user, username: str, password: str):
    """处理 Web 登录`authenticate`用户 页面。"""
    if _web_login_local_password_ok(user, password):
        return user, True
    return _web_login_try_ldap_fallback(username, password, user)


def _web_login_verify_totp_if_enabled(user, totp_code: str):
    """处理 Web 登录`verify`TOTP`if`启用 页面。"""
    cred = UserTotpCredential.objects.filter(user=user, enabled=True).first()
    if not cred:
        return True, ""

    if not totp_code:
        return False, "TOTP 验证码不能为空"

    totp_ok = Totp.verify_totp(str(getattr(cred, "secret_base32", "")), totp_code)
    if not totp_ok:
        try:
            totp_ok = bool(getattr(TotpRecovery, "consume_recovery_code_for_user")(user, totp_code))
        except Exception:
            totp_ok = False

    if not totp_ok:
        return False, MSG_TOTP_INVALID
    return True, ""


def _web_login_store_session_success(request, user) -> None:
    """处理 Web 登录`store`会话成功状态 页面。"""
    user.last_login = datetime.now()
    user.save()

    try:
        request.session.flush()
    except Exception:
        try:
            request.session.cycle_key()
        except Exception:
            logger.debug("login session cycle fallback failed user_id=%s", getattr(user, "id", None), exc_info=True)

    request.session[g_session_key_user] = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if getattr(user, "last_login", None) else "",
    }


def _env_int_clamped(name: str, default: int, *, min_value: int, max_value: int) -> int:
    """处理环境变量整数值`clamped`。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception:
            value = int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _web_login_lockout_policy_params():
    """处理 Web 登录锁定策略参数 页面。"""
    max_attempts = _env_int_clamped("BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS", 5, min_value=1, max_value=100)
    window_seconds = _env_int_clamped("BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS", 300, min_value=10, max_value=24 * 3600)
    lockout_seconds = _env_int_clamped("BEACON_LOGIN_LOCKOUT_SECONDS", 900, min_value=10, max_value=30 * 24 * 3600)
    return int(max_attempts), int(window_seconds), int(lockout_seconds)


def _lockout_age_seconds(now_ts, first_failure_at) -> float:
    """返回锁定`age`秒数。"""
    try:
        return float((now_ts - first_failure_at).total_seconds())
    except Exception:
        return 0.0


def _web_login_lockout_apply_failure(row, *, now_ts, window_seconds: int) -> None:
    """处理 Web 登录锁定应用`failure` 页面。"""
    first = getattr(row, "first_failure_at", None)
    if first is None:
        row.failures = 1
        row.first_failure_at = now_ts
    else:
        age = _lockout_age_seconds(now_ts, first)
        if age > float(window_seconds):
            row.failures = 1
            row.first_failure_at = now_ts
        else:
            try:
                row.failures = int(getattr(row, "failures", 0) or 0) + 1
            except Exception:
                row.failures = 1
    row.last_failure_at = now_ts


def _web_login_lockout_clear_keys(login_lockout_model, *, clear_keys, source_ip: str) -> None:
    """处理 Web 登录锁定清理键列表 页面。"""
    if not clear_keys:
        return
    q = login_lockout_model.objects.filter(username__in=list(clear_keys))
    if not _login_lockout_clear_all_ips_on_success():
        q = q.filter(source_ip=source_ip)
    q.delete()


def _web_login_lockout_record_failure(
    login_lockout_model,
    *,
    lockout_key_final: str,
    source_ip: str,
    now_ts,
    window_seconds: int,
    max_attempts: int,
    lockout_seconds: int,
    request,
    lockout_identifier: str,
) -> None:
    """处理 Web 登录锁定`record``failure` 页面。"""
    if not lockout_key_final:
        raise RuntimeError("empty lockout key")

    row = login_lockout_model.objects.filter(username=lockout_key_final, source_ip=source_ip).first()
    if not row:
        row = login_lockout_model(username=lockout_key_final, source_ip=source_ip)
        row.failures = 0
        row.first_failure_at = None
        row.last_failure_at = None
        row.locked_until = None

    was_locked = bool(getattr(row, "locked_until", None) and row.locked_until > now_ts)
    _web_login_lockout_apply_failure(row, now_ts=now_ts, window_seconds=window_seconds)

    if int(getattr(row, "failures", 0) or 0) >= int(max_attempts):
        row.locked_until = now_ts + timedelta(seconds=int(lockout_seconds))

    row.save()
    is_locked = bool(getattr(row, "locked_until", None) and row.locked_until > now_ts)
    if is_locked and (not was_locked):
        _write_login_security_audit_event(
            request,
            event_type="security.login_lockout.triggered",
            username=lockout_identifier,
            error_message="lockout threshold reached",
            detail_extra={
                "lockout_key": str(getattr(row, "username", "") or ""),
                "failures": int(getattr(row, "failures", 0) or 0),
                "max_attempts": int(max_attempts),
            },
        )


def _web_login_update_lockout_best_effort(lockout_state: dict, *, request, user, code: int) -> None:
    """尽力处理 Web 登录`update`锁定 页面。"""
    if not lockout_state.get("enabled") or not lockout_state.get("identifier"):
        return

    from django.utils import timezone
    from app.models import LoginLockout

    try:
        if lockout_state.get("now_ts") is None:
            lockout_state["now_ts"] = timezone.now()
        now_ts = lockout_state.get("now_ts")

        lockout_effective_user = user if user else lockout_state.get("user_hint")
        lockout_key_final = _build_login_lockout_key(lockout_state["identifier"], user=lockout_effective_user)
        if not lockout_key_final:
            lockout_key_final = str(lockout_state.get("key") or lockout_state.get("key_input") or lockout_state.get("legacy_key") or "").strip()

        if int(code or 0) == 1000:
            clear_keys = _unique_nonempty_strs(
                [
                    lockout_key_final,
                    lockout_state.get("key"),
                    lockout_state.get("key_input"),
                    lockout_state.get("legacy_key"),
                ]
            )
            _web_login_lockout_clear_keys(LoginLockout, clear_keys=clear_keys, source_ip=lockout_state["source_ip"])
            return

        max_attempts, window_seconds, lockout_seconds = _web_login_lockout_policy_params()
        _web_login_lockout_record_failure(
            LoginLockout,
            lockout_key_final=lockout_key_final,
            source_ip=lockout_state["source_ip"],
            now_ts=now_ts,
            window_seconds=window_seconds,
            max_attempts=max_attempts,
            lockout_seconds=lockout_seconds,
            request=request,
            lockout_identifier=lockout_state["identifier"],
        )
    except Exception:
        logger.debug("login lockout failure recording failed identifier=%s", lockout_state.get("identifier"), exc_info=True)


def _web_login_finalize_attempt(request, *, user, auth_ok: bool, totp_code: str, not_found_msg: str):
    """处理 Web 登录完成`attempt` 页面。"""
    if not auth_ok or not user:
        msg = "密码错误" if user else str(not_found_msg or "用户名未注册")
        return 0, msg
    if not bool(getattr(user, "is_active", False)):
        return 0, "账号已禁用"

    totp_ok, totp_msg = _web_login_verify_totp_if_enabled(user, totp_code)
    if not totp_ok:
        return 0, totp_msg

    _web_login_store_session_success(request, user)
    return 1000, "登录成功"


def web_login(request):
    """处理 Web 登录页面。"""
    context = _web_login_context()
    if request.method != "POST":
        return render(request, 'app/web_login.html', context)

    params = f_parsePostParams(request)
    username = _normalize_login_identifier(params.get("username"))
    password = params.get("password")
    verify_code = str(params.get("verify_code") or "").strip()
    totp_code = str(params.get("totp_code") or "").strip()
    context["username"] = username

    captcha_resp = _web_login_validate_captcha_or_response(
        request,
        verify_code,
        captcha_enabled=bool(context.get("captcha_enabled")),
    )
    if captcha_resp is not None:
        return captcha_resp

    lockout_state, lockout_blocked_resp = _web_login_lockout_precheck(request, username)
    if lockout_blocked_resp is not None:
        return lockout_blocked_resp

    user, not_found_msg = _web_login_lookup_user(username)
    user, auth_ok = _web_login_authenticate_user(user, username, password)
    code, msg = _web_login_finalize_attempt(
        request,
        user=user,
        auth_ok=bool(auth_ok),
        totp_code=totp_code,
        not_found_msg=not_found_msg,
    )
    _web_login_update_lockout_best_effort(lockout_state, request=request, user=user, code=int(code or 0))

    return f_responseJson({"code": int(code or 0), "msg": str(msg or "")})
