from django.utils import timezone


THREAT_LEVEL_LABELS = {
    "critical": "紧急",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}

CRITICAL_ALARM_TYPES = {"fire", "smoke", "fire_smoke"}
HIGH_ALARM_TYPES = {"intrusion", "fall", "fight", "violence", "loitering", "cross_line"}


def _clean_text(value, limit: int = 0) -> str:
    """清理告警评审文本字段。"""
    text = str(value or "").strip()
    if limit > 0:
        return text[:limit]
    return text


def _alarm_level(value) -> int:
    """归一化告警级别。"""
    level = int(value or 1)
    return max(1, min(4, level))


def _threat_level(values: dict) -> str:
    """根据告警级别和类型计算危险等级。"""
    alarm_type = _clean_text(values.get("alarm_type")).lower()
    alarm_level = _alarm_level(values.get("alarm_level"))

    if alarm_level >= 4 or alarm_type in CRITICAL_ALARM_TYPES:
        return "critical"
    if alarm_level >= 3 or alarm_type in HIGH_ALARM_TYPES:
        return "high"
    if alarm_level == 2:
        return "medium"
    return "low"


def _confidence_text(metadata_obj: dict) -> str:
    """格式化元数据中的置信度。"""
    confidence = metadata_obj.get("confidence")
    if confidence is None:
        return ""
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        value = float(confidence)
        if 0 <= value <= 1:
            value *= 100
        return f"，置信度{value:.1f}%"
    confidence_text = _clean_text(confidence, 32)
    if confidence_text:
        return f"，置信度{confidence_text}"
    return ""


def _review_reason(values: dict, threat_level: str, metadata_obj: dict) -> str:
    """生成危险分级原因。"""
    reasons = [f"告警级别{_alarm_level(values.get('alarm_level'))}"]
    alarm_type = _clean_text(values.get("alarm_type"))
    object_code = _clean_text(values.get("object_code"))
    region = _clean_text(values.get("recognition_region"))

    if alarm_type:
        reasons.append(f"类型{alarm_type}")
    if object_code:
        reasons.append(f"目标{object_code}")
    if region:
        reasons.append("命中配置区域")

    label = THREAT_LEVEL_LABELS.get(threat_level, threat_level)
    confidence = _confidence_text(metadata_obj)
    return f"{'、'.join(reasons)}{confidence}，综合判定为{label}。"


def build_alarm_ai_review(values: dict, metadata_obj: dict | None = None) -> dict:
    """构建本地规则版告警AI评审摘要。"""
    metadata = metadata_obj if isinstance(metadata_obj, dict) else {}
    desc = _clean_text(values.get("desc"), 200)
    stream_name = _clean_text(values.get("stream_name") or values.get("stream_code"), 100)
    alarm_type = _clean_text(values.get("alarm_type"), 50)
    object_code = _clean_text(values.get("object_code"), 50)
    threat_level = _threat_level(values)
    label = THREAT_LEVEL_LABELS.get(threat_level, threat_level)

    title_parts = [f"{label}告警"]
    if stream_name:
        title_parts.append(stream_name)
    if desc:
        title_parts.append(desc)
    elif alarm_type:
        title_parts.append(alarm_type)

    detail_parts = []
    if stream_name:
        detail_parts.append(f"{stream_name}触发告警")
    else:
        detail_parts.append("触发告警")
    if alarm_type:
        detail_parts.append(f"类型为{alarm_type}")
    if object_code:
        detail_parts.append(f"目标为{object_code}")
    if desc:
        detail_parts.append(f"现场描述为“{desc}”")

    confidence = _confidence_text(metadata)
    description = f"AI评审：{'，'.join(detail_parts)}{confidence}。{_review_reason(values, threat_level, metadata)}"

    title = title_parts[0]
    if len(title_parts) > 1:
        title = f"{title}：{' '.join(title_parts[1:])}"

    return {
        "title": title,
        "description": description[:2000],
        "threat_level": threat_level,
        "review_reason": _review_reason(values, threat_level, metadata),
        "provider": "local_rule_v1",
        "generated_at": timezone.now().isoformat(),
    }


def apply_alarm_ai_review(alarm, values: dict, metadata_obj: dict | None = None) -> dict:
    """把告警AI评审结果写入告警对象和元数据。"""
    metadata = dict(metadata_obj or {})
    existing_review = metadata.get("ai_review")
    if isinstance(existing_review, dict):
        review = existing_review
    else:
        review = build_alarm_ai_review(values, metadata)
        metadata["ai_review"] = review

    description = _clean_text(review.get("description"), 2000)
    if description:
        alarm.detail_desc = description
    return metadata
