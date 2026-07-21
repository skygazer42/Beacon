import requests
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone
from app.utils.Common import buildPageLabels
from datetime import datetime, timedelta
import io
import json
import logging
import os
import re
import zipfile
from typing import Any
from urllib.parse import urlencode

from app.utils.SafeLog import safe_json_dumps
from app.utils.UserPermissionRules import PERMISSION_KEYS, PERMISSION_META, parse_permissions_json, permission_key_candidates

from app.models import Alarm, AlarmFilterPreset, AlarmSound, AlgorithmModel, Control, Stream, UserPermission
from app.views.ViewsBase import (
    f_calcuFileBase64Str,
    f_parseGetParams,
    f_parsePostParams,
    f_responseJson,
    getUser,
    g_config,
    g_djangoSql,
)
from framework.settings import PROJECT_UA


logger = logging.getLogger(__name__)


ALARM_PRESET_VISIBILITY_PRIVATE = "private"
ALARM_PRESET_VISIBILITY_PERMISSION = "permission"
ALARM_PRESET_VISIBILITY_OPTIONS = (
    {"value": ALARM_PRESET_VISIBILITY_PRIVATE, "label": "Only me"},
    {"value": ALARM_PRESET_VISIBILITY_PERMISSION, "label": "Share to permission role"},
)
ALARM_PRESET_PERMISSION_LABELS = {str(item.get("key") or ""): str(item.get("name") or "") for item in PERMISSION_META}
# Legacy permission-key compatibility is centralized in UserPermissionRules.permission_key_candidates().

UPLOAD_PREFIX_ALARM = "alarm/"
PATH_LOGIN = "/login"
PATH_ALARMS = "/alarms"
PATH_ALARM_REVIEW = "/alarm/review"
TEMPLATE_MESSAGE = "app/message.html"
CONTENT_TYPE_ZIP = "application/zip"
MANIFEST_JSON = "manifest.json"
MSG_METHOD_NOT_SUPPORTED = "request method not supported"


def _alarm_openadd_split_algorithm_code(code: str) -> tuple[str, str]:
    """拆分算法编码中的设备后缀。"""
    if not code:
        return "", "CPU"
    value = str(code or "").strip()
    lower = value.lower()
    for suffix in ("_gpu", "_trt"):
        if lower.endswith(suffix):
            return value[:-len(suffix)], suffix[1:].upper()
        matched = re.search(rf"{re.escape(suffix)}(\d+)$", lower)
        if matched:
            dev_id = matched.group(1)
            return value[: -len(suffix) - len(dev_id)], f"{suffix[1:].upper()}:{dev_id}"
    for suffix in ("_cpu", "_auto", "_npu"):
        if lower.endswith(suffix):
            return value[:-len(suffix)], suffix[1:].upper()
    return value, "CPU"


def _alarm_openadd_is_plain_detection_control(alarm_data: dict) -> bool:
    """判断当前告警是否属于普通 detection 布控。"""
    control = alarm_data.get("control")
    if not control:
        return False
    if str(getattr(control, "behavior_algorithm_code", "") or "").strip():
        return False

    raw_algorithm_code = str(alarm_data.get("algorithm_code") or getattr(control, "algorithm_code", "") or "").strip()
    base_algorithm_code, _device = _alarm_openadd_split_algorithm_code(raw_algorithm_code)
    algorithm = AlgorithmModel.objects.filter(code=base_algorithm_code).first() if base_algorithm_code else None
    algorithm_subtype = str(getattr(algorithm, "algorithm_subtype", "") or "").strip().lower()
    if algorithm_subtype and algorithm_subtype != "detection":
        return False

    object_code = str(alarm_data.get("object_code") or getattr(control, "object_code", "") or "").strip()
    return bool(object_code)


def _alarm_openadd_run_local_filter(alarm_data: dict):
    """执行 openAdd 本地过滤。"""
    if not _alarm_openadd_is_plain_detection_control(alarm_data):
        return None

    desc = str(alarm_data.get("desc", "") or "").strip()
    if desc not in ("", "外部报警"):
        return None

    metadata_obj = alarm_data.get("metadata_obj")
    if not isinstance(metadata_obj, dict) or not metadata_obj:
        return None

    detects = metadata_obj.get("detects")
    if isinstance(detects, list) and len(detects) > 0:
        return None

    return {
        "code": 1000,
        "msg": "filtered",
        "reason": "empty_detects",
    }



ALARM_WORKFLOW_TRANSITIONS = {
    "new": {
        "acknowledge": "acknowledged",
        "false_positive": "false_positive",
        "closed": "closed",
    },
    "acknowledged": {
        "false_positive": "false_positive",
        "closed": "closed",
    },
    "false_positive": {
        "reopen": "acknowledged",
    },
    "closed": {
        "reopen": "acknowledged",
    },
}


def _parse_bool_param(value) -> bool:
    """解析布尔值参数。"""
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _guess_video_mime_from_url(path: str) -> str:
    """从URL获取`guess``video``mime`。"""
    clean = str(path or "").split("?", 1)[0].strip().lower()
    if clean.endswith(".mp4"):
        return "video/mp4"
    if clean.endswith((".ts", ".mpegts")):
        return "video/mp2t"
    return ""


def _guess_audio_mime_from_url(path: str) -> str:
    """从URL获取`guess`音频`mime`。"""
    clean = str(path or "").split("?", 1)[0].strip().lower()
    if clean.endswith(".mp3"):
        return "audio/mpeg"
    if clean.endswith(".wav"):
        return "audio/wav"
    if clean.endswith(".ogg"):
        return "audio/ogg"
    if clean.endswith(".m4a"):
        return "audio/mp4"
    if clean.endswith(".aac"):
        return "audio/aac"
    return ""


def _parse_datetime_local(value):
    """解析`datetime``local`。"""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # datetime-local commonly uses: 2026-02-21T11:00
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
        except Exception:
            break
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _parse_alarm_metadata_obj(raw):
    """解析告警元数据`obj`。"""
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


def _parse_alarm_extra_images(raw):
    """解析告警额外`images`。"""
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x or "").strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        path = str(item or "").strip()
        if path:
            out.append(path)
    return out


def _parse_extra_images_values(extra_images):
    """解析额外`images``values`。"""
    if extra_images is None:
        return None
    if isinstance(extra_images, list):
        return extra_images
    if isinstance(extra_images, str):
        try:
            return json.loads(extra_images) if extra_images.strip() else None
        except Exception:
            raise ValueError("extra_images must be valid JSON")
    raise ValueError("extra_images must be a JSON array or string")


def _normalize_one_extra_image(item, *, idx: int, upload_dir):
    """执行归一化`one`额外图片。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    if item is None:
        return ""
    if not isinstance(item, str):
        raise ValueError(f"extra_images[{idx}] must be a string")
    path = item.strip()
    if not path:
        return ""
    path = validate_upload_rel_path(path, required_prefix=UPLOAD_PREFIX_ALARM)
    resolve_under_base(upload_dir, path)
    return path


def _normalize_extra_images_param(extra_images, *, upload_dir):
    """执行归一化额外`images`参数。"""
    values = _parse_extra_images_values(extra_images)
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError("extra_images must be a JSON array")

    cleaned = []
    for idx, item in enumerate(values):
        path = _normalize_one_extra_image(item, idx=idx, upload_dir=upload_dir)
        if path:
            cleaned.append(path)
    return cleaned


def _first_nonempty_str(*values) -> str:
    """处理首个非空字符串。"""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _pick_variant_image_rel(metadata_obj) -> str:
    """选择`variant`图片相对路径。"""
    if not isinstance(metadata_obj, dict):
        return ""
    variants = metadata_obj.get("image_variants")
    if not isinstance(variants, dict):
        return ""
    return _first_nonempty_str(variants.get("clean"), variants.get("labelme"))


def _pick_clean_extra_image(extra_images) -> str:
    """选择清理额外图片。"""
    for item in extra_images or []:
        rel = str(item or "").strip()
        if not rel:
            continue
        name = os.path.basename(rel)
        if "_clean." in name or name.startswith("clean_") or name.endswith("_clean.jpg") or name.endswith("_clean.png"):
            return rel
    return ""


def _pick_boxed_variant_image_rel(metadata_obj) -> str:
    """选择适合预览的 boxed 变体图。"""
    if not isinstance(metadata_obj, dict):
        return ""
    variants = metadata_obj.get("image_variants")
    if not isinstance(variants, dict):
        return ""
    return _first_nonempty_str(
        variants.get("boxed"),
        variants.get("preview"),
        variants.get("main"),
    )


def _pick_middle_extra_image(extra_images) -> str:
    """选择中间额外帧。"""
    rows = [str(item or "").strip() for item in (extra_images or []) if str(item or "").strip()]
    if not rows:
        return ""
    return rows[len(rows) // 2]


def _resolve_alarm_preview_image_url(image_path: str, *, metadata_obj=None, extra_images=None) -> str:
    """返回告警可稳定预览的图片 URL。"""
    candidates = [
        str(image_path or "").strip(),
        _pick_boxed_variant_image_rel(metadata_obj),
        _pick_middle_extra_image(extra_images),
        _pick_clean_extra_image(extra_images),
        _pick_variant_image_rel(metadata_obj),
    ]
    for rel in candidates:
        url = _alarm_existing_media_url(rel)
        if url:
            return url
    return ""


def _select_labelme_image_rel(alarm, metadata_obj, extra_images):
    """选择`labelme`图片相对路径。"""
    variant_rel = _pick_variant_image_rel(metadata_obj)
    if variant_rel:
        return variant_rel

    explicit = _first_nonempty_str((metadata_obj or {}).get("labelme_image_path"))
    if explicit:
        return explicit

    image_rel = _first_nonempty_str(getattr(alarm, "image_path", ""))
    if int(getattr(alarm, "draw_type", 1) or 1) == 0 and image_rel:
        return image_rel

    clean_rel = _pick_clean_extra_image(extra_images)
    return clean_rel or image_rel


def _parse_alarm_ids_param(raw_alarm_ids):
    """解析告警`ids`参数。"""
    alarm_ids = []
    for part in str(raw_alarm_ids or "").split(","):
        try:
            value = int(str(part or "").strip())
        except Exception:
            value = 0
        if value > 0:
            alarm_ids.append(value)
    return list(dict.fromkeys(alarm_ids))


def _normalize_dataset_token(value, default):
    """执行归一化`dataset`令牌。"""
    raw = str(value or "").strip()
    if not raw:
        return default
    raw = re.sub(r"[^A-Za-z0-9_-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or default


def _parse_export_dataset_context(params):
    """解析`export``dataset``context`。"""
    scope_raw = str(params.get("export_scope") or params.get("exportScope") or "").strip().lower()
    dataset_raw = str(params.get("dataset_name") or params.get("datasetName") or "").strip()
    split_raw = str(params.get("split") or params.get("dataset_split") or params.get("datasetSplit") or "").strip()
    use_dataset_layout = bool(dataset_raw or split_raw or scope_raw == "filtered")
    return {
        "export_scope": "filtered" if scope_raw == "filtered" else "selected",
        "use_dataset_layout": use_dataset_layout,
        "dataset_name": _normalize_dataset_token(dataset_raw, "beacon_alarm_dataset") if use_dataset_layout else "",
        "split": _normalize_dataset_token(split_raw, "train") if use_dataset_layout else "",
    }


def _resolve_export_request_alarm_ids(params):
    """解析并返回`export`请求告警`ids`。"""
    raw_alarm_ids = str(params.get("alarm_ids") or params.get("alarmIds") or params.get("id") or "").strip()
    if raw_alarm_ids:
        alarm_ids = _parse_alarm_ids_param(raw_alarm_ids)
        return alarm_ids, "selected", {}, (not bool(alarm_ids))

    dataset_ctx = _parse_export_dataset_context(params)
    if dataset_ctx.get("export_scope") == "filtered":
        filters = parse_alarm_filters(params)
        qs = apply_alarm_filters(Alarm.objects.all(), filters).order_by("id")
        alarm_ids = list(qs.values_list("id", flat=True))
        return alarm_ids, "filtered", filters, False

    return [], "selected", {}, False


def _build_export_zip_paths(dataset_ctx, *, image_name, label_stem="", format_name="labelme"):
    """构建`export`压缩包`paths`。"""
    use_dataset_layout = bool(dataset_ctx.get("use_dataset_layout"))
    dataset_name = str(dataset_ctx.get("dataset_name") or "").strip()
    split = str(dataset_ctx.get("split") or "").strip()

    if use_dataset_layout and dataset_name and split:
        image_path = f"{dataset_name}/{split}/images/{image_name}"
        if format_name == "labelme":
            label_path = f"{dataset_name}/{split}/labels/{label_stem}.json"
        else:
            label_path = f"{dataset_name}/annotations/instances_{split}.json"
        manifest_path = f"{dataset_name}/{MANIFEST_JSON}"
        return image_path, label_path, manifest_path

    if format_name == "labelme":
        return f"images/{image_name}", f"labels/{label_stem}.json", MANIFEST_JSON
    return f"images/{image_name}", "annotations/instances_default.json", MANIFEST_JSON


def _resolve_export_alarm_samples(alarm_ids):
    """解析并返回`export`告警`samples`。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    alarms = list(Alarm.objects.filter(id__in=alarm_ids).order_by("id"))
    samples = []
    manifest_items = []

    for alarm in alarms:
        metadata_obj = _parse_alarm_metadata_obj(getattr(alarm, "metadata", ""))
        extra_images = _parse_alarm_extra_images(getattr(alarm, "extra_images", ""))
        detects = metadata_obj.get("detects") if isinstance(metadata_obj.get("detects"), list) else []
        if not detects:
            manifest_items.append({"alarm_id": alarm.id, "exported": False, "reason": "missing_detects"})
            continue

        image_rel = _select_labelme_image_rel(alarm, metadata_obj, extra_images)
        if not image_rel:
            manifest_items.append({"alarm_id": alarm.id, "exported": False, "reason": "missing_image"})
            continue
        try:
            image_rel = validate_upload_rel_path(image_rel, required_prefix=UPLOAD_PREFIX_ALARM)
            image_abs = resolve_under_base(g_config.uploadDir, image_rel)
        except Exception as e:
            manifest_items.append({"alarm_id": alarm.id, "exported": False, "reason": str(e)})
            continue
        if not os.path.isfile(image_abs):
            manifest_items.append({"alarm_id": alarm.id, "exported": False, "reason": "image_missing_on_disk", "image_path": image_rel})
            continue

        samples.append(
            {
                "alarm": alarm,
                "metadata_obj": metadata_obj,
                "detects": [det for det in detects if isinstance(det, dict)],
                "image_rel": image_rel,
                "image_abs": image_abs,
            }
        )

    return alarms, samples, manifest_items


