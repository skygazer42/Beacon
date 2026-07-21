from functools import wraps

from app.services import digital_human as dh_service
from app.views.ViewsBase import f_parseGetParams, f_parsePostParams, f_responseJson


def _open_success(data):
    return f_responseJson({"code": 200, "message": "success", "data": data})


def _open_error(message, *, status_code=400):
    response = f_responseJson({"code": -1, "message": str(message or "request failed"), "data": None})
    response.status_code = int(status_code or 400)
    return response


def _require_method(*allowed_methods):
    normalized_allowed = {str(item or "").upper() for item in allowed_methods}

    def _decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if str(request.method or "").upper() not in normalized_allowed:
                return _open_error("request method not supported", status_code=405)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return _decorator


def _run(callable_obj, *args, **kwargs):
    try:
        return _open_success(callable_obj(*args, **kwargs))
    except dh_service.DigitalHumanError as exc:
        return _open_error(exc, status_code=exc.status_code)


@_require_method("POST")
def open_agent_token(request):
    return _run(dh_service.issue_open_agent_token, f_parsePostParams(request))


@_require_method("POST")
def open_agent_register(request):
    return _run(dh_service.register_open_agent, request.META.get("HTTP_AUTHORIZATION"), f_parsePostParams(request))


@_require_method("POST")
def open_agent_report(request):
    return _run(dh_service.receive_open_agent_report, request.META.get("HTTP_AUTHORIZATION"), f_parsePostParams(request))


@_require_method("GET")
def open_agent_config_latest(request):
    params = f_parseGetParams(request)
    return _run(dh_service.get_open_agent_latest_config, request.META.get("HTTP_AUTHORIZATION"), params.get("deviceId"))


@_require_method("GET")
def open_agent_commands_pull(request):
    params = f_parseGetParams(request)
    return _run(dh_service.pull_open_agent_commands, request.META.get("HTTP_AUTHORIZATION"), params.get("deviceId"))


@_require_method("POST")
def open_agent_commands_result(request):
    return _run(
        dh_service.submit_open_agent_command_result,
        request.META.get("HTTP_AUTHORIZATION"),
        f_parsePostParams(request),
    )


@_require_method("POST")
def open_human_report(request):
    return _run(dh_service.receive_open_human_report, request.META.get("HTTP_AUTHORIZATION"), f_parsePostParams(request))
