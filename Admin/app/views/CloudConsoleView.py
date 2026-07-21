import json
import os
import secrets

from django.http import HttpResponse
from django.shortcuts import render
from django.contrib.auth.models import User
from django.utils import timezone

from app.models import (
    CloudAlarmEvent,
    CloudEdgeCluster,
    CloudProject,
    CloudRole,
    CloudTenant,
    CloudUserMembership,
)
from app.utils.CloudEdgeAuth import hash_edge_token
from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError
from app.utils.CloudRemotePermissions import CLOUD_REMOTE_PERMISSION_META
from app.utils.DeploymentMode import is_cloud_mode
from app.views.ViewsBase import f_parseGetParams


def _require_cloud_mode():
    """处理需要云端模式。"""
    if not is_cloud_mode():
        return HttpResponse(status=404)
    return None


_PERM_EDGE_CLUSTERS_VIEW = "cloud.edge_clusters.view"
_PERM_EDGE_CLUSTERS_MANAGE = "cloud.edge_clusters.manage"
_PERM_ALARMS_VIEW = "cloud.alarms.view"
_FLASH_KEY_CLOUD_EDGE_CLUSTERS = "_cloud_flash_edge_clusters"
_FLASH_KEY_CLOUD_IAM = "_cloud_flash_iam"
_FLASH_KEY_CLOUD_REMOTE_STREAM_DETAIL = "_cloud_flash_remote_stream_detail"

LABEL_LIVE_ROLLOUT = "Live rollout"
MSG_TENANT_NOT_FOUND = "tenant 不存在"
_EDGE_CLUSTER_MANAGE_ACTIONS = {"create", "toggle", "rotate", "update_remote"}
_IAM_ACTIONS = {"create_tenant", "toggle_tenant", "upsert_role", "upsert_membership", "set_tenant_branding"}

_IAM_PERMISSION_META = [
    {"key": _PERM_EDGE_CLUSTERS_VIEW, "name": "边缘集群-查看", "desc": "允许查看边缘集群列表"},
    {"key": _PERM_EDGE_CLUSTERS_MANAGE, "name": "边缘集群-管理", "desc": "允许创建/启用/禁用/轮换 token"},
    {"key": _PERM_ALARMS_VIEW, "name": "云告警-查看", "desc": "允许查看告警列表/详情/截图代理"},
] + CLOUD_REMOTE_PERMISSION_META


def _perm_field_name(key: str) -> str:
    """返回`perm``field`名称。"""
    return "perm_" + str(key or "").replace(".", "_")


def _parse_int_list_csv(raw: str):
    """解析整数值列表CSV。"""
    if raw is None:
        return []
    s = str(raw or "").strip()
    if not s:
        return []
    out = []
    for token in s.split(","):
        token = str(token or "").strip()
        if not token:
            continue
        try:
            i = int(token)
        except Exception:
            continue
        if i > 0:
            out.append(i)
    # dedupe while keeping deterministic order
    seen = set()
    uniq = []
    for i in out:
        if i in seen:
            continue
        seen.add(i)
        uniq.append(i)
    return uniq


def _parse_json_object(raw: str):
    """解析 JSON 对象。"""
    try:
        s = str(raw or "").strip()
    except Exception:
        s = ""
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except Exception:
        return {}
    if isinstance(obj, dict):
        return obj
    return {}