def _bbox_from_points(points) -> list:
    """从`points`获取`bbox`。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _collect_polygon_points(polygon) -> list:
    """处理`collect``polygon``points`。"""
    if not isinstance(polygon, list) or len(polygon) < 3:
        return []
    points = []
    for item in polygon:
        xy = _polygon_item_to_xy(item)
        if xy:
            points.append(xy)
    return points


def _collect_obb_points(obb) -> list:
    """处理`collect``obb``points`。"""
    if not isinstance(obb, list) or len(obb) != 8:
        return []
    points = []
    for i in range(0, 8, 2):
        points.append((float(obb[i]), float(obb[i + 1])))
    return points


def _build_coco_bbox(det):
    """构建`coco``bbox`。"""
    polygon = det.get("polygon") or det.get("segmentation") or det.get("segment")
    points = _collect_polygon_points(polygon)
    if points:
        return _bbox_from_points(points)

    points = _collect_obb_points(det.get("obb"))
    if points:
        return _bbox_from_points(points)

    x1 = float(det.get("x1", 0) or 0)
    y1 = float(det.get("y1", 0) or 0)
    x2 = float(det.get("x2", x1) or x1)
    y2 = float(det.get("y2", y1) or y1)
    return [x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)]


def _polygon_item_to_xy(item):
    """处理`polygon``item``to``xy`。"""
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return float(item[0]), float(item[1])
    if isinstance(item, dict):
        return float(item.get("x", 0.0) or 0.0), float(item.get("y", 0.0) or 0.0)
    return None


def _try_flatten_polygon(polygon) -> list:
    """处理`try``flatten``polygon`。"""
    if not isinstance(polygon, list) or len(polygon) < 3:
        return []
    flat = []
    for item in polygon:
        xy = _polygon_item_to_xy(item)
        if not xy:
            continue
        x, y = xy
        flat.extend([x, y])
    return flat if len(flat) >= 6 else []


def _try_obb_segmentation(obb) -> list:
    """处理`try``obb``segmentation`。"""
    if not isinstance(obb, list) or len(obb) != 8:
        return []
    try:
        return [float(v) for v in obb]
    except Exception:
        return []


def _build_coco_segmentation(det):
    """构建`coco``segmentation`。"""
    polygon = det.get("polygon") or det.get("segmentation") or det.get("segment")
    flat = _try_flatten_polygon(polygon)
    if flat:
        return [flat]

    obb_seg = _try_obb_segmentation(det.get("obb"))
    if obb_seg:
        return [obb_seg]

    return []


def _polygon_area(points):
    """处理`polygon``area`。"""
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) / 2.0


def _build_coco_area(bbox, segmentation):
    """构建`coco``area`。"""
    if segmentation and isinstance(segmentation, list) and segmentation and isinstance(segmentation[0], list):
        pts = segmentation[0]
        if len(pts) >= 6:
            pairs = [(float(pts[i]), float(pts[i + 1])) for i in range(0, len(pts), 2)]
            return _polygon_area(pairs)
    return float(bbox[2]) * float(bbox[3])


def _make_labelme_shape(label: str, points: list, shape_type: str) -> dict:
    """生成`labelme``shape`。"""
    return {
        "label": label,
        "points": points,
        "group_id": None,
        "description": "",
        "shape_type": shape_type,
        "flags": {},
    }


def _labelme_polygon_points(polygon) -> list:
    """处理`labelme``polygon``points`。"""
    if not isinstance(polygon, list) or len(polygon) < 3:
        return []
    points = []
    for item in polygon:
        xy = _polygon_item_to_xy(item)
        if not xy:
            continue
        x, y = xy
        points.append([x, y])
    return points if len(points) >= 3 else []


def _labelme_obb_points(obb) -> list:
    """处理`labelme``obb``points`。"""
    if not isinstance(obb, list) or len(obb) != 8:
        return []
    points = []
    for i in range(0, 8, 2):
        points.append([float(obb[i]), float(obb[i + 1])])
    return points


def _build_labelme_shape(det):
    """构建`labelme``shape`。"""
    label = str(det.get("class_name") or det.get("label") or det.get("name") or "object")
    polygon = det.get("polygon") or det.get("segmentation") or det.get("segment")
    points = _labelme_polygon_points(polygon)
    if points:
        return _make_labelme_shape(label, points, "polygon")

    points = _labelme_obb_points(det.get("obb"))
    if points:
        return _make_labelme_shape(label, points, "polygon")

    x1 = int(det.get("x1", 0) or 0)
    y1 = int(det.get("y1", 0) or 0)
    x2 = int(det.get("x2", 0) or 0)
    y2 = int(det.get("y2", 0) or 0)
    return _make_labelme_shape(label, [[x1, y1], [x2, y2]], "rectangle")


def parse_alarm_filters(params) -> dict:
    """解析告警`filters`。
    
    Parse shared alarm list filters from GET params.
    
        Note: return structure is intentionally template-friendly (strings + bools).
    """
    start = str(params.get("start", "")).strip()
    end = str(params.get("end", "")).strip()
    control_code = str(params.get("control_code", "")).strip()
    algorithm_code = str(params.get("algorithm_code", "")).strip()
    stream_code = str(params.get("stream_code", "")).strip()
    stream_app = str(params.get("stream_app", "")).strip()
    stream_name = str(params.get("stream_name", "")).strip()
    alarm_type = str(params.get("alarm_type", params.get("alarmType", ""))).strip()
    semantic_query = str(params.get("semantic_query", params.get("semanticQuery", ""))).strip()
    draw_type = params.get("draw_type", params.get("drawType", ""))
    draw_type = str(draw_type or "").strip()
    handled = str(params.get("handled", "") or "").strip()

    filters = {
        "start": start,
        "end": end,
        "control_code": control_code,
        "algorithm_code": algorithm_code,
        "stream_code": stream_code,
        "stream_app": stream_app,
        "stream_name": stream_name,
        "alarm_type": alarm_type,
        "semantic_query": semantic_query,
        "draw_type": draw_type,
        "handled": handled,
        "unread": _parse_bool_param(params.get("unread")),
        "has_video": _parse_bool_param(params.get("has_video")),
    }
    return filters


def _apply_alarm_icontains_filter(queryset, value, field: str):
    """处理应用告警`icontains``filter`。"""
    raw = str(value or "").strip()
    if not raw:
        return queryset
    return queryset.filter(**{f"{field}__icontains": raw})


def _apply_alarm_type_filter(queryset, alarm_type_raw: str):
    """处理应用告警类型`filter`。"""
    alarm_type_raw = str(alarm_type_raw or "").strip()
    if not alarm_type_raw:
        return queryset
    alarm_types = [s.strip() for s in alarm_type_raw.split(",") if str(s or "").strip()]
    if not alarm_types:
        return queryset
    return queryset.filter(alarm_type__in=alarm_types)


def _apply_alarm_int_field_from_bool_str(queryset, raw, field: str):
    """从布尔值字符串获取应用告警整数值`field`。"""
    raw = str(raw or "").strip()
    if raw not in ("0", "1"):
        return queryset
    return queryset.filter(**{field: int(raw)})


def _apply_alarm_bool_field_from_bool_str(queryset, raw, field: str):
    """从布尔值字符串获取应用告警布尔值`field`。"""
    raw = str(raw or "").strip()
    if raw not in ("0", "1"):
        return queryset
    return queryset.filter(**{field: bool(int(raw))})


def _apply_alarm_unread_filter(queryset, unread) -> Any:
    """处理应用告警`unread``filter`。"""
    return queryset.filter(state=0) if bool(unread) else queryset


def _apply_alarm_has_video_filter(queryset, has_video) -> Any:
    """处理应用告警`has``video``filter`。"""
    if not bool(has_video):
        return queryset
    return queryset.exclude(video_path="").exclude(video_path__isnull=True)


def _parse_end_dt_inclusive(end_raw: str):
    """解析`end``dt``inclusive`。"""
    end_raw = str(end_raw or "").strip()
    end_dt = _parse_datetime_local(end_raw)
    if not end_dt:
        return None
    # When user provides date-only (YYYY-MM-DD), include the whole day (23:59:59.999999).
    if re.match(r"^\d{4}-\d{2}-\d{2}$", end_raw):
        end_dt = end_dt + timedelta(days=1) - timedelta(microseconds=1)
    return end_dt


def _apply_alarm_time_range_filters(queryset, *, start_value, end_value):
    """处理应用告警时间`range``filters`。"""
    start_dt = _parse_datetime_local(start_value)
    if start_dt:
        queryset = queryset.filter(create_time__gte=start_dt)

    end_dt = _parse_end_dt_inclusive(end_value)
    if end_dt:
        queryset = queryset.filter(create_time__lte=end_dt)

    return queryset


def apply_alarm_filters(queryset, filters: dict):
    """处理应用告警`filters`。
    
    Apply parsed alarm filters to a Django queryset.
    """
    if not isinstance(filters, dict):
        return queryset
    queryset = _apply_alarm_icontains_filter(queryset, filters.get("control_code"), "control_code")
    queryset = _apply_alarm_icontains_filter(queryset, filters.get("algorithm_code"), "algorithm_code")
    queryset = _apply_alarm_type_filter(queryset, filters.get("alarm_type"))
    queryset = _apply_alarm_icontains_filter(queryset, filters.get("stream_code"), "stream_code")
    queryset = _apply_alarm_icontains_filter(queryset, filters.get("stream_app"), "stream_app")
    queryset = _apply_alarm_icontains_filter(queryset, filters.get("stream_name"), "stream_name")
    queryset = _apply_alarm_int_field_from_bool_str(queryset, filters.get("draw_type"), "draw_type")
    queryset = _apply_alarm_bool_field_from_bool_str(queryset, filters.get("handled"), "handled")
    queryset = _apply_alarm_unread_filter(queryset, filters.get("unread"))
    queryset = _apply_alarm_has_video_filter(queryset, filters.get("has_video"))
    queryset = _apply_alarm_time_range_filters(
        queryset,
        start_value=filters.get("start"),
        end_value=filters.get("end"),
    )
    return queryset


def _parse_alarm_note_entries(raw):
    """解析告警`note``entries`。"""
    source = _alarm_note_entries_source(raw)

    note_entries = []
    for item in source:
        parsed = _parse_alarm_note_entry(item)
        if parsed:
            note_entries.append(parsed)
    return note_entries


def _alarm_note_entries_source(raw) -> list:
    """处理告警`note``entries`来源。"""
    if isinstance(raw, list):
        return raw
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_alarm_note_entry(item):
    """解析告警`note`条目。"""
    if not isinstance(item, dict):
        return None
    note = str(item.get("note") or "").strip()
    if not note:
        return None
    return {
        "author": str(item.get("author") or "").strip(),
        "note": note,
        "created_at": str(item.get("created_at") or "").strip(),
    }


def _parse_alarm_workflow_alarm_ids(value):
    """解析告警`workflow`告警`ids`。"""
    alarm_ids = []
    for part in str(value or "").split(","):
        raw = str(part or "").strip()
        if not raw:
            continue
        try:
            alarm_id = int(raw)
        except Exception:
            return [], "invalid alarm id list"
        if alarm_id > 0:
            alarm_ids.append(alarm_id)
    return list(dict.fromkeys(alarm_ids)), ""


def _get_alarm_workflow_actor(request) -> str:
    """获取告警`workflow``actor`。"""
    session_user = getUser(request) or {}
    return str(session_user.get("username") or session_user.get("email") or "").strip()


def _resolve_alarm_workflow_transition(current_status: str, transition: str) -> str:
    """解析并返回告警`workflow``transition`。"""
    current = str(current_status or "new").strip().lower() or "new"
    step = str(transition or "").strip().lower()
    target = ALARM_WORKFLOW_TRANSITIONS.get(current, {}).get(step)
    if not target:
        raise ValueError(f"invalid workflow transition: {current} -> {step}")
    return target


def api_workflow_transition(request):
    """处理 `workflow_transition` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "method_not_allowed"})

    params = f_parsePostParams(request)
    alarm_ids, err = _parse_alarm_workflow_alarm_ids(params.get("alarm_ids_str", params.get("alarm_ids", "")))
    if not alarm_ids:
        return f_responseJson({"code": 0, "msg": err or "alarm ids required"})

    transition = str(params.get("transition") or "").strip().lower()
    if not transition:
        return f_responseJson({"code": 0, "msg": "transition required"})

    alarms = list(Alarm.objects.filter(id__in=alarm_ids).order_by("id"))
    if len(alarms) != len(alarm_ids):
        return f_responseJson({"code": 0, "msg": "alarm not found"})

    actor = _get_alarm_workflow_actor(request)
    now = timezone.now()

    try:
        for alarm in alarms:
            target = _resolve_alarm_workflow_transition(getattr(alarm, "workflow_status", "new"), transition)
            alarm.workflow_status = target
            alarm.workflow_updated_at = now
            alarm.workflow_updated_by = actor

            if transition in ("false_positive", "closed"):
                alarm.handled = True
                alarm.handled_time = now
                alarm.handled_by = actor
            else:
                alarm.handled = False
                alarm.handled_time = None
                alarm.handled_by = ""

            alarm.save(
                update_fields=[
                    "workflow_status",
                    "workflow_updated_at",
                    "workflow_updated_by",
                    "handled",
                    "handled_time",
                    "handled_by",
                ]
            )
    except ValueError as exc:
        return f_responseJson({"code": 0, "msg": str(exc)})

    return f_responseJson({"code": 1000, "msg": f"workflow transition applied to {len(alarms)} alarm(s)"})


