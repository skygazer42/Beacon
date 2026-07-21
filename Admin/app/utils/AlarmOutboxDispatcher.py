import logging
import json
import threading
import time
from datetime import timedelta
from typing import Any, Dict, Optional

from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from app.models import AlarmEventOutbox


logger = logging.getLogger(__name__)


def _calc_retry_delay_seconds(attempts: int) -> int:
    """返回`calc``retry``delay`秒数。
    
    Exponential backoff with an upper bound.
        attempts: 1,2,3...
    """
    try:
        n = int(attempts)
    except Exception:
        n = 1
    if n < 1:
        n = 1
    # 2,4,8,16,32,60,60,...
    delay = 2 ** min(n, 5)
    if delay > 60:
        delay = 60
    return int(delay)


class AlarmOutboxDispatcher:
    """
    DB Outbox dispatcher for alarm events.

    - at-least-once delivery
    - retries for transient failures
    - permanent failures are recorded (failed + next_retry_at=NULL)
    """

    def __init__(self, config: Any):
        """处理`init`。"""
        self._config = config
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_cleanup_ts: float = 0.0

    def start(self) -> None:
        """启动相关数据。"""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="beacon-alarm-outbox", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 3.0) -> None:
        """停止当前服务。"""
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        """执行相关数据。"""
        poll_seconds = int(getattr(self._config, "alarmOutboxPollSeconds", 2) or 2)
        if poll_seconds < 1:
            poll_seconds = 1
        if poll_seconds > 10:
            poll_seconds = 10

        while not self._shutdown.is_set():
            close_old_connections()
            try:
                processed = self.dispatch_once()
            except Exception:
                processed = 0

            now_ts = time.time()
            if now_ts - self._last_cleanup_ts > 300:
                try:
                    self.cleanup_once()
                except Exception:
                    logger.debug("suppressed exception in app/utils/AlarmOutboxDispatcher.py:86", exc_info=True)
                self._last_cleanup_ts = now_ts

            if processed <= 0:
                time.sleep(poll_seconds)

    def _reclaim_stuck_sending_rows(self, batch_now) -> None:
        # Reclaim stuck "sending" rows (e.g., worker crash between claim and send).
        """返回`reclaim``stuck``sending`记录。"""
        try:
            sending_timeout_seconds = int(getattr(self._config, "alarmOutboxSendingTimeoutSeconds", 300) or 300)
        except Exception:
            sending_timeout_seconds = 300
        if sending_timeout_seconds < 1:
            sending_timeout_seconds = 1

        try:
            cutoff = batch_now - timedelta(seconds=sending_timeout_seconds)
            AlarmEventOutbox.objects.filter(status="sending", update_time__lt=cutoff).update(
                status="failed",
                next_retry_at=batch_now,
                last_error="sending timeout reclaimed",
                update_time=batch_now,
            )
        except Exception:
            logger.exception("AlarmOutboxDispatcher reclaim failed")

    def _get_max_batch(self) -> int:
        """获取最大值批量。"""
        max_batch = int(getattr(self._config, "alarmOutboxMaxBatch", 50) or 50)
        if max_batch < 1:
            max_batch = 1
        if max_batch > 200:
            max_batch = 200
        return max_batch

    def _fetch_candidates(self, batch_now, max_batch: int):
        """获取`candidates`。"""
        return list(
            AlarmEventOutbox.objects.filter(
                (Q(status="pending") & (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=batch_now)))
                | (Q(status="failed") & Q(next_retry_at__lte=batch_now))
            )
            .order_by("id")[:max_batch]
        )

    def _claim_row_for_sending(self, row) -> int:
        """获取`sending`的声明记录。"""
        claim_now = timezone.now()
        attempt_no = int(row.attempts or 0) + 1
        claimed = (
            AlarmEventOutbox.objects.filter(id=row.id, status__in=["pending", "failed"])
            .update(status="sending", attempts=attempt_no, update_time=claim_now)
        )
        return attempt_no if claimed == 1 else 0

    def _parse_payload(self, row) -> Dict[str, Any]:
        """解析 Outbox 事件对象，拒绝无法投递的毒消息。"""
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid payload_json: malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid payload_json: expected object, got {type(payload).__name__}")
        return payload

    def _finalize_send_attempt(self, *, row_id: int, attempt_no: int, result: Dict[str, Any]) -> None:
        """完成发送`attempt`。"""
        ok = bool(result.get("ok"))
        retriable = bool(result.get("retriable"))
        http_status = int(result.get("http_status") or 0)
        error = str(result.get("error") or "")

        finish_now = timezone.now()
        if ok:
            AlarmEventOutbox.objects.filter(id=row_id, status="sending", attempts=attempt_no).update(
                status="sent",
                sent_at=finish_now,
                next_retry_at=None,
                last_error="",
                last_http_status=http_status,
                update_time=finish_now,
            )
            return

        next_retry_at = None
        if retriable:
            delay = _calc_retry_delay_seconds(attempt_no)
            next_retry_at = finish_now + timedelta(seconds=delay)
        AlarmEventOutbox.objects.filter(id=row_id, status="sending", attempts=attempt_no).update(
            status="failed",
            next_retry_at=next_retry_at,
            last_error=error,
            last_http_status=http_status,
            update_time=finish_now,
        )

    def dispatch_once(self) -> int:
        """分发一次。"""
        if not bool(getattr(self._config, "alarmOutboxEnabled", True)):
            return 0

        batch_now = timezone.now()

        self._reclaim_stuck_sending_rows(batch_now)
        max_batch = self._get_max_batch()
        candidates = self._fetch_candidates(batch_now, max_batch)

        if not candidates:
            return 0

        from app.utils.AlarmSinks import publish_alarm_event_to_sink

        processed = 0
        for row in candidates:
            close_old_connections()
            attempt_no = self._claim_row_for_sending(row)
            if attempt_no <= 0:
                continue

            try:
                payload = self._parse_payload(row)
            except ValueError as exc:
                self._finalize_send_attempt(
                    row_id=int(row.id),
                    attempt_no=int(attempt_no),
                    result={"ok": False, "retriable": False, "error": str(exc)},
                )
                processed += 1
                continue

            result = publish_alarm_event_to_sink(self._config, row.sink_type, payload)
            try:
                self._finalize_send_attempt(row_id=int(row.id), attempt_no=int(attempt_no), result=dict(result or {}))
            except Exception:
                # best-effort - keep row as failed/sending as-is if update fails
                logger.debug("AlarmOutboxDispatcher finalize failed", exc_info=True)

            processed += 1

        return processed

    def cleanup_once(self) -> int:
        """清理一次。"""
        retention_hours = int(getattr(self._config, "alarmOutboxRetentionHours", 72) or 72)
        if retention_hours < 1:
            retention_hours = 1
        cutoff = timezone.now() - timedelta(hours=retention_hours)
        try:
            deleted, _ = AlarmEventOutbox.objects.filter(status="sent", sent_at__lt=cutoff).delete()
            return int(deleted or 0)
        except Exception:
            return 0
