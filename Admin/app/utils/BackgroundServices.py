import logging
import threading
import time
from django.db import close_old_connections

from app.utils.AlarmOutboxDispatcher import AlarmOutboxDispatcher
from app.utils.AlarmSinkDispatcher import AlarmSinkDispatcher
from app.utils.BackgroundRoles import get_background_role
from app.utils.RecordingPlanService import RecordingPlanService
from app.utils.SystemConfigHelper import get_bool
from app.utils.TaskPlanService import TaskPlanService
from app.utils.TranscodeManager import TranscodeManager
from app.views.ViewsBase import AllStreamStartForward, g_config, g_zlm

_started = False
_startup_lock = threading.RLock()
_startup_attempt_lock = threading.Lock()
_startup_state = "not_started"
_startup_role = None
_startup_failures = {}
_started_components = set()
_background_threads = {}
_service_candidates = {}
_services = {}
_PERSISTENT_BACKGROUND_THREADS = frozenset(
    {
        "beacon-alarm-cache-clean",
        "beacon-alarm-retention",
        "beacon-recording-retention",
        "beacon-log-retention",
        "beacon-storage-quota",
    }
)

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
        state = _startup_state
        failures = dict(_startup_failures)
        if state == "running":
            for component_name, service in _services.items():
                thread = getattr(service, "_thread", None)
                is_alive = getattr(thread, "is_alive", None)
                if not callable(is_alive):
                    continue
                try:
                    alive = is_alive()
                except Exception:
                    alive = None
                if alive is False:
                    failures[component_name] = "ThreadStopped"

            for component_name in _PERSISTENT_BACKGROUND_THREADS:
                thread = _background_threads.get(component_name)
                if thread is None:
                    continue
                is_alive = getattr(thread, "is_alive", None)
                if not callable(is_alive):
                    continue
                try:
                    alive = is_alive()
                except Exception:
                    alive = None
                if alive is False:
                    failures[component_name] = "ThreadStopped"
            if failures:
                state = "degraded"

        return {
            "state": state,
            "role": _startup_role or get_background_role(),
            "started": state == "running",
            "started_components": sorted(_started_components),
            "failed_components": sorted(failures),
            "failure_types": dict(sorted(failures.items())),
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

def _service_specs_for_role(role: str):
    web_specs = (
        ("alarm_sink", lambda: AlarmSinkDispatcher(g_config)),
    )
    edge_specs = (
        # TranscodeManager tracks cooldown and idle state in process memory and
        # controls the local ZLMediaKit instance.  It therefore belongs only to
        # the single-process Edge compatibility role, never a replicated Cloud
        # Web process.
        ("transcode", lambda: TranscodeManager(g_config, g_zlm)),
    )
    worker_specs = (
        ("alarm_outbox", lambda: AlarmOutboxDispatcher(g_config)),
        ("recording_plan", lambda: RecordingPlanService(g_config)),
        ("task_plan", TaskPlanService),
    )
    if role == "web":
        return web_specs
    if role == "worker":
        return worker_specs
    return web_specs + edge_specs + worker_specs


def _thread_specs_for_role(role: str):
    if role == "web":
        return ()
    return (
        ("beacon-alarm-cache-clean", _alarm_cache_clean_task),
        ("beacon-alarm-retention", _alarm_data_retention_task),
        ("beacon-recording-retention", _recording_data_retention_task),
        ("beacon-log-retention", _log_retention_task),
        ("beacon-storage-quota", _storage_quota_task),
        ("beacon-auto-forward", _auto_start_forward_task),
        ("beacon-control-auto-recover", _control_auto_recover_task),
    )


def start_background_services(*, role: str = None) -> dict:
    """启动`background``services`。"""
    global _started, _startup_role, _startup_state
    resolved_role = role or get_background_role()
    if resolved_role not in {"all", "web", "worker", "init", "disabled"}:
        raise ValueError(f"unsupported background role: {resolved_role}")
    if not _startup_attempt_lock.acquire(blocking=False):
        return get_background_services_status()
    try:
        with _startup_lock:
            if _startup_role and _startup_role != resolved_role and (
                _started_components or _background_threads
            ):
                raise RuntimeError(
                    f"background services already initialized for role {_startup_role}"
                )
            _startup_role = resolved_role
            if _startup_state == "running":
                return get_background_services_status()

            if resolved_role in {"init", "disabled"}:
                _started = False
                _startup_state = "disabled"
                _startup_failures.clear()
                return get_background_services_status()

            _started = False
            _startup_state = "starting"

        service_specs = _service_specs_for_role(resolved_role)
        for component_name, factory in service_specs:
            _ensure_service_started(component_name, factory)

        thread_specs = _thread_specs_for_role(resolved_role)
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


def shutdown_background_services() -> None:
    """Best-effort shutdown for service objects owned by a worker process."""
    global _started, _startup_state
    with _startup_lock:
        services = tuple(_services.values())
    for service in reversed(services):
        shutdown = getattr(service, "shutdown", None)
        if not callable(shutdown):
            continue
        try:
            shutdown()
        except Exception:
            logger.exception(
                "Background component shutdown failed: component=%s",
                type(service).__name__,
            )
    with _startup_lock:
        _started = False
        _startup_state = "stopped"


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
