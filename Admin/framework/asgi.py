"""
ASGI config for framework project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'framework.settings')

django_asgi_app = get_asgi_application()


async def application(scope, receive, send):
    """处理`application`。"""
    if scope.get("type") == "websocket":
        if scope.get("path") == "/ws/alarm/poll":
            from app.ws import alarm_poll_websocket

            return await alarm_poll_websocket(scope, receive, send)
        await send({"type": "websocket.close", "code": 4404})
        return

    return await django_asgi_app(scope, receive, send)
