import os
import shutil
import json
import logging
import threading
import time
from datetime import datetime
from urllib.parse import quote
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone

from app.models import (
    AlgorithmModel,
    AlgorithmModelVersion,
    Alarm,
    AlarmEventOutbox,
    AlarmFilterPreset,
    AlarmSound,
    ApiKey,
    CloudAlarmEvent,
    CloudEdgeCluster,
    CloudTenant,
    Control,
    LicenseLease,
    OpsAuditLog,
    RecordingPlan,
    Stream,
)
from app.utils.AlgorithmRegistry import ensure_algorithm_version_registry
from app.utils.CloudRemotePermissions import (
    PERM_CLOUD_REMOTE_PLATFORM_VIEW,
    PERM_CLOUD_REMOTE_RECORDINGS_VIEW,
    PERM_CLOUD_REMOTE_STREAMS_MANAGE,
    PERM_CLOUD_REMOTE_STREAMS_VIEW,
)
from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError
from app.utils.DeploymentMode import is_cloud_mode
from app.utils.SystemConfigHelper import get_int, get_value
from app.utils.Utils import gen_random_code_s
from app.views import (
    AlarmView,
    AlarmSoundView,
    Algorithm,
    CloudConsoleView,
    CloudRemotePlatformView,
    CloudRemoteRecordingsView,
    CloudRemoteStreamDetailView,
    CloudRemoteStreamsView,
    ConfigExportView,
    ControlView,
    ControlLogView,
    DeveloperView,
    LogExportView,
    ONVIFView,
    OpsDiagnosticsView,
    OpsApiKeyView,
    OpsAuditLogView,
    OpsView,
    OpsUpgradeView,
    StreamRecordingView,
    StreamView,
    SystemConfigView,
    UserManageView,
    LicenseView,
    api as api_view,
    web,
)
from app.views.ScreenView import _build_birdseye_streams
from app.views.SystemConfigView import _build_system_context
from app.views.ViewsBase import GetStream, f_parseGetParams, f_parsePostParams, f_responseJson, g_config, get_public_host_for_urls
from framework.settings import PROJECT_VERSION

logger = logging.getLogger(__name__)
MSG_METHOD_NOT_SUPPORTED_CN = "请求方法不支持"
DEFAULT_UPLOAD_URL_PREFIX = "/static/upload/"
DEFAULT_OSD_FONT_COLOR = "255,255,255"
MSG_CLOUD_CLUSTER_UNAVAILABLE = "边缘集群不存在或当前账号无权访问该集群"
_DASHBOARD_NETWORK_LOCK = threading.Lock()
_DASHBOARD_NETWORK_STATE = {"timestamp": None, "bytes_sent": None, "bytes_recv": None, "series": []}


def _safe_list(value):
    """返回安全列表。"""
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _safe_float(value, default=0.0):
    """处理安全浮点数。"""
    try:
        return float(value)
    except Exception:
        return float(default)


def _percent_string_from_ratio(value):
    """从`ratio`获取`percent`字符串。"""
    percent = _safe_float(value, 0.0)
    if percent < 0:
        percent = 0.0
    # Edge runtime payloads currently report CPU / memory usage in 0-100,
    # while some older test fixtures still use 0-1 ratios.
    if percent <= 1.0:
        percent *= 100.0
    return f"{percent:.1f}%"


def _normalize_process_summary(row):
    """执行归一化进程`summary`。"""
    row = row or {}
    resource = row.get("resource") or {}
    scheduler = row.get("scheduler") or {}
    running_controls = scheduler.get("runningControls")
    if running_controls is None:
        running_controls = scheduler.get("currentControls", resource.get("currentControls", 0))
    loaded_algorithms = scheduler.get("loadedAlgorithms")
    if loaded_algorithms is None:
        loaded_algorithms = scheduler.get("algorithmLoadSuccess", 0)
    return {
        "process_index": int(row.get("process_index", 0) or 0),
        "analyzer_host": str(row.get("analyzer_host", "") or ""),
        "ok": bool(row.get("ok")),
        "msg": str(row.get("msg", "") or ""),
        "resource": {
            "cpuUsage": _safe_float(resource.get("cpuUsage"), 0.0),
            "cpuUsageText": _percent_string_from_ratio(resource.get("cpuUsage")),
            "memoryUsage": _safe_float(resource.get("memoryUsage"), 0.0),
            "memoryUsageText": _percent_string_from_ratio(resource.get("memoryUsage")),
            "currentControls": int(resource.get("currentControls", 0) or 0),
        },
        "scheduler": {
            "runningControls": int(running_controls or 0),
            "queuedControls": int(scheduler.get("queuedControls", 0) or 0),
            "loadedAlgorithms": int(loaded_algorithms or 0),
        },
    }


def _safe_count(queryset):
    """处理安全统计。"""
    try:
        return int(queryset.count())
    except Exception:
        return 0


def _short_identifier(value, prefix=8, suffix=8):
    """处理`short``identifier`。"""
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= prefix + suffix + 3:
        return text
    return f"{text[:prefix]}...{text[-suffix:]}"


def _safe_int(value, fallback=0):
    """处理安全整数值。"""
    try:
        return int(value or fallback)
    except Exception:
        return int(fallback)


def _dashboard_network_monotonic():
    """处理`dashboard``network``monotonic`。"""
    return time.monotonic()


def _format_mbps(value):
    """处理`format``mbps`。"""
    return f"{_safe_float(value, 0.0):.1f} Mbps"


def _build_dashboard_network_snapshot(os_info):
    """构建`dashboard``network`快照。"""
    sent = _safe_int((os_info or {}).get("os_net_bytes_sent"), 0)
    recv = _safe_int((os_info or {}).get("os_net_bytes_recv"), 0)
    if sent <= 0 and recv <= 0:
        return {}

    now = _dashboard_network_monotonic()
    with _DASHBOARD_NETWORK_LOCK:
        prev_ts = _DASHBOARD_NETWORK_STATE.get("timestamp")
        prev_sent = _DASHBOARD_NETWORK_STATE.get("bytes_sent")
        prev_recv = _DASHBOARD_NETWORK_STATE.get("bytes_recv")
        prev_series = list(_DASHBOARD_NETWORK_STATE.get("series") or [])

        _DASHBOARD_NETWORK_STATE["timestamp"] = now
        _DASHBOARD_NETWORK_STATE["bytes_sent"] = sent
        _DASHBOARD_NETWORK_STATE["bytes_recv"] = recv

        if prev_ts is None or prev_sent is None or prev_recv is None:
            _DASHBOARD_NETWORK_STATE["series"] = []
            return {}

        if now <= prev_ts or sent < prev_sent or recv < prev_recv:
            _DASHBOARD_NETWORK_STATE["series"] = []
            return {}

        elapsed = float(now - prev_ts)
        if elapsed <= 0:
            _DASHBOARD_NETWORK_STATE["series"] = prev_series
            return {}

        upload_mbps = round(((sent - prev_sent) * 8.0) / elapsed / 1000000.0, 1)
        download_mbps = round(((recv - prev_recv) * 8.0) / elapsed / 1000000.0, 1)
        series = (prev_series + [{"upload": upload_mbps, "download": download_mbps}])[-8:]
        _DASHBOARD_NETWORK_STATE["series"] = series

        return {
            "upload_mbps": upload_mbps,
            "download_mbps": download_mbps,
            "upload": _format_mbps(upload_mbps),
            "download": _format_mbps(download_mbps),
            "series": series,
        }


def _online_source_label(source_type):
    """处理在线来源标签。"""
    return {
        0: "用户推流",
        1: "数据库视频流",
        2: "算法推流",
    }.get(source_type, "未知来源")


def _normalize_online_stream_row(row):
    """执行归一化在线流记录。"""
    source_type = _safe_int(row.get("source_type"))
    viewer_count = _safe_int(row.get("viewer_count") or row.get("clients") or row.get("client_count"))
    bytes_speed = _safe_int(
        row.get("bytes_speed")
        or row.get("produce_speed")
        or row.get("bitrate")
        or row.get("ingress_bitrate")
    )
    display_name = str(
        row.get("display_name")
        or row.get("source_nickname")
        or "{}{}".format(str(row.get("app") or "").rstrip("/") + "/" if row.get("app") else "", row.get("name") or "")
    )
    return {
        "app": str(row.get("app") or ""),
        "name": str(row.get("name") or ""),
        "source_type": source_type,
        "source_label": _online_source_label(source_type),
        "display_name": display_name,
        "source_nickname": str(row.get("source_nickname") or ""),
        "viewer_count": viewer_count,
        "bytes_speed": bytes_speed,
        "video": str(row.get("video") or row.get("video_codec", "") or ""),
        "audio": str(row.get("audio") or row.get("audio_codec", "") or ""),
        "control_code": str(row.get("control_code") or ""),
        "control_stream_app": str(row.get("control_stream_app") or ""),
        "control_stream_name": str(row.get("control_stream_name") or ""),
        "control_algorithm_code": str(row.get("control_algorithm_code") or ""),
    }


def _build_online_summary(rows, top_msg):
    """构建在线`summary`。"""
    counters = {}
    for row in rows or []:
        stype = _safe_int(row.get("source_type"))
        counters[stype] = counters.get(stype, 0) + 1
    return {
        "total_count": len(rows),
        "analyzer_push_count": counters.get(2, 0),
        "db_stream_count": counters.get(1, 0),
        "passive_push_count": counters.get(0, 0),
        "top_msg": top_msg,
    }


def _dispatch_app_shell_action(request, action, action_map, *, scope):
    """分发`app``shell`动作。"""
    normalized_action = str(action or "").strip().strip("/")
    handler = action_map.get(normalized_action)
    if not handler:
        return f_responseJson({"code": 0, "msg": f"unsupported {scope} action: {normalized_action}"})
    return handler(request)


_APP_SHELL_STREAM_ACTIONS = {
    "openAdd": StreamView.api_openAdd,
    "openEdit": StreamView.api_openEdit,
    "openDel": StreamView.api_openDel,
    "openGet": StreamView.api_openGet,
    "getOnline": StreamView.api_getOnline,
    "batchImport": StreamView.api_batchImport,
    "openBatchAddStreamProxy": StreamView.api_openBatchAddStreamProxy,
    "openBatchDelStreamProxy": StreamView.api_openBatchDelStreamProxy,
    "openAddStreamProxy": StreamView.api_openAddStreamProxy,
    "openDelStreamProxy": StreamView.api_openDelStreamProxy,
    "openAddStreamPusherProxy": StreamView.api_openAddStreamPusherProxy,
    "openSetState": StreamView.api_openSetState,
    "getAllStartForward": StreamView.api_getAllStartForward,
    "getAllUpdateForwardState": StreamView.api_getAllUpdateForwardState,
    "getAutoStartConfig": StreamView.api_getAutoStartConfig,
    "setAutoStartConfig": StreamView.api_setAutoStartConfig,
    "webrtcSelfCheck": StreamView.api_webrtcSelfCheck,
    "openGb28181Ptz": StreamView.api_openGb28181Ptz,
    "getPlayUrl": StreamView.api_getPlayUrl,
    "talkback/config/get": StreamView.api_talkback_config_get,
    "talkback/config/save": StreamView.api_talkback_config_save,
    "talkback/start": StreamView.api_talkback_start,
    "talkback/stop": StreamView.api_talkback_stop,
    "talkback/status": StreamView.api_talkback_status,
}


_APP_SHELL_ALARM_ACTIONS = {
    "workflow": AlarmView.api_workflow_transition,
    "assignment": AlarmView.api_assignment_update,
    "openAdd": AlarmView.api_openAdd,
    "exportEvidence": AlarmView.api_exportEvidence,
    "exportLabelme": AlarmView.api_exportLabelme,
    "exportCoco": AlarmView.api_exportCoco,
    "poll": api_view.api_alarmPoll,
    "semantic-search": AlarmView.api_semanticSearch,
    "vlm-search": AlarmView.api_vlmSearch,
    "cross-camera-search": api_view.api_crossCameraSearch,
    "postHandleAlarm": api_view.api_postHandleAlarm,
    "sinks/testSend": api_view.api_alarmSinksTestSend,
}


_APP_SHELL_ALARM_SOUND_ACTIONS = {
    "upload": AlarmSoundView.api_upload,
    "delete": AlarmSoundView.api_delete,
    "setDefault": AlarmSoundView.api_setDefault,
    "list": AlarmSoundView.api_list,
}


_APP_SHELL_CONTROL_ACTIONS = {
    "openStartControl": ControlView.api_openStartControl,
    "openStopControl": ControlView.api_openStopControl,
    "openBatchStart": ControlView.api_openBatchStart,
    "openBatchStop": ControlView.api_openBatchStop,
    "openDel": ControlView.api_openDel,
    "openCopy": ControlView.api_openCopy,
    "openBatchCopyToStreams": ControlView.api_openBatchCopyToStreams,
    "openQuickSet": ControlView.api_openQuickSet,
    "postAddControl": api_view.api_postAddControl,
    "postEditControl": api_view.api_postEditControl,
    "openIndex": ControlView.api_openIndex,
    "logs/export": ControlLogView.api_export_logs,
}


_APP_SHELL_ALGORITHM_ACTIONS = {
    "marketplace": Algorithm.api_marketplace,
    "openDel": Algorithm.api_openDel,
    "openVersionActivate": Algorithm.api_openVersionActivate,
    "openVersionRollback": Algorithm.api_openVersionRollback,
    "openVersionGray": Algorithm.api_openVersionGray,
    "openAnalyzerLoad": Algorithm.api_openAnalyzerLoad,
    "openAnalyzerUnload": Algorithm.api_openAnalyzerUnload,
    "openTestInfer": Algorithm.api_openTestInfer,
}


_APP_SHELL_RECORDING_ACTIONS = {
    "startRecording": StreamRecordingView.api_start_recording,
    "stopRecording": StreamRecordingView.api_stop_recording,
    "getRecordingStatus": StreamRecordingView.api_get_recording_status,
    "listActiveRecordings": StreamRecordingView.api_list_active_recordings,
    "captureSnapshot": StreamRecordingView.api_capture_snapshot,
    "batchCaptureSnapshots": StreamRecordingView.api_batch_capture_snapshots,
    "file/list": api_view.api_openListRecordingFiles,
    "file/playUrl": api_view.api_openRecordingFilePlayUrl,
    "plan/add": api_view.api_openAddRecordingPlan,
    "plan/edit": api_view.api_openEditRecordingPlan,
    "plan/delete": api_view.api_openDeleteRecordingPlan,
    "plan/list": api_view.api_openListRecordingPlans,
    "task-plan/add": api_view.api_openAddTaskPlan,
    "task-plan/edit": api_view.api_openEditTaskPlan,
    "task-plan/delete": api_view.api_openDeleteTaskPlan,
    "task-plan/list": api_view.api_openListTaskPlans,
}


_APP_SHELL_USERS_ACTIONS = {
    "getUserList": UserManageView.api_get_user_list,
    "getUserDetail": UserManageView.api_get_user_detail,
    "addUser": UserManageView.api_add_user,
    "editUser": UserManageView.api_edit_user,
    "deleteUser": UserManageView.api_delete_user,
    "batchDeleteUsers": UserManageView.api_batch_delete_users,
    "toggleUserStatus": UserManageView.api_toggle_user_status,
    "permissions/get": UserManageView.api_get_user_permissions,
    "permissions/set": UserManageView.api_set_user_permissions,
}


_APP_SHELL_CONFIG_ACTIONS = {
    "export": ConfigExportView.api_export,
    "import": ConfigExportView.api_import,
    "preview": ConfigExportView.api_preview_import,
    "history/rollback": SystemConfigView.api_history_rollback,
    "system/save": SystemConfigView.api_save_system,
    "logs/export": LogExportView.api_export_logs,
}


_APP_SHELL_FACES_ACTIONS = {
    "add": api_view.api_openFaceAdd,
    "delete": api_view.api_openFaceDelete,
    "list": api_view.api_openFaceList,
    "search": api_view.api_openFaceSearch,
    "enable": api_view.api_openFaceEnable,
    "disable": api_view.api_openFaceDisable,
}


_APP_SHELL_DEVELOPER_ACTIONS = {
    "algorithmCallback": DeveloperView.api_algorithmCallback,
    "getStreamInfo": DeveloperView.api_getStreamInfo,
    "getAlgorithmInfo": DeveloperView.api_getAlgorithmInfo,
}


_APP_SHELL_ONVIF_ACTIONS = {
    "discover": ONVIFView.api_onvif_discover,
    "getDeviceInfo": ONVIFView.api_onvif_get_device_info,
    "getRtspUrls": ONVIFView.api_onvif_get_rtsp_urls,
    "captureSnapshot": ONVIFView.api_onvif_capture_snapshot,
    "importStreams": ONVIFView.api_onvif_import_streams,
}


_APP_SHELL_OPS_ACTIONS = {
    "audit/list": OpsAuditLogView.api_list,
    "audit/export": OpsAuditLogView.export,
    "apikeys/list": OpsApiKeyView.api_list,
    "apikeys/create": OpsApiKeyView.api_create,
    "apikeys/revoke": OpsApiKeyView.api_revoke,
    "apikeys/rotate": OpsApiKeyView.api_rotate,
    "upgrade/checkVersion": api_view.api_checkVersion,
    "upgrade/upload": OpsUpgradeView.upload,
    "upgrade/list": OpsUpgradeView.list_packages,
    "upgrade/validate": OpsUpgradeView.validate,
    "upgrade/apply": OpsUpgradeView.apply,
    "upgrade/rollback": OpsUpgradeView.rollback,
    "cleanup": OpsView.cleanup,
    "outbox/replay": OpsView.outbox_replay,
    "logging/level": OpsView.logging_set_level,
    "diagnostics/export": OpsDiagnosticsView.export,
}


_APP_SHELL_PLATFORM_ACTIONS = {
    "basicInfo": api_view.api_openBasicInfo,
    "storageInfo": api_view.api_openStorageInfo,
    "restartSoftware": api_view.api_openRestartSoftware,
    "restartSystem": api_view.api_openRestartSystem,
}


_APP_SHELL_CLOUD_ACTIONS = {
    "alarm-image": CloudConsoleView.alarm_image,
}


def api_alarm_action(request, action):
    """处理 `alarm_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_ALARM_ACTIONS, scope="alarm")


def api_alarm_sound_action(request, action):
    """处理 `alarm_sound_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_ALARM_SOUND_ACTIONS, scope="alarm-sound")


def api_control_action(request, action):
    """处理 `control_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_CONTROL_ACTIONS, scope="control")


def api_algorithm_action(request, action):
    """处理 `algorithm_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_ALGORITHM_ACTIONS, scope="algorithm")


def api_stream_action(request, action):
    """处理 `stream_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_STREAM_ACTIONS, scope="stream")


def api_recording_action(request, action):
    """处理 `recording_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_RECORDING_ACTIONS, scope="recording")


def api_users_action(request, action):
    """处理 `users_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_USERS_ACTIONS, scope="users")


def api_config_action(request, action):
    """处理 `config_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_CONFIG_ACTIONS, scope="config")


def api_faces_action(request, action):
    """处理 `faces_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_FACES_ACTIONS, scope="faces")


def api_developer_action(request, action):
    """处理 `developer_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_DEVELOPER_ACTIONS, scope="developer")


def api_onvif_action(request, action):
    """处理 `onvif_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_ONVIF_ACTIONS, scope="onvif")


def api_ops_action(request, action):
    """处理 `ops_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_OPS_ACTIONS, scope="ops")


