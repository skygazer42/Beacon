from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from app.models import UserPermission
from app.utils.PasswordPolicy import validate_password
from app.utils.UserPermissionRules import PERMISSION_KEYS, PERMISSION_META, normalize_permissions_dict
from app.views.ViewsBase import f_parsePostParams, f_responseJson, getUser

from functools import wraps
import json


PERMISSION_DENIED_MSG = "权限不足"
ADMIN_ONLY_MSG = "权限不足，仅管理员可访问"
MSG_METHOD_NOT_SUPPORTED = "request method not supported"
MSG_USER_ID_REQUIRED = "user_id is required"
MSG_USER_NOT_FOUND = "user not found"


def _session_user(request):
    """返回当前会话中的用户信息。"""
    return getUser(request) or {}


def _db_user_from_session(request):
    """根据会话信息查询数据库中的用户对象。"""
    session_user = _session_user(request)
    try:
        user_id = int(session_user.get("id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return None
    return User.objects.filter(id=user_id).first()


def _is_admin_user(db_user) -> bool:
    """判断用户是否具备管理员权限。"""
    return bool(db_user and (db_user.is_staff or db_user.is_superuser))


def _to_bool(value, default: bool = False) -> bool:
    """将输入值规范化为布尔值。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off", ""):
        return False
    return default


def _render_permission_denied(request):
    """渲染权限不足提示页。"""
    return render(
        request,
        "app/message.html",
        {
            "msg": PERMISSION_DENIED_MSG,
            "is_success": False,
            "redirect_url": "/",
        },
    )


def require_admin(view_func):
    """为视图增加管理员权限校验。"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """执行包装后的权限校验逻辑。"""
        db_user = _db_user_from_session(request)
        if not db_user:
            return redirect("/login")
        if not _is_admin_user(db_user):
            return f_responseJson({"code": 403, "msg": ADMIN_ONLY_MSG})
        return view_func(request, *args, **kwargs)

    return wrapper


def user_manage_index(request):
    """渲染用户管理页面。"""
    db_user = _db_user_from_session(request)
    if not db_user:
        return redirect("/login")
    if not _is_admin_user(db_user):
        return _render_permission_denied(request)
    return render(
        request,
        "app/user/index.html",
        {
            "user": _session_user(request),
            "permission_meta": PERMISSION_META,
        },
    )


def _parse_user_list_params(request):
    """解析用户列表参数。"""
    params = f_parsePostParams(request)
    page = max(1, int(params.get("page", 1) or 1))
    page_size = max(1, min(200, int(params.get("page_size", 20) or 20)))
    keyword = str(params.get("keyword", "") or "").strip()
    return page, page_size, keyword


def _user_type_label(user) -> str:
    """处理用户类型标签。"""
    if getattr(user, "is_superuser", False):
        return "superuser"
    if getattr(user, "is_staff", False):
        return "staff"
    return "user"


def _user_row(user) -> dict:
    """返回用户记录。"""
    last_login = getattr(user, "last_login", None)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "is_active": bool(user.is_active),
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "user_type": _user_type_label(user),
        "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S"),
        "last_login": last_login.strftime("%Y-%m-%d %H:%M:%S") if last_login else "never",
    }


@require_admin
def api_get_user_list(request):
    """处理 `get_user_list` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED, "data": []})

    try:
        page, page_size, keyword = _parse_user_list_params(request)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e), "data": []})

    users_query = User.objects.all().order_by("-id")
    if keyword:
        from django.db.models import Q

        users_query = users_query.filter(
            Q(username__icontains=keyword)
            | Q(email__icontains=keyword)
            | Q(first_name__icontains=keyword)
            | Q(last_name__icontains=keyword)
        )

    total = users_query.count()
    start = (page - 1) * page_size
    users = users_query[start : start + page_size]

    data = [_user_row(user) for user in users]

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@require_admin
def api_add_user(request):
    """处理 `add_user` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
        username = str(params.get("username", "") or "").strip()
        password = str(params.get("password", "") or "").strip()
        email = str(params.get("email", "") or "").strip()
        first_name = str(params.get("first_name", "") or "").strip()
        last_name = str(params.get("last_name", "") or "").strip()
        is_staff = _to_bool(params.get("is_staff"), default=False)
        is_superuser = _to_bool(params.get("is_superuser"), default=False)
        is_active = _to_bool(params.get("is_active"), default=True)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    if not username:
        return f_responseJson({"code": 0, "msg": "username is required"})
    if not password:
        return f_responseJson({"code": 0, "msg": "password is required"})

    candidate_user = User(username=username, email=email, first_name=first_name, last_name=last_name)
    ok_pw, pw_msg = validate_password(password, user=candidate_user)
    if not ok_pw:
        return f_responseJson({"code": 0, "msg": pw_msg})

    if User.objects.filter(username=username).exists():
        return f_responseJson({"code": 0, "msg": "username already exists"})
    if email and User.objects.filter(email=email).exists():
        return f_responseJson({"code": 0, "msg": "email already exists"})

    user = User.objects.create(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_staff=is_staff,
        is_superuser=is_superuser,
        is_active=is_active,
    )
    user.set_password(password)  # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password -- validated above
    user.save()
    return f_responseJson({"code": 1000, "msg": "success"})


@require_admin
def api_edit_user(request):
    """处理 `edit_user` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
        user_id = int(params.get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return f_responseJson({"code": 0, "msg": MSG_USER_ID_REQUIRED})

    user = User.objects.filter(id=user_id).first()
    if not user:
        return f_responseJson({"code": 0, "msg": MSG_USER_NOT_FOUND})

    email = str(params.get("email", "") or "").strip()
    if email and User.objects.filter(email=email).exclude(id=user_id).exists():
        return f_responseJson({"code": 0, "msg": "email already exists"})

    user.email = email
    user.first_name = str(params.get("first_name", "") or "").strip()
    user.last_name = str(params.get("last_name", "") or "").strip()
    user.is_staff = _to_bool(params.get("is_staff"), default=bool(user.is_staff))
    user.is_superuser = _to_bool(params.get("is_superuser"), default=bool(user.is_superuser))
    user.is_active = _to_bool(params.get("is_active"), default=bool(user.is_active))

    password = str(params.get("password", "") or "").strip()
    if password:
        ok_pw, pw_msg = validate_password(password, user=user)
        if not ok_pw:
            return f_responseJson({"code": 0, "msg": pw_msg})
        user.set_password(password)  # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password -- validated above

    user.save()
    return f_responseJson({"code": 1000, "msg": "success"})


@require_admin
def api_get_user_permissions(request):
    """处理 `get_user_permissions` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
        user_id = int(params.get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return f_responseJson({"code": 0, "msg": MSG_USER_ID_REQUIRED})

    target = User.objects.filter(id=user_id).first()
    if not target:
        return f_responseJson({"code": 0, "msg": MSG_USER_NOT_FOUND})

    perm_obj = UserPermission.objects.filter(user_id=user_id).first()
    perms = {}
    if perm_obj and str(getattr(perm_obj, "permissions_json", "") or "").strip():
        try:
            loaded = json.loads(str(getattr(perm_obj, "permissions_json", "") or "").strip())
            perms = normalize_permissions_dict(loaded)
        except Exception:
            perms = {}

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "user_id": user_id,
                "username": str(getattr(target, "username", "") or ""),
                "permission_keys": list(PERMISSION_KEYS),
                "permissions": perms,
            },
        }
    )


def _parse_permissions_payload(raw_json):
    """解析`permissions`载荷。"""
    if raw_json is None:
        return {}, ""
    if isinstance(raw_json, dict):
        return raw_json, ""

    text = str(raw_json or "").strip()
    if not text:
        return {}, ""
    try:
        loaded = json.loads(text)
    except Exception:
        return None, "permissions_json is invalid json"
    if isinstance(loaded, dict):
        return loaded, ""
    return {}, ""


@require_admin
def api_set_user_permissions(request):
    """处理 `set_user_permissions` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    try:
        user_id = int(params.get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return f_responseJson({"code": 0, "msg": MSG_USER_ID_REQUIRED})

    raw_json = params.get("permissions_json")
    if raw_json is None:
        raw_json = params.get("permissions")

    perms_in, err = _parse_permissions_payload(raw_json)
    if err:
        return f_responseJson({"code": 0, "msg": err})

    perms = normalize_permissions_dict(perms_in)
    target = User.objects.filter(id=user_id).first()
    if not target:
        return f_responseJson({"code": 0, "msg": MSG_USER_NOT_FOUND})

    obj = UserPermission.objects.filter(user_id=user_id).first()
    if not obj:
        obj = UserPermission(user_id=user_id)
    obj.permissions_json = json.dumps(perms, ensure_ascii=False)
    obj.save()
    return f_responseJson({"code": 1000, "msg": "success"})


@require_admin
def api_delete_user(request):
    """处理 `delete_user` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
        user_id = int(params.get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return f_responseJson({"code": 0, "msg": MSG_USER_ID_REQUIRED})

    current_user = _session_user(request)
    if int(current_user.get("id") or 0) == user_id:
        return f_responseJson({"code": 0, "msg": "cannot delete current user"})

    user = User.objects.filter(id=user_id).first()
    if not user:
        return f_responseJson({"code": 0, "msg": MSG_USER_NOT_FOUND})

    username = user.username
    user.delete()
    return f_responseJson({"code": 1000, "msg": f"deleted {username}"})


@require_admin
def api_get_user_detail(request):
    """处理 `get_user_detail` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED, "data": {}})

    try:
        params = f_parsePostParams(request)
        user_id = int(params.get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return f_responseJson({"code": 0, "msg": MSG_USER_ID_REQUIRED, "data": {}})

    user = User.objects.filter(id=user_id).first()
    if not user:
        return f_responseJson({"code": 0, "msg": MSG_USER_NOT_FOUND, "data": {}})

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "id": user.id,
                "username": user.username,
                "email": user.email or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "is_active": bool(user.is_active),
                "is_staff": bool(user.is_staff),
                "is_superuser": bool(user.is_superuser),
                "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S"),
                "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else "never",
            },
        }
    )


