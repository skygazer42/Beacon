import json
import logging
from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import redirect, render

from app.models import AlgorithmModel, ConfigHistorySnapshot, Control, Stream
from app.utils.ConfigHistory import build_diff_rows, build_system_snapshot, snapshot_payload
from app.views.ViewsBase import f_parsePostParams, f_responseJson, getUser


logger = logging.getLogger(__name__)

MSG_METHOD_NOT_SUPPORTED = "request method not supported"
EXPORT_OPTION_TYPES = [
    {
        "value": "full",
        "label": "完整导出",
        "note": "导出算法、视频流和布控配置。",
    },
    {
        "value": "partial",
        "label": "按模块导出",
        "note": "只导出当前勾选的模块。",
    },
]
EXPORT_OPTION_ITEMS = [
    {
        "value": "algorithms",
        "label": "算法资产",
        "note": "导出已启用算法模型。",
    },
    {
        "value": "streams",
        "label": "视频流",
        "note": "导出视频流接入配置。",
    },
    {
        "value": "controls",
        "label": "布控任务",
        "note": "导出布控和推流相关配置。",
    },
]
IMPORT_MERGE_MODE_OPTIONS = [
    {
        "value": "skip",
        "label": "跳过冲突项",
        "note": "遇到同编码配置时保留现有数据。",
    },
    {
        "value": "overwrite",
        "label": "覆盖冲突项",
        "note": "遇到同编码配置时用导入内容覆盖。",
    },
]


def _safe_int(value, default=0):
    """处理安全整数值。"""
    try:
        return int(value or default)
    except Exception:
        return int(default)


def _json_pretty_text(value):
    """处理JSON`pretty`文本。"""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return str(value or "")


def _value_preview(value):
    """处理值`preview`。"""
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)
    return str(value)


def _serialize_history_entry(entry, snapshot_data=None):
    """处理`serialize``history`条目。"""
    payload = snapshot_data if isinstance(snapshot_data, dict) else snapshot_payload(entry)
    return {
        "id": int(getattr(entry, "id", 0) or 0),
        "scope": str(getattr(entry, "scope", "") or ""),
        "change_type": str(getattr(entry, "change_type", "") or ""),
        "summary": str(getattr(entry, "summary", "") or ""),
        "actor": str(getattr(entry, "actor", "") or ""),
        "create_time": getattr(entry, "create_time", None),
        "site_name": str(payload.get("siteName") or "").strip(),
    }


def _serialize_diff_rows(rows):
    """返回`serialize``diff`记录。"""
    out = []
    for row in rows or []:
        target = row.get("target")
        current = row.get("current")
        out.append(
            {
                "key": str(row.get("key") or ""),
                "target": target,
                "current": current,
                "target_text": _value_preview(target),
                "current_text": _value_preview(current),
            }
        )
    return out


def build_transfer_console_metadata():
    """构建`transfer``console`元数据。"""
    return {
        "export_options": {
            "default_type": "full",
            "default_items": [item["value"] for item in EXPORT_OPTION_ITEMS],
            "types": list(EXPORT_OPTION_TYPES),
            "items": list(EXPORT_OPTION_ITEMS),
        },
        "import_merge_modes": {
            "default": "skip",
            "options": list(IMPORT_MERGE_MODE_OPTIONS),
        },
    }


def build_history_detail_payload(snapshot_id=None, *, limit=50):
    """构建`history`详情载荷。"""
    entries = list(ConfigHistorySnapshot.objects.order_by("-id")[: max(1, _safe_int(limit, 50))])
    selected = None
    selected_id = _safe_int(snapshot_id, 0)
    serialized_history = []

    for entry in entries:
        payload = snapshot_payload(entry)
        setattr(entry, "snapshot_data", payload)
        setattr(entry, "site_name", str(payload.get("siteName") or "").strip())
        serialized_history.append(_serialize_history_entry(entry, payload))
        if selected is None and (selected_id <= 0 or int(getattr(entry, "id", 0) or 0) == selected_id):
            selected = entry

    if selected is None and entries:
        selected = entries[0]

    current_snapshot = build_system_snapshot()
    selected_snapshot = snapshot_payload(selected) if selected else {}
    diff_rows = _serialize_diff_rows(build_diff_rows(selected_snapshot, current_snapshot) if selected else [])
    selected_snapshot_entry = _serialize_history_entry(selected, selected_snapshot) if selected else None
    if selected_snapshot_entry is not None:
        selected_snapshot_entry["snapshot_data"] = selected_snapshot

    return {
        "entries": entries,
        "history": serialized_history,
        "selected_entry": selected,
        "selected_snapshot": selected_snapshot_entry,
        "selected_snapshot_json": _json_pretty_text(selected_snapshot or {}),
        "current_snapshot": current_snapshot,
        "current_snapshot_json": _json_pretty_text(current_snapshot or {}),
        "diff_rows": diff_rows,
        "diff_lines": diff_rows,
    }


