import json

from app.utils.PermissionCoerce import coerce_permission_bool


_PERMISSION_CATALOG = (
    {"key": "streams", "name": "Streams (Legacy)", "desc": "Legacy stream module access for existing permission records."},
    {"key": "streams.view", "name": "Streams: View", "desc": "View stream pages and read-oriented stream endpoints."},
    {"key": "talkback", "name": "Talkback", "desc": "Use stream talkback configuration and live talkback controls."},
    {"key": "controls", "name": "Controls", "desc": "Access control rules and control execution pages."},
    {"key": "alarms", "name": "Alarms (Legacy)", "desc": "Legacy alarm module access for existing permission records."},
    {"key": "alarms.view", "name": "Alarms: View", "desc": "View alarm review lists, detail pages, and alarm sound pages."},
    {"key": "alarms.export", "name": "Alarms: Export", "desc": "Export alarm evidence and dataset packages."},
    {"key": "algorithms", "name": "Algorithms", "desc": "Manage the algorithm catalog and versions."},
    {"key": "recording", "name": "Recording", "desc": "Access recording plans, playback, and snapshot features."},
    {"key": "face", "name": "Face", "desc": "Manage face libraries and related search flows."},
    {"key": "onvif", "name": "ONVIF", "desc": "Discover ONVIF devices and import them into Beacon."},
    {"key": "system", "name": "System (Legacy)", "desc": "Legacy config and system management access for existing permission records."},
    {"key": "config.view", "name": "Config: View", "desc": "Open configuration overview, import, and export pages."},
    {"key": "config.export", "name": "Config: Export", "desc": "Export system configuration and diagnostics-style config bundles."},
    {"key": "config.manage", "name": "Config: Manage", "desc": "Import configuration and save system settings."},
    {"key": "license", "name": "License", "desc": "Access license manager and lease details."},
    {"key": "ops", "name": "Ops (Legacy)", "desc": "Legacy ops module access for existing permission records."},
    {"key": "ops.audit.view", "name": "Ops Audit: View", "desc": "View the audit center and list audit events."},
    {"key": "ops.audit.export", "name": "Ops Audit: Export", "desc": "Export audit data from the ops audit center."},
    {"key": "cloud", "name": "Cloud", "desc": "Access Beacon cloud and edge fleet pages."},
    {"key": "developer", "name": "Developer", "desc": "Access developer documentation and integration endpoints."},
)

PERMISSION_META = list(_PERMISSION_CATALOG)
PERMISSION_KEYS = tuple(item["key"] for item in _PERMISSION_CATALOG)

# Frequently-used permission keys (reduce literal duplication for static analysis).
PERM_STREAMS_VIEW = "streams.view"
PERM_ALARMS_VIEW = "alarms.view"
PERM_ALARMS_EXPORT = "alarms.export"
PERM_CONFIG_VIEW = "config.view"
PERM_CONFIG_EXPORT = "config.export"
PERM_CONFIG_MANAGE = "config.manage"
PERM_OPS_AUDIT_VIEW = "ops.audit.view"
PERM_OPS_AUDIT_EXPORT = "ops.audit.export"

# Some Beacon deployments still rely on legacy module-level permission keys
# (e.g. "alarms") while newer screens check granular keys (e.g. "alarms.view").
# Keep these aliases centralized so features like "share to permission role"
# can match both representations consistently.
PERMISSION_KEY_ALIASES = {
    PERM_STREAMS_VIEW: (PERM_STREAMS_VIEW, "streams"),
    PERM_ALARMS_VIEW: (PERM_ALARMS_VIEW, "alarms"),
    PERM_ALARMS_EXPORT: (PERM_ALARMS_EXPORT, "alarms"),
    PERM_CONFIG_VIEW: (PERM_CONFIG_VIEW, "system"),
    PERM_CONFIG_EXPORT: (PERM_CONFIG_EXPORT, "system"),
    PERM_CONFIG_MANAGE: (PERM_CONFIG_MANAGE, "system"),
    PERM_OPS_AUDIT_VIEW: (PERM_OPS_AUDIT_VIEW, "ops"),
    PERM_OPS_AUDIT_EXPORT: (PERM_OPS_AUDIT_EXPORT, "ops"),
}

