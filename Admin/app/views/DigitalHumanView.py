from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, render

from app.services import digital_human as dh_service
from app.views import UserManageView
from app.views.ViewsBase import getUser


def _admin_user_or_response(request):
    user = getUser(request)
    if not user:
        return None, redirect("/login")
    db_user = UserManageView._db_user_from_session(request)
    if not db_user:
        return None, redirect("/login")
    if not UserManageView._is_admin_user(db_user):
        return None, UserManageView._render_permission_denied(request)
    return db_user, None


def _render_react_shell(request):
    """渲染数字人监管 React 页面壳。"""
    db_user, response = _admin_user_or_response(request)
    if response:
        return response

    return render(
        request,
        "app/base_react_shell.html",
        {
            "user": getUser(request),
            "bootstrap_is_staff": bool(getattr(db_user, "is_staff", False)),
            "bootstrap_is_superuser": bool(getattr(db_user, "is_superuser", False)),
        },
    )


def dashboard(request):
    """渲染数字人监管大盘。"""
    return _render_react_shell(request)


def device_monitor(request):
    """渲染数字人设备监控页。"""
    return _render_react_shell(request)


def alert_center(request):
    """渲染数字人告警中心页。"""
    return _render_react_shell(request)


def monitor_logs(request):
    """渲染数字人监管日志页。"""
    return _render_react_shell(request)


def ops_report(request):
    """渲染数字人运维报告页。"""
    return _render_react_shell(request)


def system_settings(request):
    """渲染数字人系统设置页。"""
    return _render_react_shell(request)


def device_screenshot(request):
    """返回数字人设备截图。"""
    _db_user, response = _admin_user_or_response(request)
    if response:
        return response

    try:
        descriptor = dh_service.get_device_screenshot_descriptor(request.GET.get("id"))
    except dh_service.DigitalHumanError as exc:
        return HttpResponse(status=int(exc.status_code or 404))

    storage = str((descriptor or {}).get("storage") or "").strip().lower()
    content_type = str((descriptor or {}).get("content_type") or "application/octet-stream").strip() or "application/octet-stream"
    if not content_type.lower().startswith("image/"):
        content_type = "application/octet-stream"
    if storage == "local":
        try:
            file_handle = open(descriptor["path"], "rb")
        except Exception:
            return HttpResponse(status=404)
        response = FileResponse(file_handle, content_type=content_type)
        response["Cache-Control"] = "private, max-age=60"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    if storage == "inline":
        response = HttpResponse(descriptor.get("image_bytes") or b"", content_type=content_type)
        response["Cache-Control"] = "private, max-age=60"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    if storage == "s3":
        from app.utils.CloudS3 import make_s3_client_from_env

        try:
            client = make_s3_client_from_env()
            obj = client.get_object(Bucket=str(descriptor["bucket"]), Key=str(descriptor["object_key"]))
            body = obj.get("Body")
            if not body:
                return HttpResponse(status=404)
            response = StreamingHttpResponse(
                streaming_content=iter(lambda: body.read(64 * 1024), b""),
                content_type=content_type,
            )
            response["Cache-Control"] = "private, max-age=60"
            response["X-Content-Type-Options"] = "nosniff"
            return response
        except Exception:
            return HttpResponse(status=404)
    return HttpResponse(status=404)
