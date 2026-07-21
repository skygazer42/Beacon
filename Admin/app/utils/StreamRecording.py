# ========== 视频流录像和截图工具 ==========
# 提供视频流手动录像、截图功能

import os
import re
import subprocess
import threading
import time
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, Dict

try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None


logger = logging.getLogger(__name__)


_VALID_STREAM_CODE_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
_ALLOWED_STREAM_URL_SCHEMES = {"rtsp", "rtsps", "rtmp", "rtmps", "http", "https"}
_ALLOWED_RECORD_FORMATS = {"mp4", "flv", "ts"}
MSG_INVALID_STREAM_CODE = "视频流编号非法"


def _normalize_stream_code(stream_code: str) -> str:
    """执行归一化流编码。"""
    try:
        token = str(stream_code or "").strip()
    except Exception:
        token = ""
    if not token:
        return ""
    if len(token) > 128:
        return ""
    if _VALID_STREAM_CODE_RE.fullmatch(token):
        return token
    return ""


def _normalize_record_format(fmt: str) -> str:
    """执行归一化`record``format`。"""
    token = str(fmt or "").strip().lower()
    if token in _ALLOWED_RECORD_FORMATS:
        return token
    return "mp4"


def _validate_stream_url(stream_url: str) -> str:
    """校验流URL。"""
    try:
        url = str(stream_url or "").strip()
    except Exception:
        url = ""
    if not url:
        return ""
    if len(url) > 2048:
        return ""
    if any(ch in url for ch in ("\r", "\n", "\x00")):
        return ""

    parsed = urllib.parse.urlparse(url)
    scheme = str(parsed.scheme or "").lower()
    if scheme not in _ALLOWED_STREAM_URL_SCHEMES:
        return ""
    if not parsed.netloc:
        return ""

    return url


def _safe_join(base_dir: str, *parts: str) -> str:
    """安全拼接路径。"""
    base = os.path.abspath(str(base_dir or ""))
    candidate = os.path.abspath(os.path.join(base, *[str(p or "") for p in parts]))

    try:
        common = os.path.commonpath([base, candidate])
    except Exception as e:
        raise ValueError(f"invalid path: {candidate}") from e

    if common != base:
        raise ValueError(f"path escapes base dir: {candidate}")

    return candidate


