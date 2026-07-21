import asyncio
import json
import os
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from django.conf import settings
from django.contrib.sessions.models import Session

from app.utils.AlarmPoll import build_alarm_poll_summary, parse_after_id

# This module serves a very small ASGI websocket surface without Channels.
# Allowing sync ORM calls here keeps the implementation dependency-light and
# avoids SQLite test database visibility issues across worker threads.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _parse_query_params(scope):
    """解析查询参数参数。"""
    raw = scope.get("query_string", b"") or b""
    try:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=False)
    except Exception:
        parsed = {}
    out = {}
    for key, values in parsed.items():
        if not values:
            continue
        out[str(key)] = str(values[-1] or "")
    return out


def _get_cookie_value(scope, name: str) -> str:
    """获取`cookie`值。"""
    for key, value in scope.get("headers", []) or []:
        if key != b"cookie":
            continue
        try:
            raw = value.decode("utf-8", errors="ignore")
        except Exception:
            raw = ""
        if not raw:
            continue
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            continue
        morsel = cookie.get(name)
        if morsel:
            return str(morsel.value or "").strip()
    return ""


def _get_scope_session_user(scope):
    """获取作用域会话用户。"""
    session_key = _get_cookie_value(scope, settings.SESSION_COOKIE_NAME)
    if not session_key:
        return None
    try:
        session = Session.objects.filter(session_key=session_key).first()
        if not session:
            return None
        data = session.get_decoded() or {}
    except Exception:
        return None
    user = data.get("user")
    if not isinstance(user, dict):
        return None
    if not int(user.get("id") or 0):
        return None
    return user


def _parse_interval_ms(value) -> int:
    """解析`interval``ms`。"""
    try:
        interval_ms = int(value or 3000)
    except Exception:
        interval_ms = 3000
    if interval_ms < 250:
        interval_ms = 250
    if interval_ms > 10000:
        interval_ms = 10000
    return interval_ms


async def _ws_close(send, code: int):
    """关闭 WebSocket 连接。"""
    await send({"type": "websocket.close", "code": int(code)})


async def _ws_send_alarm_poll(send, summary: dict):
    """通过 WebSocket 发送告警轮询数据。"""
    await send(
        {
            "type": "websocket.send",
            "text": json.dumps({"type": "alarm.poll", "data": summary}, ensure_ascii=False),
        }
    )


def _ws_event_type(event) -> str:
    """返回 WebSocket 事件类型。"""
    return str((event or {}).get("type") or "")


def _maybe_cursor_from_ws_event(event):
    """按需从 WebSocket 事件中提取游标。"""
    if _ws_event_type(event) != "websocket.receive":
        return None

    raw_text = str((event or {}).get("text") or "").strip()
    if not raw_text:
        return None
    try:
        payload = json.loads(raw_text)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if "after_id" not in payload:
        return None
    return parse_after_id(payload.get("after_id"))


async def _wait_for_ws_event(receive_task, timeout_s: float):
    """等待 WebSocket 事件。"""
    done, _ = await asyncio.wait({receive_task}, timeout=timeout_s)
    if done:
        return receive_task.result()
    return None


def _cancel_task(task):
    """处理`cancel`任务。"""
    if not task:
        return
    if not task.done():
        task.cancel()


async def _send_initial_alarm_poll(send, params: dict, cursor: int) -> int:
    """处理发送`initial`告警轮询。"""
    initial = build_alarm_poll_summary(params, after_id=cursor)
    cursor = max(cursor, int(initial.get("newest_id") or 0))
    await _ws_send_alarm_poll(send, initial)
    return cursor


async def _send_periodic_alarm_poll(send, params: dict, cursor: int) -> int:
    """处理发送`periodic`告警轮询。"""
    summary = build_alarm_poll_summary(params, after_id=cursor)
    if int(summary.get("new_count") or 0) <= 0:
        return cursor
    cursor = max(cursor, int(summary.get("newest_id") or 0))
    await _ws_send_alarm_poll(send, summary)
    return cursor


async def alarm_poll_websocket(scope, receive, send):
    """处理告警轮询 WebSocket 请求。"""
    event = await receive()
    if _ws_event_type(event) != "websocket.connect":
        return await _ws_close(send, 4400)

    if not _get_scope_session_user(scope):
        return await _ws_close(send, 4401)

    params = _parse_query_params(scope)
    interval_ms = _parse_interval_ms(params.get("interval_ms"))
    cursor = parse_after_id(params.get("after_id"))

    await send({"type": "websocket.accept"})

    cursor = await _send_initial_alarm_poll(send, params, cursor)

    receive_task = asyncio.create_task(receive())
    try:
        while True:
            event = await _wait_for_ws_event(receive_task, interval_ms / 1000.0)
            if event is None:
                cursor = await _send_periodic_alarm_poll(send, params, cursor)
                continue

            if _ws_event_type(event) == "websocket.disconnect":
                return
            receive_task = asyncio.create_task(receive())

            updated_cursor = _maybe_cursor_from_ws_event(event)
            if updated_cursor is not None:
                cursor = updated_cursor
    finally:
        _cancel_task(receive_task)
