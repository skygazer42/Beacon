import logging
import json
import os
from urllib.parse import urlsplit
import settings_store  # type: ignore

from django.shortcuts import render

from app.models import ConfigHistorySnapshot
from app.utils.ConfigHistory import apply_system_snapshot, build_system_snapshot, record_system_change, snapshot_equals, snapshot_payload
from app.utils.SystemConfigHelper import get_value, set_value
from app.views.ViewsBase import f_parsePostParams, f_responseJson, g_config, getUser
from framework.settings import BASE_DIR


logger = logging.getLogger(__name__)


_SYSTEM_KEYS = {
    "siteName": {"remark": "System name"},
    "siteTitle": {"remark": "System title"},
    "siteLogo": {"remark": "System logo"},
    "authorName": {"remark": "Author name"},
    "authorLink": {"remark": "Author link"},
    "siteIcp": {"remark": "ICP"},
    "loginBg": {"remark": "Login background"},
    "loginCaptchaEnabled": {"remark": "Login captcha enabled"},
    "customCss": {"remark": "Custom CSS"},
    "customScript": {"remark": "Custom script"},
    "docsUrl": {"remark": "Docs URL"},
    "downloadUrl": {"remark": "Download URL"},
    "alarmVideoSeconds": {"remark": "Alarm video seconds"},
    "alarmSegmentMaxSeconds": {"remark": "Alarm segment max seconds"},
    "alarmPushDelaySeconds": {"remark": "Alarm push delay seconds"},
    "alarmAiReviewEnabled": {"remark": "Alarm AI review enabled"},
    "modelCacheSeconds": {"remark": "Model cache seconds"},
    "modelEncrypt": {"remark": "Model encrypt"},
    "modelEncryptKey": {"remark": "Model encrypt key"},
    "modelEncryptSuffix": {"remark": "Model encrypt suffix"},
    "modelDecryptDir": {"remark": "Model decrypt dir"},
    "faceDefaultFeatureAlgorithmCode": {"remark": "Face default feature algorithm"},
    "stream_auto_start": {"remark": "Stream auto start"},
    "software_auto_start": {"remark": "Software auto start"},
    "screenLoginRequired": {"remark": "Screen login required"},
    "control_auto_recover": {"remark": "Control auto recover"},
    "logAutoCleanEnabled": {"remark": "Log auto clean enabled"},
    "logRetentionDays": {"remark": "Log retention days"},
    "alarmDataAutoCleanEnabled": {"remark": "Alarm auto clean enabled"},
    "alarmDataRetentionDays": {"remark": "Alarm retention days"},
    "alarmDataMaxStorageMB": {"remark": "Alarm max storage MB"},
    "recordingDataAutoCleanEnabled": {"remark": "Recording auto clean enabled"},
    "recordingDataRetentionDays": {"remark": "Recording retention days"},
    "recordingDataMaxStorageMB": {"remark": "Recording max storage MB"},
    "gb28181Provider": {"remark": "GB28181 provider"},
    "gb28181WvpBaseUrl": {"remark": "GB28181 WVP base url"},
    "gb28181WvpStartPlayUrlTemplate": {"remark": "GB28181 WVP start template"},
    "gb28181WvpStopPlayUrlTemplate": {"remark": "GB28181 WVP stop template"},
    "gb28181WvpPtzControlUrlTemplate": {"remark": "GB28181 WVP PTZ template"},
    "gb28181CustomBaseUrl": {"remark": "GB28181 custom base url"},
    "gb28181CustomStartPlayUrlTemplate": {"remark": "GB28181 custom start template"},
    "gb28181CustomStopPlayUrlTemplate": {"remark": "GB28181 custom stop template"},
    "gb28181CustomPtzControlUrlTemplate": {"remark": "GB28181 custom PTZ template"},
    "gb28181TransportMode": {"remark": "GB28181 transport mode"},
    "gb28181StartupPolicy": {"remark": "GB28181 startup policy"},
    "gb28181RequestParamPolicy": {"remark": "GB28181 param policy"},
    "gb28181RequestParamAllowlist": {"remark": "GB28181 allowlist"},
    "gb28181RequestParamBlocklist": {"remark": "GB28181 blocklist"},
    "gb28181HttpTimeoutSeconds": {"remark": "GB28181 timeout seconds"},
    "maxHardwareDecodeChannels": {"remark": "Max hardware decode channels"},
    "maxHardwareEncodeChannels": {"remark": "Max hardware encode channels"},
    "webrtcStunUrls": {"remark": "WebRTC STUN urls"},
    "webrtcTurnUrl": {"remark": "WebRTC TURN url"},
    "webrtcTurnUsername": {"remark": "WebRTC TURN username"},
    "webrtcTurnPassword": {"remark": "WebRTC TURN password"},
    "webrtcSelfCheckTimeoutSeconds": {"remark": "WebRTC self-check timeout"},
    "openApiRateLimitEnabled": {"remark": "OpenAPI rate limit enabled"},
    "openApiRateLimitPerMinute": {"remark": "OpenAPI requests per minute"},
    "openApiRateLimitBurst": {"remark": "OpenAPI rate limit burst"},
    "openApiWafEnabled": {"remark": "OpenAPI WAF enabled"},
    "openApiWafMaxBodyBytes": {"remark": "OpenAPI WAF max body bytes"},
    "cloudEnabled": {"remark": "Cloud alarm delivery enabled"},
    "cloudBaseUrl": {"remark": "Beacon Cloud base URL"},
    "cloudEdgeToken": {"remark": "Beacon Cloud edge token"},
}

