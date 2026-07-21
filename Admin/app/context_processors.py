from app.views import ViewsBase
from app.utils.SystemConfigHelper import get_value
from django.conf import settings
from django.contrib.auth.models import User

import json
import re
import settings_store  # type: ignore


def _get_settings_str(key: str) -> str:
    """读取设置中的字符串值。"""
    if not key:
        return ""
    try:
        value = settings_store.get_setting(key, "")
        return str(value or "").strip()
    except Exception:
        return ""


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _sanitize_hex_color(value: str) -> str:
    """清洗十六进制颜色值。
    
    Minimal CSS color sanitizer for themeColor.
    
        Only allow hex forms (#RGB/#RRGGBB/#RRGGBBAA). Anything else is rejected.
    """
    try:
        s = str(value or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    if _HEX_COLOR_RE.match(s):
        return s
    return ""


def _parse_json_object(raw: str):
    """解析 JSON 对象。"""
    try:
        s = str(raw or "").strip()
    except Exception:
        s = ""
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except Exception:
        return {}
    if isinstance(obj, dict):
        return obj
    return {}


def _cloud_mode_enabled() -> bool:
    """判断是否启用云端模式。"""
    from app.utils.DeploymentMode import is_cloud_mode

    try:
        return bool(is_cloud_mode())
    except Exception:
        return False


def _session_user_id(request) -> int:
    """返回会话中的用户 ID。"""
    try:
        session = getattr(request, "session", None)
        session_user = session.get("user") if session else None
    except Exception:
        session_user = None

    try:
        return int((session_user or {}).get("id") or 0)
    except Exception:
        return 0


def _session_admin_flags(request) -> tuple[bool, bool]:
    """返回当前会话用户的管理员标记。"""
    user_id = _session_user_id(request)
    if user_id <= 0:
        return False, False

    try:
        db_user = User.objects.filter(id=user_id).only("is_staff", "is_superuser").first()
    except Exception:
        db_user = None

    if not db_user:
        return False, False

    return bool(getattr(db_user, "is_staff", False)), bool(getattr(db_user, "is_superuser", False))


def _membership_tenant_for_non_admin_user(user_id: int):
    """获取非管理员用户所属的租户信息。"""
    from django.contrib.auth.models import User

    try:
        db_user = User.objects.filter(id=user_id).only("id", "is_staff", "is_superuser").first()
    except Exception:
        db_user = None

    if not db_user:
        return None, False

    if db_user.is_staff or db_user.is_superuser:
        return None, False

    from app.models import CloudUserMembership

    try:
        m = (
            CloudUserMembership.objects.select_related("tenant")
            .filter(user_id=user_id, enabled=True, tenant__enabled=True)
            .order_by("-is_default", "id")
            .first()
        )
        return getattr(m, "tenant", None) if m else None, True
    except Exception:
        return None, True


def _tenant_slug_from_query(request) -> str:
    """从查询参数中获取租户 slug。"""
    try:
        return str((getattr(request, "GET", {}) or {}).get("tenant") or "").strip()
    except Exception:
        return ""


def _tenant_by_slug(slug: str):
    """按 slug 查询租户。"""
    if not slug:
        return None
    from app.models import CloudTenant

    try:
        return CloudTenant.objects.filter(slug=slug, enabled=True).first()
    except Exception:
        return None


def _resolve_cloud_tenant_for_branding(request):
    """解析品牌配置对应的云端租户。"""
    if not _cloud_mode_enabled():
        return None

    # 1) Logged-in non-admin user: membership determines tenant.
    user_id = _session_user_id(request)
    if user_id > 0:
        tenant, handled = _membership_tenant_for_non_admin_user(int(user_id))
        if handled:
            return tenant

    # 2) Unauthenticated (login page) or admin preview: ?tenant=<slug>
    return _tenant_by_slug(_tenant_slug_from_query(request))


def _branding_value_with_cfg_fallback(cfg, key: str, *, default: str) -> str:
    """优先读取设置值，缺失时回退到配置项。"""
    return (
        _get_settings_str(key)
        or str(get_value(key, getattr(cfg, key, default)) or "").strip()
        or getattr(cfg, key, default)
    )


def _branding_value(key: str, *, default: str = "") -> str:
    """读取品牌配置值。"""
    return _get_settings_str(key) or str(get_value(key, default) or "").strip()


def _tenant_branding_overrides(tenant) -> dict:
    """提取租户品牌覆盖配置。"""
    branding_obj = _parse_json_object(getattr(tenant, "branding_json", ""))
    overrides = {}

    mapping = {
        "siteName": "site_name",
        "siteTitle": "site_title",
        "siteLogo": "site_logo",
        "loginBg": "login_bg",
    }

    for json_key, context_key in mapping.items():
        v = str(branding_obj.get(json_key) or "").strip()
        if v:
            overrides[context_key] = v

    theme_color = _sanitize_hex_color(str(branding_obj.get("themeColor") or ""))
    if theme_color:
        overrides["theme_color"] = theme_color

    return overrides


def branding(request):
    """构造品牌相关模板上下文。"""
    cfg = ViewsBase.g_config
    bootstrap_is_staff, bootstrap_is_superuser = _session_admin_flags(request)

    context = {
        "debug_enabled": bool(getattr(settings, "DEBUG", False)),
        "site_name": _branding_value_with_cfg_fallback(cfg, "siteName", default="Beacon"),
        "site_title": _branding_value_with_cfg_fallback(cfg, "siteTitle", default="Beacon 新一代 AI 视频分析系统"),
        "site_logo": _branding_value_with_cfg_fallback(cfg, "siteLogo", default="/static/images/logo.png"),
        "author_name": _branding_value("authorName", default=getattr(cfg, "authorName", "")),
        "author_link": _branding_value("authorLink", default=getattr(cfg, "authorLink", "")),
        "site_icp": _branding_value("siteIcp", default=getattr(cfg, "siteIcp", "")),
        "custom_css": _branding_value("customCss", default=getattr(cfg, "customCss", "")),
        "custom_script": _branding_value("customScript", default=getattr(cfg, "customScript", "")),
        "login_bg": _branding_value("loginBg", default=getattr(cfg, "loginBg", "")),
        "docs_url": _branding_value("docsUrl", default=""),
        "download_url": _branding_value("downloadUrl", default=""),
        "theme_color": "",
        "project_version": str(getattr(settings, "PROJECT_VERSION", "") or "dev"),
        "deployment_mode": "cloud" if _cloud_mode_enabled() else "edge",
        "bootstrap_is_staff": bootstrap_is_staff,
        "bootstrap_is_superuser": bootstrap_is_superuser,
    }

    # Cloud SaaS: allow per-tenant white-label overrides.
    tenant = _resolve_cloud_tenant_for_branding(request)
    if tenant:
        context.update(_tenant_branding_overrides(tenant))

    return context
