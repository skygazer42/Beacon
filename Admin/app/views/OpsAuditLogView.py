import json
from datetime import datetime
from urllib.parse import quote

from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import redirect, render

from app.models import UserPermission
from app.utils.UserPermissionRules import is_path_allowed, parse_permissions_json
from app.views.ViewsBase import f_parsePostParams, f_responseJson, getUser


def _get_db_user(request):
    """获取数据库用户。"""
    session_user = getUser(request) or {}
    try:
        user_id = int(session_user.get("id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return None
    return User.objects.filter(id=user_id).first()


def _is_admin(db_user) -> bool:
    """判断管理员。"""
    if not db_user:
        return False
    return bool(getattr(db_user, "is_staff", False) or getattr(db_user, "is_superuser", False))


def _has_audit_access(db_user, *, export: bool = False) -> bool:
    """检查审计`access`。"""
    if _is_admin(db_user):
        return True
    if not db_user:
        return False

    perm_obj = UserPermission.objects.filter(user_id=getattr(db_user, "id", 0)).first()
    parsed, perms = parse_permissions_json(getattr(perm_obj, "permissions_json", "") if perm_obj else "")
    if parsed is not True:
        return False

    path = "ops/audit/export" if export else "ops/audit"
    return bool(is_path_allowed(perms, path))


def _deny(request, *, json_mode: bool):
    """处理拒绝。"""
    msg = "权限不足，仅管理员可访问"
    if json_mode:
        return f_responseJson({"code": 403, "msg": msg})
    return render(
        request,
        "app/message.html",
        {"msg": msg, "is_success": False, "redirect_url": "/"},
    )


def _parse_dt(value: str):
    """解析`dt`。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except Exception:
        return None


def _action_label(event_type: str) -> str:
    """处理动作标签。"""
    raw = str(event_type or "").strip()
    if not raw:
        return "-"
    if "." not in raw:
        return raw
    return raw.split(".")[-1] or raw


def _load_detail_object(raw: str):
    """加载详情`object`。"""
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


def _safe_record_url(raw: str) -> str:
    """返回安全`record`URL。"""
    try:
        url = str(raw or "").strip()
    except Exception:
        url = ""
    if not url.startswith("/"):
        return ""
    if any(ch in url for ch in ("\r", "\n", "\t")):
        return ""
    return url


def _derive_record_url(row, detail_obj) -> str:
    """返回`derive``record`URL。"""
    explicit = _safe_record_url(detail_obj.get("path"))
    if explicit:
        return explicit

    control_code = str(getattr(row, "control_code", "") or "").strip()
    if control_code:
        return "/controls?code=" + quote(control_code)
    algorithm_code = str(getattr(row, "algorithm_code", "") or "").strip()
    if algorithm_code:
        return "/algorithm/index?code=" + quote(algorithm_code)
    lease_id = str(getattr(row, "lease_id", "") or "").strip()
    if lease_id:
        return "/license/manager?lease_id=" + quote(lease_id)
    return ""


def _derive_object_label(row, detail_obj) -> str:
    """处理`derive``object`标签。"""
    explicit = str(detail_obj.get("object_label") or "").strip()
    if explicit:
        return explicit
    for value in (
        getattr(row, "control_code", ""),
        getattr(row, "algorithm_code", ""),
        getattr(row, "lease_id", ""),
        getattr(row, "node_id", ""),
    ):
        s = str(value or "").strip()
        if s:
            return s
    return "-"


def _serialize_audit_row(row):
    """返回`serialize`审计记录。"""
    detail_json = getattr(row, "detail_json", "")
    detail_obj = _load_detail_object(detail_json)
    return {
        "id": getattr(row, "id", None),
        "create_time": getattr(row, "create_time", None),
        "event_type": getattr(row, "event_type", ""),
        "action_label": _action_label(getattr(row, "event_type", "")),
        "ok": bool(getattr(row, "ok", False)),
        "operator": getattr(row, "operator", ""),
        "actor_label": str(getattr(row, "operator", "") or "").strip() or "-",
        "source_ip": getattr(row, "source_ip", ""),
        "node_id": getattr(row, "node_id", ""),
        "control_code": getattr(row, "control_code", ""),
        "algorithm_code": getattr(row, "algorithm_code", ""),
        "lease_id": getattr(row, "lease_id", ""),
        "object_label": _derive_object_label(row, detail_obj),
        "record_url": _derive_record_url(row, detail_obj),
        "error_code": getattr(row, "error_code", ""),
        "error_message": getattr(row, "error_message", ""),
        "detail_json": detail_json,
    }


_OK_TRUE_VALUES = ("1", "true", "yes", "y", "on")
_OK_FALSE_VALUES = ("0", "false", "no", "n", "off")


def _apply_ok_filter(qs, ok_raw: str):
    """处理应用通过`filter`。"""
    if ok_raw in _OK_TRUE_VALUES:
        return qs.filter(ok=True)
    if ok_raw in _OK_FALSE_VALUES:
        return qs.filter(ok=False)
    return qs


def _apply_object_filter(qs, object_value: str):
    """处理应用`object``filter`。"""
    if not object_value:
        return qs
    return qs.filter(
        Q(node_id__icontains=object_value)
        | Q(control_code__icontains=object_value)
        | Q(algorithm_code__icontains=object_value)
        | Q(lease_id__icontains=object_value)
        | Q(detail_json__icontains=object_value)
    )


def _apply_keyword_filter(qs, keyword: str):
    """处理应用`keyword``filter`。"""
    if not keyword:
        return qs
    return qs.filter(
        Q(operator__icontains=keyword)
        | Q(source_ip__icontains=keyword)
        | Q(node_id__icontains=keyword)
        | Q(control_code__icontains=keyword)
        | Q(algorithm_code__icontains=keyword)
        | Q(lease_id__icontains=keyword)
        | Q(error_message__icontains=keyword)
        | Q(detail_json__icontains=keyword)
        | Q(event_type__icontains=keyword)
    )


def _apply_filters(queryset, params):
    """处理应用`filters`。"""
    event_type = str(params.get("event_type", "") or "").strip()
    keyword = str(params.get("keyword", "") or "").strip()
    actor = str(params.get("actor", "") or "").strip()
    object_value = str(params.get("object", "") or "").strip()
    action = str(params.get("action", "") or "").strip().lower()
    ok_raw = str(params.get("ok", "") or "").strip().lower()

    since = _parse_dt(str(params.get("since", "") or "").strip())
    until = _parse_dt(str(params.get("until", "") or "").strip())

    qs = queryset
    if event_type:
        qs = qs.filter(event_type=event_type)
    if actor:
        qs = qs.filter(operator__icontains=actor)
    if action:
        qs = qs.filter(Q(event_type__iendswith="." + action) | Q(event_type__iexact=action))
    qs = _apply_ok_filter(qs, ok_raw)
    if since:
        qs = qs.filter(create_time__gte=since)
    if until:
        qs = qs.filter(create_time__lte=until)

    qs = _apply_object_filter(qs, object_value)
    qs = _apply_keyword_filter(qs, keyword)
    return qs


def index(request):
    """渲染默认页面。"""
    user = getUser(request)
    if not user:
        return redirect("/login")

    db_user = _get_db_user(request)
    if not _has_audit_access(db_user):
        return _deny(request, json_mode=False)

    return render(request, "app/ops/audit.html", {"user": user})


def api_list(request):
    """处理 `list` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "请求方法不支持"})

    user = getUser(request)
    if not user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})

    db_user = _get_db_user(request)
    if not _has_audit_access(db_user):
        return _deny(request, json_mode=True)

    from app.models import OpsAuditLog

    params = f_parsePostParams(request)
    try:
        page = int(params.get("page", 1) or 1)
    except Exception:
        page = 1
    try:
        page_size = int(params.get("page_size", 20) or 20)
    except Exception:
        page_size = 20

    page = max(1, page)
    page_size = max(1, min(200, page_size))

    qs = OpsAuditLog.objects.all().order_by("-id")
    qs = _apply_filters(qs, params)

    total = qs.count()
    skip = (page - 1) * page_size
    rows = list(qs[skip : skip + page_size])
    data = [_serialize_audit_row(row) for row in rows]

    return f_responseJson({"code": 1000, "msg": "success", "data": data, "total": total})


def export(request):
    """执行`export`。"""
    user = getUser(request)
    if not user:
        return redirect("/login")

    db_user = _get_db_user(request)
    if not _has_audit_access(db_user, export=True):
        return _deny(request, json_mode=False)

    from app.views import OpsView

    return OpsView.audit_export(request)
