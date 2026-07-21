import base64
import hashlib
import json
import math
import os
import re
import time

from app.utils.AlarmVlmSearch import CONCEPT_ALIASES
from app.utils.Security import resolve_under_base, validate_upload_rel_path


BACKEND_NAME = "alarm_local_vector_v1"
EMBEDDING_BACKEND = "local_hash_text_image_v1"
INDEX_KIND = "alarm_image_vector"
INDEX_DIR_NAME = ".beacon-index"
INDEX_FILENAME = "alarm_vectors.json"
UPLOAD_PREFIX_ALARM = "alarm/"
VECTOR_DIM = 128
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _clean_text(value, limit: int = 0) -> str:
    """清理向量索引文本。"""
    text = str(value or "").strip()
    if limit > 0:
        return text[:limit]
    return text


def _metadata_obj(raw) -> dict:
    """解析告警元数据对象。"""
    if isinstance(raw, dict):
        return raw
    text = _clean_text(raw)
    if not text:
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _flatten_metadata_values(value, output: list, *, depth: int = 0) -> None:
    """展开元数据文本。"""
    if depth > 4 or len(output) >= 120:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = _clean_text(key, 80)
            if key_text:
                output.append(key_text)
            _flatten_metadata_values(item, output, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value[:60]:
            _flatten_metadata_values(item, output, depth=depth + 1)
        return
    text = _clean_text(value, 240)
    if text:
        output.append(text)


def _field_value(alarm, name: str) -> str:
    """读取告警字段文本。"""
    return _clean_text(getattr(alarm, name, ""))


def _alarm_text(alarm) -> str:
    """构建告警向量文本。"""
    metadata_values = []
    metadata = _metadata_obj(getattr(alarm, "metadata", ""))
    _flatten_metadata_values(metadata, metadata_values)
    parts = [
        _field_value(alarm, "desc"),
        _field_value(alarm, "detail_desc"),
        _field_value(alarm, "control_code"),
        _field_value(alarm, "algorithm_code"),
        _field_value(alarm, "object_code"),
        _field_value(alarm, "alarm_type"),
        _field_value(alarm, "stream_code"),
        _field_value(alarm, "stream_name"),
        " ".join(metadata_values),
    ]
    return " ".join([item for item in parts if item])


def _concept_tokens(text: str) -> list:
    """识别并返回概念 token。"""
    lowered = _clean_text(text).lower()
    concepts = []
    for concept, aliases in CONCEPT_ALIASES.items():
        if any(str(alias).lower() in lowered for alias in aliases):
            concepts.append(f"concept:{concept}")
    return concepts


def _cjk_ngrams(value: str) -> list:
    """提取中文短语 ngram。"""
    grams = []
    for run in re.findall(r"[\u4e00-\u9fff]+", value):
        run_len = len(run)
        for size in (2, 3, 4):
            if run_len < size:
                continue
            for idx in range(0, run_len - size + 1):
                grams.append(run[idx : idx + size])
    return grams


def _text_tokens(text: str) -> list:
    """提取向量文本 token。"""
    raw = _clean_text(text).lower()
    tokens = []
    for token in re.findall(r"[0-9a-z_.:-]+|[\u4e00-\u9fff]+", raw):
        item = _clean_text(token, 120)
        if item:
            tokens.append(item)
    tokens.extend(_cjk_ngrams(raw))
    tokens.extend(_concept_tokens(raw))
    return tokens


def _hash_int(value: str) -> int:
    """计算稳定哈希整数。"""
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def _add_token(vector: list, token: str, weight: float) -> None:
    """向向量追加 token 权重。"""
    hashed = _hash_int(token)
    index = hashed % VECTOR_DIM
    sign = 1.0 if ((hashed >> 8) & 1) == 0 else -1.0
    vector[index] += sign * float(weight)


def _normalize(vector: list) -> list:
    """归一化向量。"""
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm <= 0:
        return [0.0 for _ in vector]
    return [round(float(value) / norm, 8) for value in vector]


def _text_vector_from_tokens(tokens: list) -> list:
    """根据 token 构建文本向量。"""
    vector = [0.0] * VECTOR_DIM
    seen = set()
    for token in tokens:
        item = _clean_text(token, 120)
        if not item:
            continue
        weight = 1.0
        if item.startswith("concept:"):
            weight = 3.0
        if item in seen:
            weight *= 0.35
        seen.add(item)
        _add_token(vector, f"text:{item}", weight)
    return _normalize(vector)


def _image_vector_from_bytes(content: bytes) -> list:
    """根据图片字节构建图片向量。"""
    if not content:
        return [0.0] * VECTOR_DIM
    digest = hashlib.sha256(content).hexdigest()
    vector = [0.0] * VECTOR_DIM
    _add_token(vector, f"image:sha256:{digest}", 8.0)
    _add_token(vector, f"image:length:{len(content)}", 1.5)
    for idx in range(0, len(digest), 8):
        _add_token(vector, f"image:digest:{idx}:{digest[idx:idx + 8]}", 1.0)
    return _normalize(vector)


def _cosine(left: list, right: list) -> float:
    """计算向量余弦相似度。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    return round(sum(float(a) * float(b) for a, b in zip(left, right)), 6)


def alarm_vector_index_path(upload_root: str) -> str:
    """返回告警向量索引文件路径。"""
    root = os.path.abspath(str(upload_root or ""))
    if not root:
        raise ValueError("upload_root is required")
    return os.path.join(root, INDEX_DIR_NAME, INDEX_FILENAME)


def _read_upload_image_bytes(upload_root: str, rel_path: str):
    """读取上传目录内的告警图片字节。"""
    image_path = _clean_text(rel_path)
    if not image_path:
        return b"", "image_path_empty"
    normalized = validate_upload_rel_path(image_path, required_prefix=UPLOAD_PREFIX_ALARM)
    abs_path = resolve_under_base(upload_root, normalized)
    if not os.path.isfile(abs_path):
        return b"", "image_missing_on_disk"
    with open(abs_path, "rb") as f:
        return f.read(MAX_IMAGE_BYTES), ""


def _safe_read_upload_image_bytes(upload_root: str, rel_path: str):
    """读取图片字节并返回明确错误。"""
    try:
        return _read_upload_image_bytes(upload_root, rel_path)
    except ValueError as exc:
        return b"", str(exc)
    except OSError as exc:
        return b"", str(exc)


def _serialize_alarm_doc(alarm, *, upload_root: str, upload_url_prefix: str) -> dict:
    """序列化单条告警向量文档。"""
    text = _alarm_text(alarm)
    tokens = _text_tokens(text)
    image_path = _field_value(alarm, "image_path")
    image_bytes, image_error = _safe_read_upload_image_bytes(upload_root, image_path)
    image_indexed = bool(image_bytes)
    return {
        "id": int(getattr(alarm, "id", 0) or 0),
        "desc": _field_value(alarm, "desc"),
        "detail_desc": _field_value(alarm, "detail_desc"),
        "control_code": _field_value(alarm, "control_code"),
        "algorithm_code": _field_value(alarm, "algorithm_code"),
        "alarm_type": _field_value(alarm, "alarm_type"),
        "object_code": _field_value(alarm, "object_code"),
        "stream_code": _field_value(alarm, "stream_code"),
        "stream_name": _field_value(alarm, "stream_name"),
        "image_path": image_path,
        "video_path": _field_value(alarm, "video_path"),
        "image_url": f"{upload_url_prefix}{image_path}" if image_path else "",
        "tokens": sorted(set(tokens))[:300],
        "text_vector": _text_vector_from_tokens(tokens),
        "image_vector": _image_vector_from_bytes(image_bytes),
        "image_indexed": image_indexed,
        "image_error": "" if image_indexed else image_error,
    }


def _write_index(path: str, payload: dict) -> None:
    """写入向量索引文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp_path, path)