class StreamRecorder:
    """视频流录像器"""

    def __init__(self, storage_root: str = "upload"):
        """处理`init`。"""
        self.storage_root = storage_root
        self.active_recordings = {}  # stream_code -> recording_info
        self.lock = threading.Lock()

    @staticmethod
    def _is_process_running(process) -> bool:
        """判断进程`running`。"""
        try:
            return process is not None and process.poll() is None
        except Exception:
            return False

    @staticmethod
    def _elapsed_seconds(recording_info: dict, *, end_time=None) -> float:
        """返回耗时秒数。"""
        started = recording_info.get('start_time')
        if not isinstance(started, datetime):
            return 0.0
        finished = end_time or datetime.now()
        return max(0.0, (finished - started).total_seconds())

    def _finalize_recording(self, stream_code: str, *, status: str = 'completed') -> Optional[Dict]:
        """完成录制。"""
        with self.lock:
            recording_info = self.active_recordings.get(stream_code)
            if not recording_info:
                return None

            end_time = datetime.now()
            duration = self._elapsed_seconds(recording_info, end_time=end_time)
            recording_info['status'] = status
            recording_info['end_time'] = end_time
            recording_info['actual_duration'] = duration
            del self.active_recordings[stream_code]

        return {
            'recording_info': recording_info,
            'duration': duration,
        }

    @staticmethod
    def _build_audio_output_args(format: str, include_audio: bool) -> list:
        """构建音频`output``args`。"""
        if not include_audio:
            return ['-an']

        normalized_format = str(format or "").strip().lower()
        if normalized_format in {"mp4", "flv", "ts"}:
            return [
                '-map', '0:a?',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', '48000',
                '-ac', '2',
                '-af', 'aresample=async=1:first_pts=0',
            ]

        return ['-map', '0:a?', '-c:a', 'copy']

    @staticmethod
    def _send_stop_command(process) -> None:
        """Ask FFmpeg to stop gracefully."""
        stdin = getattr(process, 'stdin', None)
        if stdin is None:
            return
        try:
            stdin.write(b'q')  # 发送 'q' 命令优雅停止
            stdin.flush()
        except (BrokenPipeError, ValueError):
            logger.debug("suppressed exception in app/utils/StreamRecording.py:165", exc_info=True)

    @staticmethod
    def _wait_or_kill_process(process) -> None:
        """Wait for FFmpeg to exit, killing it after a grace period."""
        try:
            process.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            process.kill()  # 强制停止
        try:
            process.wait(timeout=3)
        except Exception:
            logger.debug("suppressed exception in app/utils/StreamRecording.py:178", exc_info=True)

    def _stop_recording_process(self, process) -> Optional[Dict]:
        """Stop an active recording process and return a failure payload if it remains running."""
        try:
            if self._is_process_running(process):
                self._send_stop_command(process)
                self._wait_or_kill_process(process)
        except Exception as e:
            if self._is_process_running(process):
                return {
                    'success': False,
                    'message': f'停止录像失败：{str(e)}'
                }
        return None

    def start_recording(
        self,
        stream_code: str,
        stream_url: str,
        duration: int = 60,
        format: str = "mp4",
        include_audio: bool = True,
    ) -> Dict:
        """开始录像

        Args:
            stream_code: 视频流编号
            stream_url: 拉流地址
            duration: 录像时长（秒），0表示手动停止
            format: 视频格式（mp4/flv/ts）
            include_audio: 是否录制音频（默认 True）

        Returns:
            Dict with 'success', 'message', 'record_id', 'save_path'
        """
        stream_code = _normalize_stream_code(stream_code)
        if not stream_code:
            return {
                'success': False,
                'message': MSG_INVALID_STREAM_CODE,
            }

        with self.lock:
            if stream_code in self.active_recordings:
                return {
                    'success': False,
                    'message': '该视频流正在录像中'
                }

        # 创建录像目录
        try:
            record_dir = _safe_join(self.storage_root, 'recordings', stream_code)
        except Exception:
            return {
                'success': False,
                'message': '录像目录非法'
            }
        os.makedirs(record_dir, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{stream_code}_{timestamp}.{format}"
        try:
            save_path = _safe_join(record_dir, filename)
        except Exception:
            return {
                'success': False,
                'message': '录像路径非法'
            }

        # 使用 FFmpeg 录像
        try:
            # FFmpeg 命令
            cmd = ['ffmpeg']

            # RTSP: prefer TCP for stability (best-effort)
            if isinstance(stream_url, str) and stream_url.lower().startswith(("rtsp://", "rtsps://")):
                cmd += ['-rtsp_transport', 'tcp']

            cmd += [
                '-i', stream_url,
                # Explicit mapping:
                # - Always map the first video stream
                # - Audio is optional (0:a?) when include_audio=True
                '-map', '0:v:0',
            ]
            cmd += self._build_audio_output_args(format, include_audio)

            # Video always copy to minimize CPU.
            cmd += ['-c:v', 'copy']

            cmd += ['-f', format]

            # 如果指定了时长
            if duration > 0:
                cmd.extend(['-t', str(duration)])

            cmd.append(save_path)

            # 启动 FFmpeg 进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE
            )

            # 记录录像信息
            record_id = f"{stream_code}_{timestamp}"
            recording_info = {
                'record_id': record_id,
                'stream_code': stream_code,
                'stream_url': stream_url,
                'save_path': save_path,
                'relative_path': os.path.join('recordings', stream_code, filename).replace('\\', '/'),
                'start_time': datetime.now(),
                'duration': duration,
                'format': format,
                'process': process,
                'status': 'recording'
            }

            with self.lock:
                self.active_recordings[stream_code] = recording_info

            # 如果指定了时长，启动自动停止线程
            if duration > 0:
                stop_thread = threading.Thread(
                    target=self._auto_stop_recording,
                    args=(stream_code, duration + 5)  # 额外5秒容错
                )
                stop_thread.daemon = True
                stop_thread.start()

            return {
                'success': True,
                'message': '录像已开始',
                'record_id': record_id,
                'save_path': recording_info['relative_path']
            }

        except Exception as e:
            return {
                'success': False,
                'message': f'启动录像失败：{str(e)}'
            }

    def stop_recording(self, stream_code: str) -> Dict:
        """停止录像

        Args:
            stream_code: 视频流编号

        Returns:
            Dict with 'success', 'message', 'save_path', 'duration'
        """
        stream_code = _normalize_stream_code(stream_code)
        if not stream_code:
            return {
                'success': False,
                'message': MSG_INVALID_STREAM_CODE,
            }

        with self.lock:
            if stream_code not in self.active_recordings:
                return {
                    'success': False,
                    'message': '该视频流未在录像'
                }

            recording_info = self.active_recordings[stream_code]

        process = recording_info.get('process')

        stop_error = self._stop_recording_process(process)
        if stop_error:
            return stop_error

        completed = self._finalize_recording(stream_code)
        if not completed:
            return {
                'success': False,
                'message': '该视频流未在录像'
            }

        recording_info = completed['recording_info']
        duration = completed['duration']
        return {
            'success': True,
            'message': '录像已停止',
            'save_path': recording_info['relative_path'],
            'duration': duration
        }

    def get_recording_status(self, stream_code: str) -> Optional[Dict]:
        """获取录像状态"""
        with self.lock:
            if stream_code not in self.active_recordings:
                return None

            recording_info = self.active_recordings[stream_code]

        if not self._is_process_running(recording_info.get('process')):
            self._finalize_recording(stream_code)
            return None

        # 计算已录制时长
        elapsed = self._elapsed_seconds(recording_info)

        return {
            'record_id': recording_info['record_id'],
            'stream_code': recording_info['stream_code'],
            'status': recording_info['status'],
            'start_time': recording_info['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
            'elapsed_time': int(elapsed),
            'duration': recording_info['duration'],
            'save_path': recording_info['relative_path']
        }

    def list_active_recordings(self) -> list:
        """列出所有活跃的录像"""
        with self.lock:
            items = list(self.active_recordings.items())

        recordings = []
        finished_stream_codes = []
        for stream_code, info in items:
            if not self._is_process_running(info.get('process')):
                finished_stream_codes.append(stream_code)
                continue

            elapsed = self._elapsed_seconds(info)
            recordings.append({
                'stream_code': stream_code,
                'record_id': info['record_id'],
                'status': info['status'],
                'elapsed_time': int(elapsed),
                'duration': info['duration']
            })

        for stream_code in finished_stream_codes:
            self._finalize_recording(stream_code)

        return recordings

    def _auto_stop_recording(self, stream_code: str, wait_time: int):
        """自动停止录像（内部方法）"""
        time.sleep(wait_time)
        self.stop_recording(stream_code)


class StreamSnapshotter:
    """视频流截图器"""

    def __init__(self, storage_root: str = "upload"):
        """处理`init`。"""
        self.storage_root = storage_root

    def capture_snapshot(self, stream_code: str, stream_url: str,
                        method: str = "ffmpeg") -> Dict:
        """截取视频流快照

        Args:
            stream_code: 视频流编号
            stream_url: 拉流地址
            method: 截图方法（ffmpeg/opencv）

        Returns:
            Dict with 'success', 'message', 'image_path'
        """
        stream_code = _normalize_stream_code(stream_code)
        if not stream_code:
            return {
                'success': False,
                'message': MSG_INVALID_STREAM_CODE,
            }

        stream_url = _validate_stream_url(stream_url)
        if not stream_url:
            return {
                'success': False,
                'message': '拉流地址非法',
            }

        # 创建截图目录
        try:
            snapshot_dir = _safe_join(self.storage_root, 'snapshots', stream_code)
        except Exception:
            return {
                'success': False,
                'message': '截图目录非法'
            }
        os.makedirs(snapshot_dir, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{stream_code}_{timestamp}.jpg"
        try:
            save_path = _safe_join(snapshot_dir, filename)
        except Exception:
            return {
                'success': False,
                'message': '截图路径非法'
            }

        try:
            if method == "ffmpeg":
                success = self._capture_with_ffmpeg(stream_url, save_path)
            else:
                success = self._capture_with_opencv(stream_url, save_path)

            if success:
                relative_path = os.path.join('snapshots', stream_code, filename).replace('\\', '/')
                return {
                    'success': True,
                    'message': '截图成功',
                    'image_path': relative_path,
                    'full_path': save_path
                }
            else:
                return {
                    'success': False,
                    'message': '截图失败'
                }

        except Exception as e:
            return {
                'success': False,
                'message': f'截图失败：{str(e)}'
            }

    def _capture_with_ffmpeg(self, stream_url: str, save_path: str) -> bool:
        """使用 FFmpeg 截图"""
        try:
            stream_url = _validate_stream_url(stream_url)
            if not stream_url:
                return False

            try:
                base = os.path.abspath(str(self.storage_root or ""))
                candidate = os.path.abspath(str(save_path or ""))
                if os.path.commonpath([base, candidate]) != base:
                    return False
                save_path = candidate
            except Exception:
                return False

            cmd = [
                'ffmpeg',
                '-i', stream_url,
                '-vframes', '1',  # 只截取一帧
                '-q:v', '2',      # 质量（1-31，越小质量越高）
                '-y',             # 覆盖已存在的文件
                save_path
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )

            return result.returncode == 0 and os.path.exists(save_path)

        except Exception as e:
            logger.warning("FFmpeg capture failed: %s", e)
            return False

    def _capture_with_opencv(self, stream_url: str, save_path: str) -> bool:
        """使用 OpenCV 截图"""
        if cv2 is None:
            logger.info("OpenCV capture skipped: opencv-python is not installed")
            return False
        try:
            stream_url = _validate_stream_url(stream_url)
            if not stream_url:
                return False

            try:
                base = os.path.abspath(str(self.storage_root or ""))
                candidate = os.path.abspath(str(save_path or ""))
                if os.path.commonpath([base, candidate]) != base:
                    return False
                save_path = candidate
            except Exception:
                return False

            cap = cv2.VideoCapture(stream_url)

            # 尝试读取几帧以确保稳定
            for _ in range(5):
                ret, frame = cap.read()
                if ret:
                    break

            cap.release()

            if ret and frame is not None:
                cv2.imwrite(save_path, frame)
                return os.path.exists(save_path)
            else:
                return False

        except Exception as e:
            logger.warning("OpenCV capture failed: %s", e)
            return False


# ========== 全局实例 ==========
_recorder = None
_snapshotter = None


def get_stream_recorder(storage_root: str = "upload") -> StreamRecorder:
    """获取录像器单例"""
    global _recorder
    if _recorder is None:
        _recorder = StreamRecorder(storage_root)
    return _recorder


def get_stream_snapshotter(storage_root: str = "upload") -> StreamSnapshotter:
    """获取截图器单例"""
    global _snapshotter
    if _snapshotter is None:
        _snapshotter = StreamSnapshotter(storage_root)
    return _snapshotter
