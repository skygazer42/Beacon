def coerce_permission_bool(value) -> bool:
    """处理`coerce`权限布尔值。
    
    Parse permission values safely and avoid bool("false") pitfalls.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off", ""):
            return False
    return False
