import json
import os
import logging
import re
from framework.settings import BASE_DIR


logger = logging.getLogger(__name__)

HTTP_PREFIX = "http://"
TRUTHY_CONFIG_VALUES = ("1", "true", "yes", "y", "on")
CONFIG_ALIAS_BOUNDARY_1 = re.compile(r"(.)([A-Z][a-z]+)")
CONFIG_ALIAS_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")
CONFIG_ALIAS_EXTRAS = {
    "upload_dir_www": ("uploadDir_www",),
}


def _legacy_config_field_alias(name: str) -> str:
    """Map legacy camelCase config attribute names to snake_case attributes."""
    value = str(name or "")
    value = CONFIG_ALIAS_BOUNDARY_1.sub(r"\1_\2", value)
    return CONFIG_ALIAS_BOUNDARY_2.sub(r"\1_\2", value).lower()


def _snake_config_field_legacy_names(name: str) -> tuple:
    """Return legacy names mirrored for a snake_case config attribute."""
    if not name or name.startswith("_"):
        return ()
    parts = str(name).split("_")
    camel_name = parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:] if part)
    names = [camel_name] if camel_name != name else []
    for legacy_name in CONFIG_ALIAS_EXTRAS.get(name, ()):
        if legacy_name not in names:
            names.append(legacy_name)
    return tuple(names)


def _load_config_data(filepath: str) -> dict:
    """加载配置数据。"""
    try:
        with open(filepath, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="gbk") as file_obj:
            content = file_obj.read()
    return json.loads(content)


def _config_bool_value(raw_value) -> bool:
    """返回配置布尔值值。"""
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value or "").strip().lower() in TRUTHY_CONFIG_VALUES


def _config_bool_from_env(config_data, *, env_key: str, json_key: str, default=False, environ=None) -> bool:
    """从环境变量获取配置布尔值。"""
    environ = environ if environ is not None else os.environ
    raw_value = environ.get(env_key)
    if raw_value is None:
        raw_value = config_data.get(json_key, default)
    return _config_bool_value(raw_value)


def _config_text_from_env(config_data, *, env_key: str, json_key: str, default: str = "", environ=None) -> str:
    """从环境变量获取配置文本。"""
    environ = environ if environ is not None else os.environ
    raw_value = environ.get(env_key)
    if raw_value:
        return str(raw_value).strip()
    return str(config_data.get(json_key, default) or default).strip()


def _config_text_from_nonempty_env(config_data, *, env_key: str, json_key: str, default: str = "", environ=None) -> str:
    """从非空环境变量获取配置文本。"""
    environ = environ if environ is not None else os.environ
    raw_value = environ.get(env_key)
    if raw_value is not None:
        stripped = str(raw_value or "").strip()
        if stripped:
            return stripped
    return str(config_data.get(json_key, default) or default).strip()


def _compose_service_url(host: str, port, *, scheme: str = "http") -> str:
    """组合服务 URL。"""
    normalized_host = str(host or "").strip() or "127.0.0.1"
    normalized_port = str(port or "").strip()
    return f"{scheme}://{normalized_host}:{normalized_port}"


def _config_list_from_env(config_data, *, env_key: str, json_key: str, default=None, environ=None) -> list:
    """从环境变量获取配置列表。"""
    environ = environ if environ is not None else os.environ
    raw_value = environ.get(env_key)
    if raw_value is None:
        raw_value = config_data.get(json_key, [] if default is None else default)
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]


def _clamp_int(raw_value, *, default: int, min_value=None, max_value=None) -> int:
    """限制整数值。"""
    try:
        value = int(raw_value or default)
    except Exception:
        value = int(default)
    if min_value is not None and value < int(min_value):
        value = int(min_value)
    if max_value is not None and value > int(max_value):
        value = int(max_value)
    return int(value)


def _config_int_from_env(
    config_data,
    *,
    env_key: str,
    json_key: str,
    default: int,
    min_value=None,
    max_value=None,
    environ=None,
) -> int:
    """从环境变量获取配置整数值。"""
    environ = environ if environ is not None else os.environ
    raw_value = environ.get(env_key)
    if raw_value is None or raw_value == "":
        raw_value = config_data.get(json_key, default)
    return _clamp_int(raw_value, default=default, min_value=min_value, max_value=max_value)


