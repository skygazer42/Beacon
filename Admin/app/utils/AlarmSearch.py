import re

from django.db.models import Q


FIELD_ALIASES = {
    "control": "control_code",
    "control_code": "control_code",
    "algorithm": "algorithm_code",
    "algo": "algorithm_code",
    "algorithm_code": "algorithm_code",
    "stream": "stream",
    "camera": "stream",
    "stream_code": "stream_code",
    "stream_name": "stream_name",
    "type": "alarm_type",
    "alarm_type": "alarm_type",
    "status": "status",
    "state": "status",
}

STATUS_ALIASES = {
    "open": "open",
    "opened": "open",
    "active": "open",
    "closed": "closed",
    "close": "closed",
    "done": "closed",
    "unread": "unread",
    "new": "unread",
}

_ICONTINS_FILTER_FIELDS = (
    ("control_code", "control_code"),
    ("algorithm_code", "algorithm_code"),
    ("stream_code", "stream_code"),
    ("stream_name", "stream_name"),
    ("alarm_type", "alarm_type"),
)

_TERM_SCORE_RULES = (
    (("desc",), 12),
    (("detail_desc",), 7),
    (("control_code",), 9),
    (("stream_code", "stream_name"), 8),
    (("alarm_type", "object_code"), 6),
    (("metadata",), 4),
)


def _clean_str(value) -> str:
    """处理清理字符串。"""
    return str(value or "").strip()


def _parse_semantic_filter_token(item: str):
    """解析`semantic``filter`令牌。"""
    if ":" not in item:
        return None, None

    prefix, value = item.split(":", 1)
    key = FIELD_ALIASES.get(_clean_str(prefix).lower())
    value = _clean_str(value)
    if not key or not value:
        return None, None

    if key == "status":
        status = STATUS_ALIASES.get(value.lower())
        return ("status", status) if status else (None, None)

    if key == "stream":
        return "stream_term", value

    return key, value


def parse_alarm_semantic_query(query: str) -> dict:
    """解析告警`semantic`查询参数。"""
    raw = _clean_str(query)
    filters = {}
    free_terms = []

    for token in re.split(r"\s+", raw):
        item = _clean_str(token)
        if not item:
            continue
        key, value = _parse_semantic_filter_token(item)
        if not key:
            free_terms.append(item)
            continue
        filters[key] = value

    return {
        "query": raw,
        "terms": free_terms,
        "filters": filters,
    }


def _apply_structured_filters(queryset, filters: dict):
    """处理应用`structured``filters`。"""
    if not isinstance(filters, dict):
        return queryset

    for key, field in _ICONTINS_FILTER_FIELDS:
        value = _clean_str(filters.get(key))
        if value:
            queryset = queryset.filter(**{f"{field}__icontains": value})

    stream_term = _clean_str(filters.get("stream_term"))
    if stream_term:
        queryset = queryset.filter(Q(stream_code__icontains=stream_term) | Q(stream_name__icontains=stream_term))

    status = _clean_str(filters.get("status")).lower()
    if status == "closed":
        queryset = queryset.filter(handled=True)
    elif status == "open":
        queryset = queryset.filter(handled=False)
    elif status == "unread":
        queryset = queryset.filter(state=0)

    return queryset


def _alarm_search_document(alarm) -> dict:
    """处理告警搜索`document`。"""
    return {
        "desc": str(getattr(alarm, "desc", "") or "").lower(),
        "detail_desc": str(getattr(alarm, "detail_desc", "") or "").lower(),
        "control_code": str(getattr(alarm, "control_code", "") or "").lower(),
        "algorithm_code": str(getattr(alarm, "algorithm_code", "") or "").lower(),
        "stream_code": str(getattr(alarm, "stream_code", "") or "").lower(),
        "stream_name": str(getattr(alarm, "stream_name", "") or "").lower(),
        "alarm_type": str(getattr(alarm, "alarm_type", "") or "").lower(),
        "object_code": str(getattr(alarm, "object_code", "") or "").lower(),
        "metadata": str(getattr(alarm, "metadata", "") or "").lower(),
    }


def _score_term(doc: dict, token: str) -> int:
    """处理`score``term`。"""
    score = 0
    for fields, weight in _TERM_SCORE_RULES:
        if any(token in doc.get(field, "") for field in fields):
            score += weight
    return score


def _score_alarm(alarm, terms) -> int:
    """处理`score`告警。"""
    if not terms:
        return 1

    clean_terms = []
    for term in terms:
        token = _clean_str(term).lower()
        if token:
            clean_terms.append(token)
    if not clean_terms:
        return 1

    doc = _alarm_search_document(alarm)
    score = 0
    for token in clean_terms:
        term_score = _score_term(doc, token)
        if term_score <= 0:
            return 0
        score += term_score
    return score


def search_alarm_queryset(queryset, query: str, *, limit: int = 50) -> dict:
    """返回搜索告警查询集。"""
    parsed = parse_alarm_semantic_query(query)
    filters = parsed.get("filters") or {}
    terms = parsed.get("terms") or []

    filtered = _apply_structured_filters(queryset, filters)
    candidates = list(filtered.order_by("-id")[:200])

    scored = []
    for alarm in candidates:
        score = _score_alarm(alarm, terms)
        if score <= 0:
            continue
        scored.append((score, int(getattr(alarm, "id", 0) or 0), alarm))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    top = scored[: max(int(limit or 50), 1)]

    ids = [item[1] for item in top]
    items = []
    for score, alarm_id, alarm in top:
        items.append(
            {
                "id": alarm_id,
                "desc": str(getattr(alarm, "desc", "") or ""),
                "control_code": str(getattr(alarm, "control_code", "") or ""),
                "algorithm_code": str(getattr(alarm, "algorithm_code", "") or ""),
                "stream_code": str(getattr(alarm, "stream_code", "") or ""),
                "stream_name": str(getattr(alarm, "stream_name", "") or ""),
                "alarm_type": str(getattr(alarm, "alarm_type", "") or ""),
                "score": score,
            }
        )

    return {
        "backend": "structured_fallback",
        "fallback_reason": "semantic backend unavailable; using deterministic structured fallback",
        "filters": filters,
        "terms": terms,
        "ids": ids,
        "items": items,
        "total": len(ids),
    }
