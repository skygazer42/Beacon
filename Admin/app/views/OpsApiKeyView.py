# ========== API Key 管理（工业交付：多 Key + 轮换/吊销/过期/作用域）==========

import hashlib
import json
import os
import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.utils import timezone

from app.views.ViewsBase import f_parsePostParams, f_responseJson, getUser

MSG_METHOD_NOT_SUPPORTED = "请求方法不支持"


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


def _deny(request, *, json_mode: bool):
    """处理拒绝。"""
    msg = "权限不足，仅管理员可访问"
    if json_mode:
        return f_responseJson({"code": 403, "msg": msg})
    return render(request, "app/message.html", {"msg": msg, "is_success": False, "redirect_url": "/"})


def _hash_token(token: str) -> str:
    """返回哈希令牌。"""
    pepper = str(os.environ.get("BEACON_API_KEY_PEPPER", "") or "")
    raw = (pepper + str(token or "")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _token_prefix(token: str, *, n: int = 8) -> str:
    """返回令牌前缀。"""
    try:
        s = str(token or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    try:
        n = int(n or 8)
    except Exception:
        n = 8
    n = max(4, min(16, n))
    return s[:n]


def _parse_scopes_json(raw) -> list:
    """解析`scopes`JSON。"""
    try:
        s = str(raw or "").strip()
    except Exception:
        return []
    if not s:
        return []
    try:
        loaded = json.loads(s)
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    scopes = []
    for item in loaded:
        scope = str(item or "").strip()
        if scope:
            scopes.append(scope)
    return scopes


def _serialize_api_key_row(r) -> dict:
    """返回`serialize`API键记录。"""
    return {
        "id": getattr(r, "id", None),
        "name": getattr(r, "name", ""),
        "token_prefix": getattr(r, "token_prefix", ""),
        "enabled": bool(getattr(r, "enabled", False)),
        "scopes": _parse_scopes_json(getattr(r, "scopes_json", "")),
        "expires_at": getattr(r, "expires_at", None),
        "revoked_at": getattr(r, "revoked_at", None),
        "last_used_at": getattr(r, "last_used_at", None),
        "created_by": getattr(r, "created_by", ""),
        "create_time": getattr(r, "create_time", None),
        "rate_limit_per_minute": int(getattr(r, "rate_limit_per_minute", 0) or 0),
        "burst_limit": int(getattr(r, "burst_limit", 0) or 0),
    }


_KNOWN_SCOPES = ("ops", "openapi")

def _scopes_in_from_param(raw_scopes):
    """从参数获取`scopes``in`。"""
    if isinstance(raw_scopes, list):
        return raw_scopes, None

    s = str(raw_scopes or "").strip()
    if not s:
        return [], None

    try:
        loaded = json.loads(s)
    except Exception:
        return [], "scopes 必须为 JSON array"

    if not isinstance(loaded, list):
        return [], "scopes 必须为 JSON array"

    return loaded, None


def _normalize_scopes(scopes_in):
    """执行归一化`scopes`。"""
    scopes = []
    seen = set()
    for item in scopes_in or []:
        key = str(item or "").strip()
        if not key:
            continue
        if key not in _KNOWN_SCOPES:
            continue
        if key in seen:
            continue
        seen.add(key)
        scopes.append(key)

    return scopes


def _parse_scopes_param(raw_scopes):
    """解析`scopes`参数。"""
    scopes_in, err = _scopes_in_from_param(raw_scopes)
    if err:
        return [], err

    scopes = _normalize_scopes(scopes_in)
    return (scopes or ["ops"]), None


def _parse_expires_at(raw_expires_days):
    """解析`expires``at`。"""
    s = str(raw_expires_days or "").strip()
    if not s:
        return None
    try:
        days = int(s)
    except Exception:
        days = 0
    days = max(1, min(3650, days))
    return timezone.now() + timedelta(days=days)


def _parse_limit_param(raw_value, *, default: int = 0, min_value: int = 0, max_value: int = 100000) -> int:
    """解析`limit`参数。"""
    try:
        out = int(str(raw_value or "").strip() or default)
    except Exception:
        out = int(default)
    if out < min_value:
        out = min_value
    if out > max_value:
        out = max_value
    return out


def _parse_rate_limits(params):
    """解析`rate``limits`。"""
    rate_limit_per_minute = _parse_limit_param(params.get("rate_limit_per_minute"), default=0)
    burst_limit = _parse_limit_param(params.get("burst_limit"), default=0)
    return rate_limit_per_minute, burst_limit


def _create_api_key_row(
    user,
    *,
    name: str,
    token_plain: str,
    scopes: list,
    expires_at,
    rate_limit_per_minute: int,
    burst_limit: int,
):
    """创建API键记录。"""
    from app.models import ApiKey

    try:
        row = ApiKey.objects.create(
            name=name,
            token_prefix=_token_prefix(token_plain),
            token_hash=_hash_token(token_plain),
            scopes_json=json.dumps(scopes, ensure_ascii=False),
            rate_limit_per_minute=rate_limit_per_minute,
            burst_limit=burst_limit,
            enabled=True,
            expires_at=expires_at,
            revoked_at=None,
            created_by=str(user.get("username") or user.get("name") or "").strip(),
        )
        return row, None
    except Exception as e:
        return None, str(e)



def index(request):
    """渲染默认页面。"""
    user = getUser(request)
    if not user:
        return redirect("/login")

    db_user = _get_db_user(request)
    if not _is_admin(db_user):
        return _deny(request, json_mode=False)

    return render(request, "app/ops/apikeys.html", {"user": user, "known_scopes": list(_KNOWN_SCOPES)})


def api_list(request):
    """处理 `list` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    user = getUser(request)
    if not user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})

    db_user = _get_db_user(request)
    if not _is_admin(db_user):
        return _deny(request, json_mode=True)

    from app.models import ApiKey

    rows = list(ApiKey.objects.all().order_by("-id")[:500])
    data = [_serialize_api_key_row(r) for r in rows]

    return f_responseJson({"code": 1000, "msg": "success", "data": data})


def api_create(request):
    """处理 `create` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    user = getUser(request)
    if not user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})

    db_user = _get_db_user(request)
    if not _is_admin(db_user):
        return _deny(request, json_mode=True)

    params = f_parsePostParams(request)
    name = str(params.get("name", "") or "").strip()
    if not name:
        return f_responseJson({"code": 0, "msg": "name 不能为空"})

    scopes, err = _parse_scopes_param(params.get("scopes"))
    if err:
        return f_responseJson({"code": 0, "msg": str(err)})

    expires_at = _parse_expires_at(params.get("expires_days"))
    rate_limit_per_minute, burst_limit = _parse_rate_limits(params)

    token_plain = secrets.token_urlsafe(32)
    row, err = _create_api_key_row(
        user,
        name=name,
        token_plain=token_plain,
        scopes=scopes,
        expires_at=expires_at,
        rate_limit_per_minute=rate_limit_per_minute,
        burst_limit=burst_limit,
    )
    if err:
        return f_responseJson({"code": 0, "msg": str(err)})

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "id": getattr(row, "id", None),
                "name": getattr(row, "name", ""),
                "token": token_plain,  # only returned once
                "token_prefix": getattr(row, "token_prefix", ""),
                "scopes": scopes,
                "expires_at": getattr(row, "expires_at", None),
                "rate_limit_per_minute": int(getattr(row, "rate_limit_per_minute", 0) or 0),
                "burst_limit": int(getattr(row, "burst_limit", 0) or 0),
            },
        }
    )