def api_platform_action(request, action):
    """处理 `platform_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_PLATFORM_ACTIONS, scope="platform")


def api_cloud_action(request, action):
    """处理 `cloud_action` 接口请求。"""
    return _dispatch_app_shell_action(request, action, _APP_SHELL_CLOUD_ACTIONS, scope="cloud")


def api_stream_online(request):
    """处理 `stream_online` 接口请求。"""
    top_msg, rows = StreamView.build_online_stream_app_shell_payload()
    normalized_rows = [_normalize_online_stream_row(row) for row in rows or []]
    summary = _build_online_summary(rows or [], top_msg)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "summary": summary,
                "rows": normalized_rows,
            },
        }
    )


_STREAM_PLAYER_PREFER_OPTIONS = [
    {"value": "compat", "label": "兼容模式（推荐：服务端转 H264）"},
    {"value": "raw", "label": "原码流（H265 直出/不转码）"},
    {"value": "hls", "label": "HLS（m3u8）"},
    {"value": "hls_fmp4", "label": "HLS-fMP4（低延迟）"},
]


_STREAM_PLAYER_QUALITY_OPTIONS = [
    {"value": "auto", "label": "自适应"},
    {"value": "origin", "label": "原画"},
    {"value": "1080", "label": "1080p"},
    {"value": "720", "label": "720p"},
    {"value": "540", "label": "540p"},
    {"value": "360", "label": "360p"},
    {"value": "270", "label": "270p"},
]


def _stream_player_protocol_rows(stream):
    """返回流播放器`protocol`记录。"""
    stream = stream or {}
    rows = [
        {
            "key": "webrtc",
            "label": "WebRTC 低延迟播放",
            "kind": "webrtc",
            "url": str(stream.get("webrtcApiUrl") or ""),
            "external": True,
            "action_href": str(stream.get("webrtcUrl") or ""),
            "action_label": "打开新窗口",
        },
        {
            "key": "ws_flv",
            "label": "WS-FLV",
            "kind": "websocket",
            "url": str(stream.get("wsFlvUrl") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
        {
            "key": "ws_fmp4",
            "label": "WS-fMP4",
            "kind": "websocket",
            "url": str(stream.get("wsMp4Url") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
        {
            "key": "http_flv",
            "label": "HTTP-FLV",
            "kind": "http",
            "url": str(stream.get("httpFlvUrl") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
        {
            "key": "http_fmp4",
            "label": "HTTP-fMP4",
            "kind": "http",
            "url": str(stream.get("httpMp4Url") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
        {
            "key": "rtsp",
            "label": "RTSP",
            "kind": "rtsp",
            "url": str(stream.get("rtspUrl") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
        {
            "key": "hls",
            "label": "HLS",
            "kind": "hls",
            "url": str(stream.get("hlsUrl") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
        {
            "key": "hls_fmp4",
            "label": "HLS-fMP4",
            "kind": "hls",
            "url": str(stream.get("hlsFmp4Url") or ""),
            "external": False,
            "action_href": "",
            "action_label": "",
        },
    ]
    return [row for row in rows if str(row.get("url") or "").strip() or str(row.get("action_href") or "").strip()]


def _stream_player_resolution(stream):
    """处理流播放器`resolution`。"""
    width = _safe_int((stream or {}).get("video_width"), 0)
    height = _safe_int((stream or {}).get("video_height"), 0)
    if width > 0 and height > 0:
        return f"{width}x{height}"
    return "-"


def _serialize_stream_player_stream(stream, *, talkback):
    """处理`serialize`流播放器流。"""
    stream = stream or {}
    talkback = talkback or {}
    return {
        "stream_code": str(talkback.get("stream_code") or stream.get("code") or ""),
        "app": str(stream.get("app") or ""),
        "name": str(stream.get("name") or ""),
        "is_online": bool(stream.get("is_online")),
        "video_codec_name": str(stream.get("video_codec_name") or ""),
        "video_width": _safe_int(stream.get("video_width"), 0),
        "video_height": _safe_int(stream.get("video_height"), 0),
        "video_resolution": _stream_player_resolution(stream),
        "audio_tracks": list(stream.get("audio_tracks") or []),
    }


def _build_stream_player_webrtc_payload(stream):
    """构建流播放器`webrtc`载荷。"""
    stream = stream or {}
    return {
        "api_url": str(stream.get("webrtcApiUrl") or ""),
        "open_url": str(stream.get("webrtcUrl") or ""),
        "stun_urls": list(getattr(g_config, "webrtcStunUrls", []) or []),
        "turn_url": str(getattr(g_config, "webrtcTurnUrl", "") or "").strip(),
        "turn_username": str(getattr(g_config, "webrtcTurnUsername", "") or "").strip(),
        "turn_password_masked": "***" if str(getattr(g_config, "webrtcTurnPassword", "") or "").strip() else "",
        "selfcheck_endpoint": "/api/app-shell/stream/action/webrtcSelfCheck",
    }


def _empty_stream_player_payload(*, app="", name="", code=""):
    """返回空流播放器载荷。"""
    return {
        "query": {"app": str(app or ""), "name": str(name or ""), "code": str(code or "")},
        "exists": False,
        "message": "请选择一路在线视频流后再进入播放页。",
        "stream": {
            "stream_code": "",
            "app": str(app or ""),
            "name": str(name or ""),
            "is_online": False,
            "video_codec_name": "",
            "video_width": 0,
            "video_height": 0,
            "video_resolution": "-",
            "audio_tracks": [],
        },
        "playback": {
            "recommended_url": "",
            "recommended_protocol": "compat",
            "recommended_quality": "auto",
            "prefer_options": list(_STREAM_PLAYER_PREFER_OPTIONS),
            "quality_options": list(_STREAM_PLAYER_QUALITY_OPTIONS),
            "protocol_rows": [],
            "play_url_endpoint": "/api/app-shell/stream/action/getPlayUrl",
        },
        "webrtc": {
            "api_url": "",
            "open_url": "",
            "stun_urls": list(getattr(g_config, "webrtcStunUrls", []) or []),
            "turn_url": str(getattr(g_config, "webrtcTurnUrl", "") or "").strip(),
            "turn_username": str(getattr(g_config, "webrtcTurnUsername", "") or "").strip(),
            "turn_password_masked": "***" if str(getattr(g_config, "webrtcTurnPassword", "") or "").strip() else "",
            "selfcheck_endpoint": "/api/app-shell/stream/action/webrtcSelfCheck",
        },
        "talkback": StreamView._empty_talkback_player_context("请先选择一个在线视频流。"),
    }


def api_stream_player(request):
    """处理 `stream_player` 接口请求。"""
    params = f_parseGetParams(request)
    app = str(params.get("app") or "").strip()
    name = str(params.get("name") or "").strip()
    code = str(params.get("code") or "").strip()
    payload = _empty_stream_player_payload(app=app, name=name, code=code)

    if code and (not app or not name):
        stream_row = Stream.objects.filter(code=code).only("app", "name").first()
        if stream_row:
            app = str(getattr(stream_row, "app", "") or "").strip()
            name = str(getattr(stream_row, "name", "") or "").strip()
            payload["query"]["app"] = app
            payload["query"]["name"] = name

    if not app or not name:
        return f_responseJson({"code": 1000, "msg": "success", "data": payload})

    public_host = get_public_host_for_urls(request)
    stream = GetStream(app=app, name=name, public_host=public_host)
    talkback = StreamView._build_talkback_player_context(app=app, name=name, public_host=public_host)
    if talkback.get("stream_code"):
        stream["code"] = talkback.get("stream_code")

    payload["exists"] = True
    payload["message"] = ""
    payload["stream"] = _serialize_stream_player_stream(stream, talkback=talkback)
    payload["playback"] = {
        "recommended_url": str(stream.get("wsFlvUrl") or ""),
        "recommended_protocol": "compat",
        "recommended_quality": "auto",
        "prefer_options": list(_STREAM_PLAYER_PREFER_OPTIONS),
        "quality_options": list(_STREAM_PLAYER_QUALITY_OPTIONS),
        "protocol_rows": _stream_player_protocol_rows(stream),
        "play_url_endpoint": "/api/app-shell/stream/action/getPlayUrl",
    }
    payload["webrtc"] = _build_stream_player_webrtc_payload(stream)
    payload["talkback"] = talkback
    return f_responseJson({"code": 1000, "msg": "success", "data": payload})


_ALARM_SOUND_MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _infer_alarm_sound_mime_type(file_path):
    """返回推理告警`sound``mime`类型。"""
    _, ext = os.path.splitext(str(file_path or "").strip().lower())
    return _ALARM_SOUND_MIME_BY_EXT.get(ext, "audio/mpeg")


def _serialize_alarm_sound_row(sound):
    """返回`serialize`告警`sound`记录。"""
    file_path = str(getattr(sound, "file_path", "") or "")
    return {
        "id": int(getattr(sound, "id", 0) or 0),
        "name": str(getattr(sound, "name", "") or ""),
        "file_path": file_path,
        "file_name": os.path.basename(file_path) if file_path else "",
        "duration": _safe_float(getattr(sound, "duration", 0), 0.0),
        "is_default": bool(getattr(sound, "is_default", False)),
        "remark": str(getattr(sound, "remark", "") or ""),
        "create_time": _format_datetime_label(getattr(sound, "create_time", None), fallback=""),
        "preview_mime_type": _infer_alarm_sound_mime_type(file_path),
    }


def api_alarm_sounds(request):
    """处理 `alarm_sounds` 接口请求。"""
    params = f_parseGetParams(request)
    page, page_size = _parse_page_params(params, default_page_size=10, max_page_size=100)
    queryset = AlarmSound.objects.filter(state__gte=0).order_by("-is_default", "-id")
    paginator = Paginator(queryset, page_size)
    current_page = paginator.get_page(page)
    page = current_page.number

    default_sound = queryset.filter(is_default=True).order_by("-id").first()
    rows = [_serialize_alarm_sound_row(item) for item in current_page.object_list]

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "summary": {
                    "total": int(paginator.count),
                    "current_page_count": len(rows),
                    "default_id": int(getattr(default_sound, "id", 0) or 0),
                    "default_name": str(getattr(default_sound, "name", "") or ""),
                    "default_file_path": str(getattr(default_sound, "file_path", "") or ""),
                },
                "rows": rows,
                "pageData": _build_page_data(paginator=paginator, page=page, page_size=page_size),
            },
        }
    )


def _split_gray_control_codes(value):
    """拆分`gray`控制编码列表。"""
    return [item for item in str(value or "").split(",") if str(item or "").strip()]


def _algorithm_version_source_label(version):
    """处理算法版本来源标签。"""
    algorithm_type = _safe_int(getattr(version, "algorithm_type", 0))
    basic_source = str(getattr(version, "basic_source", "") or "").strip().lower()
    if algorithm_type == 0:
        return "API" if basic_source == "api" else "模型文件"
    if str(getattr(version, "dll_path", "") or "").strip():
        return "动态库"
    if str(getattr(version, "api_url", "") or "").strip():
        return "API"
    return "内置"


def _algorithm_version_state_label(version):
    """处理算法版本状态标签。"""
    if bool(getattr(version, "is_current", False)):
        return "当前版本"
    if bool(getattr(version, "is_gray", False)):
        return "灰度版本"
    return "历史版本"


def _build_algorithm_version_config_summary(version):
    """构建算法版本配置`summary`。"""
    parts = []
    if str(getattr(version, "api_url", "") or "").strip():
        parts.append(str(getattr(version, "api_url", "") or "").strip())
    if str(getattr(version, "model_path", "") or "").strip():
        parts.append(str(getattr(version, "model_path", "") or "").strip())
    if str(getattr(version, "dll_path", "") or "").strip():
        parts.append(str(getattr(version, "dll_path", "") or "").strip())

    target_text = str(getattr(version, "object_str", "") or "").strip() or "-"
    precision_text = str(getattr(version, "model_precision", "") or "").strip() or "FP32"
    concurrency_text = _safe_int(getattr(version, "model_concurrency", 1), 1)
    parts.append(f"目标 {target_text}")
    parts.append(f"精度 {precision_text}")
    parts.append(f"并发 {concurrency_text}")

    note = str(getattr(version, "note", "") or "").strip()
    if note:
        parts.append(f"备注 {note}")
    return " | ".join(parts)


def _serialize_algorithm_version_row(version):
    """返回`serialize`算法版本记录。"""
    gray_control_codes = str(getattr(version, "gray_control_codes", "") or "").strip()
    return {
        "id": int(getattr(version, "id", 0) or 0),
        "version_no": int(getattr(version, "version_no", 0) or 0),
        "version_name": str(getattr(version, "version_name", "") or ""),
        "note": str(getattr(version, "note", "") or ""),
        "is_current": bool(getattr(version, "is_current", False)),
        "is_gray": bool(getattr(version, "is_gray", False)),
        "state_label": _algorithm_version_state_label(version),
        "source_label": _algorithm_version_source_label(version),
        "config_summary": _build_algorithm_version_config_summary(version),
        "gray_control_codes": gray_control_codes,
        "gray_control_code_list": _split_gray_control_codes(gray_control_codes),
        "create_time": _format_datetime_label(getattr(version, "create_time", None), fallback=""),
        "activated_at": _format_datetime_label(getattr(version, "activated_at", None), fallback=""),
        "api_url": str(getattr(version, "api_url", "") or ""),
        "model_path": str(getattr(version, "model_path", "") or ""),
        "dll_path": str(getattr(version, "dll_path", "") or ""),
        "object_str": str(getattr(version, "object_str", "") or ""),
        "model_precision": str(getattr(version, "model_precision", "") or ""),
        "model_concurrency": _safe_int(getattr(version, "model_concurrency", 1), 1),
    }


def api_algorithm_versions(request):
    """处理 `algorithm_versions` 接口请求。"""
    params = f_parseGetParams(request)
    code = str(params.get("code") or "").strip()
    if not code:
        return f_responseJson({"code": 0, "msg": "code is required"})

    algorithm = AlgorithmModel.objects.filter(code=code).first()
    if not algorithm:
        return f_responseJson({"code": 0, "msg": "该算法不存在"})

    ensure_algorithm_version_registry(algorithm, note="versions-console-bootstrap")
    version_rows = list(AlgorithmModelVersion.objects.filter(algorithm=algorithm).order_by("-version_no", "-id"))
    current_version = next((row for row in version_rows if bool(getattr(row, "is_current", False))), None)
    gray_version = next((row for row in version_rows if bool(getattr(row, "is_gray", False))), None)

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "algorithm": {
                    "id": int(getattr(algorithm, "id", 0) or 0),
                    "code": str(getattr(algorithm, "code", "") or ""),
                    "name": str(getattr(algorithm, "name", "") or ""),
                    "algorithm_type": _safe_int(getattr(algorithm, "algorithm_type", 0)),
                    "algorithm_subtype": str(getattr(algorithm, "algorithm_subtype", "") or ""),
                    "basic_source": str(getattr(algorithm, "basic_source", "") or ""),
                    "source_label": _algorithm_version_source_label(algorithm),
                },
                "summary": {
                    "version_count": len(version_rows),
                    "current_version_id": int(getattr(current_version, "id", 0) or 0),
                    "current_version_name": str(getattr(current_version, "version_name", "") or ""),
                    "gray_version_id": int(getattr(gray_version, "id", 0) or 0),
                    "gray_version_name": str(getattr(gray_version, "version_name", "") or ""),
                },
                "versions": [_serialize_algorithm_version_row(row) for row in version_rows],
            },
        }
    )


def _format_datetime_label(value, fallback="未提供"):
    """处理`format``datetime`标签。"""
    if not value:
        return fallback
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value or fallback)


def _license_type_label(value):
    """处理授权类型标签。"""
    mapping = {
        "community": "社区版",
        "machine": "机器授权",
        "dongle": "加密锁授权",
        "pool": "授权池",
        "manager": "管理节点授权",
    }
    return mapping.get(str(value or "").strip().lower(), "授权待确认")


def _is_local_machine_license(license_type: str) -> bool:
    """返回是否使用本机/加密锁授权。"""
    return str(license_type or "").strip().lower() in ("machine", "dongle")


def _local_license_check():
    """返回本地授权检查结果。"""
    try:
        return api_view.g_license.check() or {}
    except Exception:
        return {}


def _fetch_analyzer_license_info(*, cache_ttl_seconds=None, default_message="license_info failed"):
    """从 Analyzer 获取授权信息。"""
    kwargs = {"timeout_seconds": 2}
    if cache_ttl_seconds is not None:
        kwargs["cache_ttl_seconds"] = cache_ttl_seconds
    try:
        ok, msg, data = api_view.g_analyzer.license_info(**kwargs)
        if ok:
            return (data or {}).get("data") or {}, {}, "", True
        return {}, _local_license_check(), str(msg or default_message), False
    except Exception as exc:
        return {}, _local_license_check(), str(exc or default_message), False


def _fetch_license_info(license_type: str, *, cache_ttl_seconds=None, default_message="license_info failed"):
    """获取授权信息与兜底信息。"""
    if _is_local_machine_license(license_type):
        info, fallback_info, message, transport_ok = _fetch_analyzer_license_info(
            cache_ttl_seconds=cache_ttl_seconds,
            default_message=default_message,
        )
        return "analyzer", info, fallback_info, message, transport_ok
    try:
        return "admin", api_view.g_license.check() or {}, {}, "", True
    except Exception as exc:
        return "admin", {}, {}, str(exc or default_message), False


def _license_usage_message(extra: dict) -> str:
    """返回授权占用消息。"""
    active_controls = int((extra.get("usage") or {}).get("active_controls", 0) or 0)
    max_controls = int(((extra.get("limits") or {}).get("max_active_controls", 0)) or 0)
    if max_controls > 0:
        return f"当前已占用 {active_controls} 路授权 / 上限 {max_controls} 路。"
    return "当前授权已生效，可继续检查节点与算法包使用情况。"


def _license_summary_status(*, license_type: str, valid: bool, transport_ok: bool, message: str, extra: dict):
    """返回授权`summary`状态。"""
    if not transport_ok and _is_local_machine_license(license_type):
        return "暂不可达", "warning", message or "Analyzer 授权接口当前不可达，可到诊断中心继续排查。"
    if not valid:
        return "未授权", "critical", message or "当前授权校验未通过，请检查授权方式、机器码或许可证文件。"
    if _is_local_machine_license(license_type):
        return "已授权", "stable", "机器码基于系统稳定标识生成，换机器后会变化。"
    return "已授权", "stable", _license_usage_message(extra)


def _license_summary_identifier(license_type: str, info: dict, fallback_info: dict, extra: dict):
    """返回授权标识标签和值。"""
    if not _is_local_machine_license(license_type):
        identifier_value = _short_identifier(extra.get("license_id") or extra.get("cluster_id") or info.get("machine_code"))
        if extra.get("license_id"):
            return "许可证 ID", identifier_value
        if extra.get("cluster_id"):
            return "集群 ID", identifier_value
        return "标识", identifier_value
    return "机器码", _short_identifier(info.get("machine_code") or fallback_info.get("machine_code"))


def _license_expires_label(extra: dict, *, valid: bool) -> str:
    """返回授权过期时间标签。"""
    expires_at = extra.get("not_after")
    if expires_at:
        return _format_datetime_label(expires_at)
    return "长期有效" if valid else "未提供"


def _build_dashboard_license_summary():
    """构建`dashboard`授权`summary`。"""
    cache_ttl_seconds = api_view._index_analyzer_cache_ttl_seconds()
    license_type = str(getattr(g_config, "licenseType", "community") or "community").strip().lower()
    source, info, fallback_info, message, transport_ok = _fetch_license_info(
        license_type,
        cache_ttl_seconds=cache_ttl_seconds,
        default_message="Analyzer 授权接口暂不可达",
    )
    info = info if isinstance(info, dict) else {}
    fallback_info = fallback_info if isinstance(fallback_info, dict) else {}
    extra = info.get("extra") if isinstance(info.get("extra"), dict) else {}
    valid = bool(info.get("ok"))
    status_label, status_tone, message = _license_summary_status(
        license_type=license_type,
        valid=valid,
        transport_ok=transport_ok,
        message=message,
        extra=extra,
    )
    identifier_label, identifier_value = _license_summary_identifier(license_type, info, fallback_info, extra)

    return {
        "source": source,
        "type": license_type,
        "type_label": _license_type_label(license_type),
        "status_label": status_label,
        "status_tone": status_tone,
        "identifier_label": identifier_label,
        "identifier_value": identifier_value,
        "expires_label": _license_expires_label(extra, valid=valid),
        "message": str(message or "").strip(),
        "action_href": "/license/manager",
        "action_label": "管理授权",
    }


def _build_dashboard_platform_summary(runtime=None):
    """构建`dashboard``platform``summary`。"""
    runtime = runtime or {}
    cloud_mode = bool(is_cloud_mode())
    mode_label = "云端模式" if cloud_mode else "边缘单机"
    mode_note = "当前已启用云端多集群协同与远程接入。" if cloud_mode else "当前未启用云端多集群编排。"
    edge_cluster_count = _safe_count(CloudEdgeCluster.objects)
    api_key_count = _safe_count(ApiKey.objects)
    enabled_api_key_count = _safe_count(ApiKey.objects.filter(enabled=True, revoked_at__isnull=True))

    return {
        "license": _build_dashboard_license_summary(),
        "deployment": {
            "mode_label": mode_label,
            "mode_note": mode_note,
            "edge_cluster_count": edge_cluster_count,
            "api_key_count": api_key_count,
            "enabled_api_key_count": enabled_api_key_count,
            "host": str(runtime.get("host") or "-"),
            "action_href": "/cloud/edge-clusters" if cloud_mode else "/developer/index",
            "action_label": "查看云端集群" if cloud_mode else "查看开发入口",
        },
        "assets": {
            "algorithm_count": _safe_count(AlgorithmModel.objects),
            "control_count": _safe_count(Control.objects),
            "active_control_count": _safe_count(Control.objects.filter(state=1)),
            "recording_plan_count": _safe_count(RecordingPlan.objects),
            "enabled_recording_plan_count": _safe_count(RecordingPlan.objects.filter(enabled=True)),
            "action_href": "/controls",
            "action_label": "查看布控编排",
        },
    }


def _load_dashboard_os_info():
    """读取`dashboard`系统信息。"""
    try:
        return api_view.OSSystem().get_os_info() or {}
    except Exception:
        return {}


def _load_dashboard_diagnostics():
    """读取`dashboard`诊断信息。"""
    try:
        return OpsDiagnosticsView._load_diagnostics_summary() or {}
    except Exception:
        return OpsDiagnosticsView._build_empty_summary()


def _load_dashboard_analyzer_status(cache_ttl_seconds):
    """读取`dashboard`分析器状态。"""
    try:
        analyzer_ok, analyzer_msg, analyzer_stats = api_view.g_analyzer.scheduler_info(
            timeout_seconds=2,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        return analyzer_ok, analyzer_msg, analyzer_stats
    except Exception as exc:
        return False, str(exc), {}


def _load_dashboard_device_status(cache_ttl_seconds):
    """读取`dashboard`设备状态。"""
    try:
        device_ok, device_msg, device_info = api_view.g_analyzer.device_info(
            timeout_seconds=2,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        return device_ok, device_msg, device_info
    except Exception as exc:
        return False, str(exc), {}


def _build_dashboard_process_rows(cache_ttl_seconds):
    """构建`dashboard`进程行。"""
    try:
        hosts = api_view._core_process_hosts()
        analyzer_class = api_view._core_process_analyzer_class()
    except Exception:
        return [], []
    try:
        rows = [
            _normalize_process_summary(
                api_view._core_process_entry(
                    idx,
                    host,
                    analyzer_class,
                    cache_ttl_seconds=cache_ttl_seconds,
                )
            )
            for idx, host in enumerate(hosts)
        ]
    except Exception:
        return [], []
    return hosts, rows


def _build_dashboard_runtime():
    """构建`dashboard`运行时。"""
    cache_ttl_seconds = api_view._index_analyzer_cache_ttl_seconds()
    os_info = _load_dashboard_os_info()
    diagnostics = _load_dashboard_diagnostics()
    analyzer_ok, analyzer_msg, analyzer_stats = _load_dashboard_analyzer_status(cache_ttl_seconds)
    device_ok, device_msg, device_info = _load_dashboard_device_status(cache_ttl_seconds)
    hosts, process_rows = _build_dashboard_process_rows(cache_ttl_seconds)

    runtime = {
        "host": str(diagnostics.get("host") or os_info.get("machine_node") or "-"),
        "system_name": str(diagnostics.get("system_name") or os_info.get("system_name") or "-"),
        "os_release": str(diagnostics.get("os_release") or "-"),
        "uptime": str(diagnostics.get("uptime") or os_info.get("os_run_date_str") or "-"),
        "cpu": {
            "model": str(diagnostics.get("cpu") or "-"),
            "usage": str(os_info.get("os_cpu_used_rate_str") or diagnostics.get("cpu_usage") or "-"),
            "usage_rate": _safe_float(os_info.get("os_cpu_used_rate"), 0.0),
        },
        "memory": {
            "usage": str(os_info.get("os_virtual_mem_used_rate_str") or diagnostics.get("memory_usage") or "-"),
            "usage_rate": _safe_float(os_info.get("os_virtual_mem_used_rate"), 0.0),
        },
        "disk": {
            "usage": str(os_info.get("os_disk_used_rate_str") or diagnostics.get("disk_usage") or "-"),
            "usage_rate": _safe_float(os_info.get("os_disk_used_rate"), 0.0),
        },
        "network": _build_dashboard_network_snapshot(os_info),
        "analyzer": {
            "ok": bool(analyzer_ok),
            "msg": str(analyzer_msg or ""),
            "stats": analyzer_stats or {},
            "devices": {
                "ok": bool(device_ok),
                "msg": str(device_msg or ""),
                "onnx_providers": _safe_list((device_info or {}).get("onnxProviders")),
                "openvino_devices": _safe_list((device_info or {}).get("openvinoDevices")),
            },
        },
        "processes": {
            "process_num": int(len(hosts)),
            "process_mode": 1 if len(hosts) > 1 else 0,
            "rows": process_rows,
        },
        "controls": {
            "process_num": int(ControlView._get_analyzer_process_num() or 0),
        },
    }
    return runtime, diagnostics


def api_dashboard(request):
    """处理 `dashboard` 接口请求。"""
    data = web._build_multisite_overview_context()
    runtime, diagnostics = _build_dashboard_runtime()
    data["runtime"] = runtime
    data["diagnostics"] = diagnostics
    data["platform"] = _build_dashboard_platform_summary(runtime=runtime)
    return f_responseJson({"code": 1000, "msg": "success", "data": data})


def api_diagnostics(request):
    """处理 `diagnostics` 接口请求。"""
    try:
        summary = OpsDiagnosticsView._load_diagnostics_summary() or {}
    except Exception:
        summary = OpsDiagnosticsView._build_empty_summary()
    return f_responseJson({"code": 1000, "msg": "success", "data": {"summary": summary, "ops_toolbox": _build_diagnostics_ops_toolbox()}})


def _build_diagnostics_cleanup_toolbox():
    """构建`diagnostics`清理`toolbox`。"""
    return {
        "target_options": [
            {
                "value": "metrics_cache",
                "label": "指标缓存",
                "note": "清理进程内 metrics 缓存，适合确认最新统计是否回收。",
                "supports_dry_run": False,
            },
            {
                "value": "alarm_compose_cache",
                "label": "告警拼图缓存",
                "note": "支持仅预览，适合先确认将删除多少历史拼图缓存。",
                "supports_dry_run": True,
            },
            {
                "value": "transcode_cache",
                "label": "转码缓存",
                "note": "请求后台转码管理器清空缓存。",
                "supports_dry_run": False,
            },
            {
                "value": "logs",
                "label": "运行日志",
                "note": "按保留天数清理 Admin / Analyzer / MediaServer 日志文件。",
                "supports_dry_run": True,
            },
            {
                "value": "tmp_files",
                "label": "临时文件",
                "note": "按最长保留时长清理 tmp / temp 目录与上传缓存。",
                "supports_dry_run": True,
            },
        ],
        "defaults": {
            "dry_run": True,
            "selected_targets": ["metrics_cache", "alarm_compose_cache"],
            "log_retention_days": 7,
            "tmp_max_age_hours": 24,
        },
    }


def _build_diagnostics_outbox_toolbox():
    """构建`diagnostics``outbox``toolbox`。"""
    pending_count = _safe_count(AlarmEventOutbox.objects.filter(status="pending"))
    failed_count = _safe_count(AlarmEventOutbox.objects.filter(status="failed"))
    sink_values = list(AlarmEventOutbox.objects.exclude(sink_type="").values_list("sink_type", flat=True).distinct())
    sink_labels = {
        "webhook": "Webhook",
        "cloud": "Cloud",
    }
    sink_options = [{"value": "", "label": "全部通道"}]
    for value in sorted([str(item or "").strip() for item in sink_values if str(item or "").strip()]):
        sink_options.append({"value": value, "label": sink_labels.get(value, value)})
    return {
        "summary": {
            "pending_count": pending_count,
            "failed_count": failed_count,
        },
        "sink_options": sink_options,
        "defaults": {
            "reset_attempts": False,
        },
    }


def _build_diagnostics_logging_toolbox():
    """构建`diagnostics``logging``toolbox`。"""
    return {
        "level_options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        "logger_options": [
            {"value": "", "label": "root"},
            {"value": "app.middleware", "label": "app.middleware"},
            {"value": "app.views", "label": "app.views"},
            {"value": "app.utils", "label": "app.utils"},
            {"value": "django.request", "label": "django.request"},
        ],
        "defaults": {
            "level": "INFO",
            "logger": "",
        },
    }


def _build_diagnostics_sink_test_toolbox():
    """构建`diagnostics`接收端`test``toolbox`。"""
    sink_specs = [
        (
            "webhook",
            "Webhook",
            bool(getattr(g_config, "alarmWebhookEnabled", False))
            and any(str(url or "").strip() for url in (getattr(g_config, "alarmWebhookUrls", []) or [])),
        ),
        (
            "cloud",
            "Cloud",
            bool(getattr(g_config, "cloudEnabled", False))
            and bool(str(getattr(g_config, "cloudBaseUrl", "") or "").strip())
            and bool(str(getattr(g_config, "cloudEdgeToken", "") or "").strip()),
        ),
    ]
    enabled = [{"name": name, "label": label, "enabled": True} for name, label, is_enabled in sink_specs if is_enabled]
    disabled = [{"name": name, "label": label, "enabled": False} for name, label, is_enabled in sink_specs if not is_enabled]
    return {
        "enabled_sinks": enabled,
        "disabled_sinks": disabled,
        "summary": {
            "enabled_count": len(enabled),
            "disabled_count": len(disabled),
        },
    }


def _build_diagnostics_ops_toolbox():
    """构建`diagnostics`运维`toolbox`。"""
    return {
        "cleanup": _build_diagnostics_cleanup_toolbox(),
        "outbox": _build_diagnostics_outbox_toolbox(),
        "logging": _build_diagnostics_logging_toolbox(),
        "sink_test": _build_diagnostics_sink_test_toolbox(),
    }


def _normalize_upgrade_state(state):
    """执行归一化`upgrade`状态。"""
    state = state or {}
    return {
        "current_version": str(state.get("current_version") or PROJECT_VERSION or ""),
        "target_version": str(state.get("target_version") or ""),
        "applied_package_id": str(state.get("applied_package_id") or ""),
        "previous_package_id": str(state.get("previous_package_id") or ""),
        "applied_at": str(state.get("applied_at") or ""),
        "rolled_back_from": str(state.get("rolled_back_from") or ""),
        "rolled_back_at": str(state.get("rolled_back_at") or ""),
    }


def _build_upgrade_package_inventory():
    """构建`upgrade`打包`inventory`。"""
    OpsUpgradeView._ensure_dirs()
    rows = []
    for pkg_id in OpsUpgradeView._list_package_ids():
        meta, manifest = OpsUpgradeView._load_package_meta_and_manifest(pkg_id)
        compat_ok, compat_errors = (
            OpsUpgradeView._validate_manifest_compat_for_current(manifest) if isinstance(manifest, dict) else (False, ["manifest missing"])
        )
        rows.append(
            OpsUpgradeView._package_list_item(
                pkg_id=pkg_id,
                meta=meta if isinstance(meta, dict) else {},
                manifest=manifest if isinstance(manifest, dict) else {},
                compat_ok=bool(compat_ok),
                compat_errors=compat_errors,
            )
        )
    OpsUpgradeView._sort_packages_best_effort(rows)
    return rows


def _build_upgrade_summary(*, state, packages):
    """构建`upgrade``summary`。"""
    compatible_total = len([row for row in packages if bool(row.get("compatible_ok"))])
    incompatible_total = len(packages) - compatible_total
    return {
        "package_total": len(packages),
        "compatible_total": compatible_total,
        "incompatible_total": incompatible_total,
        "current_version": str(state.get("current_version") or PROJECT_VERSION or ""),
        "applied_package_id": str(state.get("applied_package_id") or ""),
        "previous_package_id": str(state.get("previous_package_id") or ""),
        "target_version": str(state.get("target_version") or ""),
        "latest_uploaded_at": str(packages[0].get("uploaded_at") or "") if packages else "",
        "rollback_ready": bool(state.get("previous_package_id")),
    }


def _decode_shell_json_data(response):
    """返回`decode``shell`JSON数据。"""
    try:
        payload = json.loads(response.content.decode("utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _decode_shell_text(response):
    """处理`decode``shell`文本。"""
    try:
        return response.content.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return str(response.content or "")
        except Exception:
            return ""


def _safe_metric_int(value, default=0):
    """处理安全`metric`整数值。"""
    return int(_safe_float(value, default))


def _normalize_metric_percent(value):
    """执行归一化`metric``percent`。"""
    percent = _safe_float(value, 0.0)
    if percent < 0:
        percent = 0.0
    if percent <= 1.0:
        percent *= 100.0
    return round(percent, 1)


def _format_relative_time(value):
    """返回`format``relative`时间。"""
    if not value:
        return ""
    current = value
    try:
        if not timezone.is_naive(current):
            current = timezone.localtime(current)
    except Exception:
        return ""
    now = timezone.now()
    try:
        if not timezone.is_naive(now):
            now = timezone.localtime(now)
    except Exception:
        logger.debug("localize current timestamp for relative time failed", exc_info=True)
    seconds = max(0, int((now - current).total_seconds()))
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = seconds // 3600
    if hours < 24:
        return f"{hours} 小时前"
    days = seconds // 86400
    if days < 7:
        return f"{days} 天前"
    return current.strftime("%Y-%m-%d %H:%M")


def _local_datetime_or_none(value):
    """转换为本地时间。"""
    if not value:
        return None
    try:
        return timezone.localtime(value) if not timezone.is_naive(value) else value
    except Exception:
        return None


def _format_created_at_text(value) -> str:
    """格式化创建时间文本。"""
    current = _local_datetime_or_none(value)
    if not current:
        return ""
    try:
        return current.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _build_notification_item(*, notification_id: str, kind: str, level: str, title: str, description: str, href: str, created_at, priority: int):
    """构建`notification``item`。"""
    created_dt = _local_datetime_or_none(created_at)
    time_label = _format_relative_time(created_dt)
    return {
        "id": str(notification_id or kind or ""),
        "kind": str(kind or ""),
        "level": str(level or "info"),
        "title": str(title or ""),
        "description": str(description or ""),
        "href": str(href or ""),
        "time": time_label,
        "created_at": _format_created_at_text(created_dt),
        "priority": int(priority or 0),
        "_created_sort": created_dt or timezone.now(),
    }


def _build_alarm_notification_item():
    """构建告警`notification``item`。"""
    unread_qs = Alarm.objects.filter(state=0).order_by("-create_time", "-id")
    unread_count = unread_qs.count()
    if unread_count <= 0:
        return None
    latest_alarm = unread_qs.first()
    latest_desc = ""
    latest_id = 0
    latest_created_at = timezone.now()
    if latest_alarm is not None:
        latest_desc = str(getattr(latest_alarm, "desc", "") or getattr(latest_alarm, "detail_desc", "") or "").strip()
        latest_id = int(getattr(latest_alarm, "id", 0) or 0)
        latest_created_at = getattr(latest_alarm, "create_time", None) or latest_created_at
    description = "存在未处理告警，请及时复核。"
    if latest_desc:
        description = f"最近告警：{latest_desc}"
    return _build_notification_item(
        notification_id=f"alarm-unread-{unread_count}-{latest_id}",
        kind="alarm_unread",
        level="warning",
        title=f"{unread_count} 条未处理告警",
        description=description,
        href="/alarm/review?mode=review&review_tab=unread&unread=1",
        created_at=latest_created_at,
        priority=100,
    )


def _runtime_process_rows(runtime):
    """返回运行时进程行。"""
    processes = runtime.get("processes") if isinstance(runtime.get("processes"), dict) else {}
    rows = processes.get("rows") if isinstance(processes, dict) else []
    return rows if isinstance(rows, (list, tuple)) else []


def _platform_analyzer_description(analyzer: dict, abnormal_rows) -> str:
    """返回分析器异常描述。"""
    description = str(analyzer.get("msg") or "").strip()
    if description:
        return description
    if not abnormal_rows:
        return "分析服务当前不可达，请检查 Analyzer 进程状态。"
    first_row = abnormal_rows[0]
    host = str(first_row.get("analyzer_host") or "").strip()
    row_msg = str(first_row.get("msg") or "").strip()
    return row_msg or (f"{host} 当前异常" if host else "分析服务当前不可达")


def _build_platform_analyzer_notification_item(runtime):
    """构建`platform`分析器`notification``item`。"""
    runtime = runtime if isinstance(runtime, dict) else {}
    analyzer = runtime.get("analyzer") if isinstance(runtime.get("analyzer"), dict) else {}
    process_rows = _runtime_process_rows(runtime)
    analyzer_ok = bool(analyzer.get("ok"))
    abnormal_rows = [row for row in (process_rows or []) if isinstance(row, dict) and not bool(row.get("ok"))]
    if analyzer_ok and not abnormal_rows:
        return None
    return _build_notification_item(
        notification_id="platform-analyzer",
        kind="platform_analyzer",
        level="critical",
        title="分析服务异常",
        description=_platform_analyzer_description(analyzer, abnormal_rows),
        href="/ops/platform",
        created_at=timezone.now(),
        priority=90,
    )


def _build_platform_resource_notification_item(metrics_summary):
    """构建`platform``resource``notification``item`。"""
    metrics_summary = metrics_summary if isinstance(metrics_summary, dict) else {}
    threshold = 85.0
    pressure_parts = []
    cpu_percent = _normalize_metric_percent(metrics_summary.get("cpu_ratio"))
    mem_percent = _normalize_metric_percent(metrics_summary.get("mem_ratio"))
    disk_percent = _normalize_metric_percent(metrics_summary.get("disk_ratio"))
    if cpu_percent >= threshold:
        pressure_parts.append(f"CPU {cpu_percent:.1f}%")
    if mem_percent >= threshold:
        pressure_parts.append(f"内存 {mem_percent:.1f}%")
    if disk_percent >= threshold:
        pressure_parts.append(f"磁盘 {disk_percent:.1f}%")
    if not pressure_parts:
        return None
    return _build_notification_item(
        notification_id="platform-resource",
        kind="platform_resource",
        level="warning",
        title="节点资源压力过高",
        description="，".join(pressure_parts),
        href="/ops/platform",
        created_at=timezone.now(),
        priority=80,
    )


def _build_license_notification_item(request):
    """构建授权`notification``item`。"""
    payload = _build_license_shell_payload(request)
    payload = payload if isinstance(payload, dict) else {}
    license_error = payload.get("license_error") if isinstance(payload.get("license_error"), dict) else {}
    transport_ok = bool(payload.get("transport_ok", True))
    transport_message = str(payload.get("transport_message") or "").strip()
    title = ""
    description = ""
    created_at = None

    if license_error:
        title = str(license_error.get("title") or "").strip() or "授权状态异常"
        description = (
            str(license_error.get("message") or "").strip()
            or str(license_error.get("hint") or "").strip()
            or transport_message
            or "当前授权状态异常，请检查授权配置。"
        )
        created_at = license_error.get("state_update_time")
    elif not transport_ok:
        title = "授权服务不可达"
        description = transport_message or "当前无法读取授权状态。"
        created_at = timezone.now()
    else:
        return None

    return _build_notification_item(
        notification_id="license-error",
        kind="license_error",
        level="critical",
        title=title,
        description=description,
        href="/license/manager",
        created_at=created_at or timezone.now(),
        priority=70,
    )


def _parse_prometheus_metrics(body_text):
    """解析`prometheus`指标。"""
    samples = {}
    for raw_line in str(body_text or "").splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        metric_name = str(parts[0] or "").split("{", 1)[0].strip()
        if not metric_name:
            continue
        samples[metric_name] = parts[1]
    return samples


def _build_platform_service_status(request):
    """构建`platform``service`状态。"""
    try:
        health = _decode_shell_json_data(OpsView.healthz(request))
    except Exception:
        health = {}
    try:
        ready = _decode_shell_json_data(OpsView.readyz(request))
    except Exception:
        ready = {}
    return {
        "health": health,
        "ready": ready,
    }


def _build_platform_metrics_summary(request):
    """构建`platform`指标`summary`。"""
    try:
        metrics_text = _decode_shell_text(OpsView.metrics(request))
    except Exception:
        metrics_text = ""
    samples = _parse_prometheus_metrics(metrics_text)
    return {
        "cpu_ratio": _safe_float(samples.get("beacon_admin_system_cpu_used_ratio"), 0.0),
        "mem_ratio": _safe_float(samples.get("beacon_admin_system_mem_used_ratio"), 0.0),
        "disk_ratio": _safe_float(samples.get("beacon_admin_system_disk_used_ratio"), 0.0),
        "outbox_pending": _safe_metric_int(samples.get("beacon_admin_alarm_outbox_pending"), 0),
        "outbox_failed": _safe_metric_int(samples.get("beacon_admin_alarm_outbox_failed"), 0),
        "license_active_leases": _safe_metric_int(samples.get("beacon_admin_license_active_leases"), 0),
        "login_lockout_active": _safe_metric_int(samples.get("beacon_admin_login_lockout_active"), 0),
    }


def _disk_usage_percent(total, used) -> float:
    """返回磁盘使用率百分比。"""
    total_value = _safe_float(total, 0.0)
    if total_value <= 0:
        return 0.0
    return round((_safe_float(used, 0.0) / total_value) * 100.0, 1)


def _dict_value(value) -> dict:
    """Return a dict value or an empty mapping."""
    return value if isinstance(value, dict) else {}


def _summary_text(mapping: dict, key: str) -> str:
    """Return a summary text field."""
    value = mapping.get(key)
    return "" if value is None else str(value)


def _summary_int(mapping: dict, key: str) -> int:
    """Return a summary integer field."""
    return int(mapping.get(key) or 0)


def _summary_version(basic_info: dict) -> str:
    """Return the platform version text."""
    version = basic_info.get("version")
    if version:
        return str(version)
    return str(PROJECT_VERSION or "")


def _build_platform_summary(*, basic_info, storage_info):
    """构建`platform``summary`。"""
    basic_info = _dict_value(basic_info)
    storage_info = _dict_value(storage_info)
    disk = _dict_value(storage_info.get("disk"))
    usage = _dict_value(storage_info.get("usage"))
    return {
        "version": _summary_version(basic_info),
        "node_code": _summary_text(basic_info, "nodeCode"),
        "node_name": _summary_text(basic_info, "nodeName"),
        "machine_node": _summary_text(basic_info, "machineNode"),
        "storage_root_path": _summary_text(storage_info, "storageRootPath"),
        "disk_usage_percent": _disk_usage_percent(disk.get("total"), disk.get("used")),
        "disk_total_bytes": _summary_int(disk, "total"),
        "disk_used_bytes": _summary_int(disk, "used"),
        "disk_free_bytes": _summary_int(disk, "free"),
        "alarm_usage_bytes": _summary_int(usage, "alarmBytes"),
        "recording_usage_bytes": _summary_int(usage, "recordingBytes"),
        "admin_port": _summary_int(basic_info, "adminPort"),
        "analyzer_port": _summary_int(basic_info, "analyzerPort"),
    }


def api_platform(request):
    """处理 `platform` 接口请求。"""
    db_user = OpsApiKeyView._get_db_user(request)
    if not db_user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})
    if not OpsApiKeyView._is_admin(db_user):
        return OpsApiKeyView._deny(request, json_mode=True)

    basic_info = _decode_shell_json_data(api_view.api_openBasicInfo(request))
    storage_info = _decode_shell_json_data(api_view.api_openStorageInfo(request))
    summary = _build_platform_summary(basic_info=basic_info, storage_info=storage_info)
    service_status = _build_platform_service_status(request)
    metrics_summary = _build_platform_metrics_summary(request)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "summary": summary,
                "basic_info": basic_info,
                "storage_info": storage_info,
                "service_status": service_status,
                "metrics_summary": metrics_summary,
                "actions": {
                    "refresh": "/api/app-shell/platform",
                    "basic_info": "/api/app-shell/platform/action/basicInfo",
                    "storage_info": "/api/app-shell/platform/action/storageInfo",
                    "restart_software": "/api/app-shell/platform/action/restartSoftware",
                    "restart_system": "/api/app-shell/platform/action/restartSystem",
                },
                "restart_notes": {
                    "software": "重启 Admin 进程，依赖外部守护进程或容器策略拉起。",
                    "system": "重启整机，通常需要管理员权限，执行前应确认维护窗口。",
                },
            },
        }
    )


def api_upgrade(request):
    """处理 `upgrade` 接口请求。"""
    db_user = OpsApiKeyView._get_db_user(request)
    if not db_user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})
    if not OpsApiKeyView._is_admin(db_user):
        return OpsApiKeyView._deny(request, json_mode=True)

    state = _normalize_upgrade_state(OpsUpgradeView._load_state())
    packages = _build_upgrade_package_inventory()
    summary = _build_upgrade_summary(state=state, packages=packages)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "summary": summary,
                "state": state,
                "packages": packages,
                "upload": {
                    "field_name": "file",
                    "accept": ".zip,application/zip",
                    "note": "升级包必须包含 manifest.json，并声明 compatible 元数据。",
                },
                "actions": {
                    "checkVersion": "/api/app-shell/ops/action/upgrade/checkVersion",
                    "upload": "/api/app-shell/ops/action/upgrade/upload",
                    "validate": "/api/app-shell/ops/action/upgrade/validate",
                    "apply": "/api/app-shell/ops/action/upgrade/apply",
                    "rollback": "/api/app-shell/ops/action/upgrade/rollback",
                },
            },
        }
    )


def _parse_page_params(params, *, default_page_size=20, min_page_size=1, max_page_size=100):
    """解析页面参数。"""
    try:
        page = int(params.get("page") or params.get("p") or 1)
    except Exception:
        page = 1
    try:
        page_size = int(params.get("page_size") or params.get("ps") or default_page_size)
    except Exception:
        page_size = default_page_size
    page = max(1, page)
    page_size = max(min_page_size, min(max_page_size, page_size))
    return page, page_size


def _build_page_data(*, paginator, page, page_size):
    """构建页面数据。"""
    from app.utils.Common import buildPageLabels

    return {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": buildPageLabels(page=page, page_num=paginator.num_pages),
    }


def api_users(request):
    """处理 `users` 接口请求。"""
    db_user = UserManageView._db_user_from_session(request)
    if not db_user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})
    if not UserManageView._is_admin_user(db_user):
        return f_responseJson({"code": 403, "msg": UserManageView.ADMIN_ONLY_MSG})

    params = f_parseGetParams(request)
    page, page_size = _parse_page_params(params, default_page_size=20, max_page_size=200)
    keyword = str(params.get("keyword", "") or "").strip()
    status = str(params.get("status", "") or "").strip().lower()
    user_type = str(params.get("user_type", "") or "").strip().lower()

    queryset = User.objects.all().order_by("-id")
    if keyword:
        queryset = queryset.filter(
            Q(username__icontains=keyword)
            | Q(email__icontains=keyword)
            | Q(first_name__icontains=keyword)
            | Q(last_name__icontains=keyword)
        )
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)

    if user_type == "superuser":
        queryset = queryset.filter(is_superuser=True)
    elif user_type == "staff":
        queryset = queryset.filter(is_staff=True, is_superuser=False)
    elif user_type == "user":
        queryset = queryset.filter(is_staff=False, is_superuser=False)

    paginator = Paginator(queryset, page_size)
    current_page = paginator.get_page(page)
    page = current_page.number

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": [UserManageView._user_row(row) for row in current_page.object_list],
                "pageData": _build_page_data(paginator=paginator, page=page, page_size=page_size),
                "filters": {
                    "keyword": keyword,
                    "status": status,
                    "user_type": user_type,
                },
                "permission_meta": list(UserManageView.PERMISSION_META),
                "status_choices": [
                    {"code": "", "name": "全部状态"},
                    {"code": "active", "name": "启用"},
                    {"code": "inactive", "name": "禁用"},
                ],
                "user_type_choices": [
                    {"code": "", "name": "全部类型"},
                    {"code": "superuser", "name": "超级管理员"},
                    {"code": "staff", "name": "管理员"},
                    {"code": "user", "name": "普通用户"},
                ],
                "current_user_id": int(getattr(db_user, "id", 0) or 0),
                "can_manage": True,
            },
        }
    )


def api_audit(request):
    """处理 `audit` 接口请求。"""
    db_user = OpsAuditLogView._get_db_user(request)
    if not db_user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})
    if not OpsAuditLogView._has_audit_access(db_user):
        return OpsAuditLogView._deny(request, json_mode=True)

    params = f_parseGetParams(request)
    page, page_size = _parse_page_params(params, default_page_size=20, max_page_size=200)
    queryset = OpsAuditLog.objects.all().order_by("-id")
    queryset = OpsAuditLogView._apply_filters(queryset, params)
    paginator = Paginator(queryset, page_size)
    current_page = paginator.get_page(page)
    page = current_page.number

    filters = {
        "event_type": str(params.get("event_type", "") or "").strip(),
        "keyword": str(params.get("keyword", "") or "").strip(),
        "actor": str(params.get("actor", "") or "").strip(),
        "object": str(params.get("object", "") or "").strip(),
        "action": str(params.get("action", "") or "").strip(),
        "ok": str(params.get("ok", "") or "").strip(),
        "since": str(params.get("since", "") or "").strip(),
        "until": str(params.get("until", "") or "").strip(),
    }

    export_filters = {key: value for key, value in filters.items() if value}
    export_urls = {
        "json": "/api/app-shell/ops/action/audit/export?" + urlencode({**export_filters, "format": "json"}),
        "csv": "/api/app-shell/ops/action/audit/export?" + urlencode({**export_filters, "format": "csv"}),
    }

    rows = [OpsAuditLogView._serialize_audit_row(row) for row in current_page.object_list]
    success_total = queryset.filter(ok=True).count()
    failure_total = queryset.filter(ok=False).count()

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": rows,
                "pageData": _build_page_data(paginator=paginator, page=page, page_size=page_size),
                "filters": filters,
                "stats": {
                    "filtered_total": int(paginator.count),
                    "success_total": int(success_total),
                    "failure_total": int(failure_total),
                },
                "export_urls": export_urls,
                "ok_choices": [
                    {"code": "", "name": "全部结果"},
                    {"code": "1", "name": "成功"},
                    {"code": "0", "name": "失败"},
                ],
            },
        }
    )


def _api_key_row_matches(row: dict, *, keyword: str, enabled: str, scope: str) -> bool:
    """返回 API Key 行是否匹配筛选条件。"""
    if keyword:
        haystack = " ".join(
            [
                str(row.get("name") or ""),
                str(row.get("token_prefix") or ""),
                " ".join(row.get("scopes") or []),
                str(row.get("created_by") or ""),
            ]
        ).lower()
        if keyword not in haystack:
            return False
    if enabled in ("1", "true", "yes", "on") and not bool(row.get("enabled")):
        return False
    if enabled in ("0", "false", "no", "off") and bool(row.get("enabled")):
        return False
    if scope and scope not in (row.get("scopes") or []):
        return False
    return True


def api_apikeys(request):
    """处理 `apikeys` 接口请求。"""
    db_user = OpsApiKeyView._get_db_user(request)
    if not db_user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})
    if not OpsApiKeyView._is_admin(db_user):
        return OpsApiKeyView._deny(request, json_mode=True)

    params = f_parseGetParams(request)
    keyword = str(params.get("keyword", "") or "").strip().lower()
    enabled = str(params.get("enabled", "") or "").strip().lower()
    scope = str(params.get("scope", "") or "").strip()

    rows = list(ApiKey.objects.all().order_by("-id")[:500])
    serialized_rows = [OpsApiKeyView._serialize_api_key_row(row) for row in rows]
    filtered_rows = [row for row in serialized_rows if _api_key_row_matches(row, keyword=keyword, enabled=enabled, scope=scope)]

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": filtered_rows,
                "filters": {
                    "keyword": keyword,
                    "enabled": enabled,
                    "scope": scope,
                },
                "known_scopes": list(OpsApiKeyView._KNOWN_SCOPES),
                "scope_choices": [{"code": item, "name": item} for item in OpsApiKeyView._KNOWN_SCOPES],
                "create_defaults": {
                    "expires_days": 30,
                    "rate_limit_per_minute": 60,
                    "burst_limit": 10,
                },
                "stats": {
                    "total": len(filtered_rows),
                    "enabled_total": len([row for row in filtered_rows if bool(row.get("enabled"))]),
                    "revoked_total": len([row for row in filtered_rows if not bool(row.get("enabled"))]),
                },
                "can_manage": True,
            },
        }
    )


def _recording_days_mask_label(days_mask: int) -> str:
    """处理录制`days`脱敏标签。"""
    try:
        value = int(days_mask or 0)
    except Exception:
        value = 0
    labels = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    if value == 127:
        return "每天"
    selected = [labels[index] for index in range(7) if value & (1 << index)]
    return " / ".join(selected) if selected else "未设置"


def _safe_disk_usage(path: str):
    """处理安全`disk``usage`。"""
    try:
        return shutil.disk_usage(path)
    except Exception:
        return None


def _serialize_active_recording_row(row: dict, stream_map: dict):
    """返回`serialize`活动录制记录。"""
    stream_code = str((row or {}).get("stream_code", "") or "")
    stream = stream_map.get(stream_code)
    return {
        "stream_code": stream_code,
        "record_id": str((row or {}).get("record_id", "") or ""),
        "status": str((row or {}).get("status", "") or ""),
        "elapsed_time": int((row or {}).get("elapsed_time", 0) or 0),
        "duration": int((row or {}).get("duration", 0) or 0),
        "stream_name": str(getattr(stream, "name", "") or ""),
        "stream_nickname": str(getattr(stream, "nickname", "") or ""),
        "site_label": str(getattr(stream, "site_label", "") or ""),
        "app": str(getattr(stream, "app", "") or ""),
    }


def _serialize_recording_plan_row(plan, stream_map: dict):
    """返回`serialize`录制计划记录。"""
    row = dict(api_view._recording_plan_to_dict(plan) or {})
    stream = stream_map.get(row.get("stream_code"))
    row["days_label"] = _recording_days_mask_label(row.get("days_mask", 0))
    row["stream_nickname"] = str(getattr(stream, "nickname", "") or "")
    row["site_label"] = str(getattr(stream, "site_label", "") or "")
    row["stream_exists"] = bool(stream)
    return row


def _serialize_recording_stream_row(stream, active_map: dict, *, live_keys=None):
    """返回`serialize`录制流记录。"""
    base = _serialize_stream_row(stream)
    stream_code = base["code"]
    recording_status = active_map.get(stream_code)
    is_online = _stream_is_online(stream, live_keys=live_keys)
    base.update(
        {
            "stream_code": stream_code,
            "stream_url": str(getattr(stream, "pull_stream_url", "") or ""),
            "is_online": is_online,
            "is_recording": bool(recording_status),
            "recording_status": recording_status or None,
            "forward_state_label": "转发中" if int(getattr(stream, "forward_state", 0) or 0) == 1 else "未转发",
            "online_state_label": "在线" if is_online else "离线",
            "action_hint": "可直接截图或开始录像" if str(getattr(stream, "pull_stream_url", "") or "").strip() else "缺少拉流地址",
        }
    )
    return base


def _recording_stream_queryset(q: str):
    """返回录制流查询集。"""
    queryset = Stream.objects.all().order_by("-id")
    if not q:
        return queryset
    return queryset.filter(
        Q(code__icontains=q)
        | Q(name__icontains=q)
        | Q(nickname__icontains=q)
        | Q(app__icontains=q)
        | Q(site_label__icontains=q)
        | Q(remark__icontains=q)
    )


def _recording_plan_queryset(q: str):
    """返回录制计划查询集。"""
    queryset = RecordingPlan.objects.all().order_by("-id")
    if not q:
        return queryset
    return queryset.filter(
        Q(code__icontains=q)
        | Q(name__icontains=q)
        | Q(stream_code__icontains=q)
        | Q(remark__icontains=q)
    )


def _active_recording_rows():
    """读取活动录制记录。"""
    try:
        storage_root = str(getattr(g_config, "storageRootPath", "") or getattr(g_config, "uploadDir", "") or "").strip()
        recorder = StreamRecordingView.get_stream_recorder(storage_root)
        return list(recorder.list_active_recordings() or [])
    except Exception:
        return []


def _recording_stream_map(streams, active_recordings, plans):
    """构建录制流映射。"""
    stream_lookup_codes = {str(getattr(item, "code", "") or "") for item in streams}
    stream_lookup_codes.update(str((row or {}).get("stream_code", "") or "") for row in active_recordings)
    stream_lookup_codes.update(str(getattr(plan, "stream_code", "") or "") for plan in plans)
    return {item.code: item for item in Stream.objects.filter(code__in=list(stream_lookup_codes))}


def _recording_storage_paths():
    """返回录制存储路径。"""
    storage_root = str(getattr(g_config, "storageRootPath", "") or getattr(g_config, "uploadDir", "") or "").strip()
    recording_root = str(getattr(g_config, "recordingStoragePath", "") or "").strip()
    if not recording_root:
        recording_root = os.path.join(storage_root, "recordings") if storage_root else ""
    return storage_root, recording_root


def _recording_storage_payload(storage_root: str, recording_root: str):
    """构建录制存储载荷。"""
    disk_usage = _safe_disk_usage(recording_root or storage_root)
    recording_quota_mb = int(get_int("recordingDataMaxStorageMB", 0, min_value=0, max_value=1024 * 1024) or 0)
    return {
        "paths": {
            "storage_root": storage_root,
            "recording_root": recording_root,
        },
        "disk": {
            "total": int(getattr(disk_usage, "total", 0) or 0),
            "used": int(getattr(disk_usage, "used", 0) or 0),
            "free": int(getattr(disk_usage, "free", 0) or 0),
        },
        "usage": {
            "recording_bytes": int(api_view._dir_size_bytes(recording_root) or 0),
        },
        "quota": {
            "recording_max_storage_mb": recording_quota_mb,
        },
    }


def _recording_summary(*, paginator, stream_queryset, live_keys, active_rows, plan_rows):
    """构建录制摘要。"""
    return {
        "stream_count": int(paginator.count),
        "online_streams": sum(1 for item in stream_queryset if _stream_is_online(item, live_keys=live_keys)),
        "forwarding_streams": int(stream_queryset.filter(forward_state=1).count()),
        "active_recordings": len(active_rows),
        "plan_count": len(plan_rows),
        "enabled_plan_count": len([row for row in plan_rows if bool(row.get("enabled"))]),
    }


def api_recording(request):
    """处理 `recording` 接口请求。"""
    params = f_parseGetParams(request)
    q = str(params.get("q", "") or "").strip()
    page, page_size = _parse_page_params(params, default_page_size=12, max_page_size=100)

    stream_queryset = _recording_stream_queryset(q)
    paginator = Paginator(stream_queryset, page_size)
    current_page = paginator.get_page(page)
    page = current_page.number

    active_recordings = _active_recording_rows()
    plans = list(_recording_plan_queryset(q)[:100])
    stream_map = _recording_stream_map(current_page.object_list, active_recordings, plans)

    active_rows = [_serialize_active_recording_row(row, stream_map) for row in active_recordings]
    active_map = {row["stream_code"]: row for row in active_rows}
    live_keys = _build_live_stream_keys()
    stream_rows = [_serialize_recording_stream_row(row, active_map, live_keys=live_keys) for row in current_page.object_list]
    plan_rows = [_serialize_recording_plan_row(plan, stream_map) for plan in plans]
    storage_root, recording_root = _recording_storage_paths()

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "streams": stream_rows,
                "active_recordings": active_rows,
                "plans": plan_rows,
                "pageData": _build_page_data(paginator=paginator, page=page, page_size=page_size),
                "filters": {"q": q},
                "defaults": {
                    "duration": 60,
                    "format": "mp4",
                    "snapshot_method": "ffmpeg",
                },
                "record_format_choices": [
                    {"code": "mp4", "name": "MP4"},
                    {"code": "flv", "name": "FLV"},
                    {"code": "ts", "name": "TS"},
                ],
                "snapshot_method_choices": [
                    {"code": "ffmpeg", "name": "FFmpeg"},
                    {"code": "opencv", "name": "OpenCV"},
                ],
                "storage": _recording_storage_payload(storage_root, recording_root),
                "summary": _recording_summary(
                    paginator=paginator,
                    stream_queryset=stream_queryset,
                    live_keys=live_keys,
                    active_rows=active_rows,
                    plan_rows=plan_rows,
                ),
            },
        }
    )


def _serialize_license_state(state, *, license_type: str = ""):
    """返回`serialize`授权状态。"""
    if not state:
        return {
            "type": str(license_type or ""),
            "packages": [],
            "package_limits": {},
        }

    packages = api_view._parse_packages_json(getattr(state, "packages_json", "") or "")
    package_limits = api_view._parse_package_limits_json(getattr(state, "package_limits_json", "") or "")
    return {
        "type": str(license_type or ""),
        "license_id": str(getattr(state, "license_id", "") or ""),
        "customer": str(getattr(state, "customer", "") or ""),
        "cluster_id": str(getattr(state, "cluster_id", "") or ""),
        "not_before": getattr(state, "not_before", None),
        "not_after": getattr(state, "not_after", None),
        "max_active_controls": int(getattr(state, "max_active_controls", 0) or 0),
        "max_nodes": int(getattr(state, "max_nodes", 0) or 0),
        "packages": packages,
        "package_limits": package_limits,
        "valid": bool(getattr(state, "valid", False)),
        "last_error_code": str(getattr(state, "last_error_code", "") or ""),
        "last_error_message": str(getattr(state, "last_error_message", "") or ""),
        "create_time": getattr(state, "create_time", None),
        "update_time": getattr(state, "update_time", None),
    }


def _serialize_license_lease_row(lease):
    """返回`serialize`授权`lease`记录。"""
    return {
        "lease_id": str(getattr(lease, "lease_id", "") or ""),
        "node_id": str(getattr(lease, "node_id", "") or ""),
        "stream_code": str(getattr(lease, "stream_code", "") or getattr(lease, "control_code", "") or ""),
        "control_code": str(getattr(lease, "control_code", "") or ""),
        "algorithm_code": str(getattr(lease, "algorithm_code", "") or ""),
        "package": str(getattr(lease, "package", "") or "core"),
        "expires_at": getattr(lease, "expires_at", None),
        "released_at": getattr(lease, "released_at", None),
        "create_time": getattr(lease, "create_time", None),
        "update_time": getattr(lease, "update_time", None),
    }


def _build_license_usage_payload(state):
    """构建授权`usage`载荷。"""
    if not state:
        return {
            "license_id": "",
            "customer": "",
            "cluster_id": "",
            "valid": False,
            "packages": [],
            "package_limits": {},
            "package_usage": {},
            "limits": {
                "max_active_controls": 0,
                "max_nodes": 0,
            },
            "active_controls": 0,
            "active_streams": 0,
            "active_nodes": 0,
            "edition": "",
            "thread_priority_policy": {},
        }

    now = timezone.now()
    not_started = bool(getattr(state, "not_before", None) and now < getattr(state, "not_before", None))
    expired = bool(getattr(state, "not_after", None) and now > getattr(state, "not_after", None))
    packages = api_view._parse_packages_json(getattr(state, "packages_json", "") or "")
    package_limits = api_view._parse_package_limits_json(getattr(state, "package_limits_json", "") or "")
    active_qs = api_view._active_lease_qs(now=now)
    runtime_policy = api_view._get_license_runtime_policy(state)

    return {
        "license_id": getattr(state, "license_id", "") or "",
        "customer": getattr(state, "customer", "") or "",
        "cluster_id": getattr(state, "cluster_id", "") or "",
        "valid": bool(getattr(state, "valid", False)) and (not not_started) and (not expired),
        "not_after": getattr(state, "not_after", None),
        "packages": packages,
        "package_limits": package_limits,
        "package_usage": api_view._get_license_package_usage(active_qs),
        "limits": {
            "max_active_controls": int(getattr(state, "max_active_controls", 0) or 0),
            "max_nodes": int(getattr(state, "max_nodes", 0) or 0),
        },
        "active_controls": active_qs.count(),
        "active_streams": len(api_view._distinct_active_stream_keys(active_qs)),
        "active_nodes": active_qs.values("node_id").distinct().count(),
        "edition": str(runtime_policy.get("edition", "") or ""),
        "thread_priority_policy": runtime_policy.get("thread_priority_policy") if isinstance(runtime_policy, dict) else {},
    }


def _build_license_shell_payload(request, *, top_msg: str = "", current_license_error=None):
    """构建授权`shell`载荷。"""
    license_type = str(getattr(g_config, "licenseType", "community") or "community").strip().lower()
    try:
        api_base_url = request.build_absolute_uri("/").rstrip("/")
    except Exception:
        api_base_url = "//%s" % request.get_host()
    info_source, info, fallback_info, info_message, transport_ok = _fetch_license_info(license_type)
    info = info if isinstance(info, dict) else {}
    fallback_info = fallback_info if isinstance(fallback_info, dict) else {}
    state = LicenseView._latest_state()
    usage = _build_license_usage_payload(state)
    active_leases = list(LicenseLease.objects.filter(released_at__isnull=True).order_by("-update_time", "-id")[:200])
    license_error = current_license_error or LicenseView._persisted_license_error_context(state)

    return {
        "api_base_url": api_base_url,
        "license_type": license_type,
        "top_msg": str(top_msg or ""),
        "info": info or fallback_info,
        "fallback_info": fallback_info,
        "info_source": info_source,
        "transport_ok": transport_ok,
        "transport_message": info_message,
        "state": _serialize_license_state(state, license_type=license_type),
        "usage": usage,
        "leases": [_serialize_license_lease_row(row) for row in active_leases],
        "license_error": license_error,
    }


def api_license(request):
    """处理 `license` 接口请求。"""
    payload = _build_license_shell_payload(request)
    return f_responseJson({"code": 1000, "msg": "success", "data": payload})


def api_notifications(request):
    """处理 `notifications` 接口请求。"""
    db_user = OpsApiKeyView._get_db_user(request)
    if not db_user:
        return f_responseJson({"code": 401, "msg": "unauthorized"})

    items = []
    alarm_item = _build_alarm_notification_item()
    if alarm_item:
        items.append(alarm_item)

    if OpsApiKeyView._is_admin(db_user):
        runtime, _diagnostics = _build_dashboard_runtime()
        analyzer_item = _build_platform_analyzer_notification_item(runtime)
        if analyzer_item:
            items.append(analyzer_item)

        metrics_summary = _build_platform_metrics_summary(request)
        resource_item = _build_platform_resource_notification_item(metrics_summary)
        if resource_item:
            items.append(resource_item)

        license_item = _build_license_notification_item(request)
        if license_item:
            items.append(license_item)

    items.sort(
        key=lambda item: (
            int(item.get("priority", 0) or 0),
            item.get("_created_sort") or timezone.now(),
        ),
        reverse=True,
    )
    for item in items:
        item.pop("_created_sort", None)
        item.pop("priority", None)

    return f_responseJson({"code": 1000, "msg": "success", "data": {"items": items}})


def api_license_upload(request):
    """处理 `license_upload` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN, "data": _build_license_shell_payload(request)})

    top_msg, current_license_error = LicenseView._process_license_upload(request)
    payload = _build_license_shell_payload(request, top_msg=top_msg, current_license_error=current_license_error)
    success = str(top_msg or "").strip() == "导入成功"
    return f_responseJson({"code": 1000 if success else 0, "msg": top_msg or ("success" if success else "导入失败"), "data": payload})