def export_page(request):
    """执行`export`页面。"""
    context = {
        "algorithm_count": AlgorithmModel.objects.filter(state=1).count(),
        "stream_count": Stream.objects.count(),
        "control_count": Control.objects.count(),
    }
    return render(request, "app/config/export.html", context)


def import_page(request):
    """执行导入页面。"""
    return render(request, "app/config/import.html", {})


def history_page(request):
    """处理`history`页面。"""
    user = getUser(request)
    if not user:
        return redirect("/login")

    payload = build_history_detail_payload(request.GET.get("snapshot_id"), limit=50)

    return render(request, "app/config/history.html", payload)


def _normalize_items(items):
    """执行归一化条目。"""
    if isinstance(items, str):
        return [item.strip() for item in items.split(",") if item.strip()]
    if isinstance(items, list):
        return [str(item or "").strip() for item in items if str(item or "").strip()]
    return []


def _build_export_data(export_type: str, items):
    """构建`export`数据。"""
    export_data = {
        "version": "1.0",
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "export_type": export_type,
        "data": {},
    }

    if export_type == "full" or "algorithms" in items:
        algorithms = AlgorithmModel.objects.filter(state=1).order_by("sort")
        export_data["data"]["algorithms"] = [
            {
                "code": a.code,
                "name": a.name,
                "sort": a.sort,
                "algorithm_type": a.algorithm_type,
                "basic_source": a.basic_source,
                "api_url": a.api_url,
                "model_path": a.model_path,
                "dll_path": a.dll_path,
                "builtin_behavior": a.builtin_behavior,
                "object_count": a.object_count,
                "object_str": a.object_str,
                "model_precision": getattr(a, "model_precision", "FP32"),
                "model_concurrency": getattr(a, "model_concurrency", 1),
                "input_width": getattr(a, "input_width", 640),
                "input_height": getattr(a, "input_height", 640),
                "nms_thresh": getattr(a, "nms_thresh", 0.45),
                "conf_thresh": getattr(a, "conf_thresh", 0.25),
                "max_control_count": getattr(a, "max_control_count", 0),
                "remark": a.remark,
            }
            for a in algorithms
        ]

    if export_type == "full" or "streams" in items:
        streams = Stream.objects.all().order_by("-id")
        export_data["data"]["streams"] = [
            {
                "code": s.code,
                "app": s.app,
                "name": s.name,
                "pull_stream_url": s.pull_stream_url,
                "pull_stream_type": s.pull_stream_type,
                "nickname": s.nickname,
                "remark": s.remark,
            }
            for s in streams
        ]

    if export_type == "full" or "controls" in items:
        controls = Control.objects.all().order_by("-id")
        export_data["data"]["controls"] = [
            {
                "code": c.code,
                "stream_app": c.stream_app,
                "stream_name": c.stream_name,
                "algorithm_code": c.algorithm_code,
                "object_code": c.object_code,
                "polygon": c.polygon,
                "min_interval": c.min_interval,
                "class_thresh": c.class_thresh,
                "overlap_thresh": c.overlap_thresh,
                "push_stream": c.push_stream,
                "alarm_sound_id": getattr(c, "alarm_sound_id", 0),
                "alarm_video_type": getattr(c, "alarm_video_type", "mp4"),
                "alarm_image_count": getattr(c, "alarm_image_count", 3),
                "remark": c.remark,
                "osd_enabled": getattr(c, "osd_enabled", False),
                "osd_text": getattr(c, "osd_text", ""),
                "osd_position": getattr(c, "osd_position", "top-left"),
                "push_video_codec": getattr(c, "push_video_codec", "h264"),
                "push_video_bitrate": getattr(c, "push_video_bitrate", 2000),
                "push_video_fps": getattr(c, "push_video_fps", 25),
            }
            for c in controls
        ]

    return export_data


