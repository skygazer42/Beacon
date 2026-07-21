import json


def _clean_str(value) -> str:
    """处理清理字符串。"""
    return str(value or "").strip()


def _parse_metadata(raw):
    """解析元数据。"""
    if isinstance(raw, dict):
        return raw
    text = _clean_str(raw)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


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


def _extract_detect_labels(metadata_obj, *, alarm=None):
    """提取检测标签。"""
    labels = []
    base_object = _clean_str(getattr(alarm, "object_code", "")) if alarm is not None else ""
    if base_object:
        labels.append(base_object)

    detects = metadata_obj.get("detects") if isinstance(metadata_obj, dict) else None
    labels.extend(_iter_detect_labels(detects))
    return _dedupe_case_insensitive(labels)


def build_alarm_auto_description(alarm, metadata_obj=None) -> dict:
    """构建告警自动`description`。"""
    metadata = metadata_obj if isinstance(metadata_obj, dict) else _parse_metadata(getattr(alarm, "metadata", ""))
    user_data = metadata.get("user_data") if isinstance(metadata.get("user_data"), dict) else {}
    labels = _extract_detect_labels(metadata, alarm=alarm)

    event_name = str(user_data.get("event") or getattr(alarm, "alarm_type", "") or "").strip()
    stream_name = str(getattr(alarm, "stream_name", "") or getattr(alarm, "stream_code", "") or "").strip()
    control_code = str(getattr(alarm, "control_code", "") or "").strip()
    region_index = user_data.get("region_index")
    if region_index is None:
        region_index = getattr(alarm, "region_index", None)

    parts = []
    if event_name:
        parts.append(event_name)
    if labels:
        parts.append("detected " + ", ".join(labels[:2]))
    if stream_name:
        parts.append("on " + stream_name)
    if control_code:
        parts.append("for " + control_code)
    if region_index not in (None, "", -1, "-1"):
        parts.append(f"in region {region_index}")

    if parts:
        return {
            "summary": " ".join(parts) + ".",
            "source": "metadata_fallback",
            "labels": labels,
        }

    manual_text = str(getattr(alarm, "detail_desc", "") or getattr(alarm, "desc", "") or "").strip()
    if manual_text:
        return {
            "summary": manual_text,
            "source": "manual_text",
            "labels": labels,
        }

    return {
        "summary": "No automatic description available yet.",
        "source": "placeholder",
        "labels": [],
    }