_CONTROL_OSD_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _control_osd_asset_base_url():
    """返回控制OSD`asset`基础URL。"""
    prefix = str(getattr(g_config, "uploadDir_www", DEFAULT_UPLOAD_URL_PREFIX) or DEFAULT_UPLOAD_URL_PREFIX).strip() or DEFAULT_UPLOAD_URL_PREFIX
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


def _control_osd_asset_upload_root():
    """返回控制OSD`asset`上传根目录。"""
    return str(getattr(g_config, "uploadDir", "") or "").strip()


def _control_osd_asset_row_from_rel_path(rel_path: str):
    """从相对路径路径获取控制OSD`asset`记录。"""
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    try:
        clean_rel = validate_upload_rel_path(rel_path, required_prefix="osd/")
        _, ext = os.path.splitext(clean_rel.lower())
        if ext not in _CONTROL_OSD_ASSET_EXTENSIONS:
            return None
        upload_root = _control_osd_asset_upload_root()
        if not upload_root:
            return None
        abs_path = resolve_under_base(upload_root, clean_rel)
        if not os.path.isfile(abs_path):
            return None
        stat = os.stat(abs_path)
    except Exception:
        return None

    return {
        "path": clean_rel,
        "name": os.path.basename(clean_rel),
        "url": f"{_control_osd_asset_base_url()}{clean_rel}",
        "size_bytes": int(getattr(stat, "st_size", 0) or 0),
        "update_time": datetime.fromtimestamp(getattr(stat, "st_mtime", 0) or 0).strftime("%Y-%m-%d %H:%M:%S"),
        "_sort_mtime": float(getattr(stat, "st_mtime", 0) or 0),
    }


