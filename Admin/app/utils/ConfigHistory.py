import json
import logging

from app.models import ConfigHistorySnapshot
from app.utils.SystemConfigHelper import get_value, set_value


CHANGE_TYPE_SYSTEM_SAVE = "system.save"
logger = logging.getLogger(__name__)


def _system_view_module():
    """处理系统`view``module`。"""
    from app.views import SystemConfigView

    return SystemConfigView


def _json_text(data) -> str:
    """处理JSON文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def snapshot_equals(left: dict, right: dict) -> bool:
    """判断快照是否相等。"""
    return _json_text(left or {}) == _json_text(right or {})


def build_system_snapshot() -> dict:
    """构建系统快照。"""
    system_view = _system_view_module()
    config_json = system_view._read_json_file(system_view._config_json_path()) or {}
    if not isinstance(config_json, dict):
        config_json = {}

    snapshot = {}
    for key in system_view._SYSTEM_KEYS.keys():
        if key in system_view._UI_SETTINGS_KEYS and system_view.settings_store is not None:
            try:
                stored = system_view.settings_store.get_setting(key, None)
            except Exception:
                stored = None
            if stored not in (None, ""):
                snapshot[key] = stored
                continue

        default = config_json.get(key, "")
        value = get_value(key, default)
        snapshot[key] = default if value is None else value
    return snapshot


def build_diff_rows(target_snapshot: dict, current_snapshot: dict = None):
    """构建`diff`记录。"""
    current = current_snapshot if isinstance(current_snapshot, dict) else build_system_snapshot()
    rows = []
    keys = sorted(set((target_snapshot or {}).keys()) | set(current.keys()))
    for key in keys:
        target_value = (target_snapshot or {}).get(key)
        current_value = current.get(key)
        if target_value == current_value:
            continue
        rows.append(
            {
                "key": key,
                "target": target_value,
                "current": current_value,
            }
        )
    return rows


def latest_snapshot():
    """处理`latest`快照。"""
    return ConfigHistorySnapshot.objects.order_by("-id").first()


def snapshot_payload(entry) -> dict:
    """返回快照载荷。"""
    try:
        raw = str(getattr(entry, "snapshot_json", "") or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def create_snapshot(*, actor: str = "", change_type: str = CHANGE_TYPE_SYSTEM_SAVE, summary: str = "", snapshot: dict, rollback_of=None):
    """创建快照。"""
    current_snapshot = dict(snapshot or {})
    diff_rows = build_diff_rows(current_snapshot)
    return ConfigHistorySnapshot.objects.create(
        scope="system",
        change_type=str(change_type or CHANGE_TYPE_SYSTEM_SAVE).strip() or CHANGE_TYPE_SYSTEM_SAVE,
        actor=str(actor or "").strip(),
        summary=str(summary or "").strip(),
        snapshot_json=_json_text(current_snapshot),
        diff_json=_json_text(diff_rows),
        rollback_of=rollback_of,
    )


def ensure_baseline_snapshot(*, actor: str = "", snapshot: dict = None):
    """处理`ensure``baseline`快照。"""
    current_snapshot = dict(snapshot or build_system_snapshot())
    latest = latest_snapshot()
    if latest and snapshot_equals(snapshot_payload(latest), current_snapshot):
        return latest
    return ConfigHistorySnapshot.objects.create(
        scope="system",
        change_type="baseline",
        actor=str(actor or "").strip(),
        summary="baseline",
        snapshot_json=_json_text(current_snapshot),
        diff_json="[]",
    )


def record_system_change(*, actor: str = "", change_type: str = CHANGE_TYPE_SYSTEM_SAVE, summary: str = "", before_snapshot: dict, after_snapshot: dict):
    """处理`record`系统`change`。"""
    before_data = dict(before_snapshot or {})
    after_data = dict(after_snapshot or {})
    if snapshot_equals(before_data, after_data):
        return None

    ensure_baseline_snapshot(actor=actor, snapshot=before_data)
    diff_rows = build_diff_rows(after_data, before_data)
    return ConfigHistorySnapshot.objects.create(
        scope="system",
        change_type=str(change_type or CHANGE_TYPE_SYSTEM_SAVE).strip() or CHANGE_TYPE_SYSTEM_SAVE,
        actor=str(actor or "").strip(),
        summary=str(summary or change_type or CHANGE_TYPE_SYSTEM_SAVE).strip(),
        snapshot_json=_json_text(after_data),
        diff_json=_json_text(diff_rows),
    )


def apply_system_snapshot(snapshot: dict):
    """处理应用系统快照。"""
    system_view = _system_view_module()
    current_snapshot = dict(snapshot or {})

    ui_values = {key: current_snapshot.get(key) for key in system_view._UI_SETTINGS_KEYS if key in current_snapshot}
    runtime_values = {key: current_snapshot.get(key) for key in system_view._RUNTIME_CONFIG_KEYS if key in current_snapshot}

    if system_view.settings_store is not None and ui_values:
        system_view.settings_store.update_settings(ui_values)

    for key, meta in system_view._SYSTEM_KEYS.items():
        if key not in current_snapshot:
            continue
        set_value(key, str(current_snapshot.get(key, "")), remark=str(meta.get("remark") or ""))
        try:
            setattr(system_view.g_config, key, current_snapshot.get(key))
        except Exception:
            logger.debug("sync restored config value to runtime g_config failed key=%s", key, exc_info=True)

    if runtime_values:
        system_view._update_config_json(runtime_values)
