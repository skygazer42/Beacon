import json
import logging
import threading
import time
from datetime import datetime, time as dt_time
from typing import Optional, Tuple

from django.db import close_old_connections

from app.models import TaskPlan


logger = logging.getLogger(__name__)


class OfflineStreamScanError(RuntimeError):
    """Raised when an offline-stream scan cannot make a safe decision."""


def _mask_allows_day(mask: int, weekday: int) -> bool:
    """脱敏允许`day`。
    
    weekday: datetime.weekday() => Monday=0 .. Sunday=6
        mask: bit0=Mon .. bit6=Sun
    """
    try:
        mask_int = int(mask)
    except (TypeError, ValueError, OverflowError):
        return False
    if weekday < 0 or weekday > 6:
        return False
    if mask_int < 0 or mask_int > 127:
        return False
    bit = 1 << int(weekday)
    return bool(mask_int & bit) if mask_int > 0 else True


def _same_minute(a: Optional[datetime], b: datetime) -> bool:
    """处理同一分钟。"""
    if not a:
        return False
    try:
        return (
            a.year == b.year
            and a.month == b.month
            and a.day == b.day
            and a.hour == b.hour
            and a.minute == b.minute
        )
    except Exception:
        return False


def _parse_targets(raw: str):
    """解析目标。"""
    s = str(raw or "").strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x or "").strip() for x in arr if str(x or "").strip()]
        except Exception:
            logger.debug("suppressed exception in app/utils/TaskPlanService.py:59", exc_info=True)
    return [x.strip() for x in s.split(",") if x.strip()]


def _is_stream_online_in_zlm(g_zlm, stream) -> bool:
    """判断流在线`in``zlm`。"""
    stream_key = f"{stream.app}/{stream.name}"
    try:
        info = g_zlm.getMediaInfo(stream.app, stream.name)
    except Exception as exc:
        raise OfflineStreamScanError(f"{stream_key} stream probe is unknown: {exc}") from exc

    if not isinstance(info, dict) or not isinstance(info.get("ret"), bool):
        raise OfflineStreamScanError(f"{stream_key} stream probe is unknown: malformed ZLM response")

    if "probe_ok" in info and info["probe_ok"] is not True:
        raise OfflineStreamScanError(f"{stream_key} stream probe is unknown: invalid ZLM probe")

    media_server_state = getattr(g_zlm, "mediaServerState", None)
    if media_server_state is False:
        raise OfflineStreamScanError(f"{stream_key} stream probe is unknown: ZLM is unavailable")

    return info["ret"]


def _restart_stream_forward(stream, *, stop_forward_for_stream, start_forward_for_stream) -> Tuple[bool, str]:
    """Restart forwarding only after the current forwarder is confirmed stopped."""
    try:
        stop_result = stop_forward_for_stream(stream)
    except Exception as exc:
        return False, f"stop forward failed: {exc}"

    if not isinstance(stop_result, (tuple, list)) or len(stop_result) < 1:
        return False, "stop forward failed: invalid result"
    stop_ok = bool(stop_result[0])
    stop_message = str(stop_result[1] if len(stop_result) > 1 else "")
    if not stop_ok:
        return False, f"stop forward failed: {stop_message or 'rejected'}"

    try:
        start_result = start_forward_for_stream(stream)
    except Exception as exc:
        return False, f"start forward failed: {exc}"

    if not isinstance(start_result, (tuple, list)) or len(start_result) < 1:
        return False, "start forward failed: invalid result"
    start_ok = bool(start_result[0])
    start_message = str(start_result[1] if len(start_result) > 1 else "")
    if not start_ok:
        return False, f"start forward failed: {start_message or 'rejected'}"
    return True, start_message or "forward restarted"


def _scan_offline_streams(max_items: int = 200) -> Tuple[int, int]:
    """处理`scan``offline`流列表。
    
    Best-effort offline stream scan:
        - For streams marked forward_state=1 but not actually online in ZLM, attempt restart.
        Returns: (scanned, restarted)
    """
    from app.models import Stream
    from app.views.ViewsBase import g_zlm, start_forward_for_stream, stop_forward_for_stream

    scanned = 0
    restarted = 0

    try:
        max_items_int = int(max_items or 0)
    except Exception:
        max_items_int = 0
    if max_items_int < 0:
        max_items_int = 0

    qs = Stream.objects.filter(forward_state=1).order_by("id")
    for stream in qs.iterator(chunk_size=200):
        scanned += 1
        if max_items_int > 0 and scanned > max_items_int:
            break
        if _is_stream_online_in_zlm(g_zlm, stream):
            continue

        restart_ok, restart_message = _restart_stream_forward(
            stream,
            stop_forward_for_stream=stop_forward_for_stream,
            start_forward_for_stream=start_forward_for_stream,
        )
        if not restart_ok:
            raise OfflineStreamScanError(
                f"{stream.app}/{stream.name} forward restart failed: {restart_message}"
            )
        restarted += 1

    return scanned, restarted


def _execute_restart_software() -> Tuple[bool, str]:
    """执行重启软件。"""
    from app.views.api import _schedule_admin_restart

    try:
        _schedule_admin_restart(delay_seconds=1.0)
        return True, "restarting software"
    except Exception as e:
        return False, str(e)


def _execute_restart_system() -> Tuple[bool, str]:
    """执行重启系统。"""
    from app.views.api import _schedule_system_restart

    try:
        _schedule_system_restart(delay_seconds=1.0)
        return True, "restarting system"
    except Exception as e:
        return False, str(e)


