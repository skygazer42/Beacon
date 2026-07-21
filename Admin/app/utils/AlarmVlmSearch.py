import json
import re


BACKEND_NAME = "vlm_local_metadata_v1"
INDEX_KIND = "alarm_evidence"

CONCEPT_ALIASES = {
    "person": ("person", "human", "人员", "有人", "行人", "人形", "人"),
    "intrusion": ("intrusion", "入侵", "闯入", "进入危险区域", "非法进入", "越界"),
    "loitering": ("loitering", "徘徊", "逗留"),
    "fall": ("fall", "跌倒", "摔倒"),
    "fight": ("fight", "violence", "打架", "斗殴", "暴力"),
    "fire": ("fire", "flame", "火焰", "明火", "起火"),
    "smoke": ("smoke", "烟雾", "冒烟"),
    "helmet": ("helmet", "hardhat", "安全帽", "头盔"),
    "vehicle": ("vehicle", "car", "车辆", "汽车"),
    "forklift": ("forklift", "叉车"),
}

DIRECT_FIELD_WEIGHTS = (
    ("stream_name", 28),
    ("stream_code", 20),
    ("control_code", 18),
)


def _clean_text(value, limit: int = 0) -> str:
    """清理视觉检索文本。"""
    text = str(value or "").strip()
    if limit > 0:
        return text[:limit]
    return text