def api_revoke(request):
    """处理 `revoke` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    user = getUser(request)
    if not user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})

    db_user = _get_db_user(request)
    if not _is_admin(db_user):
        return _deny(request, json_mode=True)

    params = f_parsePostParams(request)
    try:
        key_id = int(params.get("id") or 0)
    except Exception:
        key_id = 0

    if key_id <= 0:
        return f_responseJson({"code": 0, "msg": "id is required"})

    from app.models import ApiKey

    row = ApiKey.objects.filter(id=key_id).first()
    if not row:
        return f_responseJson({"code": 0, "msg": "not found"})

    try:
        row.enabled = False
        row.revoked_at = timezone.now()
        row.save()
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    return f_responseJson({"code": 1000, "msg": "success"})


def api_rotate(request):
    """处理 `rotate` 接口请求。
    
    Rotate an existing key: keep the same key row, but replace the token hash.
        The old token becomes invalid immediately.
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    user = getUser(request)
    if not user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})

    db_user = _get_db_user(request)
    if not _is_admin(db_user):
        return _deny(request, json_mode=True)

    params = f_parsePostParams(request)
    try:
        key_id = int(params.get("id") or 0)
    except Exception:
        key_id = 0

    if key_id <= 0:
        return f_responseJson({"code": 0, "msg": "id is required"})

    from app.models import ApiKey

    row = ApiKey.objects.filter(id=key_id).first()
    if not row:
        return f_responseJson({"code": 0, "msg": "not found"})

    token_plain = secrets.token_urlsafe(32)
    try:
        row.token_prefix = _token_prefix(token_plain)
        row.token_hash = _hash_token(token_plain)
        row.enabled = True
        row.revoked_at = None
        row.save()
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "id": getattr(row, "id", None),
                "token": token_plain,  # only returned once
                "token_prefix": getattr(row, "token_prefix", ""),
            },
        }
    )
