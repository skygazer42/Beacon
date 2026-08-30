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
    if len(raw) > 4096:
        raise ValueError("path is too long")

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise ValueError("path contains control character")

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
    if any(len(part) > 255 for part in parts):
        raise ValueError("path component is too long")

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
    raw_base = str(base_dir or "").strip()
    if not raw_base:
        raise ValueError("base_dir is required")
    base = os.path.realpath(os.path.abspath(raw_base))

    normalized_rel = validate_upload_rel_path(rel_path)
    target = os.path.realpath(os.path.abspath(os.path.join(base, normalized_rel)))

    if os.path.commonpath((base, target)) != base or target == base:
        raise ValueError("path escapes base_dir")

    return target


def resolve_direct_child(base_dir, child_name):
    """Resolve one untrusted filename component directly below ``base_dir``."""

    child = str(child_name or "").strip()
    if not child or child in (".", ".."):
        raise ValueError("child name is invalid")
    if (
        len(child) > 255
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in child)
        or any(ch in child for ch in ("/", "\\"))
        or os.path.splitdrive(child)[0]
    ):
        raise ValueError("child name is invalid")

    raw_base = str(base_dir or "").strip()
    if not raw_base:
        raise ValueError("base_dir is required")
    base = os.path.realpath(os.path.abspath(raw_base))
    target = os.path.realpath(os.path.join(base, child))
    if os.path.commonpath([base, target]) != base or target == base:
        raise ValueError("child escapes base_dir")
    return target