def api_assignment_update(request):
    """处理 `assignment_update` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "method_not_allowed"})

    params = f_parsePostParams(request)
    try:
        alarm_id = int(str(params.get("alarm_id") or "0").strip())
    except Exception:
        alarm_id = 0
    if alarm_id <= 0:
        return f_responseJson({"code": 0, "msg": "invalid alarm id"})

    assigned_to_provided = "assigned_to" in params
    assigned_to = str(params.get("assigned_to") or "").strip()
    note = str(params.get("note") or "").strip()
    if not assigned_to_provided and not note:
        return f_responseJson({"code": 0, "msg": "assignment payload required"})

    try:
        alarm = Alarm.objects.get(id=alarm_id)
    except Alarm.DoesNotExist:
        return f_responseJson({"code": 0, "msg": "alarm not found"})

    update_fields = []
    if assigned_to_provided:
        alarm.assigned_to = assigned_to
        update_fields.append("assigned_to")

    if note:
        note_entries = _parse_alarm_note_entries(getattr(alarm, "note_entries", "[]"))
        note_entries.append({
            "author": _get_alarm_workflow_actor(request),
            "note": note,
            "created_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        alarm.note_entries = json.dumps(note_entries, ensure_ascii=False)
        update_fields.append("note_entries")

    if not update_fields:
        return f_responseJson({"code": 0, "msg": "no changes requested"})

    alarm.save(update_fields=update_fields)
    return f_responseJson({"code": 1000, "msg": "assignment updated"})


def _normalize_alarm_review_tab(value) -> str:
    """执行归一化告警`review``tab`。"""
    raw = str(value or "").strip().lower()
    if raw in ("unread", "open", "closed"):
        return raw
    return "open"


def _apply_alarm_review_tab(queryset, review_tab: str):
    """处理应用告警`review``tab`。"""
    if review_tab == "unread":
        return queryset.filter(state=0)
    if review_tab == "closed":
        return queryset.filter(handled=True)
    return queryset.filter(handled=False)


def _build_alarm_filter_params(filters: dict) -> dict:
    """构建告警`filter`参数。"""
    filter_params = {}
    if filters.get("start"):
        filter_params["start"] = filters.get("start")
    if filters.get("end"):
        filter_params["end"] = filters.get("end")
    if filters.get("control_code"):
        filter_params["control_code"] = filters.get("control_code")
    if filters.get("algorithm_code"):
        filter_params["algorithm_code"] = filters.get("algorithm_code")
    if filters.get("alarm_type"):
        filter_params["alarm_type"] = filters.get("alarm_type")
    if filters.get("stream_code"):
        filter_params["stream_code"] = filters.get("stream_code")
    if filters.get("stream_app"):
        filter_params["stream_app"] = filters.get("stream_app")
    if filters.get("stream_name"):
        filter_params["stream_name"] = filters.get("stream_name")
    if filters.get("semantic_query"):
        filter_params["semantic_query"] = filters.get("semantic_query")
    if filters.get("draw_type") in ("0", "1"):
        filter_params["draw_type"] = filters.get("draw_type")
    if filters.get("handled") in ("0", "1"):
        filter_params["handled"] = filters.get("handled")
    if filters.get("unread"):
        filter_params["unread"] = "1"
    if filters.get("has_video"):
        filter_params["has_video"] = "1"
    return filter_params


def _encode_alarm_filter_query(params: dict) -> str:
    """处理`encode`告警`filter`查询参数。"""
    if not params:
        return ""
    try:
        return "&" + urlencode(params)
    except Exception:
        return ""


def _build_alarm_detail_url(alarm_id: int, *, review_mode: bool, review_tab: str, filter_params: dict) -> str:
    """构建告警详情URL。"""
    if not review_mode:
        return f"/alarm/detail?id={alarm_id}"
    try:
        params = {"id": alarm_id, "from": "review", "review_tab": review_tab}
        for key, value in (filter_params or {}).items():
            if key == "review_tab":
                continue
            params[key] = value
        return "/alarm/detail?" + urlencode(params)
    except Exception:
        return f"/alarm/detail?id={alarm_id}"


def _get_alarm_preset_actor(request):
    """获取告警预设`actor`。"""
    session_user = getUser(request) or {}
    try:
        user_id = int(str(session_user.get("id") or "0").strip())
    except Exception:
        user_id = 0
    username = str(session_user.get("username") or session_user.get("email") or "").strip()
    return user_id, username


def _normalize_alarm_preset_target_mode(value) -> str:
    """执行归一化告警预设`target`模式。"""
    return "review" if str(value or "").strip().lower() == "review" else "list"


def _normalize_alarm_preset_visibility_scope(value) -> str:
    """执行归一化告警预设`visibility`作用域。"""
    return ALARM_PRESET_VISIBILITY_PERMISSION if str(value or "").strip().lower() == ALARM_PRESET_VISIBILITY_PERMISSION else ALARM_PRESET_VISIBILITY_PRIVATE


def _parse_alarm_preset_visibility_scope(value) -> str:
    """解析告警预设`visibility`作用域。"""
    raw = str(value or "").strip().lower()
    if raw in ("", ALARM_PRESET_VISIBILITY_PRIVATE):
        return ALARM_PRESET_VISIBILITY_PRIVATE
    if raw == ALARM_PRESET_VISIBILITY_PERMISSION:
        return ALARM_PRESET_VISIBILITY_PERMISSION
    return ""


def _normalize_alarm_preset_share_key(value, *, visibility_scope: str) -> str:
    """执行归一化告警预设`share`键。"""
    if visibility_scope != ALARM_PRESET_VISIBILITY_PERMISSION:
        return ""
    share_key = str(value or "").strip()
    return share_key if share_key in PERMISSION_KEYS else ""


def _load_alarm_preset_viewer_state(user_id: int):
    """加载告警预设`viewer`状态。"""
    if user_id <= 0:
        return None, None, {}

    db_user = User.objects.filter(id=user_id).first()
    if not db_user:
        return None, None, {}
    if db_user.is_staff or db_user.is_superuser:
        return db_user, True, {}

    perm_obj = UserPermission.objects.filter(user_id=user_id).first()
    parsed, perms = parse_permissions_json(getattr(perm_obj, "permissions_json", "") if perm_obj else "")
    return db_user, parsed, perms


def _alarm_preset_permission_candidates(permission_key: str):
    """处理告警预设权限候选项。"""
    return permission_key_candidates(permission_key)


def _user_matches_alarm_preset_permission(perms: dict, permission_key: str) -> bool:
    """处理用户匹配告警预设权限。"""
    if not isinstance(perms, dict):
        return False
    for candidate in _alarm_preset_permission_candidates(permission_key):
        if bool(perms.get(candidate)):
            return True
    return False


def _get_alarm_preset_share_keys_for_viewer(viewer_db_user, viewer_perm_state, viewer_permissions: dict):
    """获取告警预设`share`键列表`for``viewer`。"""
    if viewer_db_user and (viewer_db_user.is_staff or viewer_db_user.is_superuser):
        return None
    if viewer_perm_state is not True:
        return ()

    visible_share_keys = []
    for permission_key in PERMISSION_KEYS:
        if _user_matches_alarm_preset_permission(viewer_permissions, permission_key):
            visible_share_keys.append(permission_key)
    return tuple(visible_share_keys)


def _build_alarm_preset_queryset_for_viewer(*, viewer_user_id: int, target_mode: str, viewer_db_user, viewer_perm_state, viewer_permissions: dict):
    """构建告警预设查询集`for``viewer`。"""
    if viewer_user_id <= 0:
        return AlarmFilterPreset.objects.none()

    base_qs = AlarmFilterPreset.objects.filter(target_mode=target_mode)
    visibility_q = Q(owner_user_id=viewer_user_id)
    visible_share_keys = _get_alarm_preset_share_keys_for_viewer(viewer_db_user, viewer_perm_state, viewer_permissions)
    if visible_share_keys is None:
        visibility_q |= Q(visibility_scope=ALARM_PRESET_VISIBILITY_PERMISSION)
    elif visible_share_keys:
        visibility_q |= Q(
            visibility_scope=ALARM_PRESET_VISIBILITY_PERMISSION,
            share_permission_key__in=visible_share_keys,
        )
    return base_qs.filter(visibility_q).order_by("name", "id")


def _can_view_alarm_preset(row, *, viewer_user_id: int, viewer_db_user, viewer_perm_state, viewer_permissions: dict) -> bool:
    """判断`view`告警预设。"""
    owner_user_id = int(getattr(row, "owner_user_id", 0) or 0)
    if owner_user_id > 0 and owner_user_id == viewer_user_id:
        return True

    if _normalize_alarm_preset_visibility_scope(getattr(row, "visibility_scope", "")) != ALARM_PRESET_VISIBILITY_PERMISSION:
        return False

    if viewer_db_user and (viewer_db_user.is_staff or viewer_db_user.is_superuser):
        return True
    if viewer_perm_state is not True:
        return False

    share_key = _normalize_alarm_preset_share_key(
        getattr(row, "share_permission_key", ""),
        visibility_scope=ALARM_PRESET_VISIBILITY_PERMISSION,
    )
    if not share_key:
        return False
    return _user_matches_alarm_preset_permission(viewer_permissions, share_key)


def _parse_alarm_preset_payload(raw) -> dict:
    """解析告警预设载荷。"""
    if isinstance(raw, dict):
        source = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            source = json.loads(text)
        except Exception:
            return {}
    if not isinstance(source, dict):
        return {}
    return _build_alarm_filter_params(parse_alarm_filters(source))


def _build_alarm_list_url(*, target_mode: str, filter_params: dict, review_tab: str = "") -> str:
    """构建告警列表URL。"""
    try:
        base_path = PATH_ALARM_REVIEW if target_mode == "review" else PATH_ALARMS
        params = {}
        if target_mode == "review":
            params["review_tab"] = _normalize_alarm_review_tab(review_tab)
        for key, value in (filter_params or {}).items():
            params[key] = value
        if not params:
            return base_path
        return base_path + "?" + urlencode(params)
    except Exception:
        return PATH_ALARM_REVIEW if target_mode == "review" else PATH_ALARMS


def _safe_alarm_redirect_target(value, *, fallback: str) -> str:
    """处理安全告警`redirect``target`。"""
    target = str(value or "").strip()
    if not target:
        return fallback
    if target.startswith("//") or not target.startswith("/"):
        return fallback
    return target


def _is_alarm_preset_active(preset, *, target_mode: str, current_filter_params: dict, review_tab: str) -> bool:
    """判断告警预设活动。"""
    if _normalize_alarm_preset_target_mode(getattr(preset, "target_mode", "")) != target_mode:
        return False
    if target_mode == "review" and _normalize_alarm_review_tab(getattr(preset, "review_tab", "")) != _normalize_alarm_review_tab(review_tab):
        return False
    return _parse_alarm_preset_payload(getattr(preset, "filter_payload", "")) == dict(current_filter_params or {})


def _build_alarm_preset_items(request, *, target_mode: str, current_filter_params: dict, review_tab: str):
    """构建告警预设条目。"""
    user_id, _username = _get_alarm_preset_actor(request)
    if user_id <= 0:
        return []

    viewer_db_user, viewer_perm_state, viewer_permissions = _load_alarm_preset_viewer_state(user_id)
    items = []
    rows = _build_alarm_preset_queryset_for_viewer(
        viewer_user_id=user_id,
        target_mode=target_mode,
        viewer_db_user=viewer_db_user,
        viewer_perm_state=viewer_perm_state,
        viewer_permissions=viewer_permissions,
    )
    for row in rows:
        if not _can_view_alarm_preset(
            row,
            viewer_user_id=user_id,
            viewer_db_user=viewer_db_user,
            viewer_perm_state=viewer_perm_state,
            viewer_permissions=viewer_permissions,
        ):
            continue
        payload = _parse_alarm_preset_payload(getattr(row, "filter_payload", ""))
        row_review_tab = _normalize_alarm_review_tab(getattr(row, "review_tab", "")) if target_mode == "review" else ""
        visibility_scope = _normalize_alarm_preset_visibility_scope(getattr(row, "visibility_scope", ""))
        share_permission_key = _normalize_alarm_preset_share_key(
            getattr(row, "share_permission_key", ""),
            visibility_scope=visibility_scope,
        )
        owner_username = str(getattr(row, "owner_username", "") or "")
        is_owned = int(getattr(row, "owner_user_id", 0) or 0) == user_id
        items.append(
            {
                "id": row.id,
                "name": str(getattr(row, "name", "") or ""),
                "owner_username": owner_username,
                "is_owned": is_owned,
                "visibility_scope": visibility_scope,
                "share_permission_key": share_permission_key,
                "share_permission_label": ALARM_PRESET_PERMISSION_LABELS.get(share_permission_key, share_permission_key),
                "apply_url": _build_alarm_list_url(
                    target_mode=target_mode,
                    filter_params=payload,
                    review_tab=row_review_tab,
                ),
                "is_active": _is_alarm_preset_active(
                    row,
                    target_mode=target_mode,
                    current_filter_params=current_filter_params,
                    review_tab=review_tab,
                ),
            }
        )
    items.sort(key=lambda item: (0 if item.get("is_owned") else 1, str(item.get("name") or "").lower(), int(item.get("id") or 0)))
    return items


def preset_save(request):
    """处理预设`save`。"""
    user = getUser(request)
    if not user:
        return redirect(PATH_LOGIN)
    if request.method != "POST":
        return redirect(PATH_ALARMS)

    user_id, username = _get_alarm_preset_actor(request)
    if user_id <= 0:
        return redirect(PATH_LOGIN)

    params = f_parsePostParams(request)
    name = str(params.get("name") or "").strip()
    target_mode = _normalize_alarm_preset_target_mode(params.get("target_mode"))
    filters = parse_alarm_filters(params)
    filter_payload = _build_alarm_filter_params(filters)
    review_tab = _normalize_alarm_review_tab(params.get("review_tab")) if target_mode == "review" else ""
    visibility_scope = _parse_alarm_preset_visibility_scope(params.get("visibility_scope"))
    share_permission_key = _normalize_alarm_preset_share_key(
        params.get("share_permission_key"),
        visibility_scope=visibility_scope,
    )
    fallback = _build_alarm_list_url(target_mode=target_mode, filter_params=filter_payload, review_tab=review_tab)
    redirect_target = _safe_alarm_redirect_target(params.get("redirect_to"), fallback=fallback)

    if not name:
        return redirect(redirect_target)

    # Fail-closed: avoid storing names that exceed the model constraint.
    try:
        max_name_len = int(getattr(AlarmFilterPreset._meta.get_field("name"), "max_length", 0) or 0)
    except Exception:
        max_name_len = 100
    if max_name_len > 0 and len(name) > max_name_len:
        return redirect(redirect_target)

    if not visibility_scope:
        return redirect(redirect_target)
    if visibility_scope == ALARM_PRESET_VISIBILITY_PERMISSION and not share_permission_key:
        return redirect(redirect_target)

    preset, _created = AlarmFilterPreset.objects.get_or_create(
        owner_user_id=user_id,
        target_mode=target_mode,
        name=name,
        defaults={
            "owner_username": username,
            "visibility_scope": visibility_scope,
            "share_permission_key": share_permission_key,
            "filter_payload": json.dumps(filter_payload, ensure_ascii=False),
            "review_tab": review_tab,
        },
    )
    preset.owner_username = username
    preset.visibility_scope = visibility_scope
    preset.share_permission_key = share_permission_key
    preset.filter_payload = json.dumps(filter_payload, ensure_ascii=False)
    preset.review_tab = review_tab
    preset.save(
        update_fields=[
            "owner_username",
            "visibility_scope",
            "share_permission_key",
            "filter_payload",
            "review_tab",
            "update_time",
        ]
    )
    return redirect(redirect_target)


def preset_delete(request):
    """处理预设`delete`。"""
    user = getUser(request)
    if not user:
        return redirect(PATH_LOGIN)
    if request.method != "POST":
        return redirect(PATH_ALARMS)

    user_id, _username = _get_alarm_preset_actor(request)
    if user_id <= 0:
        return redirect(PATH_LOGIN)

    params = f_parsePostParams(request)
    target_mode = _normalize_alarm_preset_target_mode(params.get("target_mode"))
    fallback = PATH_ALARM_REVIEW if target_mode == "review" else PATH_ALARMS
    redirect_target = _safe_alarm_redirect_target(params.get("redirect_to"), fallback=fallback)
    try:
        preset_id = int(str(params.get("preset_id") or "0").strip())
    except Exception:
        preset_id = 0
    if preset_id > 0:
        AlarmFilterPreset.objects.filter(id=preset_id, owner_user_id=user_id).delete()
    return redirect(redirect_target)


def _alarm_index_page_and_size(
    params,
    *,
    default_page: int = 1,
    default_page_size: int = 10,
    min_page_size: int = 10,
    max_page_size: int = 50,
):
    """处理告警索引页面`and`大小。"""
    try:
        page = int(params.get("p", default_page))
    except Exception:
        page = default_page
    if page < 1:
        page = 1

    try:
        page_size = int(params.get("ps", default_page_size))
    except Exception:
        page_size = default_page_size
    if page_size < min_page_size:
        page_size = min_page_size
    if page_size > max_page_size:
        page_size = max_page_size

    return page, page_size


def _alarm_index_filter_queries(filter_params: dict, *, review_mode: bool, review_tab: str):
    """处理告警索引`filter``queries`。"""
    review_base_filter_query = _encode_alarm_filter_query(filter_params)
    pagination_filter_params = dict(filter_params or {})
    if review_mode:
        pagination_filter_params["review_tab"] = review_tab
    filter_query = _encode_alarm_filter_query(pagination_filter_params)
    return review_base_filter_query, filter_query


def _apply_alarm_semantic_search(base_qs, semantic_query: str):
    """处理应用告警`semantic`搜索。"""
    semantic_search = {
        "active": False,
        "backend": "",
        "fallback_reason": "",
        "query": "",
        "total": 0,
    }

    query = str(semantic_query or "").strip()
    if not query:
        return base_qs, semantic_search

    from app.utils.AlarmSearch import search_alarm_queryset

    result = search_alarm_queryset(base_qs, query, limit=200) or {}
    if isinstance(result, dict):
        semantic_search.update(result)

    semantic_search["active"] = True
    semantic_search["query"] = query

    semantic_ids = semantic_search.get("ids") or []
    if semantic_ids:
        base_qs = base_qs.filter(id__in=semantic_ids)
    else:
        base_qs = base_qs.none()

    return base_qs, semantic_search


def _apply_alarm_review_mode(base_qs, *, review_mode: bool, review_tab: str):
    """处理应用告警`review`模式。"""
    if not review_mode:
        return base_qs, {}

    review_counts = {
        "unread": base_qs.filter(state=0).count(),
        "open": base_qs.filter(handled=False).count(),
        "closed": base_qs.filter(handled=True).count(),
    }
    qs = _apply_alarm_review_tab(base_qs, review_tab)
    return qs, review_counts


def _paginate_alarm_queryset(queryset, *, page: int, page_size: int):
    """执行分页告警查询集。"""
    from django.core.paginator import Paginator

    paginator = Paginator(queryset, page_size)

    try:
        current_page = paginator.page(page)
    except Exception:
        current_page = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    return current_page, paginator, page


def _alarm_index_preset_hidden_fields(filter_params: dict):
    """返回告警索引预设`hidden`字段。"""
    return [
        {"name": key, "value": value}
        for key, value in (filter_params or {}).items()
    ]


def _alarm_index_permission_options():
    """处理告警索引权限`options`。"""
    return [
        {"value": str(item.get("key") or ""), "label": str(item.get("name") or "")}
        for item in PERMISSION_META
    ]


def _alarm_index_control_sound_maps(control_codes: list):
    """处理告警索引控制`sound``maps`。"""
    controls = {c.code: c for c in Control.objects.filter(code__in=control_codes)}
    sound_ids = [c.alarm_sound_id for c in controls.values() if c.alarm_sound_id]
    sound_map = {s.id: s for s in AlarmSound.objects.filter(id__in=sound_ids)}
    return controls, sound_map


def _alarm_index_sound_url(control, sound_map: dict) -> str:
    """返回告警索引`sound`URL。"""
    if not control:
        return ""
    sound = sound_map.get(control.alarm_sound_id)
    if not sound:
        return ""
    return sound.file_path


def _alarm_index_build_row(item: dict, *, sound_url: str, review_mode: bool, review_tab: str, filter_params: dict):
    """返回告警索引构建记录。"""
    image_path = item.get("image_path") or ""
    video_path = item.get("video_path") or ""

    return {
        "id": item["id"],
        "imageUrl": (g_config.uploadDir_www + image_path) if image_path else "",
        "videoUrl": (g_config.uploadDir_www + video_path) if video_path else "",
        "desc": item.get("desc"),
        "create_time": item.get("create_time"),
        "state": item.get("state"),
        "soundUrl": sound_url,
        "controlCode": item.get("control_code") or "",
        "algorithmCode": item.get("algorithm_code") or "",
        "streamCode": item.get("stream_code") or "",
        "streamApp": item.get("stream_app") or "",
        "streamName": item.get("stream_name") or "",
        "drawType": int(item.get("draw_type") or 0),
        "handled": bool(item.get("handled")),
        "handledTime": item.get("handled_time"),
        "handledBy": item.get("handled_by") or "",
        "handledRemark": item.get("handled_remark") or "",
        "hasImage": bool(image_path),
        "hasVideo": bool(video_path),
        "detailUrl": _build_alarm_detail_url(
            item["id"],
            review_mode=review_mode,
            review_tab=review_tab,
            filter_params=filter_params,
        ),
    }


def _alarm_index_build_rows(items: list, *, review_mode: bool, review_tab: str, filter_params: dict):
    """返回告警索引构建记录。"""
    control_codes = [item.get("control_code") for item in items]
    controls, sound_map = _alarm_index_control_sound_maps(control_codes)

    data = []
    for item in items:
        control = controls.get(item.get("control_code"))
        sound_url = _alarm_index_sound_url(control, sound_map)
        data.append(
            _alarm_index_build_row(
                item,
                sound_url=sound_url,
                review_mode=review_mode,
                review_tab=review_tab,
                filter_params=filter_params,
            )
        )

    return data


def _render_alarm_index(request, *, review_mode: bool = False):
    """渲染告警索引。"""
    params = f_parseGetParams(request)
    filters = parse_alarm_filters(params)

    review_tab = _normalize_alarm_review_tab(params.get("review_tab")) if review_mode else ""
    target_mode = "review" if review_mode else "list"
    alarm_list_base_path = PATH_ALARM_REVIEW if review_mode else PATH_ALARMS

    filter_params = _build_alarm_filter_params(filters)
    review_base_filter_query, filter_query = _alarm_index_filter_queries(
        filter_params,
        review_mode=review_mode,
        review_tab=review_tab,
    )

    page, page_size = _alarm_index_page_and_size(params)

    base_qs = apply_alarm_filters(Alarm.objects.all(), filters)
    base_qs, semantic_search = _apply_alarm_semantic_search(base_qs, filters.get("semantic_query", ""))
    qs, review_counts = _apply_alarm_review_mode(base_qs, review_mode=review_mode, review_tab=review_tab)

    queryset = qs.order_by("-id").values(
        "id",
        "image_path",
        "video_path",
        "desc",
        "create_time",
        "state",
        "control_code",
        "algorithm_code",
        "stream_code",
        "stream_app",
        "stream_name",
        "draw_type",
        "handled",
        "handled_time",
        "handled_by",
        "handled_remark",
    )

    current_page, paginator, page = _paginate_alarm_queryset(queryset, page=page, page_size=page_size)

    data = _alarm_index_build_rows(
        current_page.object_list,
        review_mode=review_mode,
        review_tab=review_tab,
        filter_params=filter_params,
    )

    unread_count = Alarm.objects.filter(state=0).count()
    page_labels = buildPageLabels(page=page, page_num=paginator.num_pages)

    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": page_labels,
    }

    context = {
        "data": data,
        "pageData": page_data,
        "filters": filters,
        "reviewMode": review_mode,
        "reviewTab": review_tab,
        "reviewCounts": review_counts,
        "alarmListBasePath": alarm_list_base_path,
        "reviewBaseFilterQuery": review_base_filter_query,
        "filterQuery": filter_query,
        "semanticSearch": semantic_search,
        "top_msg": f"Unread alarms {unread_count}" if unread_count > 0 else "",
        "alarmPresetTargetMode": target_mode,
        "alarmPresetCurrentUrl": request.get_full_path(),
        "alarmPresetSaveHiddenFields": _alarm_index_preset_hidden_fields(filter_params),
        "alarmPresetVisibilityOptions": ALARM_PRESET_VISIBILITY_OPTIONS,
        "alarmPresetDefaultVisibility": ALARM_PRESET_VISIBILITY_PRIVATE,
        "alarmPresetPermissionOptions": _alarm_index_permission_options(),
        "alarmPresets": _build_alarm_preset_items(
            request,
            target_mode=target_mode,
            current_filter_params=filter_params,
            review_tab=review_tab,
        ),
    }

    return render(request, "app/alarm/index.html", context)


def index(request):
    """渲染默认页面。"""
    return _render_alarm_index(request, review_mode=False)


def review_center(request):
    """处理`review``center`。"""
    return _render_alarm_index(request, review_mode=True)


def api_semantic_search(request):
    """处理 `semanticSearch` 接口请求。"""
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parseGetParams(request)
    query = str(params.get("q") or params.get("query") or params.get("text") or params.get("semantic_query") or "").strip()
    if not query:
        return f_responseJson({"code": 0, "msg": "q is required"})

    filters = parse_alarm_filters(params)
    filters["semantic_query"] = ""
    queryset = apply_alarm_filters(Alarm.objects.all(), filters)

    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    from app.utils.AlarmSearch import search_alarm_queryset

    data = search_alarm_queryset(queryset, query, limit=limit)
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_semanticSearch = api_semantic_search  # pragma: no cover - compatibility alias


def api_vlm_search(request):
    """处理 `vlmSearch` 接口请求。"""
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parseGetParams(request)
    if params.get("image_path") or params.get("image") or params.get("image_base64"):
        return _alarm_vector_search_response(params)

    query = str(params.get("q") or params.get("query") or params.get("text") or params.get("semantic_query") or "").strip()
    if not query:
        return f_responseJson({"code": 0, "msg": "q is required"})

    filters = parse_alarm_filters(params)
    filters["semantic_query"] = ""
    queryset = apply_alarm_filters(Alarm.objects.all(), filters)

    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    from app.utils.AlarmVlmSearch import search_alarm_vlm_queryset

    data = search_alarm_vlm_queryset(queryset, query, limit=limit, upload_url_prefix=g_config.uploadDir_www)
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_vlmSearch = api_vlm_search  # pragma: no cover - compatibility alias


def _alarm_vector_limit(params) -> int:
    """解析告警向量检索数量。"""
    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    if limit < 1:
        return 1
    if limit > 100:
        return 100
    return limit


def _alarm_vector_queryset(params):
    """返回告警向量检索查询集。"""
    filters = parse_alarm_filters(params)
    filters["semantic_query"] = ""
    return apply_alarm_filters(Alarm.objects.all(), filters)


def api_vector_index_rebuild(request):
    """处理告警图片向量索引重建接口。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = {key: request.POST.get(key) for key in request.POST}
    queryset = _alarm_vector_queryset(params)
    try:
        limit = int(params.get("limit", 5000))
    except (TypeError, ValueError):
        limit = 5000

    from app.utils.AlarmVectorSearch import rebuild_alarm_vector_index_queryset

    data = rebuild_alarm_vector_index_queryset(
        queryset,
        upload_root=g_config.uploadDir,
        upload_url_prefix=g_config.uploadDir_www,
        limit=limit,
    )
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_vectorIndexRebuild = api_vector_index_rebuild  # pragma: no cover - compatibility alias