# URL path to permission candidates mapping rules.
_EXPLICIT_PATH_RULES = (
    (("stream/talkback/", "stream/talkback", "api/app-shell/stream/action/talkback/"), ("talkback",)),
    (
        (
            "api/app-shell/streams",
            "api/app-shell/stream-online",
            "api/app-shell/stream-player",
            "api/app-shell/stream/action/",
        ),
        (PERM_STREAMS_VIEW, "streams"),
    ),
    (
        (
            "api/app-shell/control/action/",
            "api/app-shell/control/editor",
            "api/app-shell/control/osd-assets",
            "api/app-shell/control/logs",
        ),
        ("controls",),
    ),
    (
        (
            "api/app-shell/algorithms",
            "api/app-shell/algorithm/versions",
            "api/app-shell/algorithm/action/",
        ),
        ("algorithms",),
    ),
    (
        (
            "api/app-shell/onvif",
            "api/app-shell/onvif/action/",
        ),
        ("onvif",),
    ),
    (("ops/audit/export",), (PERM_OPS_AUDIT_EXPORT, "ops")),
    (("ops/audit/api/list", "ops/audit"), (PERM_OPS_AUDIT_VIEW, "ops")),
    (
        (
            "config/api/logs/export",
            "config/api/export",
            "api/app-shell/config/action/logs/export",
            "api/app-shell/config/action/export",
        ),
        (PERM_CONFIG_EXPORT, "system"),
    ),
    (
        (
            "config/api/history/rollback",
            "config/api/preview",
            "config/api/import",
            "config/api/system/save",
            "api/app-shell/config/action/history/rollback",
            "api/app-shell/config/action/preview",
            "api/app-shell/config/action/import",
            "api/app-shell/config/action/system/save",
        ),
        (PERM_CONFIG_MANAGE, "system"),
    ),
    (("config/api/history/",), (PERM_CONFIG_VIEW, "system")),
    (("config/history", "config/export", "config/import", "config/system", "api/app-shell/config"), (PERM_CONFIG_VIEW, "system")),
    (
        (
            "alarm/exportEvidence",
            "alarm/exportLabelme",
            "alarm/exportCoco",
            "api/app-shell/alarm/action/exportEvidence",
            "api/app-shell/alarm/action/exportLabelme",
            "api/app-shell/alarm/action/exportCoco",
        ),
        (PERM_ALARMS_EXPORT, "alarms"),
    ),
    (
        (
            "alarms",
            "alarm/review",
            "alarm/detail",
            "alarm/workflow",
            "alarm/assignment",
            "alarm/api/",
            "api/postHandleAlarm",
            "alarm/preset/",
            "alarm_sound/",
            "api/app-shell/alarms",
            "api/app-shell/alarm/detail",
            "api/app-shell/alarm-sounds",
            "api/app-shell/alarm-presets/save",
            "api/app-shell/alarm-presets/delete",
            "api/app-shell/alarm/action/",
            "api/app-shell/alarm-sound/action/",
        ),
        (PERM_ALARMS_VIEW, "alarms"),
    ),
)

_MODULE_PATH_RULES = (
    (("stream/", "stream"), (PERM_STREAMS_VIEW, "streams")),
    (("controls", "control/"), ("controls",)),
    (("algorithm/", "pipeline/"), ("algorithms",)),
    (("recording/",), ("recording",)),
    (("face/",), ("face",)),
    (("onvif/",), ("onvif",)),
    (("license/",), ("license",)),
    (("developer/",), ("developer",)),
    (("cloud/",), ("cloud",)),
)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    """返回路径匹配前缀。"""
    return path == prefix or path.startswith(prefix)


def _match_rules(path: str, rules) -> tuple:
    """处理匹配规则。"""
    for prefixes, candidates in rules:
        for prefix in prefixes:
            if _path_matches_prefix(path, prefix):
                return candidates
    return ()


def permission_key_candidates(permission_key: str):
    """处理权限键`candidates`。"""
    key = str(permission_key or "").strip()
    if not key:
        return ()
    return PERMISSION_KEY_ALIASES.get(key, (key,))


def normalize_permissions_dict(value) -> dict:
    """执行归一化`permissions`字典。"""
    if not isinstance(value, dict):
        return {}
    normalized = {}
    for key in PERMISSION_KEYS:
        if key in value:
            normalized[key] = coerce_permission_bool(value.get(key))
    return normalized


def parse_permissions_json(raw) -> tuple:
    """解析`permissions`JSON。"""
    text = str(raw or "").strip()
    if not text:
        return None, {}
    try:
        loaded = json.loads(text)
    except Exception:
        return False, {}
    if not isinstance(loaded, dict):
        return False, {}
    return True, normalize_permissions_dict(loaded)


def permission_candidates_for_path(path: str):
    """获取路径的权限候选项。"""
    p = str(path or "").lstrip("/")
    if not p:
        return ()

    if p in ("profile", "logout"):
        return ()

    matched = _match_rules(p, _EXPLICIT_PATH_RULES)
    if matched:
        return matched
    return _match_rules(p, _MODULE_PATH_RULES)


def is_path_allowed(perms: dict, path: str):
    """判断`is`路径是否允许。"""
    candidates = permission_candidates_for_path(path)
    if not candidates:
        return None
    for key in candidates:
        if key in perms:
            return coerce_permission_bool(perms.get(key))
    return False