def _iter_control_osd_asset_rel_paths(upload_root: str, asset_root: str):
    """遍历控制OSD`asset`相对路径。"""
    for current_root, _dirnames, filenames in os.walk(asset_root):
        for filename in filenames:
            _, ext = os.path.splitext(str(filename or "").lower())
            if ext not in _CONTROL_OSD_ASSET_EXTENSIONS:
                continue
            abs_path = os.path.join(current_root, filename)
            yield os.path.relpath(abs_path, upload_root).replace("\\", "/")


def _clean_control_osd_asset_rows(rows, *, limit: int):
    """清洗控制OSD`asset`记录。"""
    cleaned_rows = []
    seen_paths = set()
    for item in rows:
        clean_path = str(item.get("path") or "")
        if not clean_path or clean_path in seen_paths:
            continue
        seen_paths.add(clean_path)
        cleaned_rows.append(
            {
                "path": clean_path,
                "name": str(item.get("name") or ""),
                "url": str(item.get("url") or ""),
                "size_bytes": int(item.get("size_bytes", 0) or 0),
                "update_time": str(item.get("update_time") or ""),
            }
        )
        if len(cleaned_rows) >= max(1, int(limit or 120)):
            break
    return cleaned_rows


def _list_control_osd_assets(limit: int = 120):
    """处理列表控制OSD`assets`。"""
    upload_root = _control_osd_asset_upload_root()
    if not upload_root or not os.path.isdir(upload_root):
        return []

    asset_root = os.path.join(upload_root, "osd")
    if not os.path.isdir(asset_root):
        return []

    rows = []
    for rel_path in _iter_control_osd_asset_rel_paths(upload_root, asset_root):
        row = _control_osd_asset_row_from_rel_path(rel_path)
        if row:
            rows.append(row)

    rows.sort(key=lambda item: (item.get("_sort_mtime", 0), item.get("path", "")), reverse=True)
    return _clean_control_osd_asset_rows(rows, limit=limit)