def rebuild_alarm_vector_index_queryset(
    queryset,
    *,
    upload_root: str,
    upload_url_prefix: str = "/static/upload/",
    limit: int = 5000,
) -> dict:
    """重建告警图片向量索引。"""
    max_items = max(1, min(int(limit or 5000), 50000))
    alarms = list(queryset.order_by("-id")[:max_items])
    docs = [
        _serialize_alarm_doc(alarm, upload_root=upload_root, upload_url_prefix=upload_url_prefix)
        for alarm in alarms
    ]
    index_path = alarm_vector_index_path(upload_root)
    payload = {
        "backend": BACKEND_NAME,
        "embedding_backend": EMBEDDING_BACKEND,
        "index_kind": INDEX_KIND,
        "vector_dim": VECTOR_DIM,
        "created_at": int(time.time()),
        "docs": docs,
    }
    _write_index(index_path, payload)
    image_indexed = len([item for item in docs if item.get("image_indexed")])
    return {
        "backend": BACKEND_NAME,
        "embedding_backend": EMBEDDING_BACKEND,
        "index_kind": INDEX_KIND,
        "index_path": index_path,
        "indexed": len(docs),
        "image_indexed": image_indexed,
        "ids": [item.get("id") for item in docs],
        "capabilities": ["offline_image_vector_index", "text_to_image_vector", "image_to_image_vector"],
    }


