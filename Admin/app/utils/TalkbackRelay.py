import logging
import subprocess
import threading
import time
from typing import Dict
from urllib.parse import urlsplit, urlunsplit



logger = logging.getLogger(__name__)
def _mask_url_credentials(value: str) -> str:
    """脱敏URL`credentials`。"""
    raw = str(value or "").strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    if not parts.netloc or "@" not in parts.netloc:
        return raw

    userinfo, hostport = parts.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return raw

    user, _ = userinfo.split(":", 1)
    return urlunsplit((parts.scheme, f"{user}:***@{hostport}", parts.path, parts.query, parts.fragment))


class TalkbackRelayManager:
    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        """处理`init`。"""
        self._ffmpeg_bin = str(ffmpeg_bin or "ffmpeg").strip() or "ffmpeg"
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict] = {}

    @staticmethod
    def _codec_name(codec_hint: str) -> str:
        """返回编解码器名称。"""
        hint = str(codec_hint or "").strip().lower()
        if hint == "pcmu":
            return "pcm_mulaw"
        if hint == "aac":
            return "aac"
        return "pcm_alaw"

    def build_ffmpeg_command(
        self,
        *,
        source_url: str,
        destination_url: str,
        sample_rate: int = 16000,
        codec_hint: str = "pcma",
    ) -> list:
        """构建`ffmpeg``command`。"""
        return [
            self._ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            str(source_url or "").strip(),
            "-vn",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(int(sample_rate or 16000)),
            "-c:a",
            self._codec_name(codec_hint),
            "-f",
            "rtsp",
            str(destination_url or "").strip(),
        ]

    def start_session(
        self,
        *,
        session_id: str,
        source_url: str,
        destination_url: str,
        sample_rate: int = 16000,
        codec_hint: str = "pcma",
    ) -> Dict:
        """启动会话。"""
        key = str(session_id or "").strip()
        if not key:
            return {"ok": False, "started": False, "state": "error", "msg": "session_id is required"}

        with self._lock:
            current = self._sessions.get(key)
            if current and current.get("process") and current["process"].poll() is None:
                return {
                    "ok": True,
                    "started": False,
                    "idempotent": True,
                    "state": "active",
                    "session_id": key,
                    "destination_url_masked": current.get("destination_url_masked", ""),
                }

            cmd = self.build_ffmpeg_command(
                source_url=source_url,
                destination_url=destination_url,
                sample_rate=sample_rate,
                codec_hint=codec_hint,
            )
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            row = {
                "session_id": key,
                "source_url": str(source_url or "").strip(),
                "destination_url": str(destination_url or "").strip(),
                "destination_url_masked": _mask_url_credentials(destination_url),
                "sample_rate": int(sample_rate or 16000),
                "codec_hint": str(codec_hint or "pcma").strip() or "pcma",
                "command": list(cmd),
                "process": process,
                "start_time": time.time(),
            }
            self._sessions[key] = row

        return {
            "ok": True,
            "started": True,
            "idempotent": False,
            "state": "active",
            "session_id": key,
            "destination_url_masked": row["destination_url_masked"],
        }

    def stop_session(self, session_id: str) -> Dict:
        """停止会话。"""
        key = str(session_id or "").strip()
        if not key:
            return {"ok": False, "stopped": False, "state": "error", "msg": "session_id is required"}

        with self._lock:
            current = self._sessions.pop(key, None)

        if not current:
            return {"ok": True, "stopped": False, "state": "idle", "session_id": key}

        process = current.get("process")
        if process and process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(b"q")
                    process.stdin.flush()
            except Exception:
                logger.debug("suppressed exception in app/utils/TalkbackRelay.py:155", exc_info=True)

            try:
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    logger.debug("suppressed exception in app/utils/TalkbackRelay.py:163", exc_info=True)

        return {"ok": True, "stopped": True, "state": "stopped", "session_id": key}

    def get_status(self, session_id: str) -> Dict:
        """获取状态。"""
        key = str(session_id or "").strip()
        with self._lock:
            current = self._sessions.get(key)

        if not current:
            return {"ok": True, "state": "idle", "session_id": key}

        process = current.get("process")
        state = "active" if process and process.poll() is None else "stopped"
        return {
            "ok": True,
            "state": state,
            "session_id": key,
            "source_url": current.get("source_url", ""),
            "destination_url_masked": current.get("destination_url_masked", ""),
            "sample_rate": current.get("sample_rate", 16000),
            "codec_hint": current.get("codec_hint", "pcma"),
        }