def _load_import_data_from_uploaded_file(uploaded_file):
    """加载导入数据`from``uploaded`文件。"""
    try:
        raw = uploaded_file.read().decode("utf-8")
    except Exception as e:
        return None, str(e)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"
    except Exception as e:
        return None, str(e)

    payload = data.get("data", {}) if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None, "data must be a JSON object"
    for key in ("algorithms", "streams", "controls"):
        items = payload.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return None, f"data.{key} must be an array of objects"
    return data, ""


def _collect_conflicts(items, *, model):
    """处理`collect``conflicts`。"""
    out = []
    for item in items or []:
        code = str((item or {}).get("code") or "").strip()
        if code and model.objects.filter(code=code).exists():
            out.append(code)
    return out


def _new_import_bucket():
    """处理`new`导入`bucket`。"""
    return {"success": 0, "skipped": 0, "error": 0}


def _new_import_results():
    """返回`new`导入`results`。"""
    return {
        "algorithms": _new_import_bucket(),
        "streams": _new_import_bucket(),
        "controls": _new_import_bucket(),
    }


def _import_item_code(item):
    """执行导入`item`编码。"""
    return str((item or {}).get("code") or "").strip()


def _update_existing_import_model(existing, item):
    """更新现有导入模型。"""
    for key, value in dict(item or {}).items():
        if key != "code" and hasattr(existing, key):
            setattr(existing, key, value)
    existing.save()


def _create_algorithm_from_import(item, code):
    """创建算法`from`导入。"""
    AlgorithmModel.objects.create(
        code=code,
        name=(item or {}).get("name", code),
        sort=(item or {}).get("sort", 0),
        algorithm_type=(item or {}).get("algorithm_type", 0),
        basic_source=(item or {}).get("basic_source", "model"),
        api_url=(item or {}).get("api_url", ""),
        model_path=(item or {}).get("model_path", ""),
        dll_path=(item or {}).get("dll_path", ""),
        builtin_behavior=(item or {}).get("builtin_behavior", ""),
        object_count=(item or {}).get("object_count", 0),
        object_str=(item or {}).get("object_str", ""),
        remark=(item or {}).get("remark", ""),
        state=1,
    )


def _create_stream_from_import(item, code):
    """创建流`from`导入。"""
    Stream.objects.create(
        user_id=(item or {}).get("user_id", 0),
        sort=(item or {}).get("sort", 0),
        code=code,
        app=(item or {}).get("app", "live"),
        name=(item or {}).get("name", code),
        pull_stream_url=(item or {}).get("pull_stream_url", ""),
        pull_stream_type=(item or {}).get("pull_stream_type", 1),
        nickname=(item or {}).get("nickname", ""),
        remark=(item or {}).get("remark", ""),
        forward_state=(item or {}).get("forward_state", 0),
        state=(item or {}).get("state", 1),
    )


def _create_control_from_import(item, code):
    """创建控制`from`导入。"""
    Control.objects.create(
        user_id=(item or {}).get("user_id", 0),
        sort=(item or {}).get("sort", 0),
        code=code,
        stream_app=(item or {}).get("stream_app", "live"),
        stream_name=(item or {}).get("stream_name", ""),
        stream_video=(item or {}).get("stream_video", ""),
        stream_audio=(item or {}).get("stream_audio", ""),
        algorithm_code=(item or {}).get("algorithm_code", ""),
        object_code=(item or {}).get("object_code", ""),
        polygon=(item or {}).get("polygon", ""),
        min_interval=(item or {}).get("min_interval", 180),
        class_thresh=(item or {}).get("class_thresh", 0.5),
        overlap_thresh=(item or {}).get("overlap_thresh", 0.5),
        push_stream=(item or {}).get("push_stream", False),
        remark=(item or {}).get("remark", ""),
        state=0,
    )