def _alarm_vector_search_response(params):
    """返回告警图片向量检索响应。"""
    text = str(params.get("q") or params.get("query") or params.get("text") or params.get("semantic_query") or "").strip()
    image_path = str(params.get("image_path") or params.get("image") or "").strip()
    image_base64 = str(params.get("image_base64") or "").strip()
    queryset = _alarm_vector_queryset(params)

    from app.utils.AlarmVectorSearch import search_alarm_vector_index_queryset

    try:
        data = search_alarm_vector_index_queryset(
            queryset,
            text=text,
            image_path=image_path,
            image_base64=image_base64,
            upload_root=g_config.uploadDir,
            limit=_alarm_vector_limit(params),
        )
    except ValueError as exc:
        return f_responseJson({"code": 0, "msg": str(exc)})
    return f_responseJson({"code": 1000, "msg": "success", "data": data})


def api_vector_search(request):
    """处理告警图片向量检索接口。"""
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parseGetParams(request)
    return _alarm_vector_search_response(params)
api_vectorSearch = api_vector_search  # pragma: no cover - compatibility alias


def _workflow_tone(status: str) -> str:
    """处理`workflow``tone`。"""
    current = str(status or "").strip().lower()
    if current in ("new",):
        return "warning"
    if current in ("acknowledged", "reviewing"):
        return "accent"
    if current in ("closed", "resolved"):
        return "stable"
    return "muted"


