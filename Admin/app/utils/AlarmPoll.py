import json
from datetime import timedelta

from app.models import Alarm, AlarmSound, Control


def parse_after_id(value) -> int:
    """解析`after`ID。"""
    try:
        after_id = int(value or 0)
    except Exception:
        after_id = 0
    if after_id < 0:
        after_id = 0
    return after_id


def _safe_first(queryset):
    """处理安全首个。"""
    try:
        return queryset.first()
    except Exception:
        return None


def _resolve_alarm_sound_url(qs, *, newest_alarm):
    """解析并返回告警`sound`URL。"""
    sound_alarm = _safe_first(qs.filter(state=0))
    if sound_alarm is None:
        sound_alarm = newest_alarm

    control = _safe_first(Control.objects.filter(code=sound_alarm.control_code).only("alarm_sound_id"))
    alarm_sound_id = int(getattr(control, "alarm_sound_id", 0) or 0) if control is not None else 0
    if alarm_sound_id <= 0:
        return ""

    sound = _safe_first(AlarmSound.objects.filter(id=int(alarm_sound_id)).only("file_path"))
    if sound is None:
        return ""
    return str(getattr(sound, "file_path", "") or "")


def build_alarm_poll_summary(params=None, *, after_id=0):
    """构建告警轮询`summary`。"""
    from app.views.AlarmView import apply_alarm_filters, parse_alarm_filters

    if params is None:
        params = {}
    cursor = parse_after_id(after_id)
    filters = parse_alarm_filters(params)
    qs = Alarm.objects.filter(id__gt=cursor)
    qs = apply_alarm_filters(qs, filters).order_by("-id")

    new_count = int(qs.count())
    newest_alarm = _safe_first(qs)
    if newest_alarm is None:
        return {
            "new_count": new_count,
            "newest_id": int(cursor),
            "sound_url": "",
        }

    newest_id = int(newest_alarm.id)
    sound_url = _resolve_alarm_sound_url(qs, newest_alarm=newest_alarm)

    return {
        "new_count": new_count,
        "newest_id": newest_id,
        "sound_url": sound_url,
    }


def _parse_alarm_metadata(raw):
    """解析告警元数据。"""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_str(value) -> str:
    """处理清理字符串。"""
    return str(value or "").strip()


def _iter_detect_labels(detects) -> list:
    """遍历检测标签。"""
    if not isinstance(detects, list):
        return []
    labels = []
    for item in detects:
        if not isinstance(item, dict):
            continue
        for key in ("label", "class", "name", "object", "object_code"):
            value = _clean_str(item.get(key))
            if value:
                labels.append(value)
                break
    return labels


def _dedupe_case_insensitive(values) -> list:
    """去重大小写不敏感。"""
    normalized = []
    seen = set()
    for value in values:
        token = _clean_str(value)
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(token)
    return normalized


def _extract_alarm_match_labels(alarm):
    """提取告警匹配标签。"""
    metadata = _parse_alarm_metadata(getattr(alarm, "metadata", ""))
    labels = []

    object_code = _clean_str(getattr(alarm, "object_code", ""))
    if object_code:
        labels.append(object_code)

    labels.extend(_iter_detect_labels(metadata.get("detects")))
    return metadata, _dedupe_case_insensitive(labels)


def _clamp_int(value, *, default: int, min_value: int, max_value: int) -> int:
    """限制整数值。"""
    try:
        v = int(value or default)
    except Exception:
        v = int(default)

    if v < min_value:
        v = min_value
    if v > max_value:
        v = max_value
    return v


def _cross_camera_targets(reference_alarm, ref_metadata: dict, ref_labels: list, *, object_code: str, track_id: str):
    """处理跨域摄像头目标。"""
    user_data = ref_metadata.get("user_data") if isinstance(ref_metadata.get("user_data"), dict) else {}
    target_track_id = str(track_id or user_data.get("track_id") or ref_metadata.get("track_id") or "").strip()
    target_object = str(object_code or getattr(reference_alarm, "object_code", "") or "").strip()

    if target_object:
        ref_labels = list(dict.fromkeys(list(ref_labels) + [target_object]))

    return target_track_id, target_object, ref_labels