def _execute_control_targets(targets, *, want_start: bool) -> Tuple[bool, str]:
    """执行控制目标。"""
    if not targets:
        return False, "target_codes is required"
    from app.models import Control
    from app.views.ControlView import _start_control, _stop_control

    try:
        ok_all = True
        for code in targets:
            ctl = Control.objects.filter(code=code).first()
            if not ctl:
                ok_all = False
                continue
            ok, _msg = (_start_control(ctl) if want_start else _stop_control(ctl))
            ok_all = ok_all and bool(ok)
        return ok_all, "done"
    except Exception as e:
        return False, str(e)


def _execute_forward_targets(targets, *, want_start: bool) -> Tuple[bool, str]:
    """执行转发目标。"""
    if not targets:
        return False, "target_codes is required"
    from app.models import Stream
    from app.views.ViewsBase import start_forward_for_stream, stop_forward_for_stream

    try:
        ok_all = True
        for code in targets:
            stream = Stream.objects.filter(code=code).first()
            if not stream:
                ok_all = False
                continue
            ok, _msg = (start_forward_for_stream(stream) if want_start else stop_forward_for_stream(stream))
            ok_all = ok_all and bool(ok)
        return ok_all, "done"
    except Exception as e:
        return False, str(e)


class TaskPlanService:
    """
    Background scheduler for TaskPlan.

    - Supports daily(minute-granularity) and interval schedules.
    - Executes best-effort actions (control/forward/restart/scan).
    """

    def __init__(self):
        """处理`init`。"""
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动相关数据。"""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="beacon-task-plan", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 3.0) -> None:
        """停止当前服务。"""
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _plan_allows_today(self, plan: TaskPlan, now: datetime) -> bool:
        """判断计划今天是否允许执行。"""
        try:
            days_mask = int(getattr(plan, "days_mask", 127))
            return _mask_allows_day(days_mask, int(now.weekday()))
        except (TypeError, ValueError, OverflowError):
            return False

    def _is_due_daily(self, plan: TaskPlan, now: datetime, last_run_at: Optional[datetime]) -> bool:
        """判断`due``daily`。"""
        rt = getattr(plan, "run_time", None)
        if not isinstance(rt, dt_time):
            return False
        if now.hour != rt.hour or now.minute != rt.minute:
            return False
        if _same_minute(last_run_at, now):
            return False
        return True

    def _is_due_interval(self, plan: TaskPlan, now: datetime, last_run_at: Optional[datetime]) -> bool:
        """判断`due``interval`。"""
        try:
            interval = int(getattr(plan, "interval_seconds", 0) or 0)
        except Exception:
            interval = 0
        if interval <= 0:
            return False
        if not last_run_at:
            return True
        try:
            return (now - last_run_at).total_seconds() >= float(interval)
        except (TypeError, ValueError, OverflowError):
            return False

    def _is_due(self, plan: TaskPlan, now: datetime) -> bool:
        """判断`due`。"""
        if not getattr(plan, "enabled", False):
            return False

        if not self._plan_allows_today(plan, now):
            return False

        schedule_type = str(getattr(plan, "schedule_type", "") or "").strip().lower()
        last_run_at = getattr(plan, "last_run_at", None)

        if schedule_type == "daily":
            return self._is_due_daily(plan, now, last_run_at)

        if schedule_type == "interval":
            return self._is_due_interval(plan, now, last_run_at)

        return False

    def _execute_plan(self, plan: TaskPlan) -> Tuple[bool, str]:
        """执行计划。"""
        task_type_raw = str(getattr(plan, "task_type", "") or "").strip().lower()
        task_type = task_type_raw.replace("_", "")
        targets = _parse_targets(str(getattr(plan, "target_codes", "") or ""))

        if task_type == "restartsoftware":
            return _execute_restart_software()

        if task_type == "restartsystem":
            return _execute_restart_system()

        if task_type == "scanofflinestreams":
            try:
                scanned, restarted = _scan_offline_streams()
            except OfflineStreamScanError as exc:
                return False, f"offline stream scan failed: {exc}"
            return True, f"scanned={scanned} restarted={restarted}"

        if task_type in ("controlstart", "controlstop"):
            return _execute_control_targets(targets, want_start=(task_type == "controlstart"))

        if task_type in ("forwardstart", "forwardstop"):
            return _execute_forward_targets(targets, want_start=(task_type == "forwardstart"))

        return False, f"unsupported task_type: {task_type_raw}"

    def tick_once(self, now: Optional[datetime] = None) -> None:
        """执行一次调度周期。"""
        now = now or datetime.now()
        plans = list(TaskPlan.objects.all().order_by("id"))
        for plan in plans:
            if not self._is_due(plan, now):
                continue

            ok, msg = self._execute_plan(plan)
            plan.last_run_at = now
            plan.last_result_code = 1000 if ok else 0
            plan.last_result_msg = str(msg or "")
            try:
                plan.save(update_fields=["last_run_at", "last_result_code", "last_result_msg", "update_time"])
            except Exception:
                try:
                    plan.save()
                except Exception:
                    logger.debug("suppressed exception in app/utils/TaskPlanService.py:332", exc_info=True)

    def _run(self) -> None:
        """执行相关数据。"""
        time.sleep(20)
        close_old_connections()

        while not self._shutdown.is_set():
            close_old_connections()
            try:
                self.tick_once()
            except Exception as e:
                logger.debug("TaskPlanService.tick_once error: %s", e)
            time.sleep(30)
