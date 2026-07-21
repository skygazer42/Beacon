import json
from typing import Any, Dict, Iterable, Mapping


_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "base64",
    "b64",
    "signature",
    "authorization",
    "access_key",
    "secret_key",
    "private_key",
    "license",
)


def _is_sensitive_key(key: str) -> bool:
    """判断敏感键。"""
    try:
        k = str(key).lower()
    except Exception:
        return False
    return any(fragment in k for fragment in _SENSITIVE_KEY_FRAGMENTS)


def truncate_text(text: str, max_len: int = 256) -> str:
    """处理`truncate`文本。"""
    if max_len < 8:
        max_len = 8
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"...(len={len(s)})"


def _preview_mapping(value: Mapping, *, max_len: int, max_items: int) -> Any:
    """处理`preview``mapping`。"""
    out: Dict[str, Any] = {}
    try:
        items = list(value.items())
    except Exception:
        return truncate_text(repr(value), max_len=max_len)

    for k, v in items[:max_items]:
        key = str(k)
        out[key] = "***" if _is_sensitive_key(key) else safe_preview(v, max_len=max_len, max_items=max_items)

    if len(items) > max_items:
        out["..."] = f"({len(items) - max_items} more keys)"
    return out


def _preview_sequence(value: Iterable, *, max_len: int, max_items: int) -> Any:
    """处理`preview``sequence`。"""
    seq = list(value)
    preview = [safe_preview(v, max_len=max_len, max_items=max_items) for v in seq[:max_items]]
    if len(seq) > max_items:
        preview.append(f"...({len(seq) - max_items} more items)")
    return preview


def safe_preview(value: Any, *, max_len: int = 256, max_items: int = 30) -> Any:
    """处理安全`preview`。
    
    Best-effort sanitization for logs:
        - Truncates large strings
        - Redacts values for sensitive keys in mappings
        - Limits mapping / list sizes
    """
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"<bytes len={len(value)}>"
    if isinstance(value, str):
        return truncate_text(value, max_len=max_len)

    if isinstance(value, Mapping):
        return _preview_mapping(value, max_len=max_len, max_items=max_items)

    if isinstance(value, (list, tuple, set)):
        return _preview_sequence(value, max_len=max_len, max_items=max_items)

    return truncate_text(repr(value), max_len=max_len)


def safe_json_dumps(value: Any, *, max_len: int = 2048, max_items: int = 30) -> str:
    """处理安全JSON`dumps`。
    
    Convert value into a JSON string suitable for logs (best-effort).
    """
    try:
        sanitized = safe_preview(value, max_len=max_len, max_items=max_items)
        text = json.dumps(sanitized, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    return truncate_text(text, max_len=max_len)
