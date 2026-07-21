from functools import wraps

from app.services import digital_human as dh_service
from app.views import UserManageView
from app.views.ViewsBase import f_parseGetParams, f_parsePostParams, f_responseJson, getUser


def _clear_cached_server_session():
    return None


def _success(data, msg="success"):
    return f_responseJson({"code": 1000, "msg": msg, "data": data})


def _error(msg, data=None):
    payload = {"code": 0, "msg": str(msg or "数字人监管接口请求失败")}
    if data is not None:
        payload["data"] = data
    return f_responseJson(payload)


def _unauthorized():
    response = f_responseJson({"code": 401, "msg": "unauthorized"})
    response.status_code = 401
    return response


def _forbidden():
    return f_responseJson({"code": 403, "msg": UserManageView.ADMIN_ONLY_MSG})


def _require_beacon_admin(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getUser(request):
            return _unauthorized()
        db_user = UserManageView._db_user_from_session(request)
        if not db_user:
            return _unauthorized()
        if not UserManageView._is_admin_user(db_user):
            return _forbidden()
        return view_func(request, *args, **kwargs)

    return _wrapped


def _run(callable_obj, *args, **kwargs):
    try:
        return _success(callable_obj(*args, **kwargs))
    except dh_service.DigitalHumanError as exc:
        return _error(exc)


@_require_beacon_admin
def api_dashboard(request):
    return _run(dh_service.get_dashboard_payload)


@_require_beacon_admin
def api_devices(request):
    return _run(dh_service.list_devices)


@_require_beacon_admin
def api_device_update_window(request):
    params = f_parsePostParams(request)
    device_id = params.get("deviceId") or params.get("device_id")
    if not str(device_id or "").strip():
        return _error("缺少 deviceId")
    return _run(dh_service.update_device_window, device_id, params)


@_require_beacon_admin
def api_alerts(request):
    return _run(dh_service.list_alerts)


@_require_beacon_admin
def api_alert_detail(request):
    alert_id = f_parseGetParams(request).get("id")
    if not str(alert_id or "").strip():
        return _error("缺少告警 ID")
    return _run(dh_service.get_alert_detail, alert_id)


@_require_beacon_admin
def api_alert_resolve(request):
    alert_id = f_parsePostParams(request).get("id")
    if not str(alert_id or "").strip():
        return _error("缺少告警 ID")
    return _run(dh_service.resolve_alert, alert_id)


@_require_beacon_admin
def api_alert_routing(request):
    return _run(dh_service.get_alert_routing_snapshot)


@_require_beacon_admin
def api_alert_routing_enabled(request):
    enabled = f_parsePostParams(request).get("enabled")
    return _run(dh_service.save_alert_routing_enabled, enabled)


@_require_beacon_admin
def api_alert_routing_create(request):
    return _run(dh_service.create_alert_route, f_parsePostParams(request))


@_require_beacon_admin
def api_alert_routing_update(request):
    params = f_parsePostParams(request)
    route_id = params.get("id")
    if not str(route_id or "").strip():
        return _error("缺少路由 ID")
    return _run(dh_service.update_alert_route, route_id, params)


@_require_beacon_admin
def api_alert_routing_delete(request):
    route_id = f_parsePostParams(request).get("id")
    if not str(route_id or "").strip():
        return _error("缺少路由 ID")
    return _run(dh_service.delete_alert_route, route_id)


@_require_beacon_admin
def api_monitor_logs(request):
    return _run(dh_service.list_monitor_logs, f_parseGetParams(request))


@_require_beacon_admin
def api_monitor_log_node_status(request):
    return _run(dh_service.get_monitor_log_node_status)


@_require_beacon_admin
def api_monitor_log_reanalyze(request):
    log_id = f_parsePostParams(request).get("id")
    if not str(log_id or "").strip():
        return _error("缺少日志 ID")
    return _run(dh_service.reanalyze_monitor_log, log_id)


@_require_beacon_admin
def api_ops_report(request):
    range_key = f_parseGetParams(request).get("range") or "7days"
    return _run(dh_service.get_ops_report, range_key)


@_require_beacon_admin
def api_ops_ai_insight(request):
    range_key = f_parseGetParams(request).get("range") or "7days"
    return _run(dh_service.get_ops_ai_insight, range_key)


@_require_beacon_admin
def api_system_settings_jwt_accounts(request):
    return _run(dh_service.list_jwt_accounts)


@_require_beacon_admin
def api_system_settings_jwt_account_create(request):
    return _run(dh_service.create_jwt_account, f_parsePostParams(request))


@_require_beacon_admin
def api_system_settings_jwt_account_rotate_secret(request):
    account_uuid = f_parsePostParams(request).get("accountUuid")
    if not str(account_uuid or "").strip():
        return _error("缺少 accountUuid")
    return _run(dh_service.rotate_jwt_account_secret, account_uuid)


@_require_beacon_admin
def api_system_settings_jwt_account_status(request):
    params = f_parsePostParams(request)
    account_uuid = params.get("accountUuid")
    if not str(account_uuid or "").strip():
        return _error("缺少 accountUuid")
    return _run(dh_service.update_jwt_account_status, account_uuid, params.get("enabled"))


@_require_beacon_admin
def api_system_settings_jwt_account_delete(request):
    account_uuid = f_parsePostParams(request).get("accountUuid")
    if not str(account_uuid or "").strip():
        return _error("缺少 accountUuid")
    return _run(dh_service.delete_jwt_account, account_uuid)


@_require_beacon_admin
def api_system_settings_device_authorizations(request):
    return _run(dh_service.list_device_authorizations, f_parseGetParams(request))


@_require_beacon_admin
def api_system_settings_device_authorization_detail(request):
    device_id = f_parseGetParams(request).get("id")
    if not str(device_id or "").strip():
        return _error("缺少设备授权 ID")
    return _run(dh_service.get_device_authorization_detail, device_id)


@_require_beacon_admin
def api_system_settings_device_authorization_update(request):
    params = f_parsePostParams(request)
    device_id = params.get("id")
    if not str(device_id or "").strip():
        return _error("缺少设备授权 ID")
    return _run(dh_service.update_device_authorization, device_id, params)


@_require_beacon_admin
def api_system_settings_device_authorization_delete(request):
    device_id = f_parsePostParams(request).get("id")
    if not str(device_id or "").strip():
        return _error("缺少设备授权 ID")
    return _run(dh_service.delete_device_authorization, device_id)


@_require_beacon_admin
def api_system_settings_ai_diagnosis(request):
    return _run(dh_service.get_ai_diagnosis_config)


@_require_beacon_admin
def api_system_settings_ai_diagnosis_save(request):
    return _run(dh_service.save_ai_diagnosis_config, f_parsePostParams(request))


@_require_beacon_admin
def api_system_settings_ai_diagnosis_test(request):
    return _run(dh_service.test_ai_diagnosis_connection, f_parsePostParams(request))