_UI_SETTINGS_KEYS = {
    "siteName",
    "siteTitle",
    "siteLogo",
    "authorName",
    "authorLink",
    "siteIcp",
    "loginBg",
    "customCss",
    "customScript",
    "docsUrl",
    "downloadUrl",
}

_RUNTIME_CONFIG_KEYS = set(_SYSTEM_KEYS.keys()) - set(_UI_SETTINGS_KEYS)

_BOOL_INT_KEYS = {
    "loginCaptchaEnabled",
    "modelEncrypt",
    "stream_auto_start",
    "software_auto_start",
    "screenLoginRequired",
    "control_auto_recover",
    "logAutoCleanEnabled",
    "alarmDataAutoCleanEnabled",
    "alarmAiReviewEnabled",
    "recordingDataAutoCleanEnabled",
    "openApiRateLimitEnabled",
    "openApiWafEnabled",
    "cloudEnabled",
}

_INT_FIELD_LIMITS = {
    "alarmVideoSeconds": (0, 3600),
    "alarmSegmentMaxSeconds": (1, 3600),
    "alarmPushDelaySeconds": (0, 3600),
    "modelCacheSeconds": (0, 30 * 24 * 3600),
    "logRetentionDays": (0, 3650),
    "alarmDataRetentionDays": (0, 3650),
    "alarmDataMaxStorageMB": (0, 1024 * 1024),
    "recordingDataRetentionDays": (0, 3650),
    "recordingDataMaxStorageMB": (0, 1024 * 1024),
    "gb28181HttpTimeoutSeconds": (1, 60),
    "maxHardwareDecodeChannels": (0, 9999),
    "maxHardwareEncodeChannels": (0, 9999),
    "webrtcSelfCheckTimeoutSeconds": (1, 30),
    "openApiRateLimitPerMinute": (1, 100000),
    "openApiRateLimitBurst": (0, 100000),
    "openApiWafMaxBodyBytes": (1, 1024 * 1024 * 1024),
}

_STRING_LIMITS = {
    "customCss": 20000,
    "customScript": 20000,
    "webrtcStunUrls": 2000,
    "cloudBaseUrl": 500,
    "cloudEdgeToken": 4096,
}

