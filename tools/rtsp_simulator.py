#!/usr/bin/env python3
import contextlib
import hashlib
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional


MEDIAMTX_VERSION = "1.10.0"
MEDIAMTX_SHA256 = "2dd02ff07a938f5bb93c33bee82a18c62675379865d2afb0db1b273e4088560e"


def _cache_dir() -> Path:
    """返回缓存目录。"""
    return Path(os.environ.get("BEACON_RTSP_SIM_CACHE_DIR") or (Path.home() / ".cache" / "beacon-rtsp-sim"))


def _mediamtx_dir() -> Path:
    """返回`mediamtx`目录。"""
    return _cache_dir() / f"mediamtx-{MEDIAMTX_VERSION}"


def _is_within_directory(base_dir: Path, candidate: Path) -> bool:
    """判断`within``directory`。"""
    try:
        candidate.relative_to(base_dir)
        return True
    except ValueError:
        return False


def _resolve_safe_tar_member_target(base_dir: Path, member: tarfile.TarInfo) -> Optional[Path]:
    """解析并返回安全`tar``member``target`。"""
    member_name = str(getattr(member, "name", "") or "").strip()
    if not member_name or Path(member_name).is_absolute():
        return None
    if member.issym() or member.islnk():
        return None

    member_target = (base_dir / member_name).resolve()
    if not _is_within_directory(base_dir, member_target):
        return None
    return member_target


def _extract_regular_tar_member(tf: tarfile.TarFile, member: tarfile.TarInfo, member_target: Path) -> bool:
    """提取`regular``tar``member`。"""
    member_target.parent.mkdir(parents=True, exist_ok=True)
    extracted_file = tf.extractfile(member)
    if extracted_file is None:
        return False

    with extracted_file, open(member_target, "wb") as handle:
        shutil.copyfileobj(extracted_file, handle)
    try:
        member_target.chmod(member.mode & 0o777)
    except Exception:
        pass
    return True


def _extract_tar_safely(archive_path: Path, target_dir: Path) -> int:
    """提取`tar``safely`。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    base_dir = target_dir.resolve()
    extracted = 0

    with tarfile.open(archive_path, "r:gz") as tf:
        for member in tf.getmembers():
            member_target = _resolve_safe_tar_member_target(base_dir, member)
            if member_target is None:
                continue

            if member.isdir():
                member_target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isreg():
                continue

            if _extract_regular_tar_member(tf, member, member_target):
                extracted += 1

    return extracted


def _verify_archive_sha256(archive_path: Path, expected_sha256: str = MEDIAMTX_SHA256) -> None:
    """校验下载的 MediaMTX 发布包。"""
    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"mediamtx archive SHA-256 mismatch: expected {expected_sha256}, got {actual}"
        )


def ensure_mediamtx() -> Path:
    """处理`ensure``mediamtx`。"""
    target_dir = _mediamtx_dir()
    binary = target_dir / "mediamtx"
    if binary.exists():
        return binary

    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / "mediamtx.tar.gz"
    if archive.exists():
        try:
            _verify_archive_sha256(archive)
        except RuntimeError:
            archive.unlink()

    if not archive.exists():
        partial = archive.with_name(f"{archive.name}.part")
        try:
            # Keep the source URL literal: urllib must never receive a caller-controlled scheme or host.
            with urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                "https://github.com/bluenviron/mediamtx/releases/download/v1.10.0/mediamtx_v1.10.0_linux_amd64.tar.gz",
                timeout=30,
            ) as resp, partial.open("wb") as handle:
                shutil.copyfileobj(resp, handle)
            _verify_archive_sha256(partial)
            partial.replace(archive)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    _extract_tar_safely(archive, target_dir)
    if not binary.exists():
        raise RuntimeError(f"mediamtx binary missing after extraction: {binary}")

    binary.chmod(0o755)
    return binary


def _find_free_port() -> int:
    """查找`free`端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_free_even_udp_port_pair():
    """查找`free``even``udp`端口`pair`。"""
    while True:
        port = _find_free_port()
        if port % 2 != 0:
            port += 1
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s1, contextlib.closing(
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ) as s2:
            try:
                s1.bind(("127.0.0.1", port))
                s2.bind(("127.0.0.1", port + 1))
                return port, port + 1
            except OSError:
                continue


