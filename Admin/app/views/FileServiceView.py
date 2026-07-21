import logging
import mimetypes
import os
from urllib.parse import quote

from django.http import FileResponse, HttpResponse

from app.views.ViewsBase import g_config


logger = logging.getLogger(__name__)


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
    return rel, resolve_under_base(root, rel)


def _build_local_file_response(abs_path: str):
    """构建本地文件流响应。"""
    if not os.path.isfile(abs_path):
        return HttpResponse(status=404)

    try:
        content_type, _encoding = mimetypes.guess_type(abs_path)
        if not content_type:
            content_type = "application/octet-stream"

        f = open(abs_path, "rb")
        resp = FileResponse(f, content_type=content_type)
        try:
            resp["Content-Length"] = str(os.path.getsize(abs_path))
        except Exception:
            logger.debug("set recording file content length failed path=%s", abs_path, exc_info=True)
        resp["Content-Disposition"] = 'inline; filename="%s"' % os.path.basename(abs_path)
        return resp
    except Exception as e:
        logger.exception("file service file error: err=%s", e)
        return HttpResponse(status=500)


def open_serve(request, rel_path: str):
    """处理开放文件服务。"""
    if request.method != "GET":
        return HttpResponse(status=405)

    if not _file_service_root_dir():
        return HttpResponse(status=404)

    try:
        _rel, abs_path = _resolve_abs_path(rel_path)
    except Exception as e:
        logger.warning("open_serve invalid path: err=%s", e)
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
    except Exception as e:
        logger.warning("recording_session_serve invalid path: err=%s", e)
        return HttpResponse(status=400)

    return _build_local_file_response(abs_path)