def _config_int_value(config_data, *, json_key: str, default: int, min_value=None, max_value=None) -> int:
    """返回配置整数值值。"""
    return _clamp_int(config_data.get(json_key, default), default=default, min_value=min_value, max_value=max_value)


def _looks_like_windows_drive_path(value: str) -> bool:
    """返回外观`like``windows``drive`路径。"""
    if not value or len(value) < 3:
        return False
    drive = value[0]
    return drive.isalpha() and value[1] == ":" and value[2] in ("\\", "/")


def _resolve_config_dir(
    *,
    raw_value,
    base_dir_parent: str,
    default_relative: str,
    json_key: str,
    platform_name=None,
) -> str:
    """解析并返回配置目录。"""
    raw = str(raw_value or "").strip() or str(default_relative or "").strip()
    platform_name = os.name if platform_name is None else str(platform_name)
    if platform_name != "nt" and _looks_like_windows_drive_path(raw):
        logger.warning(
            "config.%s looks like a Windows path on non-Windows: %s; fallback to %s",
            json_key,
            raw,
            default_relative,
        )
        raw = str(default_relative or "").strip()
    is_windows_abs = _looks_like_windows_drive_path(raw)
    if not os.path.isabs(raw) and not is_windows_abs:
        raw = os.path.join(base_dir_parent, raw)
    return os.path.normpath(raw)


def _ensure_dir(path: str) -> None:
    """返回`ensure`目录。"""
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


