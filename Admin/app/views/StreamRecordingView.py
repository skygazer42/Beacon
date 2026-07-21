# ========== 视频流录像和截图 API 视图 ==========
# 提供手动录像、截图的 Web API 接口

from django.shortcuts import render

from app.models import Stream
from app.utils.StreamRecording import get_stream_recorder, get_stream_snapshotter
from app.utils.Config import Config

from app.views.ViewsBase import f_parsePostParams, f_responseJson, g_config


MSG_STREAM_CODE_REQUIRED = "视频流编号不能为空"
MSG_METHOD_NOT_SUPPORTED = "请求方法不支持"


def _snapshot_image_url(rel_path: str) -> str:
    """返回快照图片可访问 URL。"""
    path = str(rel_path or "").strip().lstrip("/")
    if not path:
        return ""
    base = str(getattr(g_config, "uploadDir_www", "/static/upload/") or "/static/upload/")
    return base.rstrip("/") + "/" + path


def _clamp_duration_seconds(raw_value, *, default: int = 60, min_value: int = 0, max_value: int = 3600) -> int:
    """限制`duration`秒数。"""
    try:
        value = int(raw_value if raw_value is not None else default)
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


def _normalize_record_format(raw_value, *, default: str = "mp4") -> str:
    """执行归一化`record``format`。"""
    fmt = str(raw_value or default).strip().lower() or default
    return fmt if fmt in ("mp4", "flv", "ts") else default


def recording_manager(request):
    """视频流录像管理页面"""
    context = {
        "streams": Stream.objects.all().order_by("-id"),
        "media_rtsp_port": getattr(g_config, "mediaRtspPort", 0) or 0,
    }
    return render(request, 'app/recording/manager.html', context)


def api_start_recording(request):
    """API: 开始录像"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED, "data": {}})

    try:
        params = f_parsePostParams(request)
        stream_code = str(params.get("stream_code", "") or "").strip()
        stream_url = str(params.get("stream_url", "") or "").strip()
        duration = _clamp_duration_seconds(params.get("duration", 60))
        fmt = _normalize_record_format(params.get("format", "mp4"))

        if not stream_code:
            return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_REQUIRED, "data": {}})
        if not stream_url:
            return f_responseJson({"code": 0, "msg": "拉流地址不能为空", "data": {}})

        storage_root = Config().storageRootPath
        recorder = get_stream_recorder(storage_root)

        result = recorder.start_recording(
            stream_code=stream_code,
            stream_url=stream_url,
            duration=duration,
            format=fmt,
        )

        if bool(result.get("success")):
            return f_responseJson(
                {
                    "code": 1000,
                    "msg": str(result.get("message") or ""),
                    "data": {
                        "record_id": result.get("record_id"),
                        "save_path": result.get("save_path"),
                    },
                }
            )
        return f_responseJson({"code": 0, "msg": str(result.get("message") or ""), "data": {}})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": f"开始录像失败：{str(e)}", "data": {}})


def api_stop_recording(request):
    """API: 停止录像"""
    code = 0
    msg = "未知错误"
    data = {}

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            stream_code = params.get('stream_code', '').strip()

            if not stream_code:
                msg = MSG_STREAM_CODE_REQUIRED
                return f_responseJson({"code": code, "msg": msg})

            # 获取存储根路径
            config = Config()
            storage_root = config.storageRootPath

            # 获取录像器
            recorder = get_stream_recorder(storage_root)

            # 停止录像
            result = recorder.stop_recording(stream_code)

            if result['success']:
                code = 1000
                msg = result['message']
                data = {
                    'save_path': result['save_path'],
                    'duration': result['duration']
                }
            else:
                msg = result['message']

        except Exception as e:
            msg = f"停止录像失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)


def api_get_recording_status(request):
    """API: 获取录像状态"""
    code = 0
    msg = "未知错误"
    data = {}

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            stream_code = params.get('stream_code', '').strip()

            if not stream_code:
                msg = MSG_STREAM_CODE_REQUIRED
                return f_responseJson({"code": code, "msg": msg})

            # 获取存储根路径
            config = Config()
            storage_root = config.storageRootPath

            # 获取录像器
            recorder = get_stream_recorder(storage_root)

            # 获取状态
            status = recorder.get_recording_status(stream_code)

            if status:
                code = 1000
                msg = "获取成功"
                data = status
            else:
                code = 1000
                msg = "该视频流未在录像"
                data = None

        except Exception as e:
            msg = f"获取状态失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)


def api_list_active_recordings(request):
    """API: 列出所有活跃的录像"""
    code = 0
    msg = "未知错误"
    data = []

    if request.method == 'POST':
        try:
            # 获取存储根路径
            config = Config()
            storage_root = config.storageRootPath

            # 获取录像器
            recorder = get_stream_recorder(storage_root)

            # 获取活跃录像列表
            recordings = recorder.list_active_recordings()

            code = 1000
            msg = f"获取成功，当前 {len(recordings)} 个活跃录像"
            data = recordings

        except Exception as e:
            msg = f"获取列表失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)


def api_capture_snapshot(request):
    """API: 截取视频流快照"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED, "data": {}})

    try:
        params = f_parsePostParams(request)
        stream_code = str(params.get("stream_code", "") or "").strip()
        method = str(params.get("method", "ffmpeg") or "ffmpeg").strip()

        if not stream_code:
            return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_REQUIRED})

        stream_obj = _get_snapshot_stream(stream_code)
        stream_url = str(getattr(stream_obj, "pull_stream_url", "") or "").strip() if stream_obj else ""
        if not stream_url:
            return f_responseJson({"code": 0, "msg": "视频流不存在或拉流地址为空"})
        snapshot_stream_code = str(getattr(stream_obj, "code", "") or stream_code).strip()

        if method not in ["ffmpeg", "opencv"]:
            method = "ffmpeg"

        snapshotter = get_stream_snapshotter(Config().storageRootPath)
        result = snapshotter.capture_snapshot(
            stream_code=snapshot_stream_code,
            stream_url=stream_url,
            method=method,
        )

        if bool(result.get("success")):
            image_path = str(result.get("image_path") or "").strip()
            return f_responseJson(
                {
                    "code": 1000,
                    "msg": str(result.get("message") or ""),
                    "data": {
                        "image_path": image_path,
                        "image_url": _snapshot_image_url(image_path),
                        "full_path": result["full_path"],
                    },
                }
            )

        return f_responseJson({"code": 0, "msg": str(result.get("message") or ""), "data": {}})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": f"截图失败：{str(e)}", "data": {}})


