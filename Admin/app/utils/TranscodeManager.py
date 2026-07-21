import logging
import threading
import time
from typing import Dict, Optional



logger = logging.getLogger(__name__)
class TranscodeManager:
    def __init__(self, config, zlm):
        """处理`init`。"""
        self._config = config
        self._zlm = zlm
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._last_access: Dict[str, float] = {}  # key -> timestamp
        self._last_start: Dict[str, float] = {}   # key -> timestamp
        self._stream_to_key: Dict[str, str] = {}  # "app/name" -> key

    def start(self):
        """启动相关数据。"""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="beacon-transcode-clean", daemon=True)
        self._thread.start()

    def touch(self, key: str):
        """刷新相关数据。"""
        if not key:
            return
        now = time.time()
        with self._lock:
            self._last_access[key] = now

    def register_stream(self, stream_id: str, key: str):
        """处理`register`流。"""
        if not stream_id or not key:
            return
        with self._lock:
            self._stream_to_key[stream_id] = key
            self._last_access[key] = time.time()

    def touch_stream(self, stream_id: str):
        """刷新流。"""
        if not stream_id:
            return
        with self._lock:
            key = self._stream_to_key.get(stream_id)
        if key:
            self.touch(key)

    def can_start(self, token: str) -> bool:
        """
        token 通常使用 dst_url 或 stream_id，用于短时间内避免重复触发 addFFmpegSource。
        """
        if not token:
            return True
        cooldown = int(getattr(self._config, "transcodeStartCooldownSeconds", 5) or 5)
        if cooldown < 1:
            cooldown = 1
        now = time.time()
        with self._lock:
            last = self._last_start.get(token, 0)
            if (now - last) < cooldown:
                return False
            self._last_start[token] = now
            return True

    def cooldown_remaining_ms(self, token: str) -> int:
        """
        返回距离下一次允许 start 的剩余毫秒数（用于前端 retry_after_ms）。
        """
        if not token:
            return 0
        cooldown = int(getattr(self._config, "transcodeStartCooldownSeconds", 5) or 5)
        if cooldown < 1:
            cooldown = 1
        now = time.time()
        with self._lock:
            last = float(self._last_start.get(token, 0) or 0)
        remain = cooldown - (now - last)
        if remain <= 0:
            return 0
        return int(remain * 1000)

    def flush_all(self) -> Dict[str, int]:
        """处理`flush`全部。
        
        Best-effort: stop and forget all tracked transcode sources.
        
                This is used by ops cleanup tooling to quickly recover from bad states
                (e.g. stale ffmpeg sources, runaway CPU) without restarting the service.
        """
        with self._lock:
            keys = list(self._last_access.keys())

        for key in keys:
            try:
                self._zlm.delFFmpegSource(key)
            except Exception:
                continue

        with self._lock:
            self._last_access.clear()
            self._last_start.clear()
            self._stream_to_key.clear()

        return {"cleared_keys": int(len(keys))}

    def _idle_cutoff(self) -> float:
        """处理空闲截止时间。"""
        idle = int(getattr(self._config, "transcodeIdleSeconds", 300) or 300)
        if idle < 30:
            idle = 30
        return time.time() - idle

    def _collect_keys_to_del(self, cutoff: float):
        """处理`collect`键列表`to``del`。"""
        keys_to_del = []
        with self._lock:
            for key, ts in self._last_access.items():
                if ts < cutoff:
                    keys_to_del.append(key)
        return keys_to_del

    def _delete_key_best_effort(self, key: str) -> None:
        """尽力处理`delete`键。"""
        try:
            self._zlm.delFFmpegSource(key)
        except Exception:
            logger.debug("suppressed exception in app/utils/TranscodeManager.py:130", exc_info=True)

        with self._lock:
            self._last_access.pop(key, None)
            # 清理反向映射
            for sid, k in tuple(self._stream_to_key.items()):
                if k == key:
                    self._stream_to_key.pop(sid, None)

    def _run(self):
        """执行相关数据。"""
        while not self._shutdown.is_set():
            cutoff = self._idle_cutoff()
            for key in self._collect_keys_to_del(cutoff):
                self._delete_key_best_effort(key)

            time.sleep(30)
