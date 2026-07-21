from django.shortcuts import redirect, render

from app.views.ViewsBase import getUser


def index(request):
    """渲染默认页面。"""
    from app.views import OpsApiKeyView

    user = getUser(request)
    if not user:
        return redirect("/login")

    db_user = OpsApiKeyView._get_db_user(request)
    if not OpsApiKeyView._is_admin(db_user):
        return OpsApiKeyView._deny(request, json_mode=False)

    return render(request, "app/ops/platform.html", {"user": user})
