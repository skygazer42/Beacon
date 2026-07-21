import os
import ssl
from typing import Any, Dict, Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in ("1", "true", "yes", "y", "on")


def _env_str(name: str, default: str = "") -> str:
    """读取环境变量并转换为字符串。"""
    return str(os.environ.get(name, "") or default or "").strip()


def is_enabled() -> bool:
    """判断`is`是否启用。
    
    LDAP/AD auth is opt-in and disabled by default.
    
        This module is dependency-optional (ldap3). If ldap3 is not installed, the
        caller should treat LDAP auth as unavailable.
    """
    return _env_bool("BEACON_LDAP_ENABLED", default=False)


def _fail(reason: str) -> Tuple[bool, Dict[str, Any]]:
    """处理失败。"""
    return False, {"reason": reason}


def _format_template(template: str, username: str) -> str:
    """处理`format``template`。"""
    try:
        return template.format(username=username)
    except Exception:
        return template.replace("{username}", username)


def _ldap_auto_bind(ldap3, starttls: bool):
    """处理LDAP自动绑定。"""
    return ldap3.AUTO_BIND_TLS_BEFORE_BIND if starttls else ldap3.AUTO_BIND_NO_TLS


def _ldap_tls(ldap3, tls_verify: bool):
    """处理LDAPTLS。"""
    try:
        validate = ssl.CERT_REQUIRED if tls_verify else ssl.CERT_NONE
        return ldap3.TLS(validate=validate, version=ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return None


def _ldap_connect_timeout():
    """返回LDAP连接超时时间。"""
    raw_timeout = _env_str("BEACON_LDAP_CONNECT_TIMEOUT_SECONDS", "")
    if not raw_timeout:
        return None
    try:
        return max(1.0, min(60.0, float(raw_timeout)))
    except Exception:
        return None


def _ldap_build_server(ldap3, url: str):
    """处理LDAP构建服务端。"""
    use_ssl = url.lower().startswith("ldaps://") or _env_bool("BEACON_LDAP_USE_SSL", default=False)
    starttls = _env_bool("BEACON_LDAP_STARTTLS", default=False)
    tls_verify = _env_bool("BEACON_LDAP_TLS_VERIFY", default=True)

    server = ldap3.Server(
        url,
        use_ssl=use_ssl,
        tls=_ldap_tls(ldap3, tls_verify),
        connect_timeout=_ldap_connect_timeout(),
        get_info=ldap3.NONE,
    )
    email_attr = _env_str("BEACON_LDAP_EMAIL_ATTR", "mail") or "mail"
    return server, starttls, email_attr


def _ldap_bind(ldap3, server, *, user: str, password: str, starttls: bool):
    """处理LDAP绑定。"""
    return ldap3.Connection(server, user=user, password=password, auto_bind=_ldap_auto_bind(ldap3, starttls))


def _ldap_lookup_email(ldap3, conn, user_dn: str, email_attr: str) -> str:
    """在 LDAP 中查询邮箱字段。"""
    email = ""
    try:
        conn.search(user_dn, "(objectClass=*)", search_scope=ldap3.BASE, attributes=[email_attr])
        if not conn.entries:
            return ""
        entry = conn.entries[0]
        if email_attr in entry:
            email = str(entry[email_attr].value or "").strip()
    except Exception:
        email = ""
    return email


def _ldap_escape_filter_username(user_input: str) -> str:
    """处理LDAP转义`filter``username`。"""
    from ldap3.utils.conv import escape_filter_chars  # type: ignore

    return escape_filter_chars(user_input)


def _ldap_render_user_filter(user_filter_template: str, user_input: str) -> str:
    """处理LDAP渲染用户`filter`。"""
    safe_username = _ldap_escape_filter_username(user_input)
    return _format_template(user_filter_template, safe_username)


def _ldap_auth_direct_bind(
    ldap3,
    server,
    user_input: str,
    password: str,
    *,
    dn_template: str,
    starttls: bool,
    email_attr: str,
) -> Tuple[bool, Dict[str, Any]]:
    """处理LDAP认证直接绑定。"""
    user_dn = _format_template(dn_template, user_input)

    try:
        conn = _ldap_bind(ldap3, server, user=user_dn, password=password, starttls=starttls)
    except Exception:
        return _fail("bind_failed")

    email = _ldap_lookup_email(ldap3, conn, user_dn, email_attr)
    return True, {"username": user_input, "email": email, "dn": user_dn}


def _ldap_auth_search_bind(
    ldap3,
    server,
    user_input: str,
    password: str,
    *,
    starttls: bool,
    email_attr: str,
) -> Tuple[bool, Dict[str, Any]]:
    """处理LDAP认证搜索绑定。"""
    bind_dn = _env_str("BEACON_LDAP_BIND_DN", "")
    bind_password = _env_str("BEACON_LDAP_BIND_PASSWORD", "")
    base_dn = _env_str("BEACON_LDAP_BASE_DN", "")
    user_filter_template = _env_str("BEACON_LDAP_USER_FILTER", "(uid={username})") or "(uid={username})"
    if not (bind_dn and bind_password and base_dn):
        return _fail("missing_bind_config")

    user_filter = _ldap_render_user_filter(user_filter_template, user_input)

    try:
        admin_conn = _ldap_bind(ldap3, server, user=bind_dn, password=bind_password, starttls=starttls)
    except Exception:
        return _fail("service_bind_failed")

    try:
        admin_conn.search(base_dn, user_filter, attributes=[email_attr], size_limit=1)
    except Exception:
        return _fail("search_failed")

    if not admin_conn.entries:
        return _fail("user_not_found")

    entry = admin_conn.entries[0]
    user_dn = str(getattr(entry, "entry_dn", "") or "").strip()
    if not user_dn:
        return _fail("dn_missing")

    email = ""
    try:
        if email_attr in entry:
            email = str(entry[email_attr].value or "").strip()
    except Exception:
        email = ""

    try:
        _ = _ldap_bind(ldap3, server, user=user_dn, password=password, starttls=starttls)
    except Exception:
        return _fail("bind_failed")

    return True, {"username": user_input, "email": email, "dn": user_dn}


def authenticate(username: str, password: str) -> Tuple[bool, Dict[str, Any]]:
    """处理`authenticate`。
    
    Authenticate a user against LDAP/AD.
    
        Returns:
          (ok, info)
        where info may contain:
          - username: str (suggested local username)
          - email: str (best-effort)
          - dn: str (resolved user DN)
          - reason: str (on failure)
    
        Notes:
        - Uses ldap3 if installed; otherwise returns (False, reason=ldap3_missing).
        - Supports two common patterns:
          1) Direct bind: BEACON_LDAP_USER_DN_TEMPLATE="uid={username},ou=People,dc=example,dc=com"
          2) Search + bind (service account):
             BEACON_LDAP_BIND_DN / BEACON_LDAP_BIND_PASSWORD + BEACON_LDAP_BASE_DN + BEACON_LDAP_USER_FILTER
    """
    if not is_enabled():
        return _fail("disabled")

    user_input = str(username or "").strip()
    if not user_input:
        return _fail("missing_username")
    if not str(password or ""):
        return _fail("missing_password")

    url = _env_str("BEACON_LDAP_URL", "")
    if not url:
        return _fail("missing_url")

    try:
        import ldap3  # type: ignore
    except ImportError:
        return _fail("ldap3_missing")

    server, starttls, email_attr = _ldap_build_server(ldap3, url)

    dn_template = _env_str("BEACON_LDAP_USER_DN_TEMPLATE", "")
    if dn_template:
        return _ldap_auth_direct_bind(
            ldap3,
            server,
            user_input,
            password,
            dn_template=dn_template,
            starttls=starttls,
            email_attr=email_attr,
        )

    return _ldap_auth_search_bind(
        ldap3,
        server,
        user_input,
        password,
        starttls=starttls,
        email_attr=email_attr,
    )