def _alarm_review_back_params(review_tab: str, filter_params: dict) -> dict:
    """Build back-link query params for alarm review mode."""
    back_params = {"review_tab": review_tab}
    for key, value in (filter_params or {}).items():
        if key != "review_tab":
            back_params[key] = value
    return back_params


def _build_alarm_detail_navigation(params) -> dict:
    """构建告警详情`navigation`。"""
    review_mode = str((params or {}).get("from") or "").strip().lower() == "review"
    review_tab = _normalize_alarm_review_tab((params or {}).get("review_tab")) if review_mode else ""
    filters = parse_alarm_filters(params or {})
    filter_params = _build_alarm_filter_params(filters)

    if review_mode:
        back_params = _alarm_review_back_params(review_tab, filter_params)
        query = urlencode(back_params) if back_params else ""
        back_href = PATH_ALARM_REVIEW + (f"?{query}" if query else "")
        return {
            "review_mode": True,
            "review_tab": review_tab,
            "back_href": back_href,
            "back_label": "返回复核中心",
            "filter_params": filter_params,
        }

    query = urlencode(filter_params) if filter_params else ""
    return {
        "review_mode": False,
        "review_tab": "",
        "back_href": PATH_ALARMS + (f"?{query}" if query else ""),
        "back_label": "返回告警列表",
        "filter_params": filter_params,
    }


