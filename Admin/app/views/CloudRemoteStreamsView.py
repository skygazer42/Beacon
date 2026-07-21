from django.shortcuts import render

from app.models import CloudEdgeCluster
from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError
from app.utils.CloudRemotePermissions import PERM_CLOUD_REMOTE_STREAMS_VIEW
from app.views.CloudConsoleView import (
    _build_cluster_rollout_state,
    _filter_clusters_for_auth,
    _forbidden,
    _get_cloud_auth,
    _get_cluster_for_auth,
    _has_perm,
    _not_found,
    _require_cloud_mode,
)
from app.views.ViewsBase import f_parseGetParams


def _parse_int(value, default: int = 0) -> int:
    """解析整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _resolve_selected_cluster(auth: dict, clusters_qs, cluster_id: int):
    """解析并返回`selected`集群。"""
    selected_cluster = None
    if cluster_id <= 0:
        first_cluster = clusters_qs.first()
        cluster_id = int(getattr(first_cluster, "id", 0) or 0)

    if cluster_id > 0:
        selected_cluster = _get_cluster_for_auth(auth, cluster_id)
        if not selected_cluster:
            return None, cluster_id, _not_found()

    return selected_cluster, cluster_id, None


def _fetch_remote_streams(selected_cluster):
    """获取远端流列表。"""
    if not selected_cluster:
        return "", []
    if not (selected_cluster.edge_admin_base_url and selected_cluster.edge_openapi_token):
        return "当前边缘集群未配置远控连接信息，请先在边缘集群页保存边缘 Admin URL 和 OpenAPI Token。", []
    try:
        client = CloudEdgeClient(
            base_url=selected_cluster.edge_admin_base_url,
            open_api_token=selected_cluster.edge_openapi_token,
        )
        return "", list(client.list_streams() or [])
    except CloudEdgeClientError as e:
        return str(e), []


def streams(request):
    """处理流列表。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return render(request, "app/cloud/remote_streams.html", {})
        return resp

    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, PERM_CLOUD_REMOTE_STREAMS_VIEW):
        return _forbidden(request, "权限不足：无权访问云平台-远程摄像头")

    params = f_parseGetParams(request)
    cluster_id = _parse_int(params.get("cluster_id") or 0, default=0)

    clusters_qs = CloudEdgeCluster.objects.select_related("project", "project__tenant").all().order_by("id")
    clusters_qs = _filter_clusters_for_auth(auth, clusters_qs)
    selected_cluster, cluster_id, error_resp = _resolve_selected_cluster(auth, clusters_qs, cluster_id)
    if error_resp:
        return error_resp

    remote_error, stream_rows = _fetch_remote_streams(selected_cluster)

    context = {
        "clusters": list(clusters_qs),
        "selected_cluster": selected_cluster,
        "selected_cluster_id": int(getattr(selected_cluster, "id", 0) or 0),
        "selected_cluster_rollout": _build_cluster_rollout_state(selected_cluster),
        "remote_error": remote_error,
        "stream_rows": stream_rows,
    }
    return render(request, "app/cloud/remote_streams.html", context)
