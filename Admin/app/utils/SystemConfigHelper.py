from app.models import SystemConfig
from typing import Optional


def get_value(key: str, default: str = "") -> str:
    """获取值。"""
    try:
        item = SystemConfig.objects.filter(key=key).first()
        if not item:
            return default
        return str(item.value)
    except Exception:
        return default


def get_bool(key: str, default: bool = False) -> bool:
    """获取布尔值。"""
    value = str(get_value(key, "1" if default else "0")).strip().lower()
    return value in ("1", "true", "yes", "y", "on")


def get_int(key: str, default: int = 0, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """获取整数值。"""
    try:
        value = int(str(get_value(key, str(default))).strip())
    except Exception:
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def set_value(key: str, value: str, remark: str = "") -> None:
    """设置值。"""
    obj, created = SystemConfig.objects.get_or_create(
        key=key,
        defaults={"value": str(value), "remark": remark or ""},
    )
    if not created:
        obj.value = str(value)
        if remark:
            obj.remark = remark
        obj.save()