def build_alarm_detail_payload(request):
    """构建告警详情载荷。"""
    params = f_parseGetParams(request)
    alarm_id = _parse_alarm_id_param(params)
    navigation = _build_alarm_detail_navigation(params)
    if alarm_id <= 0:
        return None, {"found": False, "message": "invalid_alarm_id", "navigation": navigation}

    alarm = Alarm.objects.filter(id=alarm_id).first()
    if not alarm:
        return None, {"found": False, "message": "alarm_not_found", "navigation": navigation}

    metadata_obj = _parse_alarm_metadata_obj(getattr(alarm, "metadata", ""))
    extra_images = _parse_alarm_extra_images(getattr(alarm, "extra_images", ""))
    video_url = _alarm_existing_media_url(getattr(alarm, "video_path", ""))
    image_url = _resolve_alarm_preview_image_url(
        getattr(alarm, "image_path", ""),
        metadata_obj=metadata_obj,
        extra_images=extra_images,
    )
    control = Control.objects.filter(code=alarm.control_code).first()
    sound = AlarmSound.objects.filter(id=control.alarm_sound_id).first() if control and control.alarm_sound_id else None

    extra_image_urls = _alarm_existing_extra_image_urls(extra_images)
    try:
        user_data = metadata_obj.get("user_data") if isinstance(metadata_obj.get("user_data"), dict) else {}
    except Exception:
        user_data = {}
    try:
        metadata_pretty = json.dumps(metadata_obj, ensure_ascii=False, indent=2) if metadata_obj else ""
    except Exception:
        metadata_pretty = ""

    note_entries = _parse_alarm_note_entries(getattr(alarm, "note_entries", "[]"))

    from app.utils.AlarmDescribe import build_alarm_auto_description

    auto_description = build_alarm_auto_description(alarm, metadata_obj=metadata_obj)
    sound_url = sound.file_path if sound else ""

    payload = {
        "found": True,
        "message": "",
        "alarm": {
            "id": int(getattr(alarm, "id", 0) or 0),
            "desc": _safe_str(getattr(alarm, "desc", "")),
            "detail_desc": _safe_str(getattr(alarm, "detail_desc", "")),
            "alarm_type": _safe_str(getattr(alarm, "alarm_type", "")),
            "algorithm_code": _safe_str(getattr(alarm, "algorithm_code", "")),
            "object_code": _safe_str(getattr(alarm, "object_code", "")),
            "control_code": _safe_str(getattr(alarm, "control_code", "")),
            "stream_code": _safe_str(getattr(alarm, "stream_code", "")),
            "stream_app": _safe_str(getattr(alarm, "stream_app", "")),
            "stream_name": _safe_str(getattr(alarm, "stream_name", "")),
            "create_time": _fmt_dt(getattr(alarm, "create_time", None)),
            "state": int(getattr(alarm, "state", 0) or 0),
            "workflow_status": _safe_str(getattr(alarm, "workflow_status", "")),
            "workflow_tone": _workflow_tone(getattr(alarm, "workflow_status", "")),
        },
        "media": {
            "has_video": bool(video_url),
            "has_image": bool(image_url),
            "video_url": video_url,
            "video_mime": _guess_video_mime_from_url(video_url),
            "image_url": image_url,
            "sound_url": sound_url,
            "sound_mime": _guess_audio_mime_from_url(sound_url),
            "extra_images": extra_image_urls,
        },
        "workflow": {
            "handled": bool(getattr(alarm, "handled", False)),
            "handled_by": _safe_str(getattr(alarm, "handled_by", "")),
            "handled_time": _fmt_dt(getattr(alarm, "handled_time", None)),
            "handled_remark": _safe_str(getattr(alarm, "handled_remark", "")),
            "assigned_to": _safe_str(getattr(alarm, "assigned_to", "")),
            "workflow_status": _safe_str(getattr(alarm, "workflow_status", "")),
            "workflow_updated_at": _fmt_dt(getattr(alarm, "workflow_updated_at", None)),
            "workflow_updated_by": _safe_str(getattr(alarm, "workflow_updated_by", "")),
        },
        "notes": note_entries,
        "metadata": {
            "obj": metadata_obj,
            "pretty": metadata_pretty,
            "user_data": user_data,
        },
        "auto_description": {
            "summary": _safe_str((auto_description or {}).get("summary", "")),
            "source": _safe_str((auto_description or {}).get("source", "")),
        },
        "downloads": {
            "labelme_url": f"/alarm/exportLabelme?alarm_ids={int(alarm.id)}",
            "coco_url": f"/alarm/exportCoco?alarm_ids={int(alarm.id)}",
            "evidence_url": f"/alarm/exportEvidence?id={int(alarm.id)}",
        },
        "actions": {
            "workflow": "/alarm/workflow",
            "assignment": "/alarm/assignment",
            "handle": "/api/postHandleAlarm",
        },
        "navigation": navigation,
    }
    return alarm, payload


def _alarm_detail_template_context(alarm, payload: dict) -> dict:
    """Build the legacy alarm detail template context from the API payload."""
    media = payload.get("media") or {}
    metadata = payload.get("metadata") or {}
    workflow = payload.get("workflow") or {}
    return {
        "alarm": alarm,
        "video_url": media.get("video_url") or "",
        "video_mime": media.get("video_mime") or "",
        "image_url": media.get("image_url") or "",
        "sound_url": media.get("sound_url") or "",
        "sound_mime": media.get("sound_mime") or "",
        "has_video": bool(media.get("has_video")),
        "has_image": bool(media.get("has_image")),
        "metadata_obj": metadata.get("obj") or {},
        "metadata_pretty": metadata.get("pretty") or "",
        "user_data": metadata.get("user_data") or {},
        "extra_image_urls": media.get("extra_images") or [],
        "has_extra_images": bool(media.get("extra_images")),
        "auto_description": payload.get("auto_description") or {},
        "assigned_to": workflow.get("assigned_to") or "",
        "note_entries": payload.get("notes") or [],
    }


def detail(request):
    """处理详情。"""
    alarm, payload = build_alarm_detail_payload(request)
    if not payload.get("found"):
        return render(request, TEMPLATE_MESSAGE, {"msg": payload.get("message") or "alarm_not_found", "is_success": False, "redirect_url": PATH_ALARMS})

    return render(request, 'app/alarm/detail.html', _alarm_detail_template_context(alarm, payload))


def _resolve_alarm_evidence_file(rel_path):
    """解析并返回告警`evidence`文件。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    clean_rel = str(rel_path or "").strip()
    if not clean_rel:
        return "", ""
    try:
        clean_rel = validate_upload_rel_path(clean_rel, required_prefix=UPLOAD_PREFIX_ALARM)
        clean_abs = resolve_under_base(g_config.uploadDir, clean_rel)
    except Exception:
        return clean_rel, ""
    return clean_rel, clean_abs


def _parse_alarm_id_param(params) -> int:
    """解析告警ID参数。"""
    raw_alarm_id = (params or {}).get("id") or (params or {}).get("alarm_id") or (params or {}).get("alarmId")
    try:
        return int(str(raw_alarm_id or "0").strip())
    except Exception:
        return 0


def _safe_str(value) -> str:
    """处理安全字符串。"""
    if not value:
        return ""
    return str(value)


def _fmt_dt(dt) -> str:
    """处理`fmt``dt`。"""
    if not dt:
        return ""
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _try_add_alarm_evidence_file(
    zf,
    manifest: dict,
    *,
    base_dir: str,
    kind: str,
    rel_path,
    zip_stem: str,
    default_ext: str,
) -> None:
    """处理`try`新增告警`evidence`文件。"""
    rel, abs_path = _resolve_alarm_evidence_file(rel_path)
    if not rel or not abs_path or not os.path.isfile(abs_path):
        return

    ext = os.path.splitext(rel)[1] or default_ext
    zip_path = f"{base_dir}/{zip_stem}{ext.lower()}"
    zf.write(abs_path, zip_path)
    manifest["files"].append({"kind": kind, "path": zip_path, "source": rel})


def api_export_evidence(request):
    """处理 `exportEvidence` 接口请求。"""
    user = getUser(request)
    if not user:
        return redirect(PATH_LOGIN)

    params = f_parseGetParams(request)
    alarm_id = _parse_alarm_id_param(params)
    if alarm_id <= 0:
        return render(request, TEMPLATE_MESSAGE, {"msg": "invalid_alarm_id", "is_success": False, "redirect_url": PATH_ALARMS})

    alarm = Alarm.objects.filter(id=alarm_id).first()
    if not alarm:
        return render(request, TEMPLATE_MESSAGE, {"msg": "alarm_not_found", "is_success": False, "redirect_url": PATH_ALARMS})

    metadata_obj = _parse_alarm_metadata_obj(getattr(alarm, "metadata", ""))
    note_entries = _parse_alarm_note_entries(getattr(alarm, "note_entries", "[]"))

    payload = {
        "alarm_id": int(alarm.id),
        "control_code": _safe_str(getattr(alarm, "control_code", "")),
        "desc": _safe_str(getattr(alarm, "desc", "")),
        "detail_desc": _safe_str(getattr(alarm, "detail_desc", "")),
        "alarm_type": _safe_str(getattr(alarm, "alarm_type", "")),
        "stream_code": _safe_str(getattr(alarm, "stream_code", "")),
        "stream_name": _safe_str(getattr(alarm, "stream_name", "")),
        "workflow_status": _safe_str(getattr(alarm, "workflow_status", "")),
        "workflow_updated_at": _fmt_dt(getattr(alarm, "workflow_updated_at", None)),
        "workflow_updated_by": _safe_str(getattr(alarm, "workflow_updated_by", "")),
        "assigned_to": _safe_str(getattr(alarm, "assigned_to", "")),
        "note_entries": note_entries,
        "handled": bool(getattr(alarm, "handled", False)),
        "handled_by": _safe_str(getattr(alarm, "handled_by", "")),
        "handled_time": _fmt_dt(getattr(alarm, "handled_time", None)),
        "handled_remark": _safe_str(getattr(alarm, "handled_remark", "")),
        "metadata": metadata_obj,
    }

    buf = io.BytesIO()
    base_dir = f"alarm_{alarm.id}"
    manifest = {"alarm_id": int(alarm.id), "files": []}
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _try_add_alarm_evidence_file(
            zf,
            manifest,
            base_dir=base_dir,
            kind="snapshot",
            rel_path=getattr(alarm, "image_path", ""),
            zip_stem="snapshot",
            default_ext=".jpg",
        )
        _try_add_alarm_evidence_file(
            zf,
            manifest,
            base_dir=base_dir,
            kind="video",
            rel_path=getattr(alarm, "video_path", ""),
            zip_stem="video",
            default_ext=".mp4",
        )

        metadata_zip_path = f"{base_dir}/metadata.json"
        manifest_zip_path = f"{base_dir}/{MANIFEST_JSON}"
        zf.writestr(metadata_zip_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        manifest["files"].append({"kind": "metadata", "path": metadata_zip_path})
        zf.writestr(manifest_zip_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    filename = f"beacon_alarm_evidence_{alarm.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    resp = HttpResponse(buf.getvalue(), content_type=CONTENT_TYPE_ZIP)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
api_exportEvidence = api_export_evidence  # pragma: no cover - compatibility alias


def api_export_labelme(request):
    """处理 `exportLabelme` 接口请求。"""
    user = getUser(request)
    if not user:
        return redirect(PATH_LOGIN)

    params = f_parseGetParams(request)
    dataset_ctx = _parse_export_dataset_context(params)
    alarm_ids, export_scope, export_filters, invalid_explicit_ids = _resolve_export_request_alarm_ids(params)
    if invalid_explicit_ids:
        return render(request, TEMPLATE_MESSAGE, {"msg": "invalid_alarm_ids", "is_success": False, "redirect_url": PATH_ALARMS})
    if not alarm_ids:
        msg = "no alarms match current filters" if export_scope == "filtered" else "select at least one alarm"
        return render(request, TEMPLATE_MESSAGE, {"msg": msg, "is_success": False, "redirect_url": PATH_ALARMS})

    alarms, samples, manifest_items = _resolve_export_alarm_samples(alarm_ids)
    if not alarms:
        return render(request, TEMPLATE_MESSAGE, {"msg": "alarm_data_not_found", "is_success": False, "redirect_url": PATH_ALARMS})

    buf = io.BytesIO()
    manifest = {
        "alarm_ids": alarm_ids,
        "items": list(manifest_items),
        "dataset_name": dataset_ctx.get("dataset_name") or "",
        "split": dataset_ctx.get("split") or "",
        "export_scope": export_scope,
        "filters": export_filters if isinstance(export_filters, dict) else {},
    }
    exported = 0
    manifest_path = MANIFEST_JSON
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sample in samples:
            alarm = sample["alarm"]
            metadata_obj = sample["metadata_obj"]
            detects = sample["detects"]
            image_rel = sample["image_rel"]
            image_abs = sample["image_abs"]
            image_name = os.path.basename(image_rel)
            label_stem = os.path.splitext(image_name)[0]
            zip_image_path, zip_label_path, manifest_path = _build_export_zip_paths(
                dataset_ctx,
                image_name=image_name,
                label_stem=label_stem,
                format_name="labelme",
            )
            zf.write(image_abs, zip_image_path)

            shapes = [_build_labelme_shape(det) for det in detects if isinstance(det, dict)]
            labelme = {
                "version": "5.0.1",
                "flags": {},
                "shapes": shapes,
                "imagePath": image_name,
                "imageData": None,
                "imageHeight": int(metadata_obj.get("image_height") or 0),
                "imageWidth": int(metadata_obj.get("image_width") or 0),
            }
            zf.writestr(zip_label_path, json.dumps(labelme, ensure_ascii=False, indent=2) + "\n")

            manifest["items"].append(
                {
                    "alarm_id": alarm.id,
                    "exported": True,
                    "image_path": image_rel,
                    "zip_image_path": zip_image_path,
                    "zip_label_path": zip_label_path,
                    "detect_count": len(shapes),
                }
            )
            exported += 1

        zf.writestr(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    if exported <= 0:
        return render(request, TEMPLATE_MESSAGE, {"msg": "没有可导出的 LabelMe 样本", "is_success": False, "redirect_url": PATH_ALARMS})

    filename = f"beacon_labelme_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    resp = HttpResponse(buf.getvalue(), content_type=CONTENT_TYPE_ZIP)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
api_exportLabelme = api_export_labelme  # pragma: no cover - compatibility alias


def _coco_det_class_name(det) -> str:
    """返回`coco``det``class`名称。"""
    return str(det.get("class_name") or det.get("label") or det.get("name") or "object").strip() or "object"


def _coco_category_id(coco: dict, category_map: dict, class_name: str) -> int:
    """返回`coco``category`ID。"""
    if class_name not in category_map:
        category_map[class_name] = len(category_map) + 1
        coco["categories"].append({"id": category_map[class_name], "name": class_name, "supercategory": "alarm"})
    return int(category_map[class_name])


def _export_coco_samples(*, zf, dataset_ctx: dict, samples: list, coco: dict, manifest: dict):
    """执行`export``coco``samples`。"""
    category_map = {}
    annotation_id = 1
    exported = 0
    annotation_path = "annotations/instances_default.json"
    manifest_path = MANIFEST_JSON

    for sample in samples:
        alarm = sample["alarm"]
        metadata_obj = sample["metadata_obj"]
        detects = sample["detects"]
        image_rel = sample["image_rel"]
        image_abs = sample["image_abs"]

        image_name = os.path.basename(image_rel)
        zip_image_path, annotation_path, manifest_path = _build_export_zip_paths(
            dataset_ctx,
            image_name=image_name,
            format_name="coco",
        )
        zf.write(image_abs, zip_image_path)

        image_id = int(alarm.id)
        coco["images"].append(
            {
                "id": image_id,
                "file_name": image_name,
                "width": int(metadata_obj.get("image_width") or 0),
                "height": int(metadata_obj.get("image_height") or 0),
            }
        )

        annotation_count = 0
        for det in detects:
            class_name = _coco_det_class_name(det)
            category_id = _coco_category_id(coco, category_map, class_name)
            bbox = _build_coco_bbox(det)
            segmentation = _build_coco_segmentation(det)
            area = _build_coco_area(bbox, segmentation)
            coco["annotations"].append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": category_id,
                    "bbox": [float(v) for v in bbox],
                    "area": float(area),
                    "iscrowd": 0,
                    "segmentation": segmentation,
                }
            )
            annotation_id += 1
            annotation_count += 1

        manifest["items"].append(
            {
                "alarm_id": alarm.id,
                "exported": True,
                "image_path": image_rel,
                "zip_image_path": zip_image_path,
                "detect_count": annotation_count,
            }
        )
        exported += 1

    return exported, annotation_path, manifest_path


def api_export_coco(request):
    """处理 `exportCoco` 接口请求。"""
    user = getUser(request)
    if not user:
        return redirect(PATH_LOGIN)

    params = f_parseGetParams(request)
    dataset_ctx = _parse_export_dataset_context(params)
    alarm_ids, export_scope, export_filters, invalid_explicit_ids = _resolve_export_request_alarm_ids(params)
    if invalid_explicit_ids:
        return render(request, TEMPLATE_MESSAGE, {"msg": "invalid_alarm_ids", "is_success": False, "redirect_url": PATH_ALARMS})
    if not alarm_ids:
        msg = "no alarms match current filters" if export_scope == "filtered" else "select at least one alarm"
        return render(request, TEMPLATE_MESSAGE, {"msg": msg, "is_success": False, "redirect_url": PATH_ALARMS})

    alarms, samples, manifest_items = _resolve_export_alarm_samples(alarm_ids)
    if not alarms:
        return render(request, TEMPLATE_MESSAGE, {"msg": "alarm_data_not_found", "is_success": False, "redirect_url": PATH_ALARMS})

    buf = io.BytesIO()
    manifest = {
        "alarm_ids": alarm_ids,
        "items": list(manifest_items),
        "dataset_name": dataset_ctx.get("dataset_name") or "",
        "split": dataset_ctx.get("split") or "",
        "export_scope": export_scope,
        "filters": export_filters if isinstance(export_filters, dict) else {},
    }
    coco = {
        "info": {
            "description": "Beacon alarm sample export",
            "version": "1.0",
            "year": datetime.now().year,
        },
        "licenses": [],
        "images": [],
        "annotations": [],
        "categories": [],
    }

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        exported, annotation_path, manifest_path = _export_coco_samples(
            zf=zf,
            dataset_ctx=dataset_ctx,
            samples=samples,
            coco=coco,
            manifest=manifest,
        )
        zf.writestr(annotation_path, json.dumps(coco, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    if exported <= 0:
        return render(request, TEMPLATE_MESSAGE, {"msg": "没有可导出的 COCO 样本", "is_success": False, "redirect_url": PATH_ALARMS})

    filename = f"beacon_coco_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    resp = HttpResponse(buf.getvalue(), content_type=CONTENT_TYPE_ZIP)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
api_exportCoco = api_export_coco  # pragma: no cover - compatibility alias


def _alarm_openadd_parse_metadata(raw):
    """处理告警`openadd``parse`元数据。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except Exception:
            raise ValueError("metadata must be valid JSON")
        if data is not None and not isinstance(data, dict):
            raise ValueError("metadata must be a JSON object")
        return data
    raise ValueError("metadata must be a JSON object or string")