_DEFAULTS = {
    "siteName": "Beacon",
    "siteTitle": "Beacon 新一代 AI 视频分析系统",
    "siteLogo": "/static/images/logo.png",
    "authorName": "",
    "authorLink": "",
    "siteIcp": "",
    "loginBg": "",
    "loginCaptchaEnabled": 1,
    "customCss": "",
    "customScript": "",
    "docsUrl": "",
    "downloadUrl": "",
    "alarmVideoSeconds": 0,
    "alarmSegmentMaxSeconds": 60,
    "alarmPushDelaySeconds": 0,
    "alarmAiReviewEnabled": 0,
    "modelCacheSeconds": 0,
    "modelEncrypt": 0,
    "modelEncryptKey": "",
    "modelEncryptSuffix": ".enc",
    "modelDecryptDir": "",
    "faceDefaultFeatureAlgorithmCode": "",
    "stream_auto_start": 0,
    "software_auto_start": 0,
    "screenLoginRequired": 1,
    "control_auto_recover": 0,
    "logAutoCleanEnabled": 0,
    "logRetentionDays": 0,
    "alarmDataAutoCleanEnabled": 0,
    "alarmDataRetentionDays": 0,
    "alarmDataMaxStorageMB": 0,
    "recordingDataAutoCleanEnabled": 0,
    "recordingDataRetentionDays": 0,
    "recordingDataMaxStorageMB": 0,
    "gb28181Provider": "wvp",
    "gb28181WvpBaseUrl": "",
    "gb28181WvpStartPlayUrlTemplate": "",
    "gb28181WvpStopPlayUrlTemplate": "",
    "gb28181WvpPtzControlUrlTemplate": "",
    "gb28181CustomBaseUrl": "",
    "gb28181CustomStartPlayUrlTemplate": "",
    "gb28181CustomStopPlayUrlTemplate": "",
    "gb28181CustomPtzControlUrlTemplate": "",
    "gb28181TransportMode": "",
    "gb28181StartupPolicy": "",
    "gb28181RequestParamPolicy": "",
    "gb28181RequestParamAllowlist": "",
    "gb28181RequestParamBlocklist": "",
    "gb28181HttpTimeoutSeconds": 8,
    "maxHardwareDecodeChannels": 0,
    "maxHardwareEncodeChannels": 0,
    "webrtcStunUrls": "",
    "webrtcTurnUrl": "",
    "webrtcTurnUsername": "",
    "webrtcTurnPassword": "",
    "webrtcSelfCheckTimeoutSeconds": 3,
    "openApiRateLimitEnabled": 0,
    "openApiRateLimitPerMinute": 60,
    "openApiRateLimitBurst": 10,
    "openApiWafEnabled": 0,
    "openApiWafMaxBodyBytes": 1048576,
    "cloudEnabled": 0,
    "cloudBaseUrl": "",
    "cloudEdgeToken": "",
}


def _config_json_path() -> str:
    """返回配置JSON路径。"""
    repo_root = os.path.dirname(str(BASE_DIR))
    return os.path.join(repo_root, "config.json")


