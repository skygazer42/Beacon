import os
import re
import posixpath


def validate_control_code(value):
    """校验控制编码。"""
    control_code = str(value or "").strip()
    if not control_code:
        raise ValueError("control_code is required")
    if len(control_code) > 64:
        raise ValueError("control_code is too long")
    if control_code[0] == ".":
        raise ValueError("control_code is invalid")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", control_code):
        raise ValueError("control_code is invalid")
    return control_code


def _validate_upload_rel_path_basic(raw: str) -> str:
    """校验上传相对路径路径`basic`。"""
    if not raw:
        raise ValueError("path is required")

    if "\x00" in raw:
        raise ValueError("path contains null byte")

    raw = raw.replace("\\", "/")
    if raw.startswith("/"):
        raise ValueError("absolute paths are not allowed")
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError("windows absolute paths are not allowed")
    if ":" in raw:
        raise ValueError("path contains invalid character")

    norm = posixpath.normpath(raw)
    if norm in (".", ".."):
        raise ValueError("path is invalid")

    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if not parts:
        raise ValueError("path is invalid")
    if any(p == ".." for p in parts):
        raise ValueError("path traversal is not allowed")

    return "/".join(parts)


def _validate_upload_prefix(normalized: str, required_prefix) -> None:
    """校验上传前缀。"""
    if not required_prefix:
        return
    prefix = str(required_prefix or "").replace("\\", "/").lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    if prefix and not normalized.startswith(prefix):
        raise ValueError("path prefix is invalid")


def validate_upload_rel_path(value, required_prefix=None):
    """校验上传相对路径路径。"""
    normalized = _validate_upload_rel_path_basic(str(value or "").strip())
    _validate_upload_prefix(normalized, required_prefix)
    return normalized


def resolve_under_base(base_dir, rel_path):
    """解析并返回低于基础。"""
    base = os.path.abspath(str(base_dir or ""))
    if not base:
        raise ValueError("base_dir is required")

    normalized_rel = validate_upload_rel_path(rel_path)
    target = os.path.abspath(os.path.join(base, normalized_rel))

    base_with_sep = base if base.endswith(os.sep) else base + os.sep
    if not target.startswith(base_with_sep):
        raise ValueError("path escapes base_dir")

    return target