def _cross_camera_candidate_queryset(reference_alarm, *, minutes: int):
    """返回跨域摄像头`candidate`查询集。"""
    qs = Alarm.objects.exclude(id=reference_alarm.id)

    reference_time = getattr(reference_alarm, "create_time", None)
    if reference_time is not None:
        start = reference_time - timedelta(minutes=minutes)
        end = reference_time + timedelta(minutes=minutes)
        qs = qs.filter(create_time__gte=start, create_time__lte=end)

    reference_stream_code = str(getattr(reference_alarm, "stream_code", "") or "").strip()
    reference_stream_name = str(getattr(reference_alarm, "stream_name", "") or "").strip()
    if reference_stream_code:
        qs = qs.exclude(stream_code=reference_stream_code)
    elif reference_stream_name:
        qs = qs.exclude(stream_name=reference_stream_name)

    return qs, reference_time


def _cross_camera_label_tokens(labels: list) -> set:
    """返回跨域摄像头标签`tokens`。"""
    return {str(item).lower() for item in (labels or [])}


def _cross_camera_score_candidate(
    alarm,
    *,
    reference_time,
    ref_label_tokens: set,
    target_track_id: str,
    target_object: str,
):
    """处理跨域摄像头`score``candidate`。"""
    metadata, labels = _extract_alarm_match_labels(alarm)
    candidate_user_data = metadata.get("user_data") if isinstance(metadata.get("user_data"), dict) else {}
    candidate_track_id = str(candidate_user_data.get("track_id") or metadata.get("track_id") or "").strip()
    candidate_labels = {str(item).lower() for item in labels}

    reasons = []
    score = 0

    if target_track_id and candidate_track_id and candidate_track_id == target_track_id:
        reasons.append("track_id")
        score += 10

    if target_object and target_object.lower() in candidate_labels:
        reasons.append("object_code")
        score += 6

    overlap = sorted(ref_label_tokens.intersection(candidate_labels))
    if overlap:
        reasons.append("label_overlap")
        score += 4

    if not reasons:
        return None

    time_delta_seconds = 0
    if reference_time is not None and getattr(alarm, "create_time", None) is not None:
        time_delta_seconds = abs(int((alarm.create_time - reference_time).total_seconds()))

    return {
        "id": int(alarm.id),
        "stream_code": str(getattr(alarm, "stream_code", "") or ""),
        "stream_name": str(getattr(alarm, "stream_name", "") or ""),
        "control_code": str(getattr(alarm, "control_code", "") or ""),
        "desc": str(getattr(alarm, "desc", "") or ""),
        "match_reason": ",".join(reasons),
        "score": score,
        "time_delta_seconds": time_delta_seconds,
    }


def _cross_camera_track_id_from_alarm(metadata: dict) -> str:
    """从告警中提取跨摄像头轨迹ID。"""
    user_data = metadata.get("user_data") if isinstance(metadata.get("user_data"), dict) else {}
    return str(user_data.get("track_id") or metadata.get("track_id") or "").strip()


def _cross_camera_timeline_node(alarm, *, reference_time, role: str, match_reason: str = "", score: int = 0) -> dict:
    """构建跨摄像头时间线节点。"""
    metadata, labels = _extract_alarm_match_labels(alarm)
    create_time = getattr(alarm, "create_time", None)
    offset_seconds = 0
    if reference_time is not None and create_time is not None:
        offset_seconds = int((create_time - reference_time).total_seconds())

    return {
        "id": int(getattr(alarm, "id", 0) or 0),
        "role": role,
        "stream_code": str(getattr(alarm, "stream_code", "") or ""),
        "stream_name": str(getattr(alarm, "stream_name", "") or ""),
        "control_code": str(getattr(alarm, "control_code", "") or ""),
        "desc": str(getattr(alarm, "desc", "") or ""),
        "object_code": str(getattr(alarm, "object_code", "") or ""),
        "track_id": _cross_camera_track_id_from_alarm(metadata),
        "labels": labels,
        "match_reason": str(match_reason or ""),
        "score": int(score or 0),
        "create_time": create_time.isoformat() if create_time is not None else "",
        "offset_seconds": offset_seconds,
    }