def _load_index(upload_root: str) -> dict:
    """读取告警图片向量索引。"""
    path = alarm_vector_index_path(upload_root)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("alarm vector index must be a JSON object")
    return data


def _decode_image_base64(value: str) -> bytes:
    """解析图片 base64 查询。"""
    raw = _clean_text(value)
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise ValueError("image_base64 is invalid") from exc


def _query_vector(*, text: str, image_path: str, image_base64: str, upload_root: str):
    """构建查询向量。"""
    if _clean_text(image_base64):
        return "image_base64", _image_vector_from_bytes(_decode_image_base64(image_base64)), []
    if _clean_text(image_path):
        content, error = _read_upload_image_bytes(upload_root, image_path)
        if error:
            raise ValueError(error)
        return "image_path", _image_vector_from_bytes(content), []
    query_text = _clean_text(text)
    if not query_text:
        raise ValueError("text or image_path is required")
    tokens = _text_tokens(query_text)
    return "text", _text_vector_from_tokens(tokens), sorted(set(tokens))[:80]


def _search_result_item(doc: dict, *, score: float, matched_terms: list) -> dict:
    """返回向量检索结果项。"""
    return {
        "id": int(doc.get("id") or 0),
        "desc": _clean_text(doc.get("desc")),
        "detail_desc": _clean_text(doc.get("detail_desc")),
        "control_code": _clean_text(doc.get("control_code")),
        "algorithm_code": _clean_text(doc.get("algorithm_code")),
        "alarm_type": _clean_text(doc.get("alarm_type")),
        "object_code": _clean_text(doc.get("object_code")),
        "stream_code": _clean_text(doc.get("stream_code")),
        "stream_name": _clean_text(doc.get("stream_name")),
        "image_path": _clean_text(doc.get("image_path")),
        "video_path": _clean_text(doc.get("video_path")),
        "image_url": _clean_text(doc.get("image_url")),
        "score": score,
        "matched_terms": matched_terms,
        "image_indexed": bool(doc.get("image_indexed")),
    }


def _doc_matched_terms(doc: dict, query_tokens: list) -> list:
    """计算文本查询命中项。"""
    doc_tokens = set(doc.get("tokens") or [])
    return [item for item in query_tokens if item in doc_tokens][:20]


def search_alarm_vector_index_queryset(
    queryset,
    *,
    text: str = "",
    image_path: str = "",
    image_base64: str = "",
    upload_root: str,
    limit: int = 20,
) -> dict:
    """执行告警图片向量检索。"""
    index = _load_index(upload_root)
    query_type, vector, query_tokens = _query_vector(
        text=text,
        image_path=image_path,
        image_base64=image_base64,
        upload_root=upload_root,
    )
    max_items = max(1, min(int(limit or 20), 100))
    allowed_ids = set(queryset.values_list("id", flat=True))
    docs = index.get("docs") if isinstance(index.get("docs"), list) else []
    scored = []
    for doc in docs:
        alarm_id = int(doc.get("id") or 0)
        if alarm_id not in allowed_ids:
            continue
        doc_vector = doc.get("image_vector") if query_type.startswith("image_") else doc.get("text_vector")
        score = _cosine(vector, doc_vector)
        if score <= 0:
            continue
        matched_terms = _doc_matched_terms(doc, query_tokens) if query_type == "text" else []
        scored.append((score, alarm_id, matched_terms, doc))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    items = [
        _search_result_item(doc, score=score, matched_terms=matched_terms)
        for score, _alarm_id, matched_terms, doc in scored[:max_items]
    ]
    return {
        "backend": BACKEND_NAME,
        "embedding_backend": EMBEDDING_BACKEND,
        "index_kind": INDEX_KIND,
        "query_type": query_type,
        "index_ready": bool(index),
        "index_doc_count": len(docs),
        "ids": [item["id"] for item in items],
        "items": items,
        "total": len(items),
        "capabilities": ["offline_image_vector_index", "text_to_image_vector", "image_to_image_vector"],
        "note": "本地向量索引使用稳定哈希 embedding,用于离线索引和接口闭环;生产可替换为 CLIP/SigLIP + pgvector/OpenSearch。",
    }
