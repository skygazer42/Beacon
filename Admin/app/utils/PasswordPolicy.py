import os
from typing import Tuple

from django.contrib.auth.password_validation import validate_password as validate_django_password
from django.core.exceptions import ValidationError


def _env_int(name: str, default: int) -> int:
    """读取环境变量并转换为整数。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def get_password_min_length() -> int:
    """获取`password``min``length`。"""
    value = _env_int("BEACON_PASSWORD_MIN_LENGTH", 8)
    # Keep reasonable bounds to avoid misconfig breaking login/user creation.
    return max(8, min(128, int(value)))


def validate_password(password: str, *, user=None) -> Tuple[bool, str]:
    """校验`password`。
    
    Returns: (ok, msg)
    """
    s = str(password or "")
    min_len = get_password_min_length()
    if len(s) < min_len:
        return False, f"密码长度不能少于{min_len}位"
    try:
        validate_django_password(s, user=user)
    except ValidationError as exc:
        return False, "；".join(exc.messages)
    return True, ""