def _wait_for_port(host: str, port: int, timeout_seconds: float = 10.0) -> None:
    """等待端口。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"timeout waiting for {host}:{port}")


class RtspSimulator:
    def __init__(self, *, path: str = "beacon-test", width: int = 160, height: int = 120, rate: int = 1):
        """处理`init`。"""
        self.path = str(path or "beacon-test").strip("/") or "beacon-test"
        self.width = int(width)
        self.height = int(height)
        self.rate = int(rate)
        self.temp_dir = None
        self.mediamtx_proc = None
        self.publisher_proc = None
        self.rtsp_port = _find_free_port()
        self.api_port = _find_free_port()
        self.rtmp_port = _find_free_port()
        self.hls_port = _find_free_port()
        self.webrtc_port = _find_free_port()
        self.webrtc_local_udp_port = _find_free_port()
        self.srt_port = _find_free_port()
        self.rtp_port, self.rtcp_port = _find_free_even_udp_port_pair()
        self.stream_url = f"rtsp://127.0.0.1:{self.rtsp_port}/{self.path}"

    def __enter__(self):
        """处理`enter`。"""
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        """处理`exit`。"""
        self.stop()
        return False

    def _write_config(self, path: Path, template_path: Path) -> None:
        """写入配置。"""
        content = template_path.read_text(encoding="utf-8")
        replacements = {
            "logLevel": "warn",
            "apiAddress": f":{self.api_port}",
            "rtspAddress": f":{self.rtsp_port}",
            "rtpAddress": f":{self.rtp_port}",
            "rtcpAddress": f":{self.rtcp_port}",
            "rtmpAddress": f":{self.rtmp_port}",
            "hlsAddress": f":{self.hls_port}",
            "webrtcAddress": f":{self.webrtc_port}",
            "webrtcLocalUDPAddress": f":{self.webrtc_local_udp_port}",
            "srtAddress": f":{self.srt_port}",
        }
        for key, value in replacements.items():
            content = re.sub(rf"(?m)^({re.escape(key)}:\s*).*$", rf"\1{value}", content)
        # The destination path comes from a TemporaryDirectory controlled by this simulator.
        path.write_text(content, encoding="utf-8")  # NOSONAR

    def start(self) -> None:
        """启动相关数据。"""
        if self.mediamtx_proc or self.publisher_proc:
            return

        binary = ensure_mediamtx()
        self.temp_dir = tempfile.TemporaryDirectory(prefix="beacon_rtsp_sim_")
        config_path = Path(self.temp_dir.name) / "mediamtx.yml"
        self._write_config(config_path, binary.with_name("mediamtx.yml"))

        self.mediamtx_proc = subprocess.Popen(
            [str(binary), str(config_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            if self.mediamtx_proc.poll() is not None:
                output = ""
                if self.mediamtx_proc.stdout is not None:
                    output = self.mediamtx_proc.stdout.read()
                raise RuntimeError(f"mediamtx exited unexpectedly: {output}")
            try:
                _wait_for_port("127.0.0.1", self.rtsp_port, timeout_seconds=0.2)
                break
            except RuntimeError:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"timeout waiting for 127.0.0.1:{self.rtsp_port}")

        time.sleep(0.3)

        self.publisher_proc = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=size={self.width}x{self.height}:rate={self.rate}",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-g",
                "1",
                "-keyint_min",
                "1",
                "-sc_threshold",
                "0",
                "-tune",
                "zerolatency",
                "-preset",
                "ultrafast",
                "-f",
                "rtsp",
                "-rtsp_transport",
                "tcp",
                self.stream_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        self.wait_until_ready()

    def wait_until_ready(self, timeout_seconds: float = 15.0) -> None:
        """等待`until``ready`。"""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.publisher_proc and self.publisher_proc.poll() is not None:
                output = ""
                if self.publisher_proc.stdout is not None:
                    output = self.publisher_proc.stdout.read()
                raise RuntimeError(f"ffmpeg publisher exited unexpectedly: {output}")
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height",
                    "-of",
                    "json",
                    self.stream_url,
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0 and "codec_name" in (probe.stdout or ""):
                return
            time.sleep(0.3)
        raise RuntimeError("timeout waiting for RTSP stream to become readable")

    def stop(self) -> None:
        """停止相关数据。"""
        for proc in (self.publisher_proc, self.mediamtx_proc):
            if not proc:
                continue
            if proc.poll() is None:
                with contextlib.suppress(Exception):
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    with contextlib.suppress(Exception):
                        proc.kill()
                    with contextlib.suppress(Exception):
                        proc.wait(timeout=3)
            with contextlib.suppress(Exception):
                if proc.stdout is not None:
                    proc.stdout.close()
        self.publisher_proc = None
        self.mediamtx_proc = None
        if self.temp_dir is not None:
            self.temp_dir.cleanup()
            self.temp_dir = None


def main() -> int:
    """处理`main`。"""
    with RtspSimulator() as sim:
        print(sim.stream_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