def _build_control_osd_assets_payload():
    """构建控制OSD`assets`载荷。"""
    return {
        "rows": _list_control_osd_assets(),
        "base_url": _control_osd_asset_base_url(),
        "accept": [ext.lstrip(".") for ext in sorted(_CONTROL_OSD_ASSET_EXTENSIONS)],
    }


def api_control_osd_assets(request):
    """处理 `control_osd_assets` 接口请求。"""
    return f_responseJson({"code": 1000, "msg": "success", "data": _build_control_osd_assets_payload()})


def api_control_osd_assets_upload(request):
    """处理 `control_osd_assets_upload` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN, "data": _build_control_osd_assets_payload()})

    file_obj = request.FILES.get("file")
    if not file_obj:
        return f_responseJson({"code": 0, "msg": "请先选择图片文件", "data": _build_control_osd_assets_payload()})

    upload_root = _control_osd_asset_upload_root()
    if not upload_root:
        return f_responseJson({"code": 0, "msg": "上传目录未配置", "data": _build_control_osd_assets_payload()})

    original_name = str(getattr(file_obj, "name", "") or "").strip()
    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    if ext not in _CONTROL_OSD_ASSET_EXTENSIONS:
        return f_responseJson({"code": 0, "msg": "仅支持 png / jpg / jpeg / webp 图片", "data": _build_control_osd_assets_payload()})

    content_type = str(getattr(file_obj, "content_type", "") or "").strip().lower()
    if content_type and not content_type.startswith("image/"):
        return f_responseJson({"code": 0, "msg": "上传文件必须是图片", "data": _build_control_osd_assets_payload()})

    from app.utils.Security import resolve_under_base

    try:
        now = datetime.now()
        date_prefix = now.strftime("%Y%m%d")
        rel_dir = f"osd/{date_prefix}"
        abs_dir = resolve_under_base(upload_root, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        rel_path = f"{rel_dir}/{now.strftime('%H%M%S')}_{gen_random_code_s(8)}{ext}"
        abs_path = resolve_under_base(upload_root, rel_path)
        with open(abs_path, "wb") as handle:
            for chunk in file_obj.chunks():
                handle.write(chunk)
        asset = _control_osd_asset_row_from_rel_path(rel_path)
    except Exception as exc:
        return f_responseJson({"code": 0, "msg": str(exc or "贴图上传失败"), "data": _build_control_osd_assets_payload()})

    payload = _build_control_osd_assets_payload()
    payload["asset"] = asset
    return f_responseJson({"code": 1000, "msg": "贴图上传成功", "data": payload})


def _serialize_control_log_row(row):
    """返回`serialize`控制`log`记录。"""
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "control_code": str(getattr(row, "control_code", "") or ""),
        "action": str(getattr(row, "action", "") or ""),
        "result_code": int(getattr(row, "result_code", 0) or 0),
        "result_msg": str(getattr(row, "result_msg", "") or ""),
        "operator": str(getattr(row, "operator", "") or ""),
        "detail": str(getattr(row, "detail", "") or ""),
        "create_time": getattr(row, "create_time", None).strftime("%Y-%m-%d %H:%M:%S")
        if getattr(row, "create_time", None)
        else "",
    }


def api_control_logs(request):
    """处理 `control_logs` 接口请求。"""
    params = f_parseGetParams(request)
    page = ControlLogView._control_log_int(params.get("p", 1), 1, min_value=1)
    page_size = ControlLogView._control_log_int(params.get("ps", 20), 20, min_value=1, max_value=100)
    filters = ControlLogView._control_log_filters(params)
    queryset = ControlLogView._control_log_filtered_queryset(filters)
    paginator = ControlLogView.Paginator(queryset, page_size)
    current_page, page = ControlLogView._control_log_paginate(paginator, page)

    rows = [_serialize_control_log_row(row) for row in current_page.object_list]
    stats = {
        "filtered_total": int(paginator.count),
        "success_total": int(queryset.filter(result_code=1000).count()),
        "failure_total": int(queryset.exclude(result_code=1000).count()),
    }

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": rows,
                "pageData": {
                    "page": page,
                    "page_size": page_size,
                    "page_num": paginator.num_pages,
                    "count": paginator.count,
                    "pageLabels": ControlLogView.buildPageLabels(page=page, page_num=paginator.num_pages),
                },
                "filters": filters,
                "stats": stats,
                "actions": [
                    {"code": "", "name": "全部"},
                    {"code": "start", "name": "启动"},
                    {"code": "stop", "name": "停止"},
                    {"code": "batch_start", "name": "批量启动"},
                    {"code": "batch_stop", "name": "批量停止"},
                    {"code": "copy", "name": "复制"},
                    {"code": "delete", "name": "删除"},
                ],
                "resultChoices": [
                    {"code": "", "name": "全部"},
                    {"code": "1000", "name": "成功"},
                    {"code": "0", "name": "失败"},
                ],
            },
        }
    )


def _split_csv_items(value):
    """拆分CSV条目。"""
    rows = []
    seen = set()
    for item in str(value or "").split(","):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _control_editor_default_control():
    """处理控制`editor`默认控制。"""
    return {
        "code": gen_random_code_s("control"),
        "stream_app": "",
        "stream_name": "",
        "stream_video": "",
        "stream_audio": "",
        "object_code": "",
        "push_stream": True,
        "polygon": "",
        "min_interval": 180,
        "decode_stride": 1,
        "class_thresh": 0.5,
        "overlap_thresh": 0.5,
        "remark": "",
        "alarm_sound_id": 0,
        "alarm_video_type": "mp4",
        "alarm_image_count": 3,
        "alarm_image_draw_mode": "boxed",
        "force_frame_alarm": False,
        "alarm_cover_position": "back",
        "alarm_cover_custom_index": 0,
        "use_pipeline_mode": False,
        "algorithm_pipeline_mode": 1,
        "enable_hw_decode": False,
        "enable_hw_encode": False,
        "draw_type": "polygon",
        "line_coordinates": "",
        "line_violation_direction": "both",
        "enable_tracking": False,
        "tracking_config": "{}",
        "classification_algorithm_code": "",
        "classification_config": "{}",
        "feature_algorithm_code": "",
        "feature_config": "{}",
        "behavior_algorithm_code": "",
        "behavior_api_url": "",
        "behavior_config": "{}",
        "analysis_prompt": "",
        "enable_hierarchical_algorithm": False,
        "secondary_algorithm_code": "",
        "secondary_api_url": "",
        "secondary_conf_thresh": 0.25,
        "osd_enabled": False,
        "osd_text": "",
        "osd_position": "top-left",
        "osd_x": 10,
        "osd_y": 30,
        "osd_font_size": 24,
        "osd_font_color": DEFAULT_OSD_FONT_COLOR,
        "osd_bg_enabled": True,
        "osd_image_path": "",
        "osd_image_x": 10,
        "osd_image_y": 10,
        "osd_image_scale": 1.0,
        "osd_image_alpha": 1.0,
        "osd_algo_x": 20,
        "osd_algo_y": 80,
        "osd_fps_x": 20,
        "osd_fps_y": 140,
        "osd_font_thickness": 2,
    }


def _control_editor_stream_code(stream_app: str, stream_name: str, fallback: str = ""):
    """处理控制`editor`流编码。"""
    app = str(stream_app or "").strip()
    name = str(stream_name or "").strip()
    if fallback:
        return str(fallback)
    stream = Stream.objects.filter(app=app, name=name).first()
    if stream and getattr(stream, "code", ""):
        return str(stream.code)
    if app and name:
        return f"{app}_{name}"
    return name or app or ""


def _serialize_control_editor_stream(row):
    """处理`serialize`控制`editor`流。"""
    item = row if isinstance(row, dict) else {}
    app = str(item.get("app") or "").strip()
    name = str(item.get("name") or "").strip()
    return {
        "code": _control_editor_stream_code(app, name, fallback=str(item.get("code") or "").strip()),
        "app": app,
        "name": name,
        "video": str(item.get("video") or "").strip(),
        "audio": str(item.get("audio") or "").strip(),
        "display_name": f"{app}/{name}" if app and name else str(item.get("code") or "").strip(),
        "ws_mp4_url": str(item.get("wsMp4Url") or "").strip(),
        "http_flv_url": str(item.get("httpFlvUrl") or "").strip(),
    }


def _serialize_control_editor_algorithm(algorithm):
    """处理`serialize`控制`editor`算法。"""
    return {
        "code": str(getattr(algorithm, "code", "") or ""),
        "name": str(getattr(algorithm, "name", "") or ""),
        "basic_source": str(getattr(algorithm, "basic_source", "") or ""),
        "api_url": str(getattr(algorithm, "api_url", "") or ""),
        "object_options": _split_csv_items(getattr(algorithm, "object_str", "") or ""),
        "object_str": str(getattr(algorithm, "object_str", "") or ""),
        "algorithm_subtype": str(getattr(algorithm, "algorithm_subtype", "") or ""),
        "algorithm_type": int(getattr(algorithm, "algorithm_type", 0) or 0),
        "support_direct_api": bool(getattr(algorithm, "support_direct_api", False)),
        "builtin_behavior": str(getattr(algorithm, "builtin_behavior", "") or ""),
    }


def _serialize_control_editor_alarm_sound(sound):
    """处理`serialize`控制`editor`告警`sound`。"""
    return {
        "id": int(getattr(sound, "id", 0) or 0),
        "name": str(getattr(sound, "name", "") or ""),
        "file_path": str(getattr(sound, "file_path", "") or ""),
        "is_default": bool(getattr(sound, "is_default", False)),
    }


def _control_attr_str(control, name: str, default: str = "") -> str:
    """读取控制文本属性。"""
    return str(getattr(control, name, default) or default)


def _control_attr_int(control, name: str, default: int = 0) -> int:
    """读取控制整数属性。"""
    return int(getattr(control, name, default) or default)


def _control_attr_float(control, name: str, default: float = 0.0) -> float:
    """读取控制浮点属性。"""
    return _safe_float(getattr(control, name, default), default)


def _control_attr_bool(control, name: str, default: bool = False) -> bool:
    """读取控制布尔属性。"""
    return bool(getattr(control, name, default))


def _serialize_control_editor_control(control):
    """处理`serialize`控制`editor`控制。"""
    if not control:
        return _control_editor_default_control()
    return {
        "code": _control_attr_str(control, "code"),
        "stream_app": _control_attr_str(control, "stream_app"),
        "stream_name": _control_attr_str(control, "stream_name"),
        "stream_video": _control_attr_str(control, "stream_video"),
        "stream_audio": _control_attr_str(control, "stream_audio"),
        "object_code": _control_attr_str(control, "object_code"),
        "push_stream": _control_attr_bool(control, "push_stream"),
        "polygon": _control_attr_str(control, "polygon"),
        "min_interval": _control_attr_int(control, "min_interval", 180),
        "decode_stride": _control_attr_int(control, "decode_stride", 1),
        "class_thresh": _control_attr_float(control, "class_thresh", 0.5),
        "overlap_thresh": _control_attr_float(control, "overlap_thresh", 0.5),
        "remark": _control_attr_str(control, "remark"),
        "alarm_sound_id": _control_attr_int(control, "alarm_sound_id"),
        "alarm_video_type": _control_attr_str(control, "alarm_video_type", "mp4"),
        "alarm_image_count": _control_attr_int(control, "alarm_image_count", 3),
        "alarm_image_draw_mode": _control_attr_str(control, "alarm_image_draw_mode", "boxed"),
        "force_frame_alarm": _control_attr_bool(control, "force_frame_alarm"),
        "alarm_cover_position": _control_attr_str(control, "alarm_cover_position", "front"),
        "alarm_cover_custom_index": _control_attr_int(control, "alarm_cover_custom_index"),
        "use_pipeline_mode": _control_attr_bool(control, "use_pipeline_mode"),
        "algorithm_pipeline_mode": _control_attr_int(control, "algorithm_pipeline_mode", 1),
        "enable_hw_decode": _control_attr_bool(control, "enable_hw_decode"),
        "enable_hw_encode": _control_attr_bool(control, "enable_hw_encode"),
        "draw_type": _control_attr_str(control, "draw_type", "polygon"),
        "line_coordinates": _control_attr_str(control, "line_coordinates"),
        "line_violation_direction": _control_attr_str(control, "line_violation_direction", "both"),
        "enable_tracking": _control_attr_bool(control, "enable_tracking"),
        "tracking_config": _control_attr_str(control, "tracking_config", "{}"),
        "classification_algorithm_code": _control_attr_str(control, "classification_algorithm_code"),
        "classification_config": _control_attr_str(control, "classification_config", "{}"),
        "feature_algorithm_code": _control_attr_str(control, "feature_algorithm_code"),
        "feature_config": _control_attr_str(control, "feature_config", "{}"),
        "behavior_algorithm_code": _control_attr_str(control, "behavior_algorithm_code"),
        "behavior_api_url": _control_attr_str(control, "behavior_api_url"),
        "behavior_config": _control_attr_str(control, "behavior_config", "{}"),
        "analysis_prompt": _control_attr_str(control, "analysis_prompt"),
        "enable_hierarchical_algorithm": _control_attr_bool(control, "enable_hierarchical_algorithm"),
        "secondary_algorithm_code": _control_attr_str(control, "secondary_algorithm_code"),
        "secondary_api_url": _control_attr_str(control, "secondary_api_url"),
        "secondary_conf_thresh": _control_attr_float(control, "secondary_conf_thresh", 0.25),
        "osd_enabled": _control_attr_bool(control, "osd_enabled"),
        "osd_text": _control_attr_str(control, "osd_text"),
        "osd_position": _control_attr_str(control, "osd_position", "top-left"),
        "osd_x": _control_attr_int(control, "osd_x", 10),
        "osd_y": _control_attr_int(control, "osd_y", 30),
        "osd_font_size": _control_attr_int(control, "osd_font_size", 24),
        "osd_font_color": _control_attr_str(control, "osd_font_color", DEFAULT_OSD_FONT_COLOR),
        "osd_bg_enabled": _control_attr_bool(control, "osd_bg_enabled", True),
        "osd_image_path": _control_attr_str(control, "osd_image_path"),
        "osd_image_x": _control_attr_int(control, "osd_image_x", 10),
        "osd_image_y": _control_attr_int(control, "osd_image_y", 10),
        "osd_image_scale": _control_attr_float(control, "osd_image_scale", 1.0),
        "osd_image_alpha": _control_attr_float(control, "osd_image_alpha", 1.0),
        "osd_algo_x": _control_attr_int(control, "osd_algo_x", 20),
        "osd_algo_y": _control_attr_int(control, "osd_algo_y", 80),
        "osd_fps_x": _control_attr_int(control, "osd_fps_x", 20),
        "osd_fps_y": _control_attr_int(control, "osd_fps_y", 140),
        "osd_font_thickness": _control_attr_int(control, "osd_font_thickness", 2),
    }


def _control_editor_algorithms():
    """返回控制编辑算法列表。"""
    return [
        _serialize_control_editor_algorithm(item)
        for item in AlgorithmModel.objects.filter(state__gte=0).order_by("sort", "id")
    ]


def _control_editor_alarm_sounds():
    """返回控制编辑告警声音列表。"""
    return [
        _serialize_control_editor_alarm_sound(item)
        for item in AlarmSound.objects.filter(state=1).order_by("-is_default", "-id")
    ]


def _control_editor_streams_for_add():
    """返回新增模式下的流列表。"""
    try:
        return [_serialize_control_editor_stream(item) for item in api_view.g_zlm.getMediaList() or []]
    except Exception:
        return []


def _control_editor_add_payload(*, algorithms, alarm_sounds):
    """构建控制编辑新增载荷。"""
    return {
        "mode": "add",
        "control": _control_editor_default_control(),
        "streams": _control_editor_streams_for_add(),
        "algorithms": algorithms,
        "alarm_sounds": alarm_sounds,
        "object_options": [],
        "osd_assets": _list_control_osd_assets(),
        "osd_asset_base_url": _control_osd_asset_base_url(),
        "control_algorithm_base": "",
        "control_algorithm_device": "CPU",
        "stream_preview": {
            "stream_code": "",
            "ws_mp4_url": "",
            "http_flv_url": "",
        },
    }


def _control_editor_object_options(control, base_code: str):
    """返回控制编辑目标选项。"""
    object_options = list(ControlView._resolve_algorithm_object_str_list(base_code) or [])
    current_object = str(getattr(control, "object_code", "") or "").strip()
    if current_object and current_object not in object_options:
        object_options.append(current_object)
    return object_options


def _control_editor_stream_preview(request, control):
    """构建控制编辑流预览。"""
    public_host = get_public_host_for_urls(request)
    try:
        ws_mp4_url = api_view.g_zlm.get_wsMp4Url(control.stream_app, control.stream_name, public_host)
    except Exception:
        ws_mp4_url = ""
    try:
        http_flv_url = api_view.g_zlm.get_httpFlvUrl(control.stream_app, control.stream_name, public_host)
    except Exception:
        http_flv_url = ""
    return {
        "stream_code": _control_editor_stream_code(control.stream_app, control.stream_name),
        "app": str(getattr(control, "stream_app", "") or ""),
        "name": str(getattr(control, "stream_name", "") or ""),
        "ws_mp4_url": str(ws_mp4_url or ""),
        "http_flv_url": str(http_flv_url or ""),
    }


def _build_control_editor_payload(request, control_code: str = ""):
    """构建控制`editor`载荷。"""
    algorithms = _control_editor_algorithms()
    alarm_sounds = _control_editor_alarm_sounds()

    code = str(control_code or "").strip()
    if not code:
        return _control_editor_add_payload(algorithms=algorithms, alarm_sounds=alarm_sounds), ""

    control = Control.objects.filter(code=code).first()
    if not control:
        return None, "该布控不存在或已被删除"

    base_code, device = ControlView._split_algorithm_code(getattr(control, "algorithm_code", "") or "")
    tracking_base, tracking_device, tracking_device_id = ControlView._split_tracking_algorithm_for_ui(
        getattr(control, "tracking_algorithm_code", "") or ""
    )

    return {
        "mode": "edit",
        "control": _serialize_control_editor_control(control),
        "streams": [],
        "algorithms": algorithms,
        "alarm_sounds": alarm_sounds,
        "object_options": _control_editor_object_options(control, base_code),
        "osd_assets": _list_control_osd_assets(),
        "osd_asset_base_url": _control_osd_asset_base_url(),
        "control_algorithm_base": base_code,
        "control_algorithm_device": device,
        "control_tracking_base": tracking_base,
        "control_tracking_device": tracking_device,
        "control_tracking_device_id": tracking_device_id,
        "stream_preview": _control_editor_stream_preview(request, control),
    }, ""


def api_control_editor(request):
    """处理 `control_editor` 接口请求。"""
    params = f_parseGetParams(request)
    payload, error_message = _build_control_editor_payload(request, control_code=params.get("code"))
    if payload is None:
        return f_responseJson({"code": 0, "msg": error_message or "读取布控编辑数据失败", "data": {}})
    return f_responseJson({"code": 1000, "msg": "success", "data": payload})


def _serialize_stream_row(row):
    """返回`serialize`流记录。"""
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "code": str(getattr(row, "code", "") or ""),
        "app": str(getattr(row, "app", "") or ""),
        "name": str(getattr(row, "name", "") or ""),
        "nickname": str(getattr(row, "nickname", "") or ""),
        "site_label": str(getattr(row, "site_label", "") or ""),
        "floor_label": str(getattr(row, "floor_label", "") or ""),
        "pull_stream_url": str(getattr(row, "pull_stream_url", "") or ""),
        "pull_stream_type": int(getattr(row, "pull_stream_type", 1) or 1),
        "forward_state": int(getattr(row, "forward_state", 0) or 0),
        "state": int(getattr(row, "state", 0) or 0),
        "remark": str(getattr(row, "remark", "") or ""),
        "last_update_time": getattr(row, "last_update_time", None),
    }


def _build_live_stream_keys() -> set:
    """构建`live`流键列表。"""
    try:
        _top_msg, rows = StreamView.build_online_stream_app_shell_payload()
    except Exception:
        return set()

    keys = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        app = str(row.get("app") or "").strip()
        name = str(row.get("name") or "").strip()
        if app and name:
            keys.add((app, name))
    return keys


def _stream_is_online(row, *, live_keys=None) -> bool:
    """处理流`is`在线。"""
    app = str(getattr(row, "app", "") or "").strip()
    name = str(getattr(row, "name", "") or "").strip()
    if live_keys and (app, name) in live_keys:
        return True
    return bool(int(getattr(row, "state", 0) or 0) == 1 or int(getattr(row, "forward_state", 0) or 0) == 1)


def api_streams(request):
    """处理 `streams` 接口请求。"""
    params = f_parseGetParams(request)
    filter_app = str(params.get("app", "") or "").strip()
    filter_site = str(params.get("site", "") or "").strip()
    q = str(params.get("q", "") or "").strip()
    app_choices, site_choices = StreamView._build_stream_index_choices()
    page, page_size = StreamView._parse_stream_index_pagination(params)

    queryset = StreamView._apply_stream_index_filters(
        Stream.objects.all().order_by("-id"),
        filter_app=filter_app,
        filter_site=filter_site,
        q=q,
    )
    live_keys = _build_live_stream_keys()
    stats = {
        "total": int(queryset.count()),
        "online": sum(1 for item in queryset if _stream_is_online(item, live_keys=live_keys)),
        "forwarding": int(queryset.filter(forward_state=1).count()),
    }
    current_page, paginator, page = StreamView._paginate_stream_index(queryset, page=page, page_size=page_size)

    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": StreamView.buildPageLabels(page=page, page_num=paginator.num_pages),
    }

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": [_serialize_stream_row(row) for row in current_page.object_list],
                "pageData": page_data,
                "filters": {
                    "app": filter_app,
                    "site": filter_site,
                    "q": q,
                },
                "stats": stats,
                "appChoices": list(app_choices or []),
                "siteChoices": list(site_choices or []),
            },
        }
    )


def _workflow_tone(workflow_status: str) -> str:
    """处理`workflow``tone`。"""
    status = str(workflow_status or "").strip().lower()
    if status in ("new",):
        return "critical"
    if status in ("acknowledged",):
        return "warning"
    if status in ("reviewing",):
        return "accent"
    if status in ("closed", "resolved"):
        return "stable"
    return "muted"


def _serialize_alarm_rows(items, *, review_mode: bool, review_tab: str, filter_params: dict):
    """返回`serialize`告警记录。"""
    control_codes = [item.get("control_code") for item in items]
    controls, sound_map = AlarmView._alarm_index_control_sound_maps(control_codes)

    rows = []
    for item in items:
        control = controls.get(item.get("control_code"))
        sound_url = AlarmView._alarm_index_sound_url(control, sound_map)
        image_path = item.get("image_path") or ""
        video_path = item.get("video_path") or ""
        metadata_obj = AlarmView._parse_alarm_metadata_obj(item.get("metadata"))
        extra_images = AlarmView._parse_alarm_extra_images(item.get("extra_images"))
        image_url = AlarmView._resolve_alarm_preview_image_url(
            image_path,
            metadata_obj=metadata_obj,
            extra_images=extra_images,
        )
        video_url = AlarmView._alarm_existing_media_url(video_path)
        rows.append(
            {
                "id": int(item["id"]),
                "desc": str(item.get("desc") or ""),
                "create_time": item.get("create_time"),
                "state": int(item.get("state") or 0),
                "workflow_status": str(item.get("workflow_status") or ""),
                "workflow_tone": _workflow_tone(item.get("workflow_status")),
                "handled": bool(item.get("handled")),
                "handled_time": item.get("handled_time"),
                "handled_by": str(item.get("handled_by") or ""),
                "handled_remark": str(item.get("handled_remark") or ""),
                "stream_code": str(item.get("stream_code") or ""),
                "stream_app": str(item.get("stream_app") or ""),
                "stream_name": str(item.get("stream_name") or ""),
                "control_code": str(item.get("control_code") or ""),
                "algorithm_code": str(item.get("algorithm_code") or ""),
                "assigned_to": str(item.get("assigned_to") or ""),
                "has_image": bool(image_url),
                "has_video": bool(video_url),
                "image_url": image_url,
                "video_url": video_url,
                "sound_url": sound_url,
                "detail_url": AlarmView._build_alarm_detail_url(
                    item["id"],
                    review_mode=review_mode,
                    review_tab=review_tab,
                    filter_params=filter_params,
                ),
            }
        )
    return rows


def _build_alarm_presets_payload(request, *, target_mode: str, current_filter_params: dict, review_tab: str):
    """构建告警`presets`载荷。"""
    mode = AlarmView._normalize_alarm_preset_target_mode(target_mode)
    normalized_review_tab = AlarmView._normalize_alarm_review_tab(review_tab) if mode == "review" else ""
    return {
        "target_mode": mode,
        "current_filters": dict(current_filter_params or {}),
        "review_tab": normalized_review_tab,
        "default_visibility": AlarmView.ALARM_PRESET_VISIBILITY_PRIVATE,
        "visibility_options": list(AlarmView.ALARM_PRESET_VISIBILITY_OPTIONS),
        "permission_options": AlarmView._alarm_index_permission_options(),
        "items": AlarmView._build_alarm_preset_items(
            request,
            target_mode=mode,
            current_filter_params=current_filter_params,
            review_tab=normalized_review_tab,
        ),
    }


def _save_alarm_preset_from_params(*, user_id: int, username: str, params):
    """保存告警预设`from`参数。"""
    name = str(params.get("name") or "").strip()
    target_mode = AlarmView._normalize_alarm_preset_target_mode(params.get("target_mode"))
    filters = AlarmView.parse_alarm_filters(params)
    filter_payload = AlarmView._build_alarm_filter_params(filters)
    review_tab = AlarmView._normalize_alarm_review_tab(params.get("review_tab")) if target_mode == "review" else ""
    visibility_scope = AlarmView._parse_alarm_preset_visibility_scope(params.get("visibility_scope"))
    share_permission_key = AlarmView._normalize_alarm_preset_share_key(
        params.get("share_permission_key"),
        visibility_scope=visibility_scope,
    )

    if not name:
        return None, "请先输入筛选视图名称", target_mode, filter_payload, review_tab

    try:
        max_name_len = int(getattr(AlarmFilterPreset._meta.get_field("name"), "max_length", 0) or 0)
    except Exception:
        max_name_len = 100
    if max_name_len > 0 and len(name) > max_name_len:
        return None, "筛选视图名称过长", target_mode, filter_payload, review_tab

    if not visibility_scope:
        return None, "共享范围无效", target_mode, filter_payload, review_tab
    if visibility_scope == AlarmView.ALARM_PRESET_VISIBILITY_PERMISSION and not share_permission_key:
        return None, "共享权限标识无效", target_mode, filter_payload, review_tab

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
    return preset, "", target_mode, filter_payload, review_tab


def api_alarm_presets_save(request):
    """处理 `alarm_presets_save` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    user_id, username = AlarmView._get_alarm_preset_actor(request)
    if user_id <= 0:
        return f_responseJson({"code": 403, "msg": "请先登录", "data": {}})

    params = f_parsePostParams(request)
    preset, error_message, target_mode, filter_payload, review_tab = _save_alarm_preset_from_params(
        user_id=user_id,
        username=username,
        params=params,
    )
    fallback = AlarmView._build_alarm_list_url(
        target_mode=target_mode,
        filter_params=filter_payload,
        review_tab=review_tab,
    )
    redirect_target = AlarmView._safe_alarm_redirect_target(params.get("redirect_to"), fallback=fallback)
    if str(params.get("redirect_to") or "").strip():
        return redirect(redirect_target)

    presets_payload = _build_alarm_presets_payload(
        request,
        target_mode=target_mode,
        current_filter_params=filter_payload,
        review_tab=review_tab,
    )
    if preset is None:
        return f_responseJson({"code": 0, "msg": error_message, "data": {"presets": presets_payload}})

    preset_item = next((item for item in presets_payload["items"] if int(item.get("id", 0) or 0) == int(preset.id)), None)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "保存成功",
            "data": {
                "preset": preset_item or {
                    "id": int(preset.id),
                    "name": str(preset.name or ""),
                    "is_active": True,
                    "is_owned": True,
                },
                "presets": presets_payload,
            },
        }
    )


