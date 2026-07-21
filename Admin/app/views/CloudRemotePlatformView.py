from django.shortcuts import render

from app.models import CloudEdgeCluster
from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError
from app.utils.CloudRemotePermissions import PERM_CLOUD_REMOTE_PLATFORM_VIEW
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


def _parse_int(value, default: int = 0) -> int:
    """解析整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _fetch_remote_platform_data(selected_cluster):
    """获取远端`platform`数据。"""
    if not selected_cluster:
        return "", [], [], {}

    if not (
        str(getattr(selected_cluster, "edge_admin_base_url", "") or "").strip()
        and str(getattr(selected_cluster, "edge_openapi_token", "") or "").strip()
    ):
        return "当前集群未配置远控连接", [], [], {}

    try:
        client = CloudEdgeClient(
            base_url=str(selected_cluster.edge_admin_base_url or "").strip(),
            open_api_token=str(selected_cluster.edge_openapi_token or "").strip(),
        )
        algorithm_flows = client.list_algorithm_flows()
        core_payload = client.list_core_processes() or {}
        core_process_data = list(core_payload.get("data") or [])
        core_process_info = core_payload.get("info") or {}
        return "", algorithm_flows, core_process_data, core_process_info
    except CloudEdgeClientError as e:
        return str(e), [], [], {}


def platform(request):
    """处理`platform`。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return render(request, "app/cloud/remote_platform.html", {})
        return resp

    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, PERM_CLOUD_REMOTE_PLATFORM_VIEW):
        return _forbidden(request, "权限不足：无权访问远程平台页面")

    params = f_parseGetParams(request)
    selected_cluster_id = _parse_int(params.get("cluster_id") or 0, default=0)

    clusters = list(_filter_clusters_for_auth(auth, CloudEdgeCluster.objects.all().order_by("id")))
    selected_cluster = None
    algorithm_flows = []
    core_process_data = []
    core_process_info = {}
    remote_error = ""

    if selected_cluster_id > 0:
        selected_cluster = _get_cluster_for_auth(auth, selected_cluster_id)
        if not selected_cluster:
            return _not_found()
        remote_error, algorithm_flows, core_process_data, core_process_info = _fetch_remote_platform_data(selected_cluster)

    context = {
        "clusters": clusters,
        "selected_cluster_id": selected_cluster_id,
        "selected_cluster": selected_cluster,
        "algorithm_flows": algorithm_flows,
        "core_process_data": core_process_data,
        "core_process_info": core_process_info,
        "remote_error": remote_error,
    }
    return render(request, "app/cloud/remote_platform.html", context)
