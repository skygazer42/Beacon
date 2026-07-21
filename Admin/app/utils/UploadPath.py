import os
import re
from typing import List


_WIN_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def looks_like_windows_drive_path(value: str) -> bool:
    """返回外观`like``windows``drive`路径。
    
    True if value looks like a Windows absolute drive path: C:\\... or C:/...
    """
    if not value:
        return False
    return bool(_WIN_DRIVE_RE.match(str(value)))


def resolve_upload_url_to_abs_path(
    value: str,
    *,
    upload_dir: str,
    upload_www_prefix: str = "/static/upload/",
) -> str:
    """解析并返回上传URL`to`绝对路径路径。
    
    Convert an upload URL (e.g. /static/upload/models/a.onnx) into an absolute filesystem path.
    
        Rules:
        - If value is an absolute path (POSIX abs or Windows drive abs), return normalized value.
        - If value starts with upload_www_prefix, strip it and join to upload_dir.
        - If value is a relative path (e.g. models/a.onnx), join to upload_dir.
        - Empty/None => empty string.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    # URL form: /static/upload/...  (must be checked BEFORE os.path.isabs)
    prefix = str(upload_www_prefix or "").strip() or "/static/upload/"
    if raw.startswith(prefix):
        rel = raw[len(prefix):].lstrip("/\\")
        return os.path.normpath(os.path.join(str(upload_dir or "").strip(), rel))

    # Already a filesystem path
    if os.path.isabs(raw) or looks_like_windows_drive_path(raw):
        return os.path.normpath(raw)

    # Relative "models/xxx" form
    rel = raw.lstrip("/\\")
    return os.path.normpath(os.path.join(str(upload_dir or "").strip(), rel))


def split_paired_path(value: str) -> List[str]:
    """拆分`paired`路径。
    
    AlgorithmModel.model_path may store paired files as "main|paired" (OpenVINO xml+bin, YOLO weights+cfg).
        This helper splits and filters empty segments.
    """
    raw = str(value or "")
    parts = [p.strip() for p in raw.split("|")]
    return [p for p in parts if p]