def api_alarm_presets_delete(request):
    """处理 `alarm_presets_delete` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    user_id, _username = AlarmView._get_alarm_preset_actor(request)
    if user_id <= 0:
        return f_responseJson({"code": 403, "msg": "请先登录", "data": {}})

    params = f_parsePostParams(request)
    target_mode = AlarmView._normalize_alarm_preset_target_mode(params.get("target_mode"))
    filters = AlarmView.parse_alarm_filters(params)
    filter_payload = AlarmView._build_alarm_filter_params(filters)
    review_tab = AlarmView._normalize_alarm_review_tab(params.get("review_tab")) if target_mode == "review" else ""
    fallback = AlarmView._build_alarm_list_url(
        target_mode=target_mode,
        filter_params=filter_payload,
        review_tab=review_tab,
    )
    redirect_target = AlarmView._safe_alarm_redirect_target(params.get("redirect_to"), fallback=fallback)

    try:
        preset_id = int(str(params.get("preset_id") or "0").strip())
    except Exception:
        preset_id = 0
    deleted_preset_id = 0
    if preset_id > 0:
        deleted_count, _details = AlarmFilterPreset.objects.filter(id=preset_id, owner_user_id=user_id).delete()
        if deleted_count > 0:
            deleted_preset_id = preset_id

    if str(params.get("redirect_to") or "").strip():
        return redirect(redirect_target)

    presets_payload = _build_alarm_presets_payload(
        request,
        target_mode=target_mode,
        current_filter_params=filter_payload,
        review_tab=review_tab,
    )
    return f_responseJson(
        {
            "code": 1000,
            "msg": "删除成功" if deleted_preset_id else "未删除任何筛选视图",
            "data": {
                "deleted_preset_id": deleted_preset_id,
                "presets": presets_payload,
            },
        }
    )


def api_alarm_detail(request):
    """处理 `alarm_detail` 接口请求。"""
    _alarm, payload = AlarmView.build_alarm_detail_payload(request)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": payload,
        }
    )


def api_alarms(request):
    """处理 `alarms` 接口请求。"""
    params = f_parseGetParams(request)
    review_mode = str(params.get("mode", "") or "").strip().lower() == "review"
    filters = AlarmView.parse_alarm_filters(params)
    review_tab = AlarmView._normalize_alarm_review_tab(params.get("review_tab")) if review_mode else ""
    filter_params = AlarmView._build_alarm_filter_params(filters)
    page, page_size = AlarmView._alarm_index_page_and_size(params)

    base_qs = AlarmView.apply_alarm_filters(Alarm.objects.all(), filters)
    base_qs, semantic_search = AlarmView._apply_alarm_semantic_search(base_qs, filters.get("semantic_query", ""))
    qs, review_counts = AlarmView._apply_alarm_review_mode(base_qs, review_mode=review_mode, review_tab=review_tab)

    queryset = qs.order_by("-id").values(
        "id",
        "image_path",
        "video_path",
        "metadata",
        "extra_images",
        "desc",
        "create_time",
        "state",
        "workflow_status",
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
        "assigned_to",
    )
    current_page, paginator, page = AlarmView._paginate_alarm_queryset(queryset, page=page, page_size=page_size)
    rows = _serialize_alarm_rows(
        current_page.object_list,
        review_mode=review_mode,
        review_tab=review_tab,
        filter_params=filter_params,
    )

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": rows,
                "total": paginator.count,
                "page": page,
                "page_size": page_size,
                "page_num": paginator.num_pages,
                "review_mode": review_mode,
                "review_tab": review_tab,
                "review_counts": review_counts,
                "filters": filter_params,
                "semantic_search": semantic_search,
                "presets": _build_alarm_presets_payload(
                    request,
                    target_mode="review" if review_mode else "list",
                    current_filter_params=filter_params,
                    review_tab=review_tab,
                ),
            },
        }
    )


def _serialize_algorithm_row(algo):
    """返回`serialize`算法记录。"""
    loaded_variants = list(getattr(algo, "analyzer_loaded_variants", []) or [])
    loaded_devices = list(getattr(algo, "analyzer_loaded_devices", []) or [])
    return {
        "id": int(getattr(algo, "id", 0) or 0),
        "code": str(getattr(algo, "code", "") or ""),
        "name": str(getattr(algo, "name", "") or ""),
        "algorithm_type": int(getattr(algo, "algorithm_type", 0) or 0),
        "algorithm_subtype": str(getattr(algo, "algorithm_subtype", "") or ""),
        "basic_source": str(getattr(algo, "basic_source", "") or ""),
        "builtin_behavior": str(getattr(algo, "builtin_behavior", "") or ""),
        "state": int(getattr(algo, "state", 0) or 0),
        "license_package": str(getattr(algo, "license_package", "") or ""),
        "loaded_variants": loaded_variants,
        "loaded_devices": loaded_devices,
        "analyzer_ref_count": int(getattr(algo, "analyzer_ref_count", 0) or 0),
    }


def api_algorithms(request):
    """处理 `algorithms` 接口请求。"""
    params = f_parseGetParams(request)
    page, page_size = Algorithm._algorithm_index_pagination_params(params)
    queryset = AlgorithmModel.objects.all().order_by("-id")
    paginator, current_page, page = Algorithm._algorithm_index_paginate(queryset, page, page_size)
    data = list(current_page.object_list)

    analyzer_state, analyzer_msg, analyzer_by_code = Algorithm._algorithm_index_analyzer_lookup()
    Algorithm._algorithm_index_apply_analyzer_summary(data, analyzer_by_code)

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "rows": [_serialize_algorithm_row(algo) for algo in data],
                "page": page,
                "page_size": page_size,
                "page_num": paginator.num_pages,
                "total": paginator.count,
                "analyzer_state": bool(analyzer_state),
                "analyzer_msg": analyzer_msg,
            },
        }
    )


def api_screen(request):
    """处理 `screen` 接口请求。"""
    rows = _build_birdseye_streams()
    return f_responseJson({"code": 1000, "msg": "success", "data": {"rows": rows, "total": len(rows)}})


def _face_tracking_algorithms():
    """返回人脸跟踪算法列表。"""
    try:
        return list(
            AlgorithmModel.objects.filter(
                state__gte=0,
                algorithm_subtype="tracking",
            ).order_by("sort", "id")
        )
    except Exception:
        return []


def _default_feature_algorithm_code() -> str:
    """返回默认特征算法编码。"""
    return str(
        get_value(
            "faceDefaultFeatureAlgorithmCode",
            getattr(g_config, "faceDefaultFeatureAlgorithmCode", ""),
        )
        or ""
    ).strip()


def _feature_algorithm_label(algorithms, default_code: str) -> str:
    """返回默认特征算法标签。"""
    for algorithm in algorithms:
        algorithm_code = str(getattr(algorithm, "code", "") or "").strip()
        if algorithm_code != default_code:
            continue
        algorithm_name = str(getattr(algorithm, "name", "") or "").strip()
        return "%s - %s" % (algorithm_code, algorithm_name) if algorithm_name else default_code
    return default_code


def _face_db_payload():
    """返回人脸库载荷。"""
    try:
        ok, msg, data = api_view.g_analyzer.face_list()
        if ok:
            return data or {}, ""
        return {}, str(msg or "face_list failed")
    except Exception as exc:
        return {}, str(exc)


def api_faces(request):
    """处理 `faces` 接口请求。"""
    tracking_algorithms = _face_tracking_algorithms()
    default_feature_algorithm_code = _default_feature_algorithm_code()
    face_db, face_db_error = _face_db_payload()

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "tracking_algorithms": [
                    {
                        "code": str(getattr(algorithm, "code", "") or ""),
                        "name": str(getattr(algorithm, "name", "") or ""),
                    }
                    for algorithm in tracking_algorithms
                ],
                "default_feature_algorithm_code": default_feature_algorithm_code,
                "default_feature_algorithm_label": _feature_algorithm_label(tracking_algorithms, default_feature_algorithm_code),
                "has_default_feature_algorithm": bool(default_feature_algorithm_code),
                "face_db": face_db,
                "face_db_error": face_db_error,
            },
        }
    )


def api_developer(request):
    """处理 `developer` 接口请求。"""
    try:
        api_base_url = request.build_absolute_uri("/").rstrip("/")
    except Exception:
        api_base_url = "//%s" % request.get_host()

    active_streams = []
    try:
        controls = Control.objects.filter(state=1).order_by("sort", "id")
        for control in controls:
            stream = Stream.objects.filter(app=control.stream_app, name=control.stream_name).first()
            if not stream:
                continue
            active_streams.append(
                {
                    "control_code": control.code,
                    "stream_code": stream.code,
                    "stream_app": stream.app,
                    "stream_name": stream.name,
                    "rtsp_url": stream.pull_stream_url,
                    "algorithm_code": control.algorithm_code,
                    "object_code": control.object_code,
                    "polygon": control.polygon,
                    "min_interval": control.min_interval,
                    "class_thresh": control.class_thresh,
                    "overlap_thresh": control.overlap_thresh,
                }
            )
    except Exception:
        active_streams = []

    type_names = {
        0: "基础算法",
        1: "行为算法",
        2: "业务算法",
    }
    algorithms = []
    try:
        queryset = AlgorithmModel.objects.filter(state__gte=0).order_by("sort", "id")
        for algorithm in queryset:
            try:
                algo_type = int(getattr(algorithm, "algorithm_type", 0) or 0)
            except Exception:
                algo_type = 0
            algorithms.append(
                {
                    "code": getattr(algorithm, "code", ""),
                    "name": getattr(algorithm, "name", ""),
                    "type": getattr(algorithm, "algorithm_type", 0),
                    "type_name": type_names.get(algo_type, "未知类型"),
                    "api_url": getattr(algorithm, "api_url", ""),
                    "support_direct_api": bool(getattr(algorithm, "support_direct_api", False)),
                    "behavior_api_version": int(getattr(algorithm, "behavior_api_version", 1) or 1),
                    "model_path": getattr(algorithm, "model_path", ""),
                    "dll_path": getattr(algorithm, "dll_path", ""),
                    "builtin_behavior": getattr(algorithm, "builtin_behavior", ""),
                    "object_str": getattr(algorithm, "object_str", ""),
                    "object_count": getattr(algorithm, "object_count", 0),
                }
            )
    except Exception:
        algorithms = []

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "api_base_url": api_base_url,
                "version": PROJECT_VERSION,
                "actions": {
                    "algorithm_callback": "/api/app-shell/developer/action/algorithmCallback",
                    "stream_info": "/api/app-shell/developer/action/getStreamInfo",
                    "algorithm_info": "/api/app-shell/developer/action/getAlgorithmInfo",
                    "alarm_test": "/api/app-shell/alarm/action/openAdd",
                },
                "open_api": {
                    "alarm_upload": "/open/alarm/upload",
                },
                "active_streams": active_streams,
                "algorithms": algorithms,
            },
        }
    )


def api_config(request):
    """处理 `config` 接口请求。"""
    values = _build_system_context()
    history_detail = {}
    try:
        params = f_parseGetParams(request)
        history_detail = ConfigExportView.build_history_detail_payload(params.get("snapshot_id"), limit=50)
    except Exception:
        history_detail = {
            "history": [],
            "selected_snapshot": None,
            "selected_snapshot_json": "{}",
            "current_snapshot_json": "{}",
            "diff_rows": [],
            "diff_lines": [],
        }

    tracking_algorithms = []
    try:
        tracking_algorithms = [
            {
                "code": str(getattr(algorithm, "code", "") or ""),
                "name": str(getattr(algorithm, "name", "") or ""),
            }
            for algorithm in AlgorithmModel.objects.filter(state__gte=0, algorithm_subtype="tracking").order_by("sort", "id")
        ]
    except Exception:
        tracking_algorithms = []

    transfer_meta = ConfigExportView.build_transfer_console_metadata()

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "values": values,
                "history": history_detail.get("history") or [],
                "tracking_algorithms": tracking_algorithms,
                "summary": {
                    "algorithm_count": AlgorithmModel.objects.filter(state=1).count(),
                    "stream_count": Stream.objects.count(),
                    "control_count": Control.objects.count(),
                },
                "selected_snapshot": history_detail.get("selected_snapshot"),
                "selected_snapshot_json": str(history_detail.get("selected_snapshot_json") or "{}"),
                "current_snapshot_json": str(history_detail.get("current_snapshot_json") or "{}"),
                "diff_rows": history_detail.get("diff_rows") or [],
                "diff_lines": history_detail.get("diff_lines") or [],
                "export_options": transfer_meta.get("export_options") or {},
                "import_merge_modes": transfer_meta.get("import_merge_modes") or {},
            },
        }
    )


def api_onvif(request):
    """处理 `onvif` 接口请求。"""
    queryset = Stream.objects.filter(code__startswith="onvif_").order_by("-id")
    rows = list(queryset[:20])
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "recent_streams": [_serialize_stream_row(row) for row in rows],
                "summary": {
                    "imported_count": queryset.count(),
                    "online_count": queryset.filter(state=1).count(),
                    "forwarding_count": queryset.filter(forward_state=1).count(),
                },
            },
        }
    )


def _cloud_access_state(request, *, perm: str = "", admin_only: bool = False):
    """返回云端`access`状态。"""
    if not is_cloud_mode():
        return {
            "mode_enabled": False,
            "access_ok": False,
            "message": "当前实例未启用 cloud 部署模式",
            "auth": None,
        }

    auth = CloudConsoleView._get_cloud_auth(request)
    if not bool(auth.get("ok")):
        return {
            "mode_enabled": True,
            "access_ok": False,
            "message": str(auth.get("msg") or "forbidden"),
            "auth": auth,
        }

    if admin_only and not bool(auth.get("is_admin")):
        return {
            "mode_enabled": True,
            "access_ok": False,
            "message": "仅管理员可访问该 cloud 页面",
            "auth": auth,
        }

    if perm and not CloudConsoleView._has_perm(auth, perm):
        return {
            "mode_enabled": True,
            "access_ok": False,
            "message": "当前账号没有 cloud 页面访问权限",
            "auth": auth,
        }

    return {
        "mode_enabled": True,
        "access_ok": True,
        "message": "",
        "auth": auth,
    }


def _edge_cloud_connection_state():
    """返回当前 Edge 到 Beacon Cloud 的真实连接状态。"""
    enabled = bool(getattr(g_config, "cloudEnabled", False))
    base_url = str(getattr(g_config, "cloudBaseUrl", "") or "").strip().rstrip("/")
    token_configured = bool(str(getattr(g_config, "cloudEdgeToken", "") or "").strip())
    state = {
        "enabled": enabled,
        "base_url": base_url,
        "token_configured": token_configured,
        "configured": bool(base_url and token_configured),
        "status": "disabled" if not enabled else "incomplete",
        "message": "连接未启用" if not enabled else "请填写云平台地址和 Edge Token",
        "version": "",
    }
    if not enabled or not state["configured"]:
        return state

    try:
        body = CloudEdgeClient(
            base_url=base_url,
            open_api_token=str(getattr(g_config, "cloudEdgeToken", "") or "").strip(),
            timeout_seconds=2,
        ).get_json("/healthz")
        data = body.get("data") or {}
        if str(data.get("deployment_mode") or "").strip().lower() != "cloud":
            raise CloudEdgeClientError("目标地址不是 Beacon Cloud 实例")
        state.update(
            {
                "status": "connected",
                "message": "Beacon Cloud 服务可达",
                "version": str(data.get("version") or "").strip(),
            }
        )
    except (CloudEdgeClientError, ValueError) as exc:
        state.update(
            {
                "status": "unreachable",
                "message": (str(exc) or "无法连接 Beacon Cloud")[:240],
            }
        )
    return state


def _pretty_json_text(raw):
    """处理`pretty`JSON文本。"""
    if isinstance(raw, (dict, list, tuple)):
        try:
            return json.dumps(raw, ensure_ascii=False, indent=2)
        except Exception:
            return str(raw)
    try:
        text = str(raw or "").strip()
    except Exception:
        text = ""
    if not text:
        return ""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except Exception:
        return text


def _serialize_cloud_cluster_ref(cluster):
    """处理`serialize`云端集群`ref`。"""
    if not cluster:
        return None
    project = getattr(cluster, "project", None)
    tenant = getattr(project, "tenant", None)
    return {
        "id": int(getattr(cluster, "id", 0) or 0),
        "tenant_slug": str(getattr(tenant, "slug", "") or ""),
        "project_name": str(getattr(project, "name", "") or ""),
        "name": str(getattr(cluster, "name", "") or ""),
        "node_code": str(getattr(cluster, "node_code", "") or ""),
        "edge_admin_base_url": str(getattr(cluster, "edge_admin_base_url", "") or ""),
        "remark": str(getattr(cluster, "remark", "") or ""),
        "enabled": bool(getattr(cluster, "enabled", False)),
        "last_seen_at": getattr(cluster, "last_seen_at", None),
        "rollout": CloudConsoleView._build_cluster_rollout_state(cluster),
    }


def _dict_text(row: dict, key: str, default: str = "") -> str:
    """返回字典文本字段。"""
    return str(row.get(key, default) or default)


def _dict_list(row: dict, key: str):
    """返回字典列表字段。"""
    return list(row.get(key) or [])


def _cluster_identity_payload(cluster):
    """构建集群基础标识载荷。"""
    project = getattr(cluster, "project", None)
    tenant = getattr(project, "tenant", None)
    return {
        "id": int(getattr(cluster, "id", 0) or 0),
        "tenant_slug": str(getattr(tenant, "slug", "") or ""),
        "project_name": str(getattr(project, "name", "") or ""),
        "name": str(getattr(cluster, "name", "") or ""),
        "node_code": str(getattr(cluster, "node_code", "") or ""),
        "edge_admin_base_url": str(getattr(cluster, "edge_admin_base_url", "") or ""),
        "remark": str(getattr(cluster, "remark", "") or ""),
        "enabled": bool(getattr(cluster, "enabled", False)),
        "last_seen_at": getattr(cluster, "last_seen_at", None),
    }


def _serialize_cloud_cluster_row(row):
    """返回`serialize`云端集群记录。"""
    cluster = row.get("cluster")
    payload = _cluster_identity_payload(cluster)
    payload.update(
        {
        "remote_configured": bool(row.get("remote_configured")),
        "heartbeat_state": _dict_text(row, "heartbeat_state"),
        "heartbeat_age_text": _dict_text(row, "heartbeat_age_text"),
        "version": _dict_text(row, "version", "-"),
        "remote_status": _dict_text(row, "remote_status"),
        "remote_error": _dict_text(row, "remote_error"),
        "issues": _dict_list(row, "issues"),
        "is_unhealthy": bool(row.get("is_unhealthy")),
        "rollout_channel": _dict_text(row, "rollout_channel"),
        "rollout_status": _dict_text(row, "rollout_status"),
        "rollout_status_label": _dict_text(row, "rollout_status_label"),
        "rollout_status_tone": _dict_text(row, "rollout_status_tone", "default"),
        "rollout_target_version": _dict_text(row, "rollout_target_version"),
        "rollout_error": _dict_text(row, "rollout_error"),
        "rollout_node_versions": _dict_list(row, "rollout_node_versions"),
        "has_rollout": bool(row.get("has_rollout")),
        }
    )
    return payload


def _serialize_cloud_top_unhealthy_row(row):
    """返回`serialize`云端`top``unhealthy`记录。"""
    cluster = row.get("cluster")
    return {
        "id": int(getattr(cluster, "id", 0) or 0),
        "name": str(getattr(cluster, "name", "") or ""),
        "node_code": str(getattr(cluster, "node_code", "") or ""),
        "issues": list(row.get("issues") or []),
        "heartbeat_age_text": str(row.get("heartbeat_age_text") or ""),
    }


def _serialize_cloud_alarm_detail_row(row):
    """返回`serialize`云端告警详情记录。"""
    base = CloudConsoleView._serialize_cloud_alarm_row(row)
    base.update(
        {
            "cluster_id": int(getattr(row, "edge_cluster_id", 0) or 0),
            "event_type": str(getattr(row, "event_type", "") or ""),
            "event_source": str(getattr(row, "event_source", "") or ""),
            "node_code": str(getattr(row, "node_code", "") or ""),
            "control_code": str(getattr(row, "control_code", "") or ""),
            "timestamp": getattr(row, "timestamp", None),
            "detail_url": f"/cloud/alarm/detail?id={int(getattr(row, 'id', 0) or 0)}",
        }
    )
    return base


def _serialize_cloud_tenant(row):
    """处理`serialize`云端租户。"""
    branding = CloudConsoleView._parse_json_object(getattr(row, "branding_json", ""))
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "slug": str(getattr(row, "slug", "") or ""),
        "name": str(getattr(row, "name", "") or ""),
        "enabled": bool(getattr(row, "enabled", False)),
        "branding": branding,
        "create_time": getattr(row, "create_time", None),
        "update_time": getattr(row, "update_time", None),
    }


def _serialize_cloud_role(row):
    """处理`serialize`云端`role`。"""
    tenant = getattr(row, "tenant", None)
    permissions = CloudConsoleView._parse_json_object(getattr(row, "permissions_json", ""))
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "tenant_id": int(getattr(row, "tenant_id", 0) or 0),
        "tenant_slug": str(getattr(tenant, "slug", "") or ""),
        "key": str(getattr(row, "key", "") or ""),
        "name": str(getattr(row, "name", "") or ""),
        "enabled": bool(getattr(row, "enabled", False)),
        "permissions": permissions,
        "permissions_json": json.dumps(permissions, ensure_ascii=False),
    }


def _serialize_cloud_membership(row):
    """处理`serialize`云端`membership`。"""
    user = getattr(row, "user", None)
    tenant = getattr(row, "tenant", None)
    role = getattr(row, "role", None)
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "user_id": int(getattr(user, "id", 0) or 0),
        "username": str(getattr(user, "username", "") or ""),
        "tenant_id": int(getattr(tenant, "id", 0) or 0),
        "tenant_slug": str(getattr(tenant, "slug", "") or ""),
        "role_id": int(getattr(role, "id", 0) or 0),
        "role_key": str(getattr(role, "key", "") or ""),
        "role_name": str(getattr(role, "name", "") or ""),
        "enabled": bool(getattr(row, "enabled", False)),
        "is_default": bool(getattr(row, "is_default", False)),
        "resource_scope_json": str(getattr(row, "resource_scope_json", "") or ""),
        "resource_scope": CloudConsoleView._parse_json_object(getattr(row, "resource_scope_json", "")),
    }


def _serialize_cloud_user(row):
    """处理`serialize`云端用户。"""
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "username": str(getattr(row, "username", "") or ""),
        "email": str(getattr(row, "email", "") or ""),
        "is_staff": bool(getattr(row, "is_staff", False)),
        "is_superuser": bool(getattr(row, "is_superuser", False)),
    }


def _serialize_remote_stream_row(row, *, cluster_id: int):
    """返回`serialize`远端流记录。"""
    item = row if isinstance(row, dict) else {}
    code = str(item.get("code") or item.get("name") or "").strip()
    return {
        "code": code,
        "app": str(item.get("app") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "nickname": str(item.get("nickname") or "").strip(),
        "remark": str(item.get("remark") or "").strip(),
        "pull_stream_url": str(item.get("pull_stream_url") or "").strip(),
        "pull_stream_type": str(item.get("pull_stream_type") or "").strip(),
        "state": item.get("state"),
        "forward_state": item.get("forward_state"),
        "detail_url": f"/cloud/remote/stream/detail?cluster_id={int(cluster_id or 0)}&code={quote(code)}" if code else "",
        "recordings_url": f"/cloud/remote/recordings?cluster_id={int(cluster_id or 0)}&stream_code={quote(code)}" if code else "",
    }


def _serialize_remote_stream_detail_row(row, *, cluster_id: int):
    """返回`serialize`远端流详情记录。"""
    item = row if isinstance(row, dict) else {}
    code = str(item.get("code") or "").strip()
    base = _serialize_remote_stream_row(item, cluster_id=cluster_id)
    base.update(
        {
            "id": int(item.get("id") or 0),
            "code": code,
            "raw_json": _pretty_json_text(item),
        }
    )
    return base


def _serialize_remote_recording_row(row):
    """返回`serialize`远端录制记录。"""
    item = row if isinstance(row, dict) else {}
    return {
        "filename": str(item.get("filename") or "").strip(),
        "rel_path": str(item.get("rel_path") or "").strip(),
        "mtime": str(item.get("mtime") or "").strip(),
        "play_url": str(item.get("play_url") or "").strip(),
        "play_error": str(item.get("play_error") or "").strip(),
    }


def _first_available_cluster(clusters):
    """返回当前账号可访问的第一个集群。"""
    for cluster in clusters or []:
        if cluster:
            return cluster
    return None


def _parse_optional_cloud_cluster_id(value) -> tuple[int, bool]:
    """Return (cluster_id, invalid); blank or zero means no explicit selection."""
    text = str(value or "").strip()
    if not text:
        return 0, False
    try:
        cluster_id = int(text)
    except (TypeError, ValueError):
        return 0, True
    if cluster_id < 0:
        return cluster_id, True
    return cluster_id, False


def _serialize_remote_algorithm_flow_row(row):
    """返回`serialize`远端算法`flow`记录。"""
    item = row if isinstance(row, dict) else {}
    return {
        "code": str(item.get("code") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "raw_json": _pretty_json_text(item),
    }


def api_cloud_edge_clusters(request):
    """处理 `cloud_edge_clusters` 接口请求。"""
    access = _cloud_access_state(request, perm=CloudConsoleView._PERM_EDGE_CLUSTERS_VIEW)
    if not access["access_ok"]:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": access["mode_enabled"],
                    "access_ok": False,
                    "access_message": access["message"],
                    "edge_connection": _edge_cloud_connection_state() if not access["mode_enabled"] else None,
                    "manage_allowed": False,
                    "summary": {},
                    "rows": [],
                    "top_unhealthy": [],
                    "rollout_rows": [],
                    "tenant_options": [],
                },
            }
        )

    auth = access["auth"]
    context = CloudConsoleView._edge_clusters_page_context(auth)
    if bool(auth.get("is_admin")):
        tenant_options = list(CloudTenant.objects.filter(enabled=True).order_by("id"))
    elif auth.get("tenant"):
        tenant_options = [auth.get("tenant")]
    else:
        tenant_options = []
    rows = [_serialize_cloud_cluster_row(row) for row in context.get("cluster_health_rows") or []]
    top_unhealthy = [_serialize_cloud_top_unhealthy_row(row) for row in context.get("top_unhealthy_clusters") or []]

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "manage_allowed": bool(auth.get("is_admin")) or CloudConsoleView._has_perm(auth, CloudConsoleView._PERM_EDGE_CLUSTERS_MANAGE),
                "summary": context.get("cluster_health_summary") or {},
                "rows": rows,
                "top_unhealthy": top_unhealthy,
                "rollout_rows": [row for row in rows if row.get("has_rollout")],
                "tenant_options": [_serialize_cloud_tenant(item) for item in tenant_options if item],
            },
        }
    )


def _cloud_edge_action_access_response(request):
    """返回云端集群操作权限响应。"""
    if request.method != "POST":
        return None, f_responseJson({"code": 0, "msg": "request method not supported"})
    access = _cloud_access_state(request, perm=CloudConsoleView._PERM_EDGE_CLUSTERS_VIEW)
    if not access["access_ok"]:
        return None, f_responseJson({"code": 0, "msg": access["message"]})
    auth = access["auth"]
    can_manage = bool(auth.get("is_admin")) or CloudConsoleView._has_perm(auth, CloudConsoleView._PERM_EDGE_CLUSTERS_MANAGE)
    if not can_manage:
        return None, f_responseJson({"code": 0, "msg": "当前账号没有管理边缘集群的权限"})
    return auth, None


def _stash_cloud_edge_action_flash(request, context: dict, resp):
    """写入云端集群操作 flash。"""
    top_msg = str(context.get("top_msg") or "").strip()
    if resp is not None and not top_msg:
        top_msg = f"操作失败({getattr(resp, 'status_code', 500)})"
    CloudConsoleView._stash_cloud_flash(
        request,
        CloudConsoleView._FLASH_KEY_CLOUD_EDGE_CLUSTERS,
        {
            "top_msg": top_msg,
            "created_token": str(context.get("created_token") or ""),
            "rotated_token": str(context.get("rotated_token") or ""),
        },
    )


def _cloud_edge_action_success_response(context: dict):
    """返回云端集群操作成功响应。"""
    return f_responseJson(
        {
            "code": 1000,
            "msg": context.get("top_msg") or "success",
            "data": {
                "created_token": context.get("created_token") or "",
                "rotated_token": context.get("rotated_token") or "",
            },
        }
    )


def api_cloud_edge_clusters_action(request):
    """处理 `cloud_edge_clusters_action` 接口请求。"""
    auth, response = _cloud_edge_action_access_response(request)
    if response is not None:
        return response

    context, resp = CloudConsoleView._handle_edge_clusters_post(request, auth)
    redirect_target = "/cloud/edge-clusters"
    if str(request.POST.get("redirect_to") or "").strip():
        _stash_cloud_edge_action_flash(request, context, resp)
        return redirect(redirect_target)
    if resp is not None:
        return f_responseJson({"code": 0, "msg": context.get("top_msg") or f"操作失败({getattr(resp, 'status_code', 500)})"})

    return _cloud_edge_action_success_response(context)


def api_cloud_alarms(request):
    """处理 `cloud_alarms` 接口请求。"""
    access = _cloud_access_state(request, perm=CloudConsoleView._PERM_ALARMS_VIEW)
    params = f_parseGetParams(request)
    cluster_id = CloudConsoleView._parse_cluster_id(params)
    q = str(params.get("q", "") or "").strip()
    event_type = str(params.get("event_type", "") or "").strip()
    page = CloudConsoleView._parse_int_clamped(params.get("p", 1), default=1, min_value=1)
    page_size = CloudConsoleView._parse_int_clamped(params.get("ps", 20), default=20, min_value=10, max_value=50)

    if not access["access_ok"]:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": access["mode_enabled"],
                    "access_ok": False,
                    "access_message": access["message"],
                    "rows": [],
                    "clusters": [],
                    "pageData": {"page": page, "page_size": page_size, "page_num": 0, "count": 0, "pageLabels": []},
                    "selected_cluster_id": cluster_id,
                },
            }
        )

    auth = access["auth"]
    queryset = CloudAlarmEvent.objects.select_related("edge_cluster").all().order_by("-received_at")
    queryset = CloudConsoleView._filter_alarms_for_auth(auth, queryset)
    if cluster_id:
        queryset = queryset.filter(edge_cluster_id=cluster_id)
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    if q:
        queryset = queryset.filter(
            Q(event_id__icontains=q)
            | Q(event_type__icontains=q)
            | Q(desc__icontains=q)
            | Q(node_code__icontains=q)
            | Q(control_code__icontains=q)
            | Q(payload_json__icontains=q)
        )

    from app.utils.Common import buildPageLabels

    paginator, current_page, page = CloudConsoleView._paginate_queryset(queryset, page=page, page_size=page_size)
    rows = [_serialize_cloud_alarm_detail_row(row) for row in current_page.object_list]
    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": buildPageLabels(page=page, page_num=paginator.num_pages),
    }
    clusters = list(CloudConsoleView._filter_clusters_for_auth(auth, CloudEdgeCluster.objects.all().order_by("id")))

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "rows": rows,
                "clusters": [{"id": int(item.id), "name": str(item.name or "")} for item in clusters],
                "pageData": page_data,
                "selected_cluster_id": cluster_id,
                "filters": {"cluster_id": cluster_id, "event_type": event_type, "q": q},
            },
        }
    )


def api_cloud_alarm_detail(request):
    """处理 `cloud_alarm_detail` 接口请求。"""
    access = _cloud_access_state(request, perm=CloudConsoleView._PERM_ALARMS_VIEW)
    params = f_parseGetParams(request)
    alarm_id = params.get("id")

    if not access["access_ok"]:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": access["mode_enabled"],
                    "access_ok": False,
                    "access_message": access["message"],
                    "found": False,
                    "alarm_id": int(alarm_id or 0) if str(alarm_id or "").isdigit() else 0,
                    "alarm": None,
                    "cluster_name": "",
                    "image_url": "",
                    "image_error": "",
                    "image_preview_mode": "",
                    "payload_pretty": "",
                    "has_image": False,
                    "message": "",
                },
            }
        )

    auth = access["auth"]
    row = CloudConsoleView._get_cloud_alarm_event_row_or_none(auth, alarm_id)
    if not row:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": True,
                    "access_ok": True,
                    "access_message": "",
                    "found": False,
                    "alarm_id": int(alarm_id or 0) if str(alarm_id or "").isdigit() else 0,
                    "alarm": None,
                    "cluster_name": "",
                    "image_url": "",
                    "image_error": "",
                    "image_preview_mode": "",
                    "payload_pretty": "",
                    "has_image": False,
                    "message": "告警不存在或当前账号无权查看该告警",
                },
            }
        )

    use_proxy = CloudConsoleView._cloud_alarm_use_proxy_preview()
    image_url, image_error = CloudConsoleView._resolve_cloud_alarm_image_preview(row, use_proxy=use_proxy)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "found": True,
                "alarm_id": int(getattr(row, "id", 0) or 0),
                "alarm": _serialize_cloud_alarm_detail_row(row),
                "cluster_name": str(getattr(getattr(row, "edge_cluster", None), "name", "") or ""),
                "image_url": image_url,
                "image_error": image_error,
                "image_preview_mode": "proxy" if use_proxy else "presigned_get",
                "payload_pretty": _pretty_json_text(getattr(row, "payload_json", "") or ""),
                "has_image": bool(image_url),
                "message": "",
            },
        }
    )


def api_cloud_remote_streams(request):
    """处理 `cloud_remote_streams` 接口请求。"""
    access = _cloud_access_state(request, perm=PERM_CLOUD_REMOTE_STREAMS_VIEW)
    params = f_parseGetParams(request)
    cluster_id, cluster_id_invalid = _parse_optional_cloud_cluster_id(params.get("cluster_id"))

    if not access["access_ok"]:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": access["mode_enabled"],
                    "access_ok": False,
                    "access_message": access["message"],
                    "manage_allowed": False,
                    "found": False,
                    "message": "",
                    "clusters": [],
                    "selected_cluster_id": cluster_id,
                    "selected_cluster": None,
                    "selected_cluster_rollout": CloudConsoleView._build_cluster_rollout_state(None),
                    "remote_error": "",
                    "rows": [],
                },
            }
        )

    auth = access["auth"]
    clusters_qs = CloudEdgeCluster.objects.select_related("project", "project__tenant").all().order_by("id")
    clusters_qs = CloudConsoleView._filter_clusters_for_auth(auth, clusters_qs)
    clusters = list(clusters_qs)
    if cluster_id_invalid:
        selected_cluster, error_resp = None, True
    else:
        selected_cluster, cluster_id, error_resp = CloudRemoteStreamsView._resolve_selected_cluster(
            auth,
            clusters_qs,
            cluster_id,
        )
    if error_resp:
        return f_responseJson(
            {
                "code": 0,
                "msg": MSG_CLOUD_CLUSTER_UNAVAILABLE,
                "data": {
                    "mode_enabled": True,
                    "access_ok": True,
                    "access_message": "",
                    "manage_allowed": CloudConsoleView._has_perm(auth, PERM_CLOUD_REMOTE_STREAMS_MANAGE),
                    "found": False,
                    "message": MSG_CLOUD_CLUSTER_UNAVAILABLE,
                    "clusters": [_serialize_cloud_cluster_ref(item) for item in clusters],
                    "selected_cluster_id": cluster_id,
                    "selected_cluster": None,
                    "selected_cluster_rollout": CloudConsoleView._build_cluster_rollout_state(None),
                    "remote_error": "",
                    "rows": [],
                },
            }
        )

    remote_error, stream_rows = CloudRemoteStreamsView._fetch_remote_streams(selected_cluster)
    selected_cluster_id = int(getattr(selected_cluster, "id", 0) or 0)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "manage_allowed": CloudConsoleView._has_perm(auth, PERM_CLOUD_REMOTE_STREAMS_MANAGE),
                "found": bool(selected_cluster),
                "message": "",
                "clusters": [_serialize_cloud_cluster_ref(item) for item in clusters],
                "selected_cluster_id": selected_cluster_id,
                "selected_cluster": _serialize_cloud_cluster_ref(selected_cluster),
                "selected_cluster_rollout": CloudConsoleView._build_cluster_rollout_state(selected_cluster),
                "remote_error": remote_error,
                "rows": [_serialize_remote_stream_row(item, cluster_id=selected_cluster_id) for item in stream_rows],
            },
        }
    )


def _cloud_remote_stream_detail_data(
    *,
    mode_enabled=True,
    access_ok=True,
    access_message="",
    manage_allowed=False,
    found=False,
    cluster_id=0,
    selected_code="",
    cluster=None,
    stream=None,
    top_msg="",
    error_msg="",
    message="",
):
    """构建远程流详情数据。"""
    return {
        "mode_enabled": mode_enabled,
        "access_ok": access_ok,
        "access_message": access_message,
        "manage_allowed": manage_allowed,
        "found": found,
        "cluster_id": cluster_id,
        "selected_code": selected_code,
        "cluster": cluster,
        "stream": stream or {},
        "top_msg": top_msg,
        "error_msg": error_msg,
        "message": message,
    }


def _cloud_remote_stream_detail_response(data: dict, *, code: int = 1000, msg: str = "success"):
    """返回远程流详情响应。"""
    return f_responseJson({"code": code, "msg": msg or "success", "data": data})


def _stream_detail_redirect_target(cluster):
    """返回远程流详情重定向目标。"""
    fallback = "/cloud/remote/stream/detail"
    cluster_id = int(getattr(cluster, "id", 0) or 0)
    if cluster_id <= 0:
        return fallback
    return "{}?{}".format(fallback, urlencode({"cluster_id": cluster_id}))


def _stream_detail_post_error(resp, context: dict) -> str:
    """返回远程流详情 POST 错误。"""
    error_msg = str(context.get("error_msg") or "").strip()
    if error_msg or resp is None:
        return error_msg
    status_code = int(getattr(resp, "status_code", 0) or 0)
    return "权限不足：无权修改远程摄像头配置" if status_code == 403 else f"操作失败({getattr(resp, 'status_code', 500)})"


def _stream_detail_post_response(request, *, cluster, client, context: dict, stream_code: str):
    """处理远程流详情 POST。"""
    if request.method != "POST":
        return None
    resp = CloudRemoteStreamDetailView._handle_stream_detail_post(
        request,
        client=client,
        context=context,
        stream_code=stream_code,
    )
    if str(request.POST.get("redirect_to") or "").strip():
        CloudConsoleView._stash_cloud_flash(
            request,
            CloudConsoleView._FLASH_KEY_CLOUD_REMOTE_STREAM_DETAIL,
            {
                "top_msg": str(context.get("top_msg") or ""),
                "error_msg": _stream_detail_post_error(resp, context),
                "selected_code": stream_code,
            },
        )
        return redirect(_stream_detail_redirect_target(cluster))
    if resp is not None:
        return f_responseJson({"code": 0, "msg": "权限不足：无权修改远程摄像头配置"})
    if context.get("error_msg"):
        return f_responseJson({"code": 0, "msg": context.get("error_msg") or "保存失败"})
    return None


def api_cloud_remote_stream_detail(request):
    """处理 `cloud_remote_stream_detail` 接口请求。"""
    access = _cloud_access_state(request, perm=PERM_CLOUD_REMOTE_STREAMS_VIEW)
    params = request.POST if request.method == "POST" else request.GET
    cluster_id, cluster_id_invalid = _parse_optional_cloud_cluster_id(params.get("cluster_id"))
    stream_code = str(params.get("code") or "").strip()

    if not access["access_ok"]:
        return _cloud_remote_stream_detail_response(
            _cloud_remote_stream_detail_data(
                mode_enabled=access["mode_enabled"],
                access_ok=False,
                access_message=access["message"],
                cluster_id=cluster_id,
                selected_code=stream_code,
            )
        )

    auth = access["auth"]
    if cluster_id_invalid:
        cluster = None
    elif cluster_id > 0:
        cluster = CloudConsoleView._get_cluster_for_auth(auth, cluster_id)
    else:
        clusters_qs = CloudEdgeCluster.objects.select_related(
            "project",
            "project__tenant",
        ).all().order_by("id")
        cluster = CloudConsoleView._filter_clusters_for_auth(auth, clusters_qs).first()
        cluster_id = int(getattr(cluster, "id", 0) or 0)
    if cluster_id_invalid or not cluster:
        return _cloud_remote_stream_detail_response(
            _cloud_remote_stream_detail_data(
                manage_allowed=CloudConsoleView._has_perm(auth, PERM_CLOUD_REMOTE_STREAMS_MANAGE),
                cluster_id=cluster_id,
                selected_code=stream_code,
                message=MSG_CLOUD_CLUSTER_UNAVAILABLE,
            ),
            code=0,
            msg=MSG_CLOUD_CLUSTER_UNAVAILABLE,
        )

    context = CloudRemoteStreamDetailView._build_stream_detail_context(auth, cluster, stream_code)
    if not CloudRemoteStreamDetailView._cluster_has_edge_config(cluster):
        context["error_msg"] = "当前集群未配置远控连接"
        return _cloud_remote_stream_detail_response(
            _cloud_remote_stream_detail_data(
                manage_allowed=bool(context.get("can_manage")),
                cluster_id=int(getattr(cluster, "id", 0) or 0),
                selected_code=stream_code,
                cluster=_serialize_cloud_cluster_ref(cluster),
                error_msg=context["error_msg"],
            )
        )

    client = CloudRemoteStreamDetailView._build_cloud_edge_client(cluster)
    post_response = _stream_detail_post_response(request, cluster=cluster, client=client, context=context, stream_code=stream_code)
    if post_response is not None:
        return post_response

    CloudRemoteStreamDetailView._load_stream_detail(client, context, stream_code)
    stream_row = _serialize_remote_stream_detail_row(context.get("stream") or {}, cluster_id=int(getattr(cluster, "id", 0) or 0))
    return _cloud_remote_stream_detail_response(
        _cloud_remote_stream_detail_data(
            manage_allowed=bool(context.get("can_manage")),
            found=bool(stream_row.get("code")),
            cluster_id=int(getattr(cluster, "id", 0) or 0),
            selected_code=stream_code,
            cluster=_serialize_cloud_cluster_ref(cluster),
            stream=stream_row,
            top_msg=context.get("top_msg") or "",
            error_msg=context.get("error_msg") or "",
        ),
        msg=context.get("top_msg") or "success",
    )


def _empty_remote_recordings_page_data(page: int, page_size: int):
    """返回空远程录制分页数据。"""
    return {"page": page, "page_size": page_size, "page_num": 0, "count": 0, "pageLabels": []}


def _remote_recordings_page_data(*, total: int, page: int, page_size: int):
    """返回远程录制分页数据。"""
    if total <= 0:
        return _empty_remote_recordings_page_data(page, page_size)
    from app.utils.Common import buildPageLabels

    page_num = (total + page_size - 1) // page_size
    return {
        "page": page,
        "page_size": page_size,
        "page_num": page_num,
        "count": total,
        "pageLabels": buildPageLabels(page=page, page_num=page_num),
    }


def _cloud_remote_recordings_data(
    *,
    mode_enabled=True,
    access_ok=True,
    access_message="",
    found=False,
    message="",
    clusters=None,
    selected_cluster_id=0,
    selected_stream_code="",
    cluster=None,
    rows=None,
    total=0,
    top_msg="",
    page_data=None,
):
    """构建远程录制数据。"""
    return {
        "mode_enabled": mode_enabled,
        "access_ok": access_ok,
        "access_message": access_message,
        "found": found,
        "message": message,
        "clusters": clusters or [],
        "selected_cluster_id": selected_cluster_id,
        "selected_stream_code": selected_stream_code,
        "cluster": cluster,
        "rows": rows or [],
        "total": total,
        "top_msg": top_msg,
        "pageData": page_data or _empty_remote_recordings_page_data(1, 20),
    }


def _cloud_remote_recordings_response(data: dict, *, code: int = 1000, msg: str = "success"):
    """返回远程录制响应。"""
    return f_responseJson({"code": code, "msg": msg, "data": data})


def _fetch_remote_recording_rows(request, cluster, stream_code: str, *, page: int, page_size: int):
    """读取远程录制行。"""
    client = CloudRemoteRecordingsView._cloud_edge_client_for_cluster(cluster)
    payload = client.list_recording_files(stream_code, page=page, page_size=page_size)
    rows = [
        _serialize_remote_recording_row(item)
        for item in CloudRemoteRecordingsView._remote_recording_rows_with_play_urls(request, cluster.id, payload)
    ]
    return rows, int((payload or {}).get("total") or len(rows))


def api_cloud_remote_recordings(request):
    """处理 `cloud_remote_recordings` 接口请求。"""
    access = _cloud_access_state(request, perm=PERM_CLOUD_REMOTE_RECORDINGS_VIEW)
    params = f_parseGetParams(request)
    cluster_id, cluster_id_invalid = _parse_optional_cloud_cluster_id(params.get("cluster_id"))
    stream_code = str(params.get("stream_code") or params.get("streamCode") or "").strip()
    page = CloudConsoleView._parse_int_clamped(params.get("p", 1), default=1, min_value=1)
    page_size = CloudConsoleView._parse_int_clamped(params.get("ps", 20), default=20, min_value=10, max_value=50)

    if not access["access_ok"]:
        return _cloud_remote_recordings_response(
            _cloud_remote_recordings_data(
                mode_enabled=access["mode_enabled"],
                access_ok=False,
                access_message=access["message"],
                selected_cluster_id=cluster_id,
                selected_stream_code=stream_code,
                page_data=_empty_remote_recordings_page_data(page, page_size),
            )
        )

    auth = access["auth"]
    clusters = list(CloudConsoleView._filter_clusters_for_auth(auth, CloudEdgeCluster.objects.all().order_by("id")))
    serialized_clusters = [_serialize_cloud_cluster_ref(item) for item in clusters]
    cluster = (
        CloudConsoleView._get_cluster_for_auth(auth, cluster_id)
        if cluster_id > 0 and not cluster_id_invalid
        else None
    )
    if cluster_id_invalid or (cluster_id > 0 and not cluster):
        return _cloud_remote_recordings_response(
            _cloud_remote_recordings_data(
                message=MSG_CLOUD_CLUSTER_UNAVAILABLE,
                clusters=serialized_clusters,
                selected_cluster_id=cluster_id,
                selected_stream_code=stream_code,
                page_data=_empty_remote_recordings_page_data(page, page_size),
            ),
            code=0,
            msg=MSG_CLOUD_CLUSTER_UNAVAILABLE,
        )

    if not cluster and cluster_id <= 0:
        cluster = _first_available_cluster(clusters)
        cluster_id = int(getattr(cluster, "id", 0) or 0)

    page_data = _empty_remote_recordings_page_data(page, page_size)
    if not cluster or not stream_code:
        return _cloud_remote_recordings_response(
            _cloud_remote_recordings_data(
                clusters=serialized_clusters,
                selected_cluster_id=cluster_id,
                selected_stream_code=stream_code,
                cluster=_serialize_cloud_cluster_ref(cluster),
                page_data=page_data,
            )
        )

    if not CloudRemoteRecordingsView._cluster_has_remote_config(cluster):
        return _cloud_remote_recordings_response(
            _cloud_remote_recordings_data(
                clusters=serialized_clusters,
                selected_cluster_id=cluster_id,
                selected_stream_code=stream_code,
                cluster=_serialize_cloud_cluster_ref(cluster),
                top_msg="当前集群未配置远控连接",
                page_data=page_data,
            )
        )

    top_msg = ""
    rows = []
    total = 0
    try:
        rows, total = _fetch_remote_recording_rows(request, cluster, stream_code, page=page, page_size=page_size)
    except Exception as exc:
        top_msg = str(exc)

    return _cloud_remote_recordings_response(
        _cloud_remote_recordings_data(
            found=bool(cluster and stream_code),
            clusters=serialized_clusters,
            selected_cluster_id=int(getattr(cluster, "id", 0) or 0),
            selected_stream_code=stream_code,
            cluster=_serialize_cloud_cluster_ref(cluster),
            rows=rows,
            total=total,
            top_msg=top_msg,
            page_data=_remote_recordings_page_data(total=total, page=page, page_size=page_size),
        )
    )


def _cloud_remote_platform_cluster_failure(clusters, cluster_id: int):
    """Return a fail-closed response for an invalid or unauthorized cluster."""
    return f_responseJson(
        {
            "code": 0,
            "msg": MSG_CLOUD_CLUSTER_UNAVAILABLE,
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "found": False,
                "message": MSG_CLOUD_CLUSTER_UNAVAILABLE,
                "clusters": [_serialize_cloud_cluster_ref(item) for item in clusters],
                "selected_cluster_id": cluster_id,
                "selected_cluster": None,
                "algorithm_flows": [],
                "core_process_data": [],
                "core_process_info": {},
                "remote_error": "",
            },
        }
    )


def api_cloud_remote_platform(request):
    """处理 `cloud_remote_platform` 接口请求。"""
    access = _cloud_access_state(request, perm=PERM_CLOUD_REMOTE_PLATFORM_VIEW)
    params = f_parseGetParams(request)
    cluster_id, cluster_id_invalid = _parse_optional_cloud_cluster_id(params.get("cluster_id"))

    if not access["access_ok"]:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": access["mode_enabled"],
                    "access_ok": False,
                    "access_message": access["message"],
                    "found": False,
                    "message": "",
                    "clusters": [],
                    "selected_cluster_id": cluster_id,
                    "selected_cluster": None,
                    "algorithm_flows": [],
                    "core_process_data": [],
                    "core_process_info": {},
                    "remote_error": "",
                },
            }
        )

    auth = access["auth"]
    clusters = list(CloudConsoleView._filter_clusters_for_auth(auth, CloudEdgeCluster.objects.all().order_by("id")))
    selected_cluster = None
    algorithm_flows = []
    core_process_data = []
    core_process_info = {}
    remote_error = ""
    found = False
    message = ""

    if cluster_id_invalid:
        return _cloud_remote_platform_cluster_failure(clusters, cluster_id)
    if cluster_id > 0:
        selected_cluster = CloudConsoleView._get_cluster_for_auth(auth, cluster_id)
        if not selected_cluster:
            return _cloud_remote_platform_cluster_failure(clusters, cluster_id)
    else:
        selected_cluster = _first_available_cluster(clusters)

    if selected_cluster:
        found = True
        remote_error, algorithm_flows, core_process_data, core_process_info = CloudRemotePlatformView._fetch_remote_platform_data(selected_cluster)

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "found": found,
                "message": message,
                "clusters": [_serialize_cloud_cluster_ref(item) for item in clusters],
                "selected_cluster_id": int(getattr(selected_cluster, "id", 0) or 0),
                "selected_cluster": _serialize_cloud_cluster_ref(selected_cluster),
                "algorithm_flows": [_serialize_remote_algorithm_flow_row(item) for item in algorithm_flows],
                "core_process_data": [_normalize_process_summary(item) for item in core_process_data],
                "core_process_info": core_process_info if isinstance(core_process_info, dict) else {},
                "remote_error": remote_error,
            },
        }
    )


def api_cloud_iam(request):
    """处理 `cloud_iam` 接口请求。"""
    access = _cloud_access_state(request, admin_only=True)
    if not access["access_ok"]:
        return f_responseJson(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "mode_enabled": access["mode_enabled"],
                    "access_ok": False,
                    "access_message": access["message"],
                    "permission_meta": [],
                    "tenants": [],
                    "roles": [],
                    "memberships": [],
                    "users": [],
                    "clusters": [],
                },
            }
        )

    context = CloudConsoleView._iam_page_context()
    clusters = list(CloudEdgeCluster.objects.select_related("project", "project__tenant").all().order_by("-id"))
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "mode_enabled": True,
                "access_ok": True,
                "access_message": "",
                "permission_meta": context.get("permission_meta") or [],
                "tenants": [_serialize_cloud_tenant(item) for item in context.get("tenants") or []],
                "roles": [_serialize_cloud_role(item) for item in context.get("roles") or []],
                "memberships": [_serialize_cloud_membership(item) for item in context.get("memberships") or []],
                "users": [_serialize_cloud_user(item) for item in context.get("users") or []],
                "clusters": [
                    {
                        "id": int(item.id),
                        "name": str(item.name or ""),
                        "tenant_slug": str(getattr(getattr(getattr(item, "project", None), "tenant", None), "slug", "") or ""),
                    }
                    for item in clusters
                ],
            },
        }
    )


def api_cloud_iam_action(request):
    """处理 `cloud_iam_action` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "request method not supported"})

    access = _cloud_access_state(request, admin_only=True)
    if not access["access_ok"]:
        return f_responseJson({"code": 0, "msg": access["message"]})

    context = CloudConsoleView._handle_iam_post_action(request)
    redirect_target = "/cloud/iam"
    if str(request.POST.get("redirect_to") or "").strip():
        CloudConsoleView._stash_cloud_flash(
            request,
            CloudConsoleView._FLASH_KEY_CLOUD_IAM,
            {
                "top_msg": str(context.get("top_msg") or ""),
            },
        )
        return redirect(redirect_target)
    return f_responseJson({"code": 1000, "msg": context.get("top_msg") or "success", "data": {}})
