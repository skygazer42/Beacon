import logging
import mimetypes
import os
import stat
from urllib.parse import quote

from django.http import FileResponse, HttpResponse
from django.utils.http import content_disposition_header
from django.utils.text import get_valid_filename

from app.views.ViewsBase import g_config


logger = logging.getLogger(__name__)
_INLINE_MEDIA_PREFIXES = ("audio/", "video/")
_INLINE_IMAGE_TYPES = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})


def _file_service_root_dir() -> str:
    """返回文件服务根目录。"""
    enabled = bool(getattr(g_config, "fileServiceEnabled", False))
    root = str(getattr(g_config, "fileServiceRootDir", "") or "").strip()
    if not enabled:
        return ""
    return root


def build_recording_session_proxy_path(rel_path: str) -> str:
    """返回本地录播会话代理路径。"""
    return f"/recording/file/{quote(str(rel_path or '').strip(), safe='/')}"


def build_recording_session_proxy_url(request, rel_path: str) -> str:
    """返回本地录播会话代理 URL。"""
    scheme = "https" if bool(getattr(request, "is_secure", lambda: False)()) else "http"
    host = str(getattr(request, "get_host", lambda: "")() or "").strip() or "127.0.0.1"
    return f"{scheme}://{host}{build_recording_session_proxy_path(rel_path)}"


def _resolve_abs_path(rel_path: str, *, required_prefix: str | None = None):
    """校验并解析文件绝对路径。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    rel = validate_upload_rel_path(rel_path, required_prefix=required_prefix)
    root = _file_service_root_dir()
    if not root:
        raise FileNotFoundError("file service is disabled")
    target = resolve_under_base(root, rel)
    real_root = os.path.realpath(os.path.abspath(root))
    real_target = os.path.realpath(target)
    if os.path.commonpath((real_root, real_target)) != real_root:
        raise ValueError("file path escapes the configured root")
    return rel, real_target


def _open_regular_file_no_follow(abs_path: str):
    if os.path.islink(abs_path):
        raise OSError("symbolic links are not served")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(abs_path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("requested path is not a regular file")
        return os.fdopen(descriptor, "rb"), int(file_stat.st_size)
    except Exception:
        os.close(descriptor)
        raise


def _build_local_file_response(abs_path: str):
    """构建本地文件流响应。"""
    try:
        f, file_size = _open_regular_file_no_follow(abs_path)
    except (OSError, ValueError):
        return HttpResponse(status=404)

    try:
        content_type, _encoding = mimetypes.guess_type(abs_path)
        content_type = str(content_type or "").lower()
        inline = content_type.startswith(_INLINE_MEDIA_PREFIXES) or content_type in _INLINE_IMAGE_TYPES
        if not inline:
            content_type = "application/octet-stream"

        resp = FileResponse(f, content_type=content_type)
        resp["Content-Length"] = str(file_size)
        filename = get_valid_filename(os.path.basename(abs_path)) or "download.bin"
        resp["Content-Disposition"] = content_disposition_header(not inline, filename)
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return resp
    except Exception as e:
        try:
            f.close()
        except Exception:
            pass
        logger.exception("file service file error: error_type=%s", type(e).__name__)
        return HttpResponse(status=500)


def _managed_upload_root_dir() -> str:
    return str(getattr(g_config, "uploadDir", "") or "").strip()


def _resolve_managed_upload_abs_path(rel_path: str) -> str:
    """Resolve a mutable upload path without allowing traversal or symlink escape."""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    root = _managed_upload_root_dir()
    if not root:
        raise FileNotFoundError("managed upload storage is not configured")
    rel = validate_upload_rel_path(rel_path)
    target = resolve_under_base(root, rel)
    real_root = os.path.realpath(root)
    real_target = os.path.realpath(target)
    if os.path.commonpath((real_root, real_target)) != real_root:
        raise ValueError("managed upload path escapes storage root")
    return real_target


def managed_upload_serve(request, rel_path: str):
    """Serve authenticated mutable uploads kept outside immutable static files."""
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405)
    try:
        abs_path = _resolve_managed_upload_abs_path(rel_path)
    except (FileNotFoundError, ValueError):
        return HttpResponse(status=404)
    except Exception:
        logger.exception("managed upload path resolution failed")
        return HttpResponse(status=500)

    response = _build_local_file_response(abs_path)
    if response.status_code == 200:
        response["Cache-Control"] = "private, max-age=300"
    return response


def open_serve(request, rel_path: str):
    """处理开放文件服务。"""
    if request.method != "GET":
        return HttpResponse(status=405)

    if not _file_service_root_dir():
        return HttpResponse(status=404)

    try:
        _rel, abs_path = _resolve_abs_path(rel_path)
    except Exception as exc:
        logger.warning("open_serve invalid path: error_type=%s", type(exc).__name__)
        return HttpResponse(status=400)

    response = _build_local_file_response(abs_path)
    if response.status_code == 404:
        logger.warning("open_serve file not found")
    return response


def recording_session_serve(request, rel_path: str):
    """处理本地录播会话文件代理。"""
    if request.method != "GET":
        return HttpResponse(status=405)

    if not _file_service_root_dir():
        return HttpResponse(status=404)

    try:
        _rel, abs_path = _resolve_abs_path(rel_path, required_prefix="recordings/")
    except Exception as exc:
        logger.warning("recording_session_serve invalid path: error_type=%s", type(exc).__name__)
        return HttpResponse(status=400)

    return _build_local_file_response(abs_path)