def _read_json_file(filepath: str):
    """读取 JSON 配置文件。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="gbk") as f:
            return json.loads(f.read())
    except Exception:
        return {}


def _write_json_file_atomic(filepath: str, data: dict) -> None:
    """原子写入 JSON 配置文件。"""
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        f.write("\n")
    os.replace(tmp, filepath)


def _coerce_bool(value) -> bool:
    """处理`coerce`布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    raw = str(value or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _update_config_key(current: dict, key: str, value, *, list_csv_keys: set, bool_keys: set) -> None:
    """更新配置键。"""
    if key not in _RUNTIME_CONFIG_KEYS:
        return

    if key in list_csv_keys:
        if isinstance(value, list):
            current[key] = [str(item or "").strip() for item in value if str(item or "").strip()]
        else:
            current[key] = [part.strip() for part in str(value or "").split(",") if part.strip()]
        return

    if isinstance(current.get(key), bool) or key in bool_keys:
        current[key] = _coerce_bool(value)
        return

    current[key] = value


def _update_config_json(values: dict) -> None:
    """更新配置JSON。"""
    config_path = _config_json_path()
    current = _read_json_file(config_path) or {}
    if not isinstance(current, dict):
        current = {}

    list_csv_keys = set()
    bool_keys = set(_BOOL_INT_KEYS)

    for key, value in (values or {}).items():
        _update_config_key(current, key, value, list_csv_keys=list_csv_keys, bool_keys=bool_keys)

    _write_json_file_atomic(config_path, current)


def _normalize_default(key: str, config_json: dict):
    """执行归一化默认。"""
    default = config_json.get(key, _DEFAULTS.get(key, getattr(g_config, key, "")))
    if key == "webrtcStunUrls" and isinstance(default, list):
        return ",".join([str(item or "").strip() for item in default if str(item or "").strip()])
    return default


def _current_value(key: str, config_json: dict):
    """返回`current`值。"""
    if key in _UI_SETTINGS_KEYS:
        try:
            stored = settings_store.get_setting(key, None)
        except Exception:
            stored = None
        if stored not in (None, ""):
            return stored

    default = _normalize_default(key, config_json)
    if key in _BOOL_INT_KEYS or key in _INT_FIELD_LIMITS:
        try:
            return int(get_value(key, default))
        except Exception:
            try:
                return int(default)
            except Exception:
                return 0
    return str(get_value(key, default) or default or "")


def _build_system_context():
    """构建系统`context`。"""
    config_json = _read_json_file(_config_json_path()) or {}
    if not isinstance(config_json, dict):
        config_json = {}

    context = {key: _current_value(key, config_json) for key in _SYSTEM_KEYS.keys()}
    context["cloudEdgeTokenConfigured"] = bool(str(context.pop("cloudEdgeToken", "") or "").strip())
    context["softwareAutoStartWarning"] = ""
    return context


def system_page(request):
    """处理系统页面。"""
    return render(request, "app/config/system.html", _build_system_context())


def _clean_str(params, key: str, default=""):
    """处理清理字符串。"""
    raw = params.get(key, None)
    if raw is None:
        raw = default
    value = str(raw or "").strip()
    max_len = _STRING_LIMITS.get(key, 500)
    if len(value) > max_len:
        value = value[:max_len]
    return value


def _clean_int(params, key: str, default=0):
    """处理清理整数值。"""
    min_v, max_v = _INT_FIELD_LIMITS.get(key, (0, 3600))
    raw = params.get(key, None)
    try:
        value = int(str(raw).strip()) if raw is not None else int(default)
    except Exception:
        value = int(default)
    if value < min_v:
        value = min_v
    if value > max_v:
        value = max_v
    return value


def _clean_bool_int(params, key: str, default=0):
    """处理清理布尔值整数值。"""
    raw = params.get(key, None)
    if raw is None:
        return 1 if default else 0
    return 1 if _coerce_bool(raw) else 0


def _sanitize_system_key(params, key: str, *, default):
    """清洗系统键。"""
    if key in _BOOL_INT_KEYS:
        return _clean_bool_int(params, key, default=default)
    if key in _INT_FIELD_LIMITS:
        return _clean_int(params, key, default=default)
    return _clean_str(params, key, default=default)


def _normalize_sanitized_values(values: dict, posted_keys) -> None:
    """执行归一化`sanitized``values`。"""
    suffix = str(values.get("modelEncryptSuffix") or ".enc").strip() or ".enc"
    if not suffix.startswith("."):
        suffix = "." + suffix
    if len(suffix) > 10:
        suffix = ".enc"
    values["modelEncryptSuffix"] = suffix



def _sanitize_values(params, posted_keys):
    """清洗`values`。"""
    config_json = _read_json_file(_config_json_path()) or {}
    if not isinstance(config_json, dict):
        config_json = {}

    values = {}
    for key in _SYSTEM_KEYS.keys():
        default = _current_value(key, config_json)
        values[key] = _sanitize_system_key(params, key, default=default)

    # Normalizations used in tests.
    _normalize_sanitized_values(values, posted_keys)

    return values


def _update_runtime_config(values, posted_keys):
    """更新运行时配置。"""
    for key in posted_keys:
        if key not in values:
            continue
        try:
            setattr(g_config, key, values[key])
        except Exception:
            logger.debug("suppressed exception in app/views/SystemConfigView.py:500", exc_info=True)

    if "webrtcStunUrls" in posted_keys:
        g_config.webrtcStunUrls = [item.strip() for item in str(values.get("webrtcStunUrls") or "").split(",") if item.strip()]


_REQUIRED_FIELDS_WHEN_ENABLED = (
    ("modelEncrypt", "modelEncryptKey", "modelEncryptKey is required when modelEncrypt=1"),
    ("cloudEnabled", "cloudBaseUrl", "请输入 Beacon Cloud 地址"),
    ("cloudEnabled", "cloudEdgeToken", "请输入 Edge Token"),
)


def _validate_required_when_enabled(values: dict) -> str:
    """判断`validate``required``when`是否启用。"""
    for enabled_key, required_key, msg in _REQUIRED_FIELDS_WHEN_ENABLED:
        if int(values.get(enabled_key) or 0) != 1:
            continue
        if str(values.get(required_key) or "").strip():
            continue
        return str(msg or "")
    return ""


def _validate_cloud_base_url(values: dict) -> str:
    """校验云平台地址。"""
    if int(values.get("cloudEnabled") or 0) != 1:
        return ""
    parsed = urlsplit(str(values.get("cloudBaseUrl") or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "云平台地址必须是完整的 http:// 或 https:// 地址"
    if parsed.username or parsed.password:
        return "云平台地址不能包含用户名或密码"
    return ""


def _apply_software_autostart_best_effort(values: dict, posted_keys) -> str:
    """尽力处理应用软件`autostart`。"""
    if "software_auto_start" not in posted_keys:
        return ""

    from app.utils.AutoStart import apply_autostart

    try:
        enabled = bool(int(values.get("software_auto_start") or 0))
        ok, detail = apply_autostart(enabled=enabled)
        if not ok:
            return str(detail or "unknown error")
    except Exception as e:
        return str(e)

    return ""


def api_save_system(request):
    """处理 `save_system` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "request method not supported"})

    before_snapshot = build_system_snapshot()
    params = f_parsePostParams(request)
    posted_keys = set((params or {}).keys()) if isinstance(params, dict) else set()
    values = _sanitize_values(params or {}, posted_keys)

    err = _validate_required_when_enabled(values)
    if err:
        return f_responseJson({"code": 0, "msg": err})
    err = _validate_cloud_base_url(values)
    if err:
        return f_responseJson({"code": 0, "msg": err})

    software_autostart_warning = _apply_software_autostart_best_effort(values, posted_keys)

    ui_values = {key: values[key] for key in _UI_SETTINGS_KEYS if key in posted_keys}
    runtime_values = {key: values[key] for key in _RUNTIME_CONFIG_KEYS if key in posted_keys}

    if ui_values:
        settings_store.update_settings(ui_values)

    for key, meta in _SYSTEM_KEYS.items():
        if key not in posted_keys:
            continue
        set_value(key, str(values[key]), remark=str(meta.get("remark") or ""))

    if runtime_values:
        _update_config_json(runtime_values)

    _update_runtime_config(values, posted_keys)

    response_data = {key: values[key] for key in posted_keys if key in values and key != "cloudEdgeToken"}
    if "cloudEdgeToken" in posted_keys:
        response_data["cloudEdgeTokenConfigured"] = bool(str(values.get("cloudEdgeToken") or "").strip())
    if software_autostart_warning:
        response_data["softwareAutoStartWarning"] = software_autostart_warning

    actor = str((getUser(request) or {}).get("username") or "").strip()
    after_snapshot = build_system_snapshot()
    summary = "system.save:" + ",".join(sorted([key for key in posted_keys if key in _SYSTEM_KEYS]))
    record_system_change(
        actor=actor,
        change_type="system.save",
        summary=summary,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )

    return f_responseJson({"code": 1000, "msg": "success", "data": response_data})


def api_history_rollback(request):
    """处理 `history_rollback` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": "request method not supported"})

    params = f_parsePostParams(request)
    try:
        snapshot_id = int(params.get("snapshot_id") or 0)
    except Exception:
        snapshot_id = 0
    if snapshot_id <= 0:
        return f_responseJson({"code": 0, "msg": "snapshot_id is required"})

    confirm = str(params.get("confirm") or "").strip().lower()
    if confirm != "rollback":
        return f_responseJson({"code": 0, "msg": "confirm=rollback is required"})

    entry = ConfigHistorySnapshot.objects.filter(id=snapshot_id).first()
    if not entry:
        return f_responseJson({"code": 0, "msg": "snapshot not found"})

    target_snapshot = snapshot_payload(entry)
    if not target_snapshot:
        return f_responseJson({"code": 0, "msg": "snapshot payload is invalid"})

    before_snapshot = build_system_snapshot()
    if snapshot_equals(before_snapshot, target_snapshot):
        return f_responseJson({"code": 0, "msg": "snapshot already active"})

    apply_system_snapshot(target_snapshot)

    actor = str((getUser(request) or {}).get("username") or "").strip()
    after_snapshot = build_system_snapshot()
    ConfigHistorySnapshot.objects.create(
        scope="system",
        change_type="system.rollback",
        actor=actor,
        summary="rollback:%s" % snapshot_id,
        snapshot_json=json.dumps(after_snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        diff_json=json.dumps([], ensure_ascii=False),
        rollback_of=entry,
    )
    return f_responseJson({"code": 1000, "msg": "success", "data": {"snapshot_id": snapshot_id}})
