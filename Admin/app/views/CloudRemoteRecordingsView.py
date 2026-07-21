import logging
import os

from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render

from app.models import CloudEdgeCluster
from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError
from app.utils.CloudRemotePermissions import PERM_CLOUD_REMOTE_RECORDINGS_VIEW
from app.views.CloudConsoleView import (
    _filter_clusters_for_auth,
    _forbidden,
    _get_cloud_auth,
    _get_cluster_for_auth,
    _has_perm,
    _not_found,
    _require_cloud_mode,
)
from app.views.ViewsBase import f_parseGetParams



logger = logging.getLogger(__name__)
TEMPLATE_REMOTE_RECORDINGS = "app/cloud/remote_recordings.html"


def _cloud_remote_recordings_int(value, default: int = 0) -> int:
    """处理云端远端`recordings`整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _cluster_has_remote_config(cluster) -> bool:
    """返回集群`has`远端配置。"""
    if not cluster:
        return False
    return bool(
        str(getattr(cluster, "edge_admin_base_url", "") or "").strip()
        and str(getattr(cluster, "edge_openapi_token", "") or "").strip()
    )


def _remote_recordings_context(clusters, cluster_id: int, stream_code: str, cluster) -> dict:
    """处理远端`recordings``context`。"""
    return {
        "clusters": clusters,
        "selected_cluster_id": int(cluster_id or 0),
        "selected_stream_code": str(stream_code or "").strip(),
        "cluster": cluster,
        "rows": [],
        "total": 0,
        "top_msg": "",
    }


def _cloud_edge_client_for_cluster(cluster) -> CloudEdgeClient:
    """获取集群的云端边缘`client`。"""
    return CloudEdgeClient(
        base_url=str(getattr(cluster, "edge_admin_base_url", "") or "").strip(),
        open_api_token=str(getattr(cluster, "edge_openapi_token", "") or "").strip(),
    )


def _absolute_url(request, path: str) -> str:
    """返回当前请求下的绝对 URL。"""
    scheme = "https" if bool(getattr(request, "is_secure", lambda: False)()) else "http"
    host = str(getattr(request, "get_host", lambda: "")() or "").strip() or "127.0.0.1"
    return f"{scheme}://{host}{path}"


def build_cloud_recording_proxy_path(cluster_id: int, rel_path: str) -> str:
    """返回云端远程录像代理路径。"""
    from urllib.parse import quote

    return f"/cloud/remote/recordings/file/{int(cluster_id or 0)}/{quote(str(rel_path or '').strip(), safe='/')}"


def build_cloud_recording_proxy_url(request, cluster_id: int, rel_path: str) -> str:
    """返回云端远程录像代理 URL。"""
    return _absolute_url(request, build_cloud_recording_proxy_path(cluster_id, rel_path))


def _normalize_remote_recording_rel_path(rel_path: str) -> str:
    """规范化远端录像相对路径。"""
    from app.utils.Security import validate_upload_rel_path

    return validate_upload_rel_path(rel_path, required_prefix="recordings/")


def _remote_recording_rows_with_play_urls(request, cluster_id: int, payload: dict):
    """返回带云端代理播放地址的远端录像记录列表。"""
    rows = []
    for item in (payload or {}).get("data") or []:
        row = dict(item or {})
        rel_path = str(row.get("rel_path") or "").strip()
        row["play_url"] = ""
        row["play_error"] = ""
        if not rel_path:
            rows.append(row)
            continue
        try:
            rel = _normalize_remote_recording_rel_path(rel_path)
            row["rel_path"] = rel
            row["play_url"] = build_cloud_recording_proxy_url(request, cluster_id, rel)
        except Exception as e:
            row["play_error"] = str(e)
        rows.append(row)
    return rows


def _iter_remote_stream(remote_response):
    """迭代远端文件流并在结束后关闭连接。"""
    try:
        for chunk in remote_response.iter_content(chunk_size=64 * 1024):
            if chunk:
                yield chunk
    finally:
        try:
            remote_response.close()
        except Exception:
            logger.debug("suppressed exception in app/views/CloudRemoteRecordingsView.py:120", exc_info=True)


def _cloud_remote_recordings_auth_or_resp(request, *, empty_get_template: bool = False):
    """Return cloud auth or an early response for remote recordings views."""
    resp = _require_cloud_mode()
    if resp:
        if empty_get_template and request.method == "GET":
            return None, render(request, TEMPLATE_REMOTE_RECORDINGS, {})
        return None, resp

    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return None, _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, PERM_CLOUD_REMOTE_RECORDINGS_VIEW):
        return None, _forbidden(request, "权限不足：无权访问云平台-远程录像")
    return auth, None


def _remote_recording_cluster_or_resp(auth, cluster_id: int):
    """Return a permitted cluster or a response for invalid recording cluster access."""
    cluster = _get_cluster_for_auth(auth, _cloud_remote_recordings_int(cluster_id, 0))
    if not cluster:
        return None, _not_found()
    if not _cluster_has_remote_config(cluster):
        return None, HttpResponse(status=404)
    return cluster, None


def _remote_recording_response(remote_response, rel: str):
    """Build a streaming response from an edge recording response."""
    content_type = str((remote_response.headers or {}).get("Content-Type") or "application/octet-stream")
    response = StreamingHttpResponse(_iter_remote_stream(remote_response), content_type=content_type)
    content_length = str((remote_response.headers or {}).get("Content-Length") or "").strip()
    if content_length:
        response["Content-Length"] = content_length
    content_disposition = str((remote_response.headers or {}).get("Content-Disposition") or "").strip()
    response["Content-Disposition"] = content_disposition or 'inline; filename="%s"' % os.path.basename(rel)
    return response


def recording_file(request, cluster_id: int, rel_path: str):
    """代理云端远程录像文件。"""
    auth, resp = _cloud_remote_recordings_auth_or_resp(request)
    if resp:
        return resp

    cluster, resp = _remote_recording_cluster_or_resp(auth, cluster_id)
    if resp:
        return resp

    try:
        rel = _normalize_remote_recording_rel_path(rel_path)
    except Exception:
        return HttpResponse(status=400)

    client = _cloud_edge_client_for_cluster(cluster)
    try:
        remote_response = client.stream_file(rel)
    except CloudEdgeClientError as e:
        status_code = int(getattr(e, "status_code", 0) or 0)
        if status_code in (400, 404):
            return HttpResponse(status=status_code)
        return HttpResponse(status=502)

    return _remote_recording_response(remote_response, rel)


def _remote_recordings_selection(request, auth):
    """Return selected recording filters and the permitted cluster list."""
    params = f_parseGetParams(request)
    cluster_id = _cloud_remote_recordings_int(params.get("cluster_id") or 0, 0)
    stream_code = str(params.get("stream_code") or params.get("streamCode") or "").strip()
    clusters = list(_filter_clusters_for_auth(auth, CloudEdgeCluster.objects.all().order_by("id")))
    cluster = _get_cluster_for_auth(auth, cluster_id) if cluster_id > 0 else None
    return clusters, cluster_id, stream_code, cluster


def _load_remote_recordings_context(request, context: dict, cluster, stream_code: str) -> None:
    """Populate remote recording rows into the page context."""
    client = _cloud_edge_client_for_cluster(cluster)
    try:
        payload = client.list_recording_files(stream_code)
        rows = _remote_recording_rows_with_play_urls(request, cluster.id, payload)
        context["rows"] = rows
        context["total"] = int((payload or {}).get("total") or len(rows))
    except CloudEdgeClientError as e:
        context["top_msg"] = str(e)


def index(request):
    """渲染默认页面。"""
    auth, resp = _cloud_remote_recordings_auth_or_resp(request, empty_get_template=True)
    if resp:
        return resp

    clusters, cluster_id, stream_code, cluster = _remote_recordings_selection(request, auth)
    if cluster_id > 0 and not cluster:
        return _not_found()

    context = _remote_recordings_context(clusters, cluster_id, stream_code, cluster)
    if not cluster or not stream_code:
        return render(request, TEMPLATE_REMOTE_RECORDINGS, context)

    if not _cluster_has_remote_config(cluster):
        context["top_msg"] = "当前集群未配置远控连接"
        return render(request, TEMPLATE_REMOTE_RECORDINGS, context)

    _load_remote_recordings_context(request, context, cluster, stream_code)
    return render(request, TEMPLATE_REMOTE_RECORDINGS, context)
