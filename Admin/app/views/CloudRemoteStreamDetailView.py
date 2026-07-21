from django.shortcuts import render

from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError
from app.utils.CloudRemotePermissions import (
    PERM_CLOUD_REMOTE_STREAMS_MANAGE,
    PERM_CLOUD_REMOTE_STREAMS_VIEW,
)
from app.views.CloudConsoleView import (
    _FLASH_KEY_CLOUD_REMOTE_STREAM_DETAIL,
    _consume_cloud_flash,
    _forbidden,
    _get_cloud_auth,
    _get_cluster_for_auth,
    _has_perm,
    _not_found,
    _require_cloud_mode,
)

REMOTE_STREAM_DETAIL_TEMPLATE = "app/cloud/remote_stream_detail.html"


def _stream_detail_auth_or_resp(request):
    """处理流详情认证`or``resp`。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return (
                None,
                render(
                    request,
                    REMOTE_STREAM_DETAIL_TEMPLATE,
                    {
                        "cluster": {},
                        "selected_code": "",
                        "stream": {},
                        "top_msg": "",
                        "error_msg": "",
                        "can_manage": False,
                    },
                ),
            )
        return None, resp

    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return None, _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, PERM_CLOUD_REMOTE_STREAMS_VIEW):
        return None, _forbidden(request, "权限不足：无权查看远程摄像头详情")
    return auth, None


def _parse_stream_detail_params(request):
    """解析流详情参数。"""
    params = request.POST if request.method == "POST" else request.GET
    try:
        cluster_id = int(params.get("cluster_id") or 0)
    except Exception:
        cluster_id = 0
    stream_code = str(params.get("code") or "").strip()
    return cluster_id, stream_code


def _build_stream_detail_context(auth, cluster, stream_code: str):
    """构建流详情`context`。"""
    return {
        "cluster": cluster,
        "selected_code": stream_code,
        "stream": {},
        "top_msg": "",
        "error_msg": "",
        "can_manage": _has_perm(auth, PERM_CLOUD_REMOTE_STREAMS_MANAGE),
    }


def _cluster_has_edge_config(cluster) -> bool:
    """返回集群`has`边缘配置。"""
    return bool(
        str(getattr(cluster, "edge_admin_base_url", "") or "").strip()
        and str(getattr(cluster, "edge_openapi_token", "") or "").strip()
    )


def _build_cloud_edge_client(cluster) -> CloudEdgeClient:
    """构建云端边缘`client`。"""
    return CloudEdgeClient(
        base_url=str(getattr(cluster, "edge_admin_base_url", "") or "").strip(),
        open_api_token=str(getattr(cluster, "edge_openapi_token", "") or "").strip(),
    )


def _handle_stream_detail_post(request, *, client: CloudEdgeClient, context: dict, stream_code: str):
    """处理流详情`post`。"""
    if request.method != "POST":
        return None
    if not context.get("can_manage"):
        return _forbidden(request, "权限不足：无权修改远程摄像头配置")

    payload = {
        "code": stream_code,
        "app": str(request.POST.get("app") or "").strip(),
        "nickname": str(request.POST.get("nickname") or "").strip(),
        "remark": str(request.POST.get("remark") or "").strip(),
        "pull_stream_url": str(request.POST.get("pull_stream_url") or "").strip(),
        "pull_stream_type": str(request.POST.get("pull_stream_type") or "").strip(),
    }
    try:
        client.edit_stream(payload)
        context["top_msg"] = "保存成功"
    except CloudEdgeClientError as e:
        context["error_msg"] = str(e)
    return None


def _load_stream_detail(client: CloudEdgeClient, context: dict, stream_code: str) -> None:
    """加载流详情。"""
    if not stream_code:
        return
    try:
        context["stream"] = client.get_stream(stream_code)
    except CloudEdgeClientError as e:
        context["error_msg"] = str(e)


def _resolve_stream_detail_flash(request, stream_code: str) -> tuple[str, dict]:
    """Return the selected stream code and any GET flash context."""
    if request.method != "GET":
        return stream_code, {}
    flash_context = _consume_cloud_flash(request, _FLASH_KEY_CLOUD_REMOTE_STREAM_DETAIL)
    flash_code = str(flash_context.get("selected_code") or "").strip()
    return (flash_code if not stream_code and flash_code else stream_code), flash_context


def _apply_stream_detail_flash(context: dict, flash_context: dict) -> None:
    """Apply top/error messages from consumed flash context."""
    for key in ("top_msg", "error_msg"):
        if flash_context.get(key):
            context[key] = str(flash_context.get(key) or "")


def stream_detail(request):
    """处理流详情。"""
    auth, resp = _stream_detail_auth_or_resp(request)
    if resp:
        return resp

    cluster_id, stream_code = _parse_stream_detail_params(request)
    cluster = _get_cluster_for_auth(auth, cluster_id)
    if not cluster:
        return _not_found()

    stream_code, flash_context = _resolve_stream_detail_flash(request, stream_code)

    context = _build_stream_detail_context(auth, cluster, stream_code)
    _apply_stream_detail_flash(context, flash_context)

    if not _cluster_has_edge_config(cluster):
        context["error_msg"] = "当前集群未配置远控连接"
        return render(request, REMOTE_STREAM_DETAIL_TEMPLATE, context)

    client = _build_cloud_edge_client(cluster)

    resp = _handle_stream_detail_post(request, client=client, context=context, stream_code=stream_code)
    if resp:
        return resp

    _load_stream_detail(client, context, stream_code)

    return render(request, REMOTE_STREAM_DETAIL_TEMPLATE, context)
