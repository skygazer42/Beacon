import logging
import threading
import time
from datetime import datetime, time as dt_time
from typing import Any, Dict, Optional, Tuple

from django.db import close_old_connections

from app.models import RecordingPlan, Stream
from app.utils.SafeLog import safe_json_dumps
from app.utils.StreamRecording import get_stream_recorder


logger = logging.getLogger(__name__)
_RECORDER_ALREADY_STOPPED_MESSAGE = "该视频流未在录像"


def _minute_time(now: datetime) -> dt_time:
    """返回分钟时间。"""
    return dt_time(hour=now.hour, minute=now.minute)


def _mask_allows_day(mask: int, weekday: int) -> bool:
    """脱敏允许`day`。
    
    weekday: datetime.weekday() => Monday=0 .. Sunday=6
        mask: bit0=Mon .. bit6=Sun
    """
    try:
        mask_int = int(mask or 0)
    except Exception:
        mask_int = 0
    if weekday < 0 or weekday > 6:
        return True
    bit = 1 << int(weekday)
    return bool(mask_int & bit)


def _should_run_now(plan: RecordingPlan, now: Optional[datetime] = None) -> bool:
    """判断`run`当前时间。"""
    if not getattr(plan, "enabled", False):
        return False
    now = now or datetime.now()

    try:
        weekday = int(now.weekday())
    except Exception:
        weekday = 0
    if not _mask_allows_day(int(getattr(plan, "days_mask", 0) or 0), weekday):
        return False

    start_t = getattr(plan, "start_time", None) or dt_time(0, 0)
    end_t = getattr(plan, "end_time", None) or dt_time(23, 59)

    # Convention: start==end means "all day" (avoid surprising 0-length window).
    if start_t == end_t:
        return True

    cur = _minute_time(now)

    if start_t < end_t:
        return start_t <= cur <= end_t
    # Crosses midnight.
    return cur >= start_t or cur <= end_t


class RecordingPlanService:
    """
    Background scheduler for RecordingPlan.

    - Polls DB periodically (sqlite-friendly)
    - Starts/stops FFmpeg recording via StreamRecorder
    """

    def __init__(self, config: Any):
        """处理`init`。"""
        self._config = config
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active: Dict[str, str] = {}  # plan_code -> recorder_key

    def start(self) -> None:
        """启动相关数据。"""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="beacon-recording-plan", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 3.0) -> None:
        """停止当前服务。"""
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=timeout)

        for plan_code in tuple(self._active):
            self._stop_plan(plan_code)

    def _resolve_stream_url(self, plan: RecordingPlan) -> str:
        """解析并返回流URL。"""
        url = str(getattr(plan, "stream_url", "") or "").strip()
        if url:
            return url
        stream_code = str(getattr(plan, "stream_code", "") or "").strip()
        if not stream_code:
            return ""
        stream = Stream.objects.filter(code=stream_code).first()
        if not stream:
            return ""
        return str(getattr(stream, "pull_stream_url", "") or "").strip()

    def _start_plan(self, plan: RecordingPlan) -> None:
        """启动计划。"""
        plan_code = str(getattr(plan, "code", "") or "").strip()
        if not plan_code:
            return
        if plan_code in self._active:
            return

        stream_url = self._resolve_stream_url(plan)
        if not stream_url:
            logger.warning("RecordingPlan start skipped: stream_url empty, plan=%s", plan_code)
            return

        key = f"plan_{plan_code}"
        fmt = str(getattr(plan, "format", "") or "mp4").strip().lower() or "mp4"
        if fmt not in ("mp4", "ts", "flv"):
            fmt = "mp4"

        include_audio = bool(getattr(plan, "record_audio", False))

        recorder = get_stream_recorder(getattr(self._config, "storageRootPath", "upload"))
        result = recorder.start_recording(
            stream_code=key,
            stream_url=stream_url,
            duration=0,
            format=fmt,
            include_audio=include_audio,
        )
        if result.get("success"):
            self._active[plan_code] = key
            logger.info("RecordingPlan started: plan=%s stream=%s", plan_code, str(getattr(plan, "stream_code", "")))
        else:
            logger.warning("RecordingPlan start failed: plan=%s msg=%s", plan_code, result.get("message"))

    def _stop_plan(self, plan_code: str) -> Tuple[bool, str]:
        """停止计划。"""
        if not plan_code:
            return False, "录像计划编号为空"
        key = self._active.get(plan_code)
        if not key:
            return True, "录像计划未运行"

        try:
            recorder = get_stream_recorder(getattr(self._config, "storageRootPath", "upload"))
            result = recorder.stop_recording(key)
        except Exception as exc:
            message = "停止录像调用异常"
            logger.warning(
                "RecordingPlan stop failed: %s",
                safe_json_dumps(
                    {"plan_code": plan_code, "message": message, "error": str(exc)},
                    max_len=512,
                ),
            )
            return False, message

        if not isinstance(result, dict):
            message = "停止录像返回格式错误"
            logger.warning(
                "RecordingPlan stop failed: %s",
                safe_json_dumps(
                    {"plan_code": plan_code, "message": message, "result": result},
                    max_len=512,
                ),
            )
            return False, message

        success = result.get("success")
        result_message = result.get("message")
        if type(success) is not bool or not isinstance(result_message, str):
            message = "停止录像返回字段错误"
            logger.warning(
                "RecordingPlan stop failed: %s",
                safe_json_dumps(
                    {"plan_code": plan_code, "message": message, "result": result},
                    max_len=512,
                ),
            )
            return False, message

        stopped = success or result_message == _RECORDER_ALREADY_STOPPED_MESSAGE
        if not stopped:
            logger.warning(
                "RecordingPlan stop failed: %s",
                safe_json_dumps(
                    {"plan_code": plan_code, "message": result_message},
                    max_len=512,
                ),
            )
            return False, result_message

        self._active.pop(plan_code, None)
        logger.info(
            "RecordingPlan stopped: %s",
            safe_json_dumps({"plan_code": plan_code}, max_len=256),
        )
        return True, result_message

    def tick_once(self) -> None:
        """执行一次调度周期。"""
        now = datetime.now()
        plans = list(RecordingPlan.objects.all())
        plan_by_code = {str(p.code): p for p in plans if getattr(p, "code", None)}

        # Stop orphaned (deleted) plans.
        for active_code in tuple(self._active):
            if active_code not in plan_by_code:
                self._stop_plan(active_code)

        for plan in plans:
            plan_code = str(getattr(plan, "code", "") or "").strip()
            if not plan_code:
                continue
            should_run = _should_run_now(plan, now=now)
            if should_run and plan_code not in self._active:
                self._start_plan(plan)
            elif (not should_run) and plan_code in self._active:
                self._stop_plan(plan_code)

    def _run(self) -> None:
        # Give Admin a short warmup time.
        """执行相关数据。"""
        time.sleep(15)
        close_old_connections()

        while not self._shutdown.is_set():
            close_old_connections()
            try:
                self.tick_once()
            except Exception:
                logger.debug("suppressed exception in app/utils/RecordingPlanService.py:201", exc_info=True)
            # 30s tick: minute-level schedule, lightweight.
            time.sleep(30)