def _cross_camera_camera_key(item: dict) -> str:
    """返回跨摄像头时间线机位键。"""
    return str(item.get("stream_code") or item.get("stream_name") or "").strip()


def build_cross_camera_timeline(reference_alarm, matched_items: list, *, track_id: str = "", object_code: str = "") -> dict:
    """构建跨摄像头统一时间线。"""
    if reference_alarm is None:
        return {
            "reference_alarm_id": 0,
            "track_id": str(track_id or "").strip(),
            "object_code": str(object_code or "").strip(),
            "items": [],
            "camera_count": 0,
            "total": 0,
        }

    ref_metadata, ref_labels = _extract_alarm_match_labels(reference_alarm)
    target_track_id, target_object, _ref_labels = _cross_camera_targets(
        reference_alarm,
        ref_metadata,
        ref_labels,
        object_code=object_code,
        track_id=track_id,
    )
    reference_time = getattr(reference_alarm, "create_time", None)

    match_by_id = {
        int(item.get("id") or 0): item
        for item in (matched_items or [])
        if int(item.get("id") or 0) > 0
    }
    alarms_by_id = {
        int(alarm.id): alarm
        for alarm in Alarm.objects.filter(id__in=list(match_by_id.keys()))
    }

    nodes = [_cross_camera_timeline_node(reference_alarm, reference_time=reference_time, role="reference")]
    for alarm_id, item in match_by_id.items():
        alarm = alarms_by_id.get(alarm_id)
        if alarm is None:
            continue
        nodes.append(
            _cross_camera_timeline_node(
                alarm,
                reference_time=reference_time,
                role="match",
                match_reason=str(item.get("match_reason") or ""),
                score=int(item.get("score") or 0),
            )
        )

    nodes.sort(key=lambda item: (str(item.get("create_time") or ""), int(item.get("id") or 0)))
    camera_keys = {_cross_camera_camera_key(item) for item in nodes if _cross_camera_camera_key(item)}

    return {
        "reference_alarm_id": int(getattr(reference_alarm, "id", 0) or 0),
        "track_id": target_track_id,
        "object_code": target_object,
        "items": nodes,
        "camera_count": len(camera_keys),
        "total": len(nodes),
        "summary": f"同一目标在 {len(camera_keys)} 个机位出现 {len(nodes)} 次。",
    }


def find_cross_camera_matches(reference_alarm, *, window_minutes=30, object_code="", track_id="", limit=20):
    """判断`find`跨域摄像头是否匹配。"""
    if reference_alarm is None:
        return []

    minutes = _clamp_int(window_minutes, default=30, min_value=1, max_value=24 * 60)
    max_items = _clamp_int(limit, default=20, min_value=1, max_value=100)

    ref_metadata, ref_labels = _extract_alarm_match_labels(reference_alarm)
    target_track_id, target_object, ref_labels = _cross_camera_targets(
        reference_alarm,
        ref_metadata,
        ref_labels,
        object_code=object_code,
        track_id=track_id,
    )

    qs, reference_time = _cross_camera_candidate_queryset(reference_alarm, minutes=minutes)
    ref_label_tokens = _cross_camera_label_tokens(ref_labels)

    results = []
    for alarm in qs.order_by("create_time", "id")[:200]:
        item = _cross_camera_score_candidate(
            alarm,
            reference_time=reference_time,
            ref_label_tokens=ref_label_tokens,
            target_track_id=target_track_id,
            target_object=target_object,
        )
        if item is not None:
            results.append(item)

    results.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            int(item.get("time_delta_seconds") or 0),
            -int(item.get("id") or 0),
        )
    )
    return results[:max_items]