def _parse_user_ids_list(value):
    """解析用户`ids`列表。"""
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                loaded = json.loads(text)
                return loaded if isinstance(loaded, list) else []
            except Exception:
                return [x.strip() for x in text.split(",") if x.strip()]
        return [x.strip() for x in text.split(",") if x.strip()]

    return []


def _normalize_user_ids(user_ids, *, current_user_id: int):
    """执行归一化用户`ids`。"""
    normalized = []
    for item in user_ids or []:
        try:
            value = int(item)
        except Exception:
            continue
        if value != current_user_id:
            normalized.append(value)
    return normalized


@require_admin
def api_batch_delete_users(request):
    """处理 `batch_delete_users` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    user_ids = _parse_user_ids_list(params.get("user_ids", []))
    if not isinstance(user_ids, list) or not user_ids:
        return f_responseJson({"code": 0, "msg": "user_ids is required"})

    current_user_id = int((_session_user(request) or {}).get("id") or 0)
    normalized_ids = _normalize_user_ids(user_ids, current_user_id=current_user_id)
    if not normalized_ids:
        return f_responseJson({"code": 0, "msg": "cannot delete current user"})

    deleted_count = User.objects.filter(id__in=normalized_ids).delete()[0]
    return f_responseJson({"code": 1000, "msg": f"deleted {deleted_count} users"})


@require_admin
def api_toggle_user_status(request):
    """处理 `toggle_user_status` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
        user_id = int(params.get("user_id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return f_responseJson({"code": 0, "msg": MSG_USER_ID_REQUIRED})

    current_user_id = int((_session_user(request) or {}).get("id") or 0)
    if current_user_id == user_id:
        return f_responseJson({"code": 0, "msg": "cannot disable current user"})

    user = User.objects.filter(id=user_id).first()
    if not user:
        return f_responseJson({"code": 0, "msg": MSG_USER_NOT_FOUND})

    user.is_active = not bool(user.is_active)
    user.save(update_fields=["is_active"])
    return f_responseJson({"code": 1000, "msg": "success"})
