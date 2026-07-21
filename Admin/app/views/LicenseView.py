import json
import logging
import os

from django.shortcuts import render
from django.utils import timezone

from app.models import LicenseLease, LicenseState, OpsAuditLog
from app.views.ViewsBase import g_session_key_user

logger = logging.getLogger(__name__)

LICENSE_ERROR_MESSAGES = {
    "missing_public_key": {
        "title": "未配置 License 公钥",
        "hint": "当前服务端未配置 BEACON_LICENSE_PUBLIC_KEY_B64，无法校验 License 签名。请先补齐公钥配置后再重新导入。",
    },
    "cluster_mismatch": {
        "title": "License 集群编号不匹配",
        "hint": "导入的 License 与当前服务端集群编号不一致。请核对 license 文件中的 cluster_id 与 BEACON_CLUSTER_ID。",
    },
    "bad_public_key": {
        "title": "License 公钥格式无效",
        "hint": "BEACON_LICENSE_PUBLIC_KEY_B64 无法正确解码，请检查是否填入了正确的 Base64 公钥。",
    },
    "missing_signature": {
        "title": "License 缺少签名",
        "hint": "当前上传的 License 文件缺少 signature 字段，无法验证来源与完整性。",
    },
    "unsupported_signature": {
        "title": "License 签名算法不受支持",
        "hint": "当前系统仅支持 ed25519 签名 License，请确认导入的是受支持的授权文件。",
    },
    "bad_signature": {
        "title": "License 签名校验失败",
        "hint": "License 签名无法通过校验。请确认文件未被篡改，且公钥与签发方一致。",
    },
    "license_not_yet_valid": {
        "title": "License 尚未生效",
        "hint": "当前时间早于 License 生效时间，请核对授权时间窗口与系统时钟。",
    },
    "license_expired": {
        "title": "License 已过期",
        "hint": "当前 License 已超过有效期，请更新新的授权文件。",
    },
    "malformed": {
        "title": "License 内容结构不正确",
        "hint": "License 顶层内容应为 JSON 对象，请检查文件结构是否完整。",
    },
    "malformed_json": {
        "title": "License 文件解析失败",
        "hint": "上传内容不是合法 JSON。请确认文件编码和内容格式后重新导入。",
    },
    "empty_upload": {
        "title": "未读取到 License 文件内容",
        "hint": "上传文件为空或无法解码，请确认选择了正确的 license.json 文件。",
    },
    "license_invalid": {
        "title": "License 校验失败",
        "hint": "当前授权文件未通过校验，请根据错误码和底层原因继续排查。",
    },
}


def _normalize_stream_code(stream_code, control_code=""):
    """执行归一化流编码。"""
    value = str(stream_code or "").strip()
    if value:
        return value
    return str(control_code or "").strip()


def _latest_state():
    """返回`latest`状态。"""
    try:
        return LicenseState.objects.order_by("-update_time", "-id").first()
    except Exception:
        return None


def _active_usage(now=None):
    """处理活动`usage`。"""
    now = now or timezone.now()
    try:
        qs = LicenseLease.objects.filter(released_at__isnull=True, expires_at__gt=now)
        stream_keys = set()
        for node_id, stream_code, control_code in qs.values_list("node_id", "stream_code", "control_code"):
            node = str(node_id or "").strip()
            stream = _normalize_stream_code(stream_code, control_code)
            if node and stream:
                stream_keys.add((node, stream))
        return {
            "active_controls": qs.count(),
            "active_streams": len(stream_keys),
            "active_nodes": qs.values("node_id").distinct().count(),
        }
    except Exception:
        return {"active_controls": 0, "active_streams": 0, "active_nodes": 0}


def _read_upload_as_text(uploaded_file):
    """读取上传`as`文本。"""
    if not uploaded_file:
        return ""
    data = uploaded_file.read()
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk")
        except Exception:
            return ""


def _read_license_payload(raw_text):
    """读取授权载荷。"""
    try:
        payload = json.loads(str(raw_text or ""))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _prefer_payload_or_state(payload: dict, state, *, payload_key: str, state_attr: str) -> str:
    """返回`prefer`载荷`or`状态。"""
    try:
        val = str(payload.get(payload_key, "") or "").strip()
    except Exception:
        val = ""
    if val:
        return val
    if state is None:
        return ""
    try:
        return str(getattr(state, state_attr, "") or "").strip()
    except Exception:
        return ""


