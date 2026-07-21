import logging
import os
import threading
import time
from django.db import close_old_connections

from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher
from app.utils.AlarmSinkDispatcher import AlarmSinkDispatcher
from app.utils.RecordingPlanService import RecordingPlanService
from app.utils.SystemConfigHelper import get_bool
from app.utils.TaskPlanService import TaskPlanService
from app.utils.TranscodeManager import TranscodeManager
from app.views.ViewsBase import AllStreamStartForward, g_config, g_zlm

_started = False
_startup_lock = threading.RLock()
_startup_attempt_lock = threading.Lock()
_startup_state = "not_started"
_startup_failures = {}
_started_components = set()
_background_threads = {}
_service_candidates = {}
_services = {}

logger = logging.getLogger(__name__)


def get_alarm_sink_dispatcher():
    """获取告警接收端`dispatcher`。"""
    return _services.get("alarm_sink")

def get_alarm_outbox_dispatcher():
    """获取告警`outbox``dispatcher`。"""
    return _services.get("alarm_outbox")

def get_transcode_manager():
    """获取转码`manager`。"""
    return _services.get("transcode")

def get_recording_plan_service():
    """获取录制计划`service`。"""
    return _services.get("recording_plan")

def get_task_plan_service():
    """获取任务计划`service`。"""
    return _services.get("task_plan")


def get_background_services_status() -> dict:
    """Return a stable snapshot of background-service startup state."""
    with _startup_lock:
        return {
            "state": _startup_state,
            "started": _startup_state == "running",
            "started_components": sorted(_started_components),
            "failed_components": sorted(_startup_failures),
            "failure_types": dict(sorted(_startup_failures.items())),
            "background_threads": sorted(_background_threads),
        }


def _record_startup_failure(component_name: str, exc: Exception) -> None:
    with _startup_lock:
        _startup_failures[component_name] = type(exc).__name__
    logger.error(
        "Background component startup failed: component=%s exception_type=%s",
        component_name,
        type(exc).__name__,
    )


def _ensure_service_started(component_name: str, factory) -> None:
    with _startup_lock:
        if component_name in _started_components:
            return
        service = _services.get(component_name) or _service_candidates.get(component_name)
    if service is None:
        try:
            service = factory()
        except Exception as exc:
            _record_startup_failure(component_name, exc)
            return
        with _startup_lock:
            _service_candidates[component_name] = service

    try:
        service.start()
    except Exception as exc:
        _record_startup_failure(component_name, exc)
        return

    with _startup_lock:
        _started_components.add(component_name)
        _startup_failures.pop(component_name, None)
        _service_candidates.pop(component_name, None)
        _services[component_name] = service


def _ensure_background_thread_started(component_name: str, target) -> None:
    with _startup_lock:
        if component_name in _background_threads:
            return
    try:
        thread = threading.Thread(target=target, name=component_name, daemon=True)
        thread.start()
    except Exception as exc:
        _record_startup_failure(component_name, exc)
        return
    with _startup_lock:
        _background_threads[component_name] = thread
        _startup_failures.pop(component_name, None)

def start_background_services() -> dict:
    """启动`background``services`。"""
    global _started, _startup_state
    if not _startup_attempt_lock.acquire(blocking=False):
        return get_background_services_status()
    try:
        with _startup_lock:
            if _startup_state == "running":
                return get_background_services_status()

            if os.environ.get("BEACON_DISABLE_BACKGROUND") == "1":
                _started = False
                _startup_state = "disabled"
                _startup_failures.clear()
                return get_background_services_status()

            _started = False
            _startup_state = "starting"

        service_specs = (
            ("alarm_sink", lambda: AlarmSinkDispatcher(g_config)),
            ("alarm_outbox", lambda: AlarmOutboxDispatcher(g_config)),
            ("transcode", lambda: TranscodeManager(g_config, g_zlm)),
            ("recording_plan", lambda: RecordingPlanService(g_config)),
            ("task_plan", TaskPlanService),
        )
        for component_name, factory in service_specs:
            _ensure_service_started(component_name, factory)

        thread_specs = (
            ("beacon-alarm-cache-clean", _alarm_cache_clean_task),
            ("beacon-alarm-retention", _alarm_data_retention_task),
            ("beacon-recording-retention", _recording_data_retention_task),
            ("beacon-log-retention", _log_retention_task),
            ("beacon-storage-quota", _storage_quota_task),
            ("beacon-auto-forward", _auto_start_forward_task),
            ("beacon-control-auto-recover", _control_auto_recover_task),
        )
        for component_name, target in thread_specs:
            _ensure_background_thread_started(component_name, target)

        expected_services = {item[0] for item in service_specs}
        expected_threads = {item[0] for item in thread_specs}
        with _startup_lock:
            if expected_services <= _started_components and expected_threads <= set(_background_threads):
                _started = True
                _startup_state = "running"
            else:
                _startup_state = "degraded"
        return get_background_services_status()
    finally:
        _startup_attempt_lock.release()