def _extract_cloud_alarm_stream_code(row) -> str:
    """从云端告警载荷提取视频流编号。"""
    payload = _parse_json_object(getattr(row, "payload_json", ""))
    candidates = [
        payload.get("stream_code"),
        payload.get("streamCode"),
    ]
    for key in ("data", "stream", "alarm"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.extend(
                [
                    nested.get("stream_code"),
                    nested.get("streamCode"),
                    nested.get("code"),
                ]
            )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _parse_rollout_node_versions(raw: str):
    """解析`rollout``node``versions`。"""
    try:
        s = str(raw or "").strip()
    except Exception:
        s = ""
    if not s:
        return []
    try:
        obj = json.loads(s)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []

    rows = []
    for item in obj:
        if not isinstance(item, dict):
            continue
        node_code = str(item.get("node_code") or item.get("node") or item.get("name") or "").strip()
        version = str(item.get("version") or item.get("current_version") or item.get("target_version") or "").strip()
        if not node_code and not version:
            continue
        rows.append(
            {
                "node_code": node_code or "-",
                "version": version or "-",
            }
        )
    return rows


def _normalize_rollout_node_versions_json(raw: str) -> str:
    """执行归一化`rollout``node``versions`JSON。"""
    rows = _parse_rollout_node_versions(raw)
    if not rows:
        return ""
    return json.dumps(rows, ensure_ascii=False)


def _build_cluster_rollout_state(cluster):
    """构建集群`rollout`状态。"""
    if not cluster:
        return {
            "channel": "",
            "status": "",
            "status_label": "Unspecified",
            "status_tone": "default",
            "target_version": "",
            "error": "",
            "node_versions": [],
            "has_rollout": False,
        }

    channel = str(getattr(cluster, "rollout_channel", "") or "").strip()
    status = str(getattr(cluster, "rollout_status", "") or "").strip().lower()
    target_version = str(getattr(cluster, "rollout_target_version", "") or "").strip()
    error = str(getattr(cluster, "rollout_error", "") or "").strip()
    node_versions = _parse_rollout_node_versions(getattr(cluster, "rollout_node_versions_json", ""))

    label_map = {
        "live": (LABEL_LIVE_ROLLOUT, "success"),
        "active": (LABEL_LIVE_ROLLOUT, "success"),
        "success": (LABEL_LIVE_ROLLOUT, "success"),
        "completed": (LABEL_LIVE_ROLLOUT, "success"),
        "pending": ("Pending rollout", "warning"),
        "queued": ("Pending rollout", "warning"),
        "failed": ("Failed rollout", "danger"),
    }
    status_label, status_tone = label_map.get(status, ((status.replace("_", " ").title() or "Unspecified"), "default"))

    return {
        "channel": channel,
        "status": status,
        "status_label": status_label,
        "status_tone": status_tone,
        "target_version": target_version,
        "error": error,
        "node_versions": node_versions,
        "has_rollout": bool(channel or status or target_version or error or node_versions),
    }


def _parse_edge_cluster_ids_from_scope(raw_scope_json: str):
    """解析边缘集群`ids``from`作用域。"""
    scope = _parse_json_object(raw_scope_json)
    ids = scope.get("edge_cluster_ids")
    if not isinstance(ids, list):
        return []

    out = []
    for v in ids:
        try:
            i = int(v)
        except Exception:
            continue
        if i > 0:
            out.append(i)
    # dedupe while keeping deterministic order
    seen = set()
    uniq = []
    for i in out:
        if i in seen:
            continue
        seen.add(i)
        uniq.append(i)
    return uniq


def _session_user_id(request) -> int:
    """返回会话中的用户 ID。"""
    try:
        session = getattr(request, "session", None)
        session_user = session.get("user") if session else None
    except Exception:
        session_user = None

    try:
        return int((session_user or {}).get("id") or 0)
    except Exception:
        return 0


def _get_enabled_membership(user_id: int):
    """获取启用`membership`。"""
    if user_id <= 0:
        return None
    try:
        return (
            CloudUserMembership.objects.select_related("tenant", "role")
            .filter(user_id=user_id, enabled=True, tenant__enabled=True)
            .order_by("-is_default", "id")
            .first()
        )
    except Exception:
        return None


def _resolve_role_perms(tenant, role):
    """解析并返回`role``perms`。"""
    if not tenant or not role:
        return {}
    if not bool(getattr(role, "enabled", False)):
        return {}
    if int(getattr(role, "tenant_id", 0) or 0) != int(getattr(tenant, "id", 0) or 0):
        return {}

    perms = _parse_json_object(getattr(role, "permissions_json", ""))
    return perms if isinstance(perms, dict) else {}


def _get_cloud_auth(request):
    """获取云端认证。
    
    Resolve current cloud tenant + role permissions from the logged-in web session.
    
        Returns:
          {
            ok: bool,
            status: int,
            msg: str,
            is_admin: bool,  # staff/superuser bypass
            user: django User|None,
            tenant: CloudTenant|None,
            role: CloudRole|None,
            perms: dict,
            edge_cluster_ids: list[int],  # resource scope allowlist; empty = no restriction
          }
    """
    user_id = _session_user_id(request)

    db_user = User.objects.filter(id=user_id).first() if user_id > 0 else None
    if db_user and (db_user.is_staff or db_user.is_superuser):
        return {
            "ok": True,
            "status": 200,
            "msg": "",
            "is_admin": True,
            "user": db_user,
            "tenant": None,
            "role": None,
            "perms": {"*": True},
            "edge_cluster_ids": [],
        }

    membership = _get_enabled_membership(user_id)
    if not membership:
        return {
            "ok": False,
            "status": 403,
            "msg": "权限不足：当前账号未绑定租户",
            "is_admin": False,
            "user": db_user,
            "tenant": None,
            "role": None,
            "perms": {},
            "edge_cluster_ids": [],
        }

    tenant = getattr(membership, "tenant", None)
    role = getattr(membership, "role", None)

    return {
        "ok": True,
        "status": 200,
        "msg": "",
        "is_admin": False,
        "user": db_user,
        "tenant": tenant,
        "role": role,
        "perms": _resolve_role_perms(tenant, role),
        "edge_cluster_ids": _parse_edge_cluster_ids_from_scope(getattr(membership, "resource_scope_json", "")),
    }


def _has_perm(auth, key: str) -> bool:
    """检查`perm`。"""
    if not auth or not bool(auth.get("ok")):
        return False
    if bool(auth.get("is_admin")):
        return True
    perms = auth.get("perms") or {}
    if not isinstance(perms, dict):
        return False
    return bool(perms.get(key))


def _forbidden(request, msg: str):
    """处理`forbidden`。"""
    return render(
        request,
        "app/message.html",
        {"msg": msg, "is_success": False, "redirect_url": "/"},
        status=403,
    )


def _not_found():
    """处理`not``found`。"""
    return HttpResponse(status=404)


def _get_or_create_default_project(*, tenant: CloudTenant):
    """获取`or``create`默认`project`。
    
    Minimal bootstrap for v1:
        - If Tenant/Project not created yet, create a default one.
        This avoids blocking the UI on day-0 installs.
    """
    if not tenant:
        raise ValueError("tenant is required")
    project, _ = CloudProject.objects.get_or_create(tenant=tenant, name="default", defaults={"enabled": True})
    return project


def _stash_cloud_flash(request, flash_key: str, payload: dict) -> None:
    """处理`stash`云端`flash`。"""
    session = getattr(request, "session", None)
    if session is None:
        return
    session[flash_key] = payload if isinstance(payload, dict) else {}


def _consume_cloud_flash(request, flash_key: str) -> dict:
    """处理`consume`云端`flash`。"""
    session = getattr(request, "session", None)
    if session is None:
        return {}
    payload = session.pop(flash_key, None)
    return payload if isinstance(payload, dict) else {}


def _filter_clusters_for_auth(auth, queryset):
    """获取认证的`filter``clusters`。"""
    if bool(auth.get("is_admin")):
        return queryset

    tenant = auth.get("tenant")
    if tenant:
        queryset = queryset.filter(project__tenant=tenant)

    allowed = auth.get("edge_cluster_ids") or []
    if allowed:
        queryset = queryset.filter(id__in=allowed)

    return queryset


def _filter_alarms_for_auth(auth, queryset):
    """获取认证的`filter``alarms`。"""
    if bool(auth.get("is_admin")):
        return queryset

    tenant = auth.get("tenant")
    if tenant:
        queryset = queryset.filter(edge_cluster__project__tenant=tenant)

    allowed = auth.get("edge_cluster_ids") or []
    if allowed:
        queryset = queryset.filter(edge_cluster_id__in=allowed)

    return queryset


def _parse_int_clamped(value, *, default: int, min_value: int = None, max_value: int = None) -> int:
    """解析整数值`clamped`。"""
    try:
        out = int(value or default)
    except Exception:
        out = int(default)
    if min_value is not None and out < min_value:
        out = min_value
    if max_value is not None and out > max_value:
        out = max_value
    return out


def _parse_cluster_id(params) -> int:
    """解析集群ID。"""
    raw = str(params.get("cluster_id", "") or "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except Exception:
        return 0


def _paginate_queryset(queryset, *, page: int, page_size: int):
    """执行分页查询集。"""
    from django.core.paginator import Paginator

    paginator = Paginator(queryset, page_size)
    try:
        current_page = paginator.page(page)
    except Exception:
        page = paginator.num_pages
        current_page = paginator.page(page)
    return paginator, current_page, page


def _serialize_cloud_alarm_row(row) -> dict:
    """返回`serialize`云端告警记录。"""
    return {
        "id": row.id,
        "cluster_name": getattr(getattr(row, "edge_cluster", None), "name", "") or "",
        "event_id": row.event_id,
        "desc": row.desc,
        "stream_code": _extract_cloud_alarm_stream_code(row),
        "received_at": row.received_at,
        "has_image": bool(row.image_key),
    }


def _get_cluster_for_auth(auth, cluster_id: int):
    """获取集群`for`认证。"""
    if cluster_id <= 0:
        return None
    cluster = CloudEdgeCluster.objects.select_related("project", "project__tenant").filter(id=cluster_id).first()
    if not cluster:
        return None
    if bool(auth.get("is_admin")):
        return cluster

    tenant = auth.get("tenant")
    allowed = auth.get("edge_cluster_ids") or []
    if not tenant or int(getattr(getattr(cluster, "project", None), "tenant_id", 0) or 0) != int(getattr(tenant, "id", 0) or 0):
        return None
    if allowed and int(getattr(cluster, "id", 0) or 0) not in allowed:
        return None
    return cluster


def _format_heartbeat_age(last_seen_at):
    """处理`format``heartbeat``age`。"""
    if not last_seen_at:
        return "Never reported", None

    now = timezone.now()
    age_seconds = max(0, int((now - last_seen_at).total_seconds()))
    if age_seconds >= 3600:
        hours = age_seconds // 3600
        minutes = (age_seconds % 3600) // 60
        return f"{hours}h {minutes}m ago", age_seconds
    if age_seconds >= 60:
        minutes = age_seconds // 60
        return f"{minutes}m ago", age_seconds
    return f"{age_seconds}s ago", age_seconds


def _cluster_remote_configured(cluster) -> bool:
    """处理集群远端`configured`。"""
    return bool(
        str(getattr(cluster, "edge_admin_base_url", "") or "").strip()
        and str(getattr(cluster, "edge_openapi_token", "") or "").strip()
    )


def _cluster_heartbeat_state(heartbeat_age_seconds):
    """返回集群`heartbeat`状态。"""
    if heartbeat_age_seconds is None:
        return "never"
    if heartbeat_age_seconds > 30 * 60:
        return "stale"
    return "fresh"


def _probe_edge_cluster_ops_health(cluster):
    """处理探测边缘集群运维健康检查。"""
    try:
        client = CloudEdgeClient(
            base_url=str(getattr(cluster, "edge_admin_base_url", "") or "").strip(),
            open_api_token=str(getattr(cluster, "edge_openapi_token", "") or "").strip(),
        )
        remote_data = client.get_ops_health() or {}
        remote_status = str(remote_data.get("status", "") or "").strip() or "ok"
        version = str(remote_data.get("version", "") or "").strip()
        return remote_status, version, ""
    except CloudEdgeClientError as e:
        return "", "", str(e)


def _edge_cluster_health_issues(
    cluster,
    *,
    remote_configured: bool,
    heartbeat_state: str,
    remote_error: str,
    remote_status: str,
):
    """处理边缘集群健康检查`issues`。"""
    issues = []

    if not bool(getattr(cluster, "enabled", False)):
        issues.append("Cluster disabled")

    if heartbeat_state == "stale":
        issues.append("Heartbeat stale")
    elif heartbeat_state == "never":
        issues.append("No heartbeat yet")

    if remote_error:
        issues.append("Remote probe failed")
    elif remote_configured and remote_status and remote_status.lower() != "ok":
        issues.append(f"Remote status: {remote_status}")

    return issues


def _build_edge_cluster_health_row(cluster) -> dict:
    """构建边缘集群健康检查记录。"""
    remote_configured = _cluster_remote_configured(cluster)

    heartbeat_age_text, heartbeat_age_seconds = _format_heartbeat_age(getattr(cluster, "last_seen_at", None))
    heartbeat_state = _cluster_heartbeat_state(heartbeat_age_seconds)

    remote_status = ""
    version = ""
    remote_error = ""
    if remote_configured:
        remote_status, version, remote_error = _probe_edge_cluster_ops_health(cluster)

    issues = _edge_cluster_health_issues(
        cluster,
        remote_configured=remote_configured,
        heartbeat_state=heartbeat_state,
        remote_error=remote_error,
        remote_status=remote_status,
    )

    rollout = _build_cluster_rollout_state(cluster)
    return {
        "cluster": cluster,
        "remote_configured": remote_configured,
        "heartbeat_state": heartbeat_state,
        "heartbeat_age_text": heartbeat_age_text,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "version": version or "-",
        "remote_status": remote_status or ("probe_failed" if remote_error else "unknown"),
        "remote_error": remote_error,
        "issues": issues,
        "is_unhealthy": bool(issues),
        "rollout_channel": rollout.get("channel") or "-",
        "rollout_status": rollout.get("status"),
        "rollout_status_label": rollout.get("status_label"),
        "rollout_status_tone": rollout.get("status_tone"),
        "rollout_target_version": rollout.get("target_version") or "-",
        "rollout_error": rollout.get("error"),
        "rollout_node_versions": rollout.get("node_versions") or [],
        "has_rollout": bool(rollout.get("has_rollout")),
    }


def _build_edge_cluster_health_rows(clusters):
    """构建边缘集群健康检查记录。"""
    rows = []
    summary = {
        "total_count": 0,
        "configured_count": 0,
        "unhealthy_count": 0,
        "stale_heartbeat_count": 0,
    }

    for cluster in clusters or []:
        row = _build_edge_cluster_health_row(cluster)
        rows.append(row)

        summary["total_count"] += 1
        if row.get("remote_configured"):
            summary["configured_count"] += 1
        if row.get("heartbeat_state") == "stale":
            summary["stale_heartbeat_count"] += 1
        if row.get("is_unhealthy"):
            summary["unhealthy_count"] += 1

    top_unhealthy = [row for row in rows if row.get("is_unhealthy")]
    top_unhealthy.sort(
        key=lambda item: (
            len(item.get("issues") or []),
            int(item.get("heartbeat_age_seconds") or 0),
            int(getattr(item.get("cluster"), "id", 0) or 0),
        ),
        reverse=True,
    )
    return rows, summary, top_unhealthy


def _post_int(request, key: str) -> int:
    """发送整数值。"""
    try:
        return int(request.POST.get(key) or 0)
    except Exception:
        return 0


def _post_flag(request, key: str) -> bool:
    """发送标记。"""
    return bool(str(request.POST.get(key, "") or "").strip())


def _iam_role_permissions_from_request(request):
    """从请求获取`iam``role``permissions`。"""
    perms = {}
    for item in _IAM_PERMISSION_META:
        key = str(item.get("key") or "")
        perms[key] = _post_flag(request, _perm_field_name(key))
    return perms


def _iam_branding_from_request(request):
    """从请求获取`iam`品牌。"""
    branding = {}
    field_map = {
        "site_name": "siteName",
        "site_title": "siteTitle",
        "site_logo": "siteLogo",
        "login_bg": "loginBg",
        "theme_color": "themeColor",
    }
    for field_name, branding_key in field_map.items():
        value = str(request.POST.get(field_name, "") or "").strip()
        if value:
            branding[branding_key] = value
    return branding


def _handle_iam_create_tenant(request, context):
    """处理`iam``create`租户。"""
    slug = str(request.POST.get("slug", "") or "").strip()
    name = str(request.POST.get("name", "") or "").strip()
    if not slug:
        context["top_msg"] = "tenant slug 不能为空"
        return
    if not name:
        context["top_msg"] = "tenant name 不能为空"
        return

    tenant, created = CloudTenant.objects.get_or_create(
        slug=slug,
        defaults={"name": name, "enabled": True},
    )
    if not created:
        if tenant.name != name:
            tenant.name = name
            tenant.save(update_fields=["name"])
        context["top_msg"] = f"tenant 已存在：{slug}"
        return

    _get_or_create_default_project(tenant=tenant)
    context["top_msg"] = f"tenant 创建成功：{slug}"


def _handle_iam_toggle_tenant(request, context):
    """处理`iam``toggle`租户。"""
    tenant_id = _post_int(request, "tenant_id")
    tenant = CloudTenant.objects.filter(id=tenant_id).first() if tenant_id > 0 else None
    if not tenant:
        context["top_msg"] = MSG_TENANT_NOT_FOUND
        return
    tenant.enabled = not bool(tenant.enabled)
    tenant.save(update_fields=["enabled"])
    context["top_msg"] = "tenant 状态已更新"


def _handle_iam_upsert_role(request, context):
    """处理`iam``upsert``role`。"""
    tenant_id = _post_int(request, "tenant_id")
    key = str(request.POST.get("key", "") or "").strip()
    name = str(request.POST.get("name", "") or "").strip()
    enabled = _post_flag(request, "enabled")
    if tenant_id <= 0:
        context["top_msg"] = "tenant_id 不能为空"
        return
    if not key:
        context["top_msg"] = "role key 不能为空"
        return
    if not name:
        context["top_msg"] = "role name 不能为空"
        return

    tenant = CloudTenant.objects.filter(id=tenant_id).first()
    if not tenant:
        context["top_msg"] = MSG_TENANT_NOT_FOUND
        return

    obj, created = CloudRole.objects.update_or_create(
        tenant=tenant,
        key=key,
        defaults={
            "name": name,
            "enabled": enabled,
            "permissions_json": json.dumps(_iam_role_permissions_from_request(request), ensure_ascii=False),
        },
    )
    context["top_msg"] = "role 已创建" if created else "role 已更新"
    context["last_role_id"] = getattr(obj, "id", 0) or 0


def _handle_iam_upsert_membership(request, context):
    """处理`iam``upsert``membership`。"""
    user_id = _post_int(request, "user_id")
    tenant_id = _post_int(request, "tenant_id")
    role_id = _post_int(request, "role_id")
    enabled = _post_flag(request, "enabled")
    is_default = _post_flag(request, "is_default")
    edge_cluster_ids = _parse_int_list_csv(request.POST.get("edge_cluster_ids"))

    if user_id <= 0:
        context["top_msg"] = "user_id 不能为空"
        return
    if tenant_id <= 0:
        context["top_msg"] = "tenant_id 不能为空"
        return

    tenant = CloudTenant.objects.filter(id=tenant_id).first()
    if not tenant:
        context["top_msg"] = MSG_TENANT_NOT_FOUND
        return

    role = CloudRole.objects.filter(id=role_id, tenant=tenant).first() if role_id > 0 else None
    scope_json = json.dumps({"edge_cluster_ids": edge_cluster_ids}, ensure_ascii=False) if edge_cluster_ids else ""
    membership, _ = CloudUserMembership.objects.update_or_create(
        user_id=user_id,
        tenant=tenant,
        defaults={
            "role": role,
            "enabled": enabled,
            "is_default": is_default,
            "resource_scope_json": scope_json,
        },
    )
    if is_default:
        CloudUserMembership.objects.filter(user_id=user_id).exclude(id=membership.id).update(is_default=False)
    context["top_msg"] = "membership 已保存"


def _handle_iam_set_tenant_branding(request, context):
    """处理`iam``set`租户品牌。"""
    tenant_id = _post_int(request, "tenant_id")
    tenant = CloudTenant.objects.filter(id=tenant_id).first() if tenant_id > 0 else None
    if not tenant:
        context["top_msg"] = MSG_TENANT_NOT_FOUND
        return

    branding = _iam_branding_from_request(request)
    tenant.branding_json = json.dumps(branding, ensure_ascii=False) if branding else ""
    tenant.save(update_fields=["branding_json"])
    context["top_msg"] = "tenant 白标配置已保存"


def _handle_iam_post_action(request):
    """处理`iam``post`动作。"""
    context = {}
    action = str(request.POST.get("action", "") or "").strip()
    if action == "create_tenant":
        _handle_iam_create_tenant(request, context)
    elif action == "toggle_tenant":
        _handle_iam_toggle_tenant(request, context)
    elif action == "upsert_role":
        _handle_iam_upsert_role(request, context)
    elif action == "upsert_membership":
        _handle_iam_upsert_membership(request, context)
    elif action == "set_tenant_branding":
        _handle_iam_set_tenant_branding(request, context)
    return context


def _iam_permission_meta_rows():
    """返回`iam`权限元数据记录。"""
    rows = []
    for item in _IAM_PERMISSION_META:
        key = str(item.get("key") or "")
        rows.append(
            {
                "key": key,
                "field": _perm_field_name(key),
                "name": str(item.get("name") or key),
                "desc": str(item.get("desc") or ""),
            }
        )
    return rows


def _iam_page_context():
    """处理`iam`页面`context`。"""
    return {
        "permission_meta": _iam_permission_meta_rows(),
        "tenants": list(CloudTenant.objects.all().order_by("id")),
        "roles": list(CloudRole.objects.select_related("tenant").all().order_by("tenant_id", "id")),
        "memberships": list(
            CloudUserMembership.objects.select_related("user", "tenant", "role")
            .all()
            .order_by("-id")
        ),
        "users": list(User.objects.all().order_by("id")),
    }


def iam(request):
    """处理`iam`。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return render(request, "app/cloud/iam.html", {})
        return resp

    auth = _get_cloud_auth(request)
    if not bool(auth.get("is_admin")):
        return _forbidden(request, "权限不足：仅管理员可访问 Cloud IAM")

    context = _consume_cloud_flash(request, _FLASH_KEY_CLOUD_IAM) if request.method == "GET" else {}

    if request.method == "POST":
        context.update(_handle_iam_post_action(request))

    context.update(_iam_page_context())
    return render(request, "app/cloud/iam.html", context)


def _edge_token_pepper() -> str:
    """处理边缘令牌`pepper`。"""
    return str(os.environ.get("BEACON_CLOUD_EDGE_TOKEN_PEPPER", "") or "").strip()


def _edge_cluster_create_payload(request):
    """返回边缘集群`create`载荷。"""
    return {
        "name": str(request.POST.get("name", "") or "").strip(),
        "edge_admin_base_url": str(request.POST.get("edge_admin_base_url", "") or "").strip(),
        "edge_openapi_token": str(request.POST.get("edge_openapi_token", "") or "").strip(),
        "node_code": str(request.POST.get("node_code", "") or "").strip(),
        "remark": str(request.POST.get("remark", "") or "").strip(),
    }


def _edge_remote_update_payload(request):
    """返回边缘远端`update`载荷。"""
    def _optional_str(field_name: str):
        """处理可选字符串。"""
        if field_name not in request.POST:
            return None
        return str(request.POST.get(field_name, "") or "").strip()

    def _optional_rollout_versions():
        """处理可选`rollout``versions`。"""
        if "rollout_node_versions_json" not in request.POST:
            return None
        return _normalize_rollout_node_versions_json(request.POST.get("rollout_node_versions_json", ""))

    return {
        "edge_admin_base_url": _optional_str("edge_admin_base_url"),
        "edge_openapi_token": _optional_str("edge_openapi_token"),
        "node_code": _optional_str("node_code"),
        "remark": _optional_str("remark"),
        "rollout_channel": _optional_str("rollout_channel"),
        "rollout_status": (
            _optional_str("rollout_status").lower()
            if _optional_str("rollout_status") is not None
            else None
        ),
        "rollout_target_version": _optional_str("rollout_target_version"),
        "rollout_error": _optional_str("rollout_error"),
        "rollout_node_versions_json": _optional_rollout_versions(),
    }


def _resolve_edge_cluster_create_tenant(request, auth):
    """解析并返回边缘集群`create`租户。"""
    if not bool(auth.get("is_admin")):
        return auth.get("tenant")

    tenant_id = _post_int(request, "tenant_id")
    if tenant_id > 0:
        return CloudTenant.objects.filter(id=tenant_id).first()

    tenant, _ = CloudTenant.objects.get_or_create(
        slug="default",
        defaults={"name": "default", "enabled": True},
    )
    return tenant


def _edge_cluster_or_404(request, auth):
    """处理边缘集群`or`404。"""
    cluster = _get_cluster_for_auth(auth, _post_int(request, "cluster_id"))
    if not cluster:
        return None, _not_found()
    return cluster, None


def _save_edge_remote_config(cluster, payload):
    """保存边缘远端配置。"""
    field_names = [
        "edge_admin_base_url",
        "node_code",
        "remark",
        "rollout_channel",
        "rollout_status",
        "rollout_target_version",
        "rollout_error",
        "rollout_node_versions_json",
    ]
    update_fields = []
    for field_name in field_names:
        if field_name not in payload or payload.get(field_name) is None:
            continue
        setattr(cluster, field_name, payload.get(field_name, ""))
        update_fields.append(field_name)

    edge_openapi_token = payload.get("edge_openapi_token")
    if edge_openapi_token:
        cluster.edge_openapi_token = edge_openapi_token
        update_fields.append("edge_openapi_token")

    if update_fields:
        cluster.save(update_fields=update_fields)


def _handle_edge_cluster_create(request, auth, context):
    """处理边缘集群`create`。"""
    pepper = _edge_token_pepper()
    if not pepper:
        context["top_msg"] = "缺少 BEACON_CLOUD_EDGE_TOKEN_PEPPER：无法生成 edge token"
        return None

    payload = _edge_cluster_create_payload(request)
    if not payload.get("name"):
        context["top_msg"] = "请输入集群名称"
        return None

    tenant = _resolve_edge_cluster_create_tenant(request, auth)
    if not tenant:
        context["top_msg"] = "租户不存在"
        return None

    project = _get_or_create_default_project(tenant=tenant)
    plain = secrets.token_urlsafe(32)
    cluster = CloudEdgeCluster.objects.create(
        project=project,
        name=payload.get("name", ""),
        enabled=True,
        edge_token_hash=hash_edge_token(plain),
        edge_admin_base_url=payload.get("edge_admin_base_url", ""),
        edge_openapi_token=payload.get("edge_openapi_token", ""),
        node_code=payload.get("node_code", ""),
        remark=payload.get("remark", ""),
    )
    context["top_msg"] = "创建成功：请复制 edge token（仅显示一次）"
    context["created_cluster"] = cluster
    context["created_token"] = plain
    return None


def _handle_edge_cluster_toggle(request, auth, context):
    """处理边缘集群`toggle`。"""
    cluster, resp = _edge_cluster_or_404(request, auth)
    if resp:
        return resp

    cluster.enabled = not bool(cluster.enabled)
    cluster.save(update_fields=["enabled"])
    context["top_msg"] = "已更新集群状态"
    return None


def _handle_edge_cluster_rotate(request, auth, context):
    """处理边缘集群`rotate`。"""
    pepper = _edge_token_pepper()
    if not pepper:
        context["top_msg"] = "缺少 BEACON_CLOUD_EDGE_TOKEN_PEPPER：无法轮换 edge token"
        return None

    cluster, resp = _edge_cluster_or_404(request, auth)
    if resp:
        return resp

    plain = secrets.token_urlsafe(32)
    cluster.edge_token_hash = hash_edge_token(plain)
    cluster.save(update_fields=["edge_token_hash"])
    context["top_msg"] = "已轮换 edge token（仅显示一次）"
    context["rotated_cluster"] = cluster
    context["rotated_token"] = plain
    return None


def _handle_edge_cluster_update_remote(request, auth, context):
    """处理边缘集群`update`远端。"""
    cluster, resp = _edge_cluster_or_404(request, auth)
    if resp:
        return resp

    _save_edge_remote_config(cluster, _edge_remote_update_payload(request))
    context["top_msg"] = "远控配置已保存"
    return None


def _handle_edge_clusters_post(request, auth):
    """处理边缘`clusters``post`。"""
    context = {}
    action = str(request.POST.get("action", "") or "").strip()
    if action in _EDGE_CLUSTER_MANAGE_ACTIONS and not _has_perm(auth, _PERM_EDGE_CLUSTERS_MANAGE):
        return context, _forbidden(request, "权限不足：无权管理边缘集群")

    handlers = {
        "create": _handle_edge_cluster_create,
        "toggle": _handle_edge_cluster_toggle,
        "rotate": _handle_edge_cluster_rotate,
        "update_remote": _handle_edge_cluster_update_remote,
    }
    handler = handlers.get(action)
    if not handler:
        return context, None
    return context, handler(request, auth, context)


def _edge_clusters_page_context(auth):
    """处理边缘`clusters`页面`context`。"""
    clusters_qs = CloudEdgeCluster.objects.select_related("project", "project__tenant").all().order_by("-id")
    clusters = list(_filter_clusters_for_auth(auth, clusters_qs))
    cluster_health_rows, cluster_health_summary, top_unhealthy_clusters = _build_edge_cluster_health_rows(clusters)
    return {
        "clusters": clusters,
        "cluster_health_rows": cluster_health_rows,
        "cluster_health_summary": cluster_health_summary,
        "top_unhealthy_clusters": top_unhealthy_clusters[:5],
        "cluster_rollout_rows": [row for row in cluster_health_rows if row.get("has_rollout")],
    }


def edge_clusters(request):
    """处理边缘`clusters`。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return render(request, "app/cloud/edge_clusters.html", {})
        return resp

    context = _consume_cloud_flash(request, _FLASH_KEY_CLOUD_EDGE_CLUSTERS) if request.method == "GET" else {}
    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, _PERM_EDGE_CLUSTERS_VIEW):
        return _forbidden(request, "权限不足：无权访问云平台-边缘集群")

    if request.method == "POST":
        context, resp = _handle_edge_clusters_post(request, auth)
        if resp:
            return resp

    context.update(_edge_clusters_page_context(auth))
    return render(request, "app/cloud/edge_clusters.html", context)


def alarms(request):
    """处理`alarms`。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return render(request, "app/cloud/alarms.html", {})
        return resp
    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, _PERM_ALARMS_VIEW):
        return _forbidden(request, "权限不足：无权访问云平台-云告警")

    params = f_parseGetParams(request)
    page = _parse_int_clamped(params.get("p", 1), default=1, min_value=1)
    page_size = _parse_int_clamped(params.get("ps", 20), default=20, min_value=10, max_value=50)
    cluster_id = _parse_cluster_id(params)

    queryset = CloudAlarmEvent.objects.select_related("edge_cluster").all().order_by("-received_at")
    queryset = _filter_alarms_for_auth(auth, queryset)
    if cluster_id:
        queryset = queryset.filter(edge_cluster_id=cluster_id)

    from app.utils.Common import buildPageLabels

    paginator, current_page, page = _paginate_queryset(queryset, page=page, page_size=page_size)
    data = [_serialize_cloud_alarm_row(row) for row in current_page.object_list]

    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": buildPageLabels(page=page, page_num=paginator.num_pages),
    }

    context = {
        "data": data,
        "clusters": list(_filter_clusters_for_auth(auth, CloudEdgeCluster.objects.all().order_by("id"))),
        "selected_cluster_id": cluster_id,
        "pageData": page_data,
    }

    return render(request, "app/cloud/alarms.html", context)


def _alarm_detail_auth_or_resp(request):
    """处理告警详情认证`or``resp`。"""
    resp = _require_cloud_mode()
    if resp:
        if request.method == "GET":
            return None, render(request, "app/cloud/alarm_detail.html", {})
        return None, resp
    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return None, _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, _PERM_ALARMS_VIEW):
        return None, _forbidden(request, "权限不足：无权查看云告警详情")
    return auth, None


def _get_cloud_alarm_event_row_or_none(auth, alarm_id):
    """获取云端告警事件记录`or``none`。"""
    try:
        q = CloudAlarmEvent.objects.select_related(
            "edge_cluster",
            "edge_cluster__project",
            "edge_cluster__project__tenant",
        ).all()
        q = _filter_alarms_for_auth(auth, q)
        return q.get(id=alarm_id)
    except Exception:
        return None


def _cloud_alarm_use_proxy_preview() -> bool:
    """处理云端告警`use`代理`preview`。"""
    raw = str(os.environ.get("BEACON_CLOUD_IMAGE_PREVIEW_PROXY", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _cloud_alarm_presign_expires_in_seconds() -> int:
    """返回云端告警预签名`expires``in`秒数。"""
    try:
        expires_in = int(os.environ.get("BEACON_CLOUD_PRESIGN_GET_EXPIRES_SECONDS", 60) or 60)
    except Exception:
        expires_in = 60
    if expires_in < 10:
        return 10
    if expires_in > 600:
        return 600
    return expires_in


def _resolve_cloud_alarm_image_preview(row, *, use_proxy: bool):
    """解析并返回云端告警图片`preview`。"""
    if not getattr(row, "image_key", "") or not getattr(row, "image_bucket", ""):
        return "", ""
    if use_proxy:
        return f"/cloud/alarm/image?id={row.id}", ""

    from app.utils.CloudS3 import presign_get

    try:
        expires_in = _cloud_alarm_presign_expires_in_seconds()
        url = presign_get(bucket=row.image_bucket, key=row.image_key, expires_in=expires_in).get("url") or ""
        return str(url), ""
    except Exception as e:
        return "", str(e)


def alarm_detail(request):
    """处理告警详情。"""
    auth, resp = _alarm_detail_auth_or_resp(request)
    if resp:
        return resp

    params = f_parseGetParams(request)
    alarm_id = params.get("id")

    row = _get_cloud_alarm_event_row_or_none(auth, alarm_id)
    if not row:
        return render(
            request,
            "app/message.html",
            {"msg": "告警不存在", "is_success": False, "redirect_url": "/cloud/alarms"},
            status=404,
        )

    use_proxy = _cloud_alarm_use_proxy_preview()
    image_url, image_error = _resolve_cloud_alarm_image_preview(row, use_proxy=use_proxy)

    context = {
        "alarm": row,
        "cluster_name": getattr(getattr(row, "edge_cluster", None), "name", "") or "",
        "image_url": image_url,
        "image_error": image_error,
        "image_preview_mode": "proxy" if use_proxy else "presigned_get",
        "payload_pretty": row.payload_json or "",
        "has_image": bool(image_url),
    }

    return render(request, "app/cloud/alarm_detail.html", context)


def alarm_image(request):
    """处理告警图片。
    
    Docker POC friendly alarm image preview.
    
        Why: In docker-compose, `BEACON_CLOUD_S3_ENDPOINT_URL=http://minio:9000` makes presigned GET use host `minio`,
        which the browser can't resolve. This endpoint proxies the image bytes via Cloud Admin.
    """
    resp = _require_cloud_mode()
    if resp:
        return resp
    auth = _get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return _forbidden(request, str(auth.get("msg") or "forbidden"))
    if not _has_perm(auth, _PERM_ALARMS_VIEW):
        return _forbidden(request, "权限不足：无权查看云告警截图")

    params = f_parseGetParams(request)
    alarm_id = params.get("id")
    try:
        alarm_id = int(alarm_id or 0)
    except Exception:
        alarm_id = 0

    if not alarm_id:
        return HttpResponse(status=404)

    q = CloudAlarmEvent.objects.all()
    q = _filter_alarms_for_auth(auth, q)
    row = q.filter(id=alarm_id).only(
        "id",
        "image_bucket",
        "image_key",
        "image_content_type",
    ).first()
    if not row:
        return HttpResponse(status=404)
    if not (row.image_bucket and row.image_key):
        return HttpResponse(status=404)

    from django.http import StreamingHttpResponse
    from app.utils.CloudS3 import make_s3_client_from_env

    try:
        client = make_s3_client_from_env()
        obj = client.get_object(Bucket=str(row.image_bucket), Key=str(row.image_key))
        body = obj.get("Body")
        if not body:
            return HttpResponse(status=404)

        content_type = str(row.image_content_type or obj.get("ContentType") or "application/octet-stream")
        if not content_type:
            content_type = "application/octet-stream"

        response = StreamingHttpResponse(
            streaming_content=iter(lambda: body.read(64 * 1024), b""),
            content_type=content_type,
        )
        response["Cache-Control"] = "private, max-age=60"
        return response
    except Exception:
        return HttpResponse(status=404)