def _public_key_status_text(public_key_configured) -> str:
    """处理公共键状态文本。"""
    if public_key_configured is True:
        return "已配置"
    if public_key_configured is False:
        return "未配置"
    return ""


def _build_license_error_context(
    *,
    error_code="",
    error_message="",
    payload=None,
    expected_cluster_id="",
    public_key_configured=None,
    state=None,
):
    """构建授权错误`context`。"""
    code = str(error_code or "").strip() or "license_invalid"
    payload = payload if isinstance(payload, dict) else {}
    state = state if state is not None else None
    meta = LICENSE_ERROR_MESSAGES.get(code, LICENSE_ERROR_MESSAGES["license_invalid"])

    uploaded_cluster_id = _prefer_payload_or_state(payload, state, payload_key="cluster_id", state_attr="cluster_id")
    license_id = _prefer_payload_or_state(payload, state, payload_key="license_id", state_attr="license_id")
    customer = _prefer_payload_or_state(payload, state, payload_key="customer", state_attr="customer")
    public_key_status = _public_key_status_text(public_key_configured)

    return {
        "code": code,
        "title": meta.get("title", ""),
        "hint": meta.get("hint", ""),
        "message": str(error_message or "").strip() or str(getattr(state, "last_error_message", "") or "").strip(),
        "license_id": license_id,
        "customer": customer,
        "uploaded_cluster_id": uploaded_cluster_id,
        "expected_cluster_id": str(expected_cluster_id or "").strip(),
        "public_key_status": public_key_status,
        "state_update_time": getattr(state, "update_time", None),
        "state_valid": bool(getattr(state, "valid", False)) if state is not None else False,
    }


def _parse_uploaded_license(uploaded_file):
    """解析`uploaded`授权。"""
    raw = _read_upload_as_text(uploaded_file)
    if not raw:
        return {
            "raw": "",
            "payload": None,
            "top_msg": "解析失败",
            "license_error": _build_license_error_context(
                error_code="empty_upload",
                error_message="uploaded file is empty or unreadable",
            ),
        }

    payload = _read_license_payload(raw)
    if payload is None:
        return {
            "raw": raw,
            "payload": None,
            "top_msg": "解析失败",
            "license_error": _build_license_error_context(
                error_code="malformed_json",
                error_message="invalid json text",
            ),
        }

    return {
        "raw": raw,
        "payload": payload,
        "top_msg": "",
        "license_error": None,
    }


def _validate_uploaded_license_payload(payload: dict):
    """校验`uploaded`授权载荷。"""
    from app.utils.LicenseManager import get_current_cluster_id, validate_license_payload

    public_key_b64 = str(os.environ.get("BEACON_LICENSE_PUBLIC_KEY_B64", "") or "").strip()
    expected_cluster_id = get_current_cluster_id()
    public_key_configured = bool(public_key_b64)

    if not public_key_configured:
        result = {"ok": False, "error_code": "missing_public_key", "error_message": "public key not configured"}
    else:
        result = validate_license_payload(
            payload,
            public_key_b64=public_key_b64,
            expected_cluster_id=expected_cluster_id,
        )

    return {
        "result": result,
        "expected_cluster_id": expected_cluster_id,
        "public_key_configured": public_key_configured,
    }


def _license_result_parts(result: dict):
    """处理授权结果`parts`。"""
    limits = result.get("limits") if isinstance(result.get("limits"), dict) else {}
    packages = result.get("packages") if isinstance(result.get("packages"), list) else []
    package_limits = result.get("package_limits") if isinstance(result.get("package_limits"), dict) else {}
    return limits, packages, package_limits


def _persist_license_state(raw: str, payload: dict, result: dict, *, limits: dict, packages: list, package_limits: dict) -> str:
    """返回`persist`授权状态。"""
    try:
        LicenseState.objects.create(
            license_json=raw,
            license_id=str(result.get("license_id", "") or "").strip(),
            customer=str(result.get("customer", "") or "").strip(),
            cluster_id=str(result.get("cluster_id", "") or "").strip() or str(payload.get("cluster_id", "") or "").strip(),
            not_before=result.get("not_before"),
            not_after=result.get("not_after"),
            max_active_controls=int(limits.get("max_active_controls", 0) or 0),
            max_nodes=int(limits.get("max_nodes", 0) or 0),
            packages_json=json.dumps(packages, ensure_ascii=False),
            package_limits_json=json.dumps(package_limits, ensure_ascii=False),
            valid=bool(result.get("ok")),
            last_error_code=str(result.get("error_code", "") or "").strip(),
            last_error_message=str(result.get("error_message", "") or "").strip(),
        )
    except Exception as e:
        return str(e)
    return ""


