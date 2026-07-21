import logging
import queue
import threading
from typing import Any, Dict, Optional

from django.db import close_old_connections



logger = logging.getLogger(__name__)


def _resolve_publish_alarm_event():
    from app.utils.AlarmSinks import publish_alarm_event

    return publish_alarm_event


class AlarmSinkDispatcher:
    def __init__(self, config, max_queue: int = 2000):
        """处理`init`。"""
        self._config = config
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=max_queue)
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """启动相关数据。"""
        if self._thread and self._thread.is_alive():
            return
        publish_alarm_event = _resolve_publish_alarm_event()
        self._thread = threading.Thread(
            target=self._run,
            args=(publish_alarm_event,),
            name="beacon-alarm-sinks",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self, timeout: float = 3.0):
        """停止当前服务。"""
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def enqueue(self, event: Dict[str, Any]) -> bool:
        """处理`enqueue`。"""
        if self._shutdown.is_set():
            return False
        try:
            self._q.put_nowait(event)
            return True
        except queue.Full:
            return False

    def _run(self, publish_alarm_event):
        """执行相关数据。"""
        while not self._shutdown.is_set():
            close_old_connections()
            try:
                event = self._q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                publish_alarm_event(self._config, event)
            except Exception:
                logger.debug("suppressed exception in app/utils/AlarmSinkDispatcher.py:51", exc_info=True)
            finally:
                try:
                    self._q.task_done()
                except Exception:
                    logger.debug("suppressed exception in app/utils/AlarmSinkDispatcher.py:56", exc_info=True)