class Config:
    def __getattr__(self, name):
        """Read legacy camelCase config attributes from their snake_case storage."""
        alias = _legacy_config_field_alias(name)
        if alias == name:
            raise AttributeError(name)
        try:
            return object.__getattribute__(self, alias)
        except AttributeError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        """Write legacy camelCase config attributes to their snake_case storage."""
        alias = _legacy_config_field_alias(name)
        object.__setattr__(self, alias, value)
        values = object.__getattribute__(self, "__dict__")
        for legacy_name in _snake_config_field_legacy_names(alias):
            values[legacy_name] = value

    def __delattr__(self, name):
        """Delete config attributes consistently across snake_case and legacy aliases."""
        alias = _legacy_config_field_alias(name)
        values = object.__getattribute__(self, "__dict__")
        names = (name, alias, *_snake_config_field_legacy_names(alias))
        deleted = False
        for attr_name in names:
            if attr_name in values:
                del values[attr_name]
                deleted = True
        if not deleted:
            raise AttributeError(name)

    def __init__(self):
        """处理`init`。"""
        base_dir_parent_dir = os.path.dirname(BASE_DIR)
        filepath = os.path.join(base_dir_parent_dir, "config.json")
        debug_startup_logs = os.environ.get("DJANGO_DEBUG_STARTUP_LOGS") == "1"
        if debug_startup_logs:
            logger.debug("Config.__init__ file=%s", os.path.abspath(__file__))
            logger.debug("Config.__init__ filepath=%s", filepath)

        config_data = _load_config_data(filepath)
        self._init_site_identity(config_data)
        self._init_network_and_media_settings(config_data)
        self._init_path_and_model_settings(config_data, base_dir_parent_dir)
        self._init_alarm_precheck_settings(config_data)
        self._init_file_service_settings(config_data, base_dir_parent_dir)
        self._init_webrtc_settings(config_data)
        self._init_alarm_delivery_settings(config_data)
        self._init_runtime_storage_settings(config_data)
        self._init_cloud_settings(config_data)
        self._init_gb28181_settings(config_data)

    def _init_site_identity(self, config_data) -> None:
        """处理`init``site``identity`。"""
        self.code = config_data.get("code")
        self.name = config_data.get("name")
        self.describe = config_data.get("describe")
        self.site_name = config_data.get("siteName", self.name or "Beacon")
        self.site_title = config_data.get("siteTitle", "Beacon 新一代 AI 视频分析系统")
        self.site_logo = config_data.get("siteLogo", "/static/images/logo.png")
        self.author_name = config_data.get("authorName", "")
        self.author_link = config_data.get("authorLink", "")
        self.site_icp = config_data.get("siteIcp", "")
        self.custom_css = config_data.get("customCss", "")
        self.custom_script = config_data.get("customScript", "")
        self.login_bg = config_data.get("loginBg", "")
        self.login_captcha_enabled = _config_bool_from_env(
            config_data,
            env_key="BEACON_LOGIN_CAPTCHA_ENABLED",
            json_key="loginCaptchaEnabled",
            default=False,
        )

    def _init_network_and_media_settings(self, config_data) -> None:
        """处理`init``network``and`媒体设置。"""
        self.host = config_data.get("host")
        raw_host = str(self.host or "").strip()
        self.internal_host = "127.0.0.1" if raw_host in ("0.0.0.0", "::") else raw_host or "127.0.0.1"
        self.admin_port = config_data.get("adminPort")
        self.analyzer_port = config_data.get("analyzerPort")
        self.media_http_port = config_data.get("mediaHttpPort")
        self.media_rtsp_port = config_data.get("mediaRtspPort")
        self.media_rtmp_port = config_data.get("mediaRtmpPort", 1935)
        admin_host = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_ADMIN_HOST",
            json_key="adminHost",
            default=self.internal_host,
        )
        analyzer_host = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_ANALYZER_HOST",
            json_key="analyzerHost",
            default=self.internal_host,
        )
        media_host = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_MEDIA_HOST",
            json_key="mediaHost",
            default=_config_text_from_nonempty_env(
                config_data,
                env_key="BEACON_MEDIA_SERVER_HOST",
                json_key="mediaServerHost",
                default=self.internal_host,
            ),
        )
        self.admin_host = _compose_service_url(admin_host, self.admin_port, scheme="http")
        self.analyzer_host = _compose_service_url(analyzer_host, self.analyzer_port, scheme="http")
        self.open_api_token = _config_text_from_env(
            config_data,
            env_key="BEACON_OPEN_API_TOKEN",
            json_key="openApiToken",
            default="",
        )
        self.media_http_host = _compose_service_url(media_host, self.media_http_port, scheme="http")
        self.media_ws_host = _compose_service_url(media_host, self.media_http_port, scheme="ws")
        self.media_rtsp_host = _compose_service_url(media_host, self.media_rtsp_port, scheme="rtsp")
        self.media_rtmp_host = _compose_service_url(media_host, self.media_rtmp_port, scheme="rtmp")
        self.media_secret = _config_text_from_env(
            config_data,
            env_key="BEACON_MEDIA_SECRET",
            json_key="mediaSecret",
            default="",
        )

    def _init_path_and_model_settings(self, config_data, base_dir_parent_dir: str) -> None:
        """处理`init`路径`and`模型设置。"""
        self.upload_dir = _resolve_config_dir(
            raw_value=os.environ.get("BEACON_UPLOAD_DIR") or config_data.get("uploadDir", ""),
            base_dir_parent=base_dir_parent_dir,
            default_relative="Admin/static/upload",
            json_key="uploadDir",
        )
        self.model_dir = _resolve_config_dir(
            raw_value=os.environ.get("BEACON_MODEL_DIR") or config_data.get("modelDir", ""),
            base_dir_parent=base_dir_parent_dir,
            default_relative="Analyzer/models",
            json_key="modelDir",
        )
        self.save_alarm_type = int(config_data.get("saveAlarmType", 1))
        self.save_alarm_url = str(config_data.get("saveAlarmUrl", "") or "").strip()
        self.alarm_upload_include_base64 = _config_bool_from_env(
            config_data,
            env_key="BEACON_ALARM_UPLOAD_INCLUDE_BASE64",
            json_key="alarmUploadIncludeBase64",
            default=True,
        )
        self.version_check_url = str(config_data.get("versionCheckUrl", "") or "").strip()
        self.alarm_video_seconds = int(config_data.get("alarmVideoSeconds", 0) or 0)
        self.alarm_push_delay_seconds = int(config_data.get("alarmPushDelaySeconds", 0) or 0)
        model_cache_default = int(config_data.get("modelCacheTime", 0) or 0)
        self.model_cache_seconds = _config_int_from_env(
            config_data,
            env_key="BEACON_MODEL_CACHE_SECONDS",
            json_key="modelCacheSeconds",
            default=model_cache_default,
            min_value=0,
            max_value=30 * 24 * 3600,
        )
        self.license_type = _config_text_from_env(
            config_data,
            env_key="BEACON_LICENSE_TYPE",
            json_key="licenseType",
            default="community",
        )
        self.license_key = _config_text_from_env(
            config_data,
            env_key="BEACON_LICENSE_KEY",
            json_key="licenseKey",
            default="",
        )
        self.license_dongle_cmd = str(config_data.get("licenseDongleCmd", "") or "")
        self.license_dongle_file = str(config_data.get("licenseDongleFile", "") or "")
        self.model_encrypt = _config_bool_from_env(
            config_data,
            env_key="BEACON_MODEL_ENCRYPT",
            json_key="modelEncrypt",
            default=False,
        )
        self.model_encrypt_key = _config_text_from_env(
            config_data,
            env_key="BEACON_MODEL_ENCRYPT_KEY",
            json_key="modelEncryptKey",
            default="",
        )
        self.model_encrypt_suffix = _config_text_from_env(
            config_data,
            env_key="BEACON_MODEL_ENCRYPT_SUFFIX",
            json_key="modelEncryptSuffix",
            default=".enc",
        ) or ".enc"
        self.model_decrypt_dir = _config_text_from_env(
            config_data,
            env_key="BEACON_MODEL_DECRYPT_DIR",
            json_key="modelDecryptDir",
            default="",
        )
        self.face_default_feature_algorithm_code = _config_text_from_env(
            config_data,
            env_key="BEACON_FACE_DEFAULT_FEATURE_ALGORITHM_CODE",
            json_key="faceDefaultFeatureAlgorithmCode",
            default="",
        )
        self.upload_alarm_dir = os.path.join(self.upload_dir, "alarm")
        self.upload_dir_www = "/static/upload/"

    def _init_alarm_precheck_settings(self, config_data) -> None:
        """处理`init`告警预检设置。"""
        self.alarm_ai_review_enabled = _config_bool_from_env(
            config_data,
            env_key="BEACON_ALARM_AI_REVIEW_ENABLED",
            json_key="alarmAiReviewEnabled",
            default=False,
        )
        self.alarm_precheck_enabled = _config_bool_from_env(
            config_data,
            env_key="BEACON_ALARM_PRECHECK_ENABLED",
            json_key="alarmPrecheckEnabled",
            default=False,
        )
        self.alarm_precheck_url = _config_text_from_env(
            config_data,
            env_key="BEACON_ALARM_PRECHECK_URL",
            json_key="alarmPrecheckUrl",
            default="",
        )
        self.alarm_precheck_timeout_seconds = _config_int_from_env(
            config_data,
            env_key="BEACON_ALARM_PRECHECK_TIMEOUT_SECONDS",
            json_key="alarmPrecheckTimeoutSeconds",
            default=5,
            min_value=1,
            max_value=60,
        )
        self.alarm_precheck_fail_open = _config_bool_from_env(
            config_data,
            env_key="BEACON_ALARM_PRECHECK_FAIL_OPEN",
            json_key="alarmPrecheckFailOpen",
            default=True,
        )

    def _init_file_service_settings(self, config_data, base_dir_parent_dir: str) -> None:
        """处理`init`文件`service`设置。"""
        self.file_service_enabled = _config_bool_from_env(
            config_data,
            env_key="BEACON_FILE_SERVICE_ENABLED",
            json_key="fileServiceEnabled",
            default=False,
        )
        env_root = str(os.environ.get("BEACON_FILE_SERVICE_ROOT_DIR") or "").strip()
        if env_root:
            raw_root = env_root
        else:
            configured_root = str(config_data.get("fileServiceRootDir", "") or "").strip()
            configured_upload_dir = str(config_data.get("uploadDir", "") or "").strip()
            upload_dir_overridden = bool(str(os.environ.get("BEACON_UPLOAD_DIR") or "").strip())
            if upload_dir_overridden and (not configured_root or configured_root == configured_upload_dir):
                raw_root = self.upload_dir
            else:
                raw_root = configured_root
        if raw_root:
            is_windows_abs = _looks_like_windows_drive_path(raw_root)
            if not os.path.isabs(raw_root) and not is_windows_abs:
                raw_root = os.path.join(base_dir_parent_dir, raw_root)
        self.file_service_root_dir = raw_root

    def _init_webrtc_settings(self, config_data) -> None:
        """处理`init``webrtc`设置。"""
        self.webrtc_stun_urls = _config_list_from_env(
            config_data,
            env_key="BEACON_WEBRTC_STUN_URLS",
            json_key="webrtcStunUrls",
            default=[],
        )
        self.webrtc_turn_url = _config_text_from_env(
            config_data,
            env_key="BEACON_WEBRTC_TURN_URL",
            json_key="webrtcTurnUrl",
            default="",
        )
        self.webrtc_turn_username = _config_text_from_env(
            config_data,
            env_key="BEACON_WEBRTC_TURN_USERNAME",
            json_key="webrtcTurnUsername",
            default="",
        )
        self.webrtc_turn_password = _config_text_from_env(
            config_data,
            env_key="BEACON_WEBRTC_TURN_PASSWORD",
            json_key="webrtcTurnPassword",
            default="",
        )
        self.webrtc_self_check_timeout_seconds = _config_int_from_env(
            config_data,
            env_key="BEACON_WEBRTC_SELFCHECK_TIMEOUT_SECONDS",
            json_key="webrtcSelfCheckTimeoutSeconds",
            default=3,
            min_value=1,
            max_value=30,
        )

    def _init_alarm_delivery_settings(self, config_data) -> None:
        """处理`init`告警`delivery`设置。"""
        self._init_alarm_webhook_settings(config_data)
        self._init_alarm_outbox_settings(config_data)

    def _init_alarm_webhook_settings(self, config_data) -> None:
        """处理`init`告警Webhook设置。"""
        self.alarm_webhook_enabled = bool(config_data.get("alarmWebhookEnabled", False))
        self.alarm_webhook_urls = _config_list_from_env(
            config_data,
            env_key="BEACON_ALARM_WEBHOOK_URLS",
            json_key="alarmWebhookUrls",
            default=[],
        )
        if self.alarm_webhook_urls:
            self.alarm_webhook_enabled = True
        self.alarm_webhook_secret = _config_text_from_env(
            config_data,
            env_key="BEACON_ALARM_WEBHOOK_SECRET",
            json_key="alarmWebhookSecret",
            default="",
        )
        self.alarm_webhook_timeout_seconds = _config_int_from_env(
            config_data,
            env_key="BEACON_ALARM_WEBHOOK_TIMEOUT_SECONDS",
            json_key="alarmWebhookTimeoutSeconds",
            default=5,
            min_value=1,
            max_value=30,
        )

    def _init_alarm_outbox_settings(self, config_data) -> None:
        """处理`init`告警`outbox`设置。"""
        self.alarm_outbox_enabled = bool(config_data.get("alarmOutboxEnabled", True))
        self.alarm_outbox_poll_seconds = _config_int_value(
            config_data,
            json_key="alarmOutboxPollSeconds",
            default=2,
            min_value=1,
            max_value=10,
        )
        self.alarm_outbox_max_batch = _config_int_value(
            config_data,
            json_key="alarmOutboxMaxBatch",
            default=50,
            min_value=1,
            max_value=200,
        )
        self.alarm_outbox_retention_hours = _config_int_value(
            config_data,
            json_key="alarmOutboxRetentionHours",
            default=72,
            min_value=1,
        )
        self.alarm_compose_cache_retention_hours = _config_int_value(
            config_data,
            json_key="alarmComposeCacheRetentionHours",
            default=72,
            min_value=1,
        )
        self.transcode_idle_seconds = _config_int_value(
            config_data,
            json_key="transcodeIdleSeconds",
            default=300,
            min_value=30,
        )
        self.transcode_start_cooldown_seconds = _config_int_value(
            config_data,
            json_key="transcodeStartCooldownSeconds",
            default=5,
            min_value=1,
        )

    def _init_runtime_storage_settings(self, config_data) -> None:
        """处理`init`运行时存储设置。"""
        self.storage_root_path = str(config_data.get("storageRootPath", "") or "").strip() or self.upload_dir
        _ensure_dir(self.storage_root_path)
        self.alarm_storage_path = os.path.join(self.storage_root_path, "alarm")
        self.recording_storage_path = os.path.join(self.storage_root_path, "recordings")
        self.snapshot_storage_path = os.path.join(self.storage_root_path, "snapshots")
        _ensure_dir(self.alarm_storage_path)
        _ensure_dir(self.recording_storage_path)
        _ensure_dir(self.snapshot_storage_path)

    def _init_cloud_settings(self, config_data) -> None:
        """处理`init`云端设置。"""
        self.cloud_enabled = _config_bool_from_env(
            config_data,
            env_key="BEACON_CLOUD_ENABLED",
            json_key="cloudEnabled",
            default=False,
        )
        self.cloud_base_url = _config_text_from_env(
            config_data,
            env_key="BEACON_CLOUD_BASE_URL",
            json_key="cloudBaseUrl",
            default="",
        )
        self.cloud_edge_token = _config_text_from_env(
            config_data,
            env_key="BEACON_CLOUD_EDGE_TOKEN",
            json_key="cloudEdgeToken",
            default="",
        )
        self.cloud_upload_timeout_seconds = _clamp_int(
            os.environ.get("BEACON_CLOUD_UPLOAD_TIMEOUT_SECONDS"),
            default=10,
            min_value=1,
            max_value=60,
        )
        self.cloud_ingest_timeout_seconds = _clamp_int(
            os.environ.get("BEACON_CLOUD_INGEST_TIMEOUT_SECONDS"),
            default=5,
            min_value=1,
            max_value=60,
        )

    def _init_gb28181_settings(self, config_data) -> None:
        """处理`init``gb28181`设置。"""
        self.gb28181_provider = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_PROVIDER",
            json_key="gb28181Provider",
            default="wvp",
        ).strip().lower() or "wvp"
        self.gb28181_wvp_base_url = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_WVP_BASE_URL",
            json_key="gb28181WvpBaseUrl",
            default="",
        )
        self.gb28181_wvp_start_play_url_template = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_WVP_START_PLAY_URL_TEMPLATE",
            json_key="gb28181WvpStartPlayUrlTemplate",
            default="",
        )
        self.gb28181_wvp_stop_play_url_template = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_WVP_STOP_PLAY_URL_TEMPLATE",
            json_key="gb28181WvpStopPlayUrlTemplate",
            default="",
        )
        self.gb28181_wvp_ptz_control_url_template = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_WVP_PTZ_CONTROL_URL_TEMPLATE",
            json_key="gb28181WvpPtzControlUrlTemplate",
            default="",
        )
        self.gb28181_custom_base_url = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_CUSTOM_BASE_URL",
            json_key="gb28181CustomBaseUrl",
            default="",
        )
        self.gb28181_custom_start_play_url_template = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_CUSTOM_START_PLAY_URL_TEMPLATE",
            json_key="gb28181CustomStartPlayUrlTemplate",
            default="",
        )
        self.gb28181_custom_stop_play_url_template = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_CUSTOM_STOP_PLAY_URL_TEMPLATE",
            json_key="gb28181CustomStopPlayUrlTemplate",
            default="",
        )
        self.gb28181_custom_ptz_control_url_template = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_CUSTOM_PTZ_CONTROL_URL_TEMPLATE",
            json_key="gb28181CustomPtzControlUrlTemplate",
            default="",
        )
        self.gb28181_transport_mode = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_TRANSPORT_MODE",
            json_key="gb28181TransportMode",
            default="",
        )
        self.gb28181_startup_policy = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_STARTUP_POLICY",
            json_key="gb28181StartupPolicy",
            default="",
        )
        self.gb28181_request_param_policy = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_REQUEST_PARAM_POLICY",
            json_key="gb28181RequestParamPolicy",
            default="",
        )
        self.gb28181_request_param_allowlist = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_REQUEST_PARAM_ALLOWLIST",
            json_key="gb28181RequestParamAllowlist",
            default="",
        )
        self.gb28181_request_param_blocklist = _config_text_from_nonempty_env(
            config_data,
            env_key="BEACON_GB28181_REQUEST_PARAM_BLOCKLIST",
            json_key="gb28181RequestParamBlocklist",
            default="",
        )
        self.gb28181_http_timeout_seconds = _config_int_from_env(
            config_data,
            env_key="BEACON_GB28181_HTTP_TIMEOUT_SECONDS",
            json_key="gb28181HttpTimeoutSeconds",
            default=8,
            min_value=1,
            max_value=60,
        )


    def __del__(self):
        """处理`del`。
        
        No-op destructor.
        
                Kept for backward compatibility; this class does not manage external resources
                and should not raise during GC/shutdown.
        """
        pass

    def show(self):
        """处理`show`。
        
        Legacy placeholder method.
        
                Older versions exposed Config.show() for debugging, but current code reads
                config via attributes and logging. Keep this method to avoid breaking
                external callers.
        """
        pass