def _write_license_import_audit_log(request, result: dict, *, limits: dict, packages: list, package_limits: dict):
    """写入授权导入审计`log`。"""
    try:
        session_user = request.session.get(g_session_key_user) or {}
        operator = str(session_user.get("username", "") or "").strip() or "web"
        source_ip = str(request.META.get("REMOTE_ADDR", "") or "").strip()

        OpsAuditLog.objects.create(
            event_type="license.import",
            ok=bool(result.get("ok")),
            operator=operator,
            source_ip=source_ip,
            error_code=str(result.get("error_code", "") or "").strip(),
            error_message=str(result.get("error_message", "") or "").strip(),
            detail_json=json.dumps(
                {
                    "license_id": str(result.get("license_id", "") or "").strip(),
                    "customer": str(result.get("customer", "") or "").strip(),
                    "cluster_id": str(result.get("cluster_id", "") or "").strip(),
                    "packages": packages,
                    "limits": limits,
                    "package_limits": package_limits,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
    except Exception:
        logger.debug("write license import audit log failed operator=%s", operator, exc_info=True)


def _license_import_top_msg(result: dict) -> str:
    """处理授权导入`top``msg`。"""
    if result.get("ok"):
        return "导入成功"
    return "导入失败: %s" % (str(result.get("error_code") or "license_invalid"))


def _process_license_upload(request):
    """处理授权上传。"""
    parsed = _parse_uploaded_license(request.FILES.get("file"))
    if parsed["license_error"]:
        return parsed["top_msg"], parsed["license_error"]

    payload = parsed["payload"] or {}
    validation = _validate_uploaded_license_payload(payload)
    result = validation["result"]
    current_license_error = None
    if not result.get("ok"):
        current_license_error = _build_license_error_context(
            error_code=result.get("error_code"),
            error_message=result.get("error_message"),
            payload=payload,
            expected_cluster_id=validation["expected_cluster_id"],
            public_key_configured=validation["public_key_configured"],
        )

    limits, packages, package_limits = _license_result_parts(result)
    save_error = _persist_license_state(
        parsed["raw"],
        payload,
        result,
        limits=limits,
        packages=packages,
        package_limits=package_limits,
    )
    if save_error:
        return "保存失败: %s" % save_error, current_license_error

    _write_license_import_audit_log(
        request,
        result,
        limits=limits,
        packages=packages,
        package_limits=package_limits,
    )
    return _license_import_top_msg(result), current_license_error


def _persisted_license_error_context(state):
    """处理`persisted`授权错误`context`。"""
    if state is None:
        return None
    if bool(getattr(state, "valid", False)):
        return None
    if not str(getattr(state, "last_error_code", "") or "").strip():
        return None

    from app.utils.LicenseManager import get_current_cluster_id

    persisted_payload = _read_license_payload(getattr(state, "license_json", ""))
    return _build_license_error_context(
        error_code=getattr(state, "last_error_code", ""),
        error_message=getattr(state, "last_error_message", ""),
        payload=persisted_payload,
        expected_cluster_id=get_current_cluster_id(),
        public_key_configured=bool(str(os.environ.get("BEACON_LICENSE_PUBLIC_KEY_B64", "") or "").strip()),
        state=state,
    )


def manager(request):
    """
    授权管理（License Manager）
    - GET: 展示当前授权状态与实时用量
    - POST: 上传 license.json（登录态 + CSRF）
    """
    context = {}
    context["license_error"] = None
    current_license_error = None

    if request.method == "POST":
        context["top_msg"], current_license_error = _process_license_upload(request)

    state = _latest_state()
    context["license_state"] = state
    context["license_usage"] = _active_usage()
    if current_license_error:
        context["license_error"] = current_license_error
    else:
        context["license_error"] = _persisted_license_error_context(state)
    return render(request, "app/license/manager.html", context)