def _import_model_items(items, *, merge_mode, model, results, create_item, log_label):
    """执行导入模型条目。"""
    for item in items or []:
        try:
            code = _import_item_code(item)
            if not code:
                results["error"] += 1
                continue

            existing = model.objects.filter(code=code).first()
            if existing:
                if merge_mode == "skip":
                    results["skipped"] += 1
                    continue
                _update_existing_import_model(existing, item)
                results["success"] += 1
                continue

            create_item(item, code)
            results["success"] += 1
        except Exception as e:
            logger.warning("Import %s error: %s", log_label, e)
            results["error"] += 1


def _import_config_entities(data, *, merge_mode):
    """执行导入配置`entities`。"""
    payload = data if isinstance(data, dict) else {}
    results = _new_import_results()
    _import_model_items(
        payload.get("algorithms", []),
        merge_mode=merge_mode,
        model=AlgorithmModel,
        results=results["algorithms"],
        create_item=_create_algorithm_from_import,
        log_label="algorithm",
    )
    _import_model_items(
        payload.get("streams", []),
        merge_mode=merge_mode,
        model=Stream,
        results=results["streams"],
        create_item=_create_stream_from_import,
        log_label="stream",
    )
    _import_model_items(
        payload.get("controls", []),
        merge_mode=merge_mode,
        model=Control,
        results=results["controls"],
        create_item=_create_control_from_import,
        log_label="control",
    )
    return results


def _summarize_import_results(results):
    """返回`summarize`导入`results`。"""
    total_success = sum(item["success"] for item in results.values())
    total_skipped = sum(item["skipped"] for item in results.values())
    total_error = sum(item["error"] for item in results.values())
    return total_success, total_skipped, total_error


def api_export(request):
    """处理 `export` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    export_type = str(params.get("export_type", "full") or "full").strip().lower() or "full"
    items = _normalize_items(params.get("items", ""))
    export_data = _build_export_data(export_type, items)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="beacon_config_{timestamp}.json"'
    return response


def api_preview_import(request):
    """处理 `preview_import` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return f_responseJson({"code": 0, "msg": "file is required"})

    import_data, err = _load_import_data_from_uploaded_file(uploaded_file)
    if err:
        return f_responseJson({"code": 0, "msg": str(err or "invalid json")})

    data = import_data.get("data", {}) if isinstance(import_data, dict) else {}
    conflicts = {
        "algorithms": _collect_conflicts(data.get("algorithms", []), model=AlgorithmModel),
        "streams": _collect_conflicts(data.get("streams", []), model=Stream),
        "controls": _collect_conflicts(data.get("controls", []), model=Control),
    }

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "version": import_data.get("version", "") if isinstance(import_data, dict) else "",
                "export_time": import_data.get("export_time", "") if isinstance(import_data, dict) else "",
                "counts": {
                    "algorithms": len(data.get("algorithms", [])),
                    "streams": len(data.get("streams", [])),
                    "controls": len(data.get("controls", [])),
                },
                "conflicts": conflicts,
                "has_conflicts": any(bool(v) for v in conflicts.values()),
            },
        }
    )


def api_import(request):
    """处理 `import` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    uploaded_file = request.FILES.get("file")
    merge_mode = str(request.POST.get("merge_mode", "skip") or "skip").strip().lower() or "skip"
    if not uploaded_file:
        return f_responseJson({"code": 0, "msg": "file is required"})

    import_data, err = _load_import_data_from_uploaded_file(uploaded_file)
    if err:
        return f_responseJson({"code": 0, "msg": str(err or "invalid json")})

    data = import_data.get("data", {}) if isinstance(import_data, dict) else {}
    results = _import_config_entities(data, merge_mode=merge_mode)
    total_success, total_skipped, total_error = _summarize_import_results(results)

    return f_responseJson(
        {
            "code": 1000,
            "msg": f"import complete: success {total_success}, skipped {total_skipped}, failed {total_error}",
            "data": results,
        }
    )