def _metadata_obj(raw) -> dict:
    """解析告警元数据。"""
    if isinstance(raw, dict):
        return raw
    text = _clean_text(raw)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _flatten_metadata_values(value, output: list, *, depth: int = 0) -> None:
    """展开元数据中的可搜索文本。"""
    if depth > 4 or len(output) >= 80:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            output.append(_clean_text(key, 80))
            _flatten_metadata_values(item, output, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value[:40]:
            _flatten_metadata_values(item, output, depth=depth + 1)
        return
    text = _clean_text(value, 200)
    if text:
        output.append(text)


def _alarm_metadata_text(metadata: dict) -> str:
    """返回告警元数据搜索文本。"""
    values = []
    _flatten_metadata_values(metadata, values)
    return " ".join([item for item in values if item])


def _field_value(alarm, name: str) -> str:
    """读取告警字段文本。"""
    return _clean_text(getattr(alarm, name, ""))


def _detect_concepts(text: str) -> set:
    """从文本识别视觉概念。"""
    lowered = _clean_text(text).lower()
    concepts = set()
    for concept, aliases in CONCEPT_ALIASES.items():
        if any(alias.lower() in lowered for alias in aliases):
            concepts.add(concept)
    return concepts


def _query_terms(query: str) -> dict:
    """解析视觉语言查询。"""
    raw = _clean_text(query)
    lowered = raw.lower()
    concepts = _detect_concepts(lowered)
    lexical = []
    for token in re.findall(r"[0-9A-Za-z_.:-]+|[\u4e00-\u9fff]+", raw):
        item = _clean_text(token).lower()
        if item:
            lexical.append(item)
    return {
        "raw": raw,
        "lowered": lowered,
        "concepts": concepts,
        "lexical": lexical,
    }


def _alarm_vlm_caption(alarm, metadata: dict) -> str:
    """生成告警视觉语言说明。"""
    ai_review = metadata.get("ai_review") if isinstance(metadata.get("ai_review"), dict) else {}
    parts = [
        _field_value(alarm, "stream_name") or _field_value(alarm, "stream_code"),
        _field_value(alarm, "alarm_type"),
        _field_value(alarm, "object_code"),
        _field_value(alarm, "desc"),
        _clean_text(ai_review.get("title"), 200),
    ]
    return "；".join([item for item in parts if item])[:1000]


def _alarm_vlm_document(alarm) -> dict:
    """构建告警视觉语言检索文档。"""
    metadata = _metadata_obj(getattr(alarm, "metadata", ""))
    metadata_text = _alarm_metadata_text(metadata)
    text_parts = [
        _field_value(alarm, "desc"),
        _field_value(alarm, "detail_desc"),
        _field_value(alarm, "control_code"),
        _field_value(alarm, "algorithm_code"),
        _field_value(alarm, "object_code"),
        _field_value(alarm, "alarm_type"),
        _field_value(alarm, "stream_code"),
        _field_value(alarm, "stream_name"),
        metadata_text,
    ]
    text = " ".join([item for item in text_parts if item])
    caption = _alarm_vlm_caption(alarm, metadata)
    concepts = _detect_concepts(f"{text} {caption}")
    return {
        "text": text.lower(),
        "caption": caption,
        "concepts": concepts,
        "metadata": metadata,
    }


def _matched_direct_fields(alarm, query_parts: dict) -> tuple[int, list]:
    """计算查询直接命中的告警字段。"""
    score = 0
    matched = []
    raw_query = query_parts["lowered"]
    for field, weight in DIRECT_FIELD_WEIGHTS:
        value = _field_value(alarm, field).lower()
        if value and value in raw_query:
            score += weight
            matched.append(value)
    return score, matched


def _score_alarm_vlm(alarm, query_parts: dict) -> tuple[int, list]:
    """计算告警视觉语言检索分数。"""
    document = _alarm_vlm_document(alarm)
    score, matched = _matched_direct_fields(alarm, query_parts)

    for concept in sorted(query_parts["concepts"]):
        if concept in document["concepts"]:
            score += 32
            matched.append(concept)

    for token in query_parts["lexical"]:
        if token in document["text"] or token in document["caption"].lower():
            score += 8
            matched.append(token)

    if score > 0 and (_field_value(alarm, "image_path") or _field_value(alarm, "video_path")):
        score += 3

    return score, sorted(set(matched))


def _evidence_type(alarm) -> str:
    """返回告警证据类型。"""
    has_image = bool(_field_value(alarm, "image_path"))
    has_video = bool(_field_value(alarm, "video_path"))
    if has_image and has_video:
        return "image_video"
    if has_video:
        return "video"
    if has_image:
        return "image"
    return "metadata"


def _alarm_item(alarm, *, score: int, matched_terms: list, upload_url_prefix: str) -> dict:
    """返回视觉检索结果项。"""
    image_path = _field_value(alarm, "image_path")
    video_path = _field_value(alarm, "video_path")
    document = _alarm_vlm_document(alarm)
    return {
        "id": int(getattr(alarm, "id", 0) or 0),
        "desc": _field_value(alarm, "desc"),
        "control_code": _field_value(alarm, "control_code"),
        "algorithm_code": _field_value(alarm, "algorithm_code"),
        "alarm_type": _field_value(alarm, "alarm_type"),
        "object_code": _field_value(alarm, "object_code"),
        "stream_code": _field_value(alarm, "stream_code"),
        "stream_name": _field_value(alarm, "stream_name"),
        "image_path": image_path,
        "video_path": video_path,
        "image_url": f"{upload_url_prefix}{image_path}" if image_path else "",
        "video_url": f"{upload_url_prefix}{video_path}" if video_path else "",
        "evidence_type": _evidence_type(alarm),
        "vlm_caption": document["caption"],
        "matched_terms": matched_terms,
        "score": score,
    }


def search_alarm_vlm_queryset(queryset, query: str, *, limit: int = 20, upload_url_prefix: str = "/static/upload/") -> dict:
    """执行告警视觉语言检索。"""
    query_parts = _query_terms(query)
    max_items = max(1, min(int(limit or 20), 100))
    candidates = list(queryset.order_by("-id")[:500])

    scored = []
    for alarm in candidates:
        score, matched_terms = _score_alarm_vlm(alarm, query_parts)
        if score <= 0:
            continue
        scored.append((score, int(getattr(alarm, "id", 0) or 0), matched_terms, alarm))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    top = scored[:max_items]
    items = [
        _alarm_item(alarm, score=score, matched_terms=matched_terms, upload_url_prefix=upload_url_prefix)
        for score, _alarm_id, matched_terms, alarm in top
    ]

    return {
        "backend": BACKEND_NAME,
        "index_kind": INDEX_KIND,
        "query": query_parts["raw"],
        "terms": sorted(set(query_parts["lexical"])),
        "concepts": sorted(query_parts["concepts"]),
        "ids": [item["id"] for item in items],
        "items": items,
        "total": len(items),
        "capabilities": ["text_to_alarm", "metadata_visual_search", "image_video_evidence"],
        "note": "本地 PoC 基于告警证据文本和元数据构建视觉语言索引，后续可替换为 CLIP/SigLIP + 向量库。",
    }