def _get_snapshot_stream_url(stream_code: str) -> str:
    """获取快照流URL。"""
    stream = _get_snapshot_stream(stream_code)
    return str(getattr(stream, "pull_stream_url", "") or "").strip() if stream else ""


def _get_snapshot_stream(stream_code: str):
    """按编号或`app/name`获取快照流。"""
    raw = str(stream_code or "").strip()
    if not raw:
        return None

    stream = Stream.objects.filter(code=raw).first()
    if stream:
        return stream

    for separator in ("/", ":"):
        if separator not in raw:
            continue
        app, name = [part.strip() for part in raw.split(separator, 1)]
        if app and name:
            stream = Stream.objects.filter(app=app, name=name).first()
            if stream:
                return stream
    return None


def _normalize_snapshot_method(value: str) -> str:
    """执行归一化快照`method`。"""
    raw = str(value or "").strip().lower()
    return raw if raw in ("ffmpeg", "opencv") else "ffmpeg"


def _capture_snapshot_one(snapshotter, stream: dict, *, method: str):
    """处理`capture`快照`one`。"""
    try:
        stream_code = str(stream.get("stream_code", "") or "").strip()
    except Exception:
        stream_code = ""

    if not stream_code:
        return False, {
            "stream_code": stream_code,
            "success": False,
            "message": "视频流编号为空",
        }

    stream_obj = _get_snapshot_stream(stream_code)
    stream_url = str(getattr(stream_obj, "pull_stream_url", "") or "").strip() if stream_obj else ""
    if not stream_url:
        return False, {
            "stream_code": stream_code,
            "success": False,
            "message": "视频流不存在或拉流地址为空",
        }

    snapshot_stream_code = str(getattr(stream_obj, "code", "") or stream_code).strip()
    result = snapshotter.capture_snapshot(stream_code=snapshot_stream_code, stream_url=stream_url, method=method)
    return bool(result.get("success")), {
        "stream_code": snapshot_stream_code,
        "success": bool(result.get("success")),
        "message": result.get("message"),
        "image_path": result.get("image_path", ""),
        "image_url": _snapshot_image_url(result.get("image_path", "")),
    }


def api_batch_capture_snapshots(request):
    """API: 批量截图多个视频流"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED, "data": {}})

    try:
        params = f_parsePostParams(request)
        streams = params.get("streams", [])  # [{'stream_code': ..., 'stream_url': ...}, ...]
        if not streams or not isinstance(streams, list):
            return f_responseJson({"code": 0, "msg": "视频流列表不能为空"})

        method = _normalize_snapshot_method(params.get("method", "ffmpeg"))
        snapshotter = get_stream_snapshotter(Config().storageRootPath)

        results = []
        success_count = 0
        fail_count = 0
        for stream in streams:
            ok, row = _capture_snapshot_one(snapshotter, stream, method=method)
            results.append(row)
            if ok:
                success_count += 1
            else:
                fail_count += 1

        data = {
            "total": len(streams),
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
        }
        msg = f"批量截图完成：成功 {success_count} 个，失败 {fail_count} 个"
        return f_responseJson({"code": 1000, "msg": msg, "data": data})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": f'批量截图失败：{str(e)}', "data": {}})