def _auto_start_forward_task():
    """处理自动起始转发任务。"""
    time.sleep(2)
    close_old_connections()

    if not get_bool("stream_auto_start", False):
        return

    for _ in range(30):
        close_old_connections()
        try:
            ok, _msg = AllStreamStartForward()
            if ok:
                return
        except Exception:
            logger.exception("自动启动转发失败")
        time.sleep(2)


def _alarm_cache_clean_task():
    """处理告警缓存清理任务。"""
    from app.utils.AlarmCacheCleaner import cleanup_alarm_compose_cache

    time.sleep(10)
    close_old_connections()
    while True:
        close_old_connections()
        try:
            cleanup_alarm_compose_cache(g_config)
        except Exception:
            logger.exception("告警缓存清理失败")
        time.sleep(1800)


def _alarm_data_retention_task():
    # Run after server is stable; then periodically cleanup.
    """处理告警数据`retention`任务。"""
    from app.utils.AlarmDataCleaner import cleanup_alarm_data

    time.sleep(30)
    close_old_connections()

    while True:
        close_old_connections()
        try:
            cleanup_alarm_data(g_config)
        except Exception:
            logger.exception("告警数据保留清理失败")
        time.sleep(3600)


def _log_retention_task():
    # Run after server is stable; then periodically cleanup.
    """记录`retention`任务。"""
    from app.utils.LogDataCleaner import cleanup_logs

    time.sleep(60)
    close_old_connections()

    while True:
        close_old_connections()
        try:
            cleanup_logs(dry_run=False)
        except Exception:
            logger.exception("日志保留清理失败")
        time.sleep(3600)


def _storage_quota_task():
    # Run after server is stable; then periodically enforce quota-based overwrite.
    """处理存储配额任务。"""
    from app.utils.StorageQuotaCleaner import cleanup_by_storage_quota

    time.sleep(45)
    close_old_connections()

    while True:
        close_old_connections()
        try:
            cleanup_by_storage_quota(g_config)
        except Exception:
            logger.exception("存储配额清理失败")
        # Quota checks are heavier than retention (size walk); keep it moderate.
        time.sleep(300)


def _recording_data_retention_task():
    # Run after server is stable; then periodically cleanup.
    """处理录制数据`retention`任务。"""
    from app.utils.RecordingDataCleaner import cleanup_recording_data

    time.sleep(35)
    close_old_connections()

    while True:
        close_old_connections()
        try:
            cleanup_recording_data(g_config)
        except Exception:
            logger.exception("录像数据保留清理失败")
        time.sleep(3600)


def _fetch_running_control_codes(g_analyzer) -> set:
    """获取`running`控制编码列表。"""
    running_codes = set()
    try:
        ok, _msg, items = g_analyzer.controls()
    except Exception:
        return running_codes

    if not ok or not isinstance(items, list):
        return running_codes

    for it in items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code") or "").strip()
        if code:
            running_codes.add(code)
    return running_codes


def _start_control_best_effort(start_control, control) -> bool:
    """尽力处理起始控制。"""
    try:
        start_control(control)
        return True
    except Exception:
        return False


def _control_auto_recover_task():
    """
    Industrial delivery:
    - When Analyzer is restarted unexpectedly, UI will show controls as "中断" (state=5).
    - If the operator expects "always-on", we provide a best-effort auto-recover path.

    Policy:
    - Only attempts to recover controls that were last saved as state=1 (布控中).
    - Skips those that are already running in Analyzer.
    - Runs once on startup; operators can re-trigger by restarting Admin.
    """
    # Give Admin/MediaServer/Analyzer time to come up.
    time.sleep(25)
    close_old_connections()

    if not get_bool("control_auto_recover", False):
        return

    from app.models import Control
    from app.views.ControlView import _start_control
    from app.views.ViewsBase import g_analyzer

    running_codes = _fetch_running_control_codes(g_analyzer)

    qs = Control.objects.filter(state=1).order_by("id")
    for control in qs.iterator(chunk_size=200):
        close_old_connections()
        code = str(getattr(control, "code", "") or "").strip()
        if code and code in running_codes:
            continue
        if not _start_control_best_effort(_start_control, control):
            continue
        # Avoid thundering herd against Analyzer / ZLM on low-end devices.
        time.sleep(0.05)