def _alarm_openadd_parse_unit_float(raw, field_name: str) -> float:
    """处理告警`openadd``parse``unit`浮点数。"""
    try:
        value = float(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a number")
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


def _alarm_openadd_parse_nonnegative_int(raw, field_name: str) -> int:
    """处理告警`openadd``parse``nonnegative`整数值。"""
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _alarm_openadd_parse_region_index(raw) -> int:
    """返回告警`openadd``parse`区域索引。"""
    try:
        value = int(raw)
    except Exception:
        return -1
    return value if value >= 0 else -1


def _alarm_openadd_normalize_draw_type(raw) -> int:
    """返回告警`openadd`归一化`draw`类型。"""
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return 1
    return value if value in (0, 1) else 1


def _alarm_openadd_validate_media_path(raw, *, field_name: str) -> str:
    """返回告警`openadd``validate`媒体路径。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    path = raw or ""
    if not isinstance(path, str):
        raise ValueError(f"{field_name} must be a string")
    path = path.strip()
    if not path:
        return ""
    path = validate_upload_rel_path(path, required_prefix=UPLOAD_PREFIX_ALARM)
    abs_path = resolve_under_base(g_config.uploadDir, path)
    if not os.path.isfile(abs_path):
        logger.warning("AlarmView.openAdd() dropping missing %s=%s", field_name, path)
        return ""
    return path


def _alarm_existing_media_url(rel_path: str) -> str:
    """返回告警现有媒体URL。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    path = str(rel_path or "").strip()
    if not path:
        return ""
    try:
        path = validate_upload_rel_path(path, required_prefix=UPLOAD_PREFIX_ALARM)
        abs_path = resolve_under_base(g_config.uploadDir, path)
    except Exception:
        return ""
    if not os.path.isfile(abs_path):
        return ""
    return g_config.uploadDir_www + path


def _alarm_existing_extra_image_urls(extra_images) -> list:
    """返回告警现有额外图片URL 列表。"""
    items = []
    for rel in extra_images or []:
        url = _alarm_existing_media_url(rel)
        if not url:
            continue
        items.append(
            {
                "path": rel,
                "url": url,
                "is_clean": ("_clean." in os.path.basename(rel) or os.path.basename(rel).startswith("clean_")),
            }
        )
    return items


def _alarm_openadd_control(control_code: str):
    """处理告警`openadd`控制。"""
    control = Control.objects.filter(code=control_code).first()
    if not control:
        raise ValueError(f"Control '{control_code}' not found")
    return control


def _alarm_openadd_parse_request(params) -> dict:
    """处理告警`openadd``parse`请求。"""
    if not isinstance(params, dict):
        raise ValueError("invalid request body")
    logger.debug("AlarmView.openAdd() params=%s", safe_json_dumps(params, max_len=1024))

    control_code = params.get("control_code")
    if not control_code:
        raise ValueError("control_code is required")
    if not isinstance(control_code, str) or len(control_code.strip()) == 0:
        raise ValueError("control_code must be a non-empty string")

    desc = params.get("desc")
    if not desc:
        desc = "外部报警"
    elif not isinstance(desc, str):
        raise ValueError("desc must be a string")

    video_path = _alarm_openadd_validate_media_path(params.get("video_path"), field_name="video_path")
    image_path = _alarm_openadd_validate_media_path(params.get("image_path"), field_name="image_path")

    return {
        "control_code": control_code,
        "control": _alarm_openadd_control(control_code),
        "desc": desc,
        "video_path": video_path,
        "image_path": image_path,
        "algorithm_code": params.get("algorithm_code", ""),
        "object_code": params.get("object_code", ""),
        "recognition_region": params.get("recognition_region", ""),
        "region_index": _alarm_openadd_parse_region_index(params.get("region_index", params.get("regionIndex", -1))),
        "class_thresh": _alarm_openadd_parse_unit_float(params.get("class_thresh", 0.5), "class_thresh"),
        "overlap_thresh": _alarm_openadd_parse_unit_float(params.get("overlap_thresh", 0.5), "overlap_thresh"),
        "min_interval": _alarm_openadd_parse_nonnegative_int(params.get("min_interval", 0), "min_interval"),
        "stream_code": params.get("stream_code", ""),
        "stream_app": params.get("stream_app", ""),
        "stream_name": params.get("stream_name", ""),
        "stream_url": params.get("stream_url", ""),
        "draw_type": _alarm_openadd_normalize_draw_type(params.get("draw_type", params.get("drawType", 1))),
        "metadata_obj": _alarm_openadd_parse_metadata(params.get("metadata")),
        "extra_images_list": _normalize_extra_images_param(
            params.get("extra_images", params.get("extraImages")),
            upload_dir=g_config.uploadDir,
        ),
    }


def _alarm_openadd_precheck_metadata(alarm_data: dict) -> dict:
    """处理告警`openadd`预检元数据。"""
    metadata_obj = alarm_data.get("metadata_obj")
    extra = {
        "region_index": alarm_data.get("region_index", -1),
        "draw_type": alarm_data.get("draw_type", 1),
    }
    if isinstance(metadata_obj, dict):
        return {**metadata_obj, **extra}
    return extra


def _alarm_openadd_try_resolve_upload_path(rel_path: str) -> str:
    """返回告警`openadd``try``resolve`上传路径。"""
    if not rel_path:
        return ""
    from app.utils.Security import resolve_under_base

    try:
        return resolve_under_base(g_config.uploadDir, rel_path)
    except Exception:
        return ""


def _alarm_openadd_run_precheck(alarm_data: dict):
    """处理告警`openadd``run`预检。"""
    local_filter = _alarm_openadd_run_local_filter(alarm_data)
    if local_filter:
        return local_filter

    from app.utils.AlarmPrecheck import should_store_alarm

    try:
        allow_store, precheck_reason = should_store_alarm(
            g_config,
            control_code=alarm_data.get("control_code"),
            desc=alarm_data.get("desc"),
            alarm_type="openAdd",
            algorithm_code=alarm_data.get("algorithm_code"),
            object_code=alarm_data.get("object_code"),
            recognition_region=alarm_data.get("recognition_region"),
            stream_code=alarm_data.get("stream_code"),
            stream_app=alarm_data.get("stream_app"),
            stream_name=alarm_data.get("stream_name"),
            stream_url=alarm_data.get("stream_url"),
            image_path=alarm_data.get("image_path"),
            image_abs_path=_alarm_openadd_try_resolve_upload_path(alarm_data.get("image_path", "")),
            image_base64="",
            metadata=_alarm_openadd_precheck_metadata(alarm_data),
        )
    except Exception:
        return None

    if allow_store:
        return None
    return {
        "code": 1000,
        "msg": "filtered",
        "reason": str(precheck_reason or "blocked"),
    }


def _alarm_openadd_event_extra(alarm_data: dict) -> dict:
    """处理告警`openadd`事件额外。"""
    return {
        "algorithm_code": alarm_data.get("algorithm_code", ""),
        "object_code": alarm_data.get("object_code", ""),
        "recognition_region": alarm_data.get("recognition_region", ""),
        "region_index": alarm_data.get("region_index", -1),
        "class_thresh": alarm_data.get("class_thresh", 0.5),
        "overlap_thresh": alarm_data.get("overlap_thresh", 0.5),
        "min_interval": alarm_data.get("min_interval", 0),
        "stream_code": alarm_data.get("stream_code", ""),
        "stream_app": alarm_data.get("stream_app", ""),
        "stream_name": alarm_data.get("stream_name", ""),
        "stream_url": alarm_data.get("stream_url", ""),
        "draw_type": alarm_data.get("draw_type", 1),
        "metadata": alarm_data.get("metadata_obj") or {},
        "extra_images": alarm_data.get("extra_images_list") or [],
    }


def _alarm_openadd_dispatch_created_event(alarm, *, alarm_data: dict, now_date):
    """处理告警`openadd``dispatch``created`事件。"""
    from app.utils.AlarmEventBus import (
        AlarmOutboxEnqueueError,
        build_alarm_created_event,
        enqueue_alarm_event_outbox,
    )
    from app.utils.BackgroundServices import get_alarm_sink_dispatcher

    try:
        payload = build_alarm_created_event(
            g_config,
            legacy_event="alarm_openAdd",
            event_source="openAdd",
            timestamp=now_date,
            alarm_id=alarm.id,
            control_code=alarm_data.get("control_code", ""),
            desc=alarm_data.get("desc", ""),
            image_path=alarm_data.get("image_path", ""),
            video_path=alarm_data.get("video_path", ""),
            image_url=(g_config.uploadDir_www + alarm_data.get("image_path", "")) if alarm_data.get("image_path") else "",
            video_url=(g_config.uploadDir_www + alarm_data.get("video_path", "")) if alarm_data.get("video_path") else "",
            extra=_alarm_openadd_event_extra(alarm_data),
        )

        if getattr(g_config, "alarmOutboxEnabled", True):
            enqueue_alarm_event_outbox(
                g_config,
                payload,
                alarm_id=alarm.id,
                control_code=alarm_data.get("control_code", ""),
            )
            return

        dispatcher = get_alarm_sink_dispatcher()
        if dispatcher:
            dispatcher.enqueue(payload)
    except AlarmOutboxEnqueueError:
        event_id = str(payload.get("event_id", "") or "")
        control_code = str(alarm_data.get("control_code", "") or getattr(alarm, "control_code", "") or "")
        logger.exception(
            "Alarm outbox enqueue failed event_id=%s alarm_id=%s control_code=%s",
            event_id,
            alarm.id,
            control_code,
            extra={"alarm_event_id": event_id, "alarm_id": alarm.id, "control_code": control_code},
        )
        raise
    except Exception:
        logger.debug("suppressed exception in app/views/AlarmView.py:2524", exc_info=True)


def _alarm_openadd_save_db(alarm_data: dict, *, now_date):
    """处理告警`openadd``save`数据库。"""
    alarm = Alarm()
    alarm.sort = 0
    alarm.control_code = alarm_data.get("control_code", "")
    alarm.desc = alarm_data.get("desc", "")
    alarm.detail_desc = alarm_data.get("desc", "")
    alarm.video_path = alarm_data.get("video_path", "")
    alarm.image_path = alarm_data.get("image_path", "")
    alarm.algorithm_code = alarm_data.get("algorithm_code", "")
    alarm.object_code = alarm_data.get("object_code", "")
    alarm.recognition_region = alarm_data.get("recognition_region", "")
    alarm.region_index = alarm_data.get("region_index", -1)
    alarm.class_thresh = alarm_data.get("class_thresh", 0.5)
    alarm.overlap_thresh = alarm_data.get("overlap_thresh", 0.5)
    alarm.min_interval = alarm_data.get("min_interval", 0)
    alarm.stream_code = alarm_data.get("stream_code", "")
    alarm.stream_app = alarm_data.get("stream_app", "")
    alarm.stream_name = alarm_data.get("stream_name", "")
    alarm.stream_url = alarm_data.get("stream_url", "")
    alarm.draw_type = alarm_data.get("draw_type", 1)
    if alarm_data.get("metadata_obj") is not None:
        alarm.metadata = json.dumps(alarm_data.get("metadata_obj"), ensure_ascii=False)
    if alarm_data.get("extra_images_list") is not None:
        alarm.extra_images = json.dumps(alarm_data.get("extra_images_list"), ensure_ascii=False)
    alarm.create_time = now_date
    alarm.state = 0
    alarm.save()
    _alarm_openadd_dispatch_created_event(alarm, alarm_data=alarm_data, now_date=now_date)
    return alarm


def _alarm_openadd_resolve_stream_fields(control) -> dict:
    """返回告警`openadd``resolve`流字段。"""
    stream = Stream.objects.filter(app=control.stream_app, name=control.stream_name).first()
    if stream:
        return {
            "stream_app": stream.app,
            "stream_name": stream.name,
            "stream_code": stream.code,
            "stream_nickname": stream.nickname,
        }
    return {
        "stream_app": control.stream_app,
        "stream_name": control.stream_name,
        "stream_code": control.stream_name,
        "stream_nickname": control.stream_name,
    }


def _alarm_openadd_resolve_flow_fields(control) -> dict:
    """返回告警`openadd``resolve``flow`字段。"""
    algorithm = g_djangoSql.select(
        "select * from av_algorithm where code=%s limit 1",
        [control.algorithm_code],
    )
    if len(algorithm) > 0:
        return {
            "flow_code": algorithm[0]["code"],
            "flow_name": algorithm[0]["name"],
        }
    return {
        "flow_code": control.algorithm_code,
        "flow_name": control.algorithm_code,
    }


def _alarm_openadd_append_upload_item(items: list, *, rel_path: str, index: int, path_key: str, url_key: str, include_base64: bool):
    """处理告警`openadd`追加上传`item`。"""
    abs_path = _alarm_openadd_try_resolve_upload_path(rel_path)
    if not abs_path or (not os.path.isfile(abs_path)):
        return

    item = {
        "index": index,
        path_key: rel_path,
        url_key: g_config.uploadDir_www + rel_path,
    }
    if include_base64:
        item["base64Str"] = f_calcuFileBase64Str(abs_path)
    items.append(item)


def _alarm_openadd_collect_upload_media(alarm_data: dict, *, include_base64: bool):
    """处理告警`openadd``collect`上传媒体。"""
    interface_video_array = []
    interface_image_array = []

    if alarm_data.get("video_path"):
        _alarm_openadd_append_upload_item(
            interface_video_array,
            rel_path=alarm_data.get("video_path", ""),
            index=0,
            path_key="videoPath",
            url_key="videoUrl",
            include_base64=include_base64,
        )
    if alarm_data.get("image_path"):
        _alarm_openadd_append_upload_item(
            interface_image_array,
            rel_path=alarm_data.get("image_path", ""),
            index=0,
            path_key="imagePath",
            url_key="imageUrl",
            include_base64=include_base64,
        )
    for idx, rel_path in enumerate(alarm_data.get("extra_images_list") or [], start=1):
        _alarm_openadd_append_upload_item(
            interface_image_array,
            rel_path=rel_path,
            index=idx,
            path_key="imagePath",
            url_key="imageUrl",
            include_base64=include_base64,
        )
    return interface_video_array, interface_image_array


def _alarm_openadd_upload_server(alarm_data: dict, *, now_date, alarm_obj):
    """处理告警`openadd`上传服务端。"""
    logger.debug("_alarm_openadd_upload_server() start")

    stream_fields = _alarm_openadd_resolve_stream_fields(alarm_data["control"])
    flow_fields = _alarm_openadd_resolve_flow_fields(alarm_data["control"])
    include_base64 = bool(getattr(g_config, "alarmUploadIncludeBase64", True))
    interface_video_array, interface_image_array = _alarm_openadd_collect_upload_media(
        alarm_data,
        include_base64=include_base64,
    )

    alarm_interface_data = {
        "alarmId": int(getattr(alarm_obj, "id", 0) or 0),
        "nodeCode": g_config.code,
        "streamNickname": stream_fields["stream_nickname"],
        "streamDeviceId": stream_fields["stream_nickname"],
        "streamApp": stream_fields["stream_app"],
        "streamName": stream_fields["stream_name"],
        "streamCode": stream_fields["stream_code"],
        "controlCode": alarm_data.get("control_code", ""),
        "flowCode": flow_fields["flow_code"],
        "flowName": flow_fields["flow_name"],
        "flowMode": 1,
        "drawType": alarm_data.get("draw_type", 1),
        "flag": now_date.strftime('%Y%m%d%H%M%S'),
        "desc": alarm_data.get("desc", ""),
        "videoCount": len(interface_video_array),
        "videoArray": interface_video_array,
        "imageCount": len(interface_image_array),
        "imageArray": interface_image_array,
        "imageDetects": [],
    }

    response = requests.post(
        url=g_config.saveAlarmUrl,
        headers={
            "User-Agent": PROJECT_UA,
            "Content-Type": "application/json;",
        },
        data=json.dumps(alarm_interface_data),
        timeout=60,
    )
    if response.status_code == 200:
        upload_ok = True
        upload_msg = "http_upload_ok:%s" % (response.content.decode("utf-8"))
    else:
        upload_ok = False
        upload_msg = "http_upload_failed:status=%d,%s" % (response.status_code, response.content.decode("utf-8"))

    logger.debug("_alarm_openadd_upload_server() ret=%s msg=%s", upload_ok, upload_msg)


def api_open_add(request):
    """处理 `openAdd` 接口请求。"""
    code = 0
    msg = "error"

    if request.method != 'POST':
        return f_responseJson({"code": code, "msg": "method_not_allowed"})

    try:
        params = f_parsePostParams(request)
        alarm_data = _alarm_openadd_parse_request(params)

        precheck_result = _alarm_openadd_run_precheck(alarm_data)
        if precheck_result:
            return f_responseJson(precheck_result)

        now_date = datetime.now()
        alarm_obj = None

        if g_config.saveAlarmType == 1:
            alarm_obj = _alarm_openadd_save_db(alarm_data, now_date=now_date)
        elif g_config.saveAlarmType == 2:
            _alarm_openadd_upload_server(alarm_data, now_date=now_date, alarm_obj=alarm_obj)
        elif g_config.saveAlarmType == 3:
            alarm_obj = _alarm_openadd_save_db(alarm_data, now_date=now_date)
            _alarm_openadd_upload_server(alarm_data, now_date=now_date, alarm_obj=alarm_obj)
        else:
            raise RuntimeError("unsupported saveAlarmType")

        msg = "success"
        code = 1000
    except Exception as e:
        msg = str(e)

    res = {
        "code": code,
        "msg": msg
    }
    logger.debug("AlarmView.openAdd() res=%s", safe_json_dumps(res, max_len=1024))

    return f_responseJson(res)
api_openAdd = api_open_add  # pragma: no cover - compatibility alias
