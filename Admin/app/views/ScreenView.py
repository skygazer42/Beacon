from urllib.parse import quote

from django.shortcuts import render

from app.models import Alarm, Stream


def _birdseye_stream_by_code(streams):
    """按编码查找`birdseye`流。"""
    out = {}
    for stream in streams or []:
        code = str(getattr(stream, "code", "") or "").strip()
        if code:
            out[code] = stream
    return out


def _birdseye_activity(stream_by_code):
    """处理`birdseye``activity`。"""
    if not stream_by_code:
        return {}
    activity = {}
    for alarm in Alarm.objects.filter(stream_code__in=list(stream_by_code.keys())).order_by("-id"):
        stream_code = str(getattr(alarm, "stream_code", "") or "").strip()
        if not stream_code or stream_code not in stream_by_code:
            continue
        entry = activity.setdefault(stream_code, {"count": 0, "recent_events": []})
        entry["count"] += 1
        if len(entry["recent_events"]) < 3:
            entry["recent_events"].append(
                {
                    "id": int(alarm.id),
                    "desc": str(getattr(alarm, "desc", "") or ""),
                    "detail_url": f"/alarm/detail?id={alarm.id}",
                }
            )
    return activity


def _birdseye_item(stream_code: str, *, stream, meta: dict):
    """处理`birdseye``item`。"""
    latest = (meta.get("recent_events") or [{}])[0]
    label = (
        str(getattr(stream, "nickname", "") or "").strip()
        or str(getattr(stream, "name", "") or "").strip()
        or stream_code
    )
    return {
        "stream_code": stream_code,
        "stream_app": str(getattr(stream, "app", "") or "").strip(),
        "stream_name": str(getattr(stream, "name", "") or "").strip(),
        "label": label,
        "group": str(getattr(stream, "app", "") or "").strip(),
        "alarm_count": int(meta.get("count") or 0),
        "stream_detail_url": f"/stream/edit?code={quote(stream_code)}",
        "latest_alarm_url": str(latest.get("detail_url") or ""),
        "recent_events": list(meta.get("recent_events") or []),
    }


def _build_birdseye_streams():
    """构建`birdseye`流列表。"""
    streams = list(Stream.objects.all().order_by("app", "sort", "id"))
    if not streams:
        return []

    stream_by_code = _birdseye_stream_by_code(streams)
    if not stream_by_code:
        return []

    activity = _birdseye_activity(stream_by_code)

    items = []
    for stream_code, meta in activity.items():
        stream = stream_by_code.get(stream_code)
        if not stream:
            continue
        items.append(_birdseye_item(stream_code, stream=stream, meta=meta or {}))

    items.sort(key=lambda item: (-int(item.get("alarm_count") or 0), str(item.get("label") or "")))
    return items[:8]


def index(request):
    # Big screen (multi-view) page. Frontend fetches online streams asynchronously.
    """渲染默认页面。"""
    context = {
        "birdseye_streams": _build_birdseye_streams(),
    }
    context["has_birdseye_streams"] = bool(context["birdseye_streams"])
    return render(request, "app/screen/index.html", context)
