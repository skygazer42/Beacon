import configparser
import io
import psutil  # type: ignore
import runtime_paths  # type: ignore
import os
import time
import logging
import json
import threading
import socket
import atexit
import signal
import secrets
import sys
import platform
import subprocess
import glob
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from framework.versioning import get_project_version

LOGFILE_TIMEFMT = "%Y-%m-%d_%H%M%S"
LOGFILE_WHEN = 'd'
LOGFILE_BACKUPCOUNT = 7
ROOT_DIR = runtime_paths.resolve_root_dir()
BASE_DIR = runtime_paths.resolve_admin_dir(ROOT_DIR)
LOG_DIR = runtime_paths.resolve_log_dir(ROOT_DIR)
LOCK_FILE = runtime_paths.resolve_lock_path(LOG_DIR)

MEDIA_SERVER_CONFIG_INI = "config.ini"
MEDIA_SERVER_RUNTIME_CONFIG_INI = "config.runtime.ini"
WINDOWS_PYTHON_EXE = "python.exe"
WINDOWS_MANAGE_EXE = "manage.exe"

def _pid_exists(pid):
    """判断PID是否存在。"""
    if not pid:
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    return bool(psutil.pid_exists(pid_int))

def _read_config_json(filepath):
    """读取配置JSON。"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='gbk') as f:
            return json.loads(f.read())

def _pick_first_existing(paths, require_file=False):
    """选择首个现有。"""
    for path in paths:
        if not path:
            continue
        if require_file:
            if os.path.isfile(path):
                return path
            continue
        if os.path.exists(path):
            return path
    return ""


def _unique_existing_dirs(paths):
    """返回去重后现有目录列表。"""
    seen = set()
    result = []
    for path in paths:
        if not path:
            continue
        norm = os.path.normpath(path)
        if norm in seen or not os.path.isdir(norm):
            continue
        seen.add(norm)
        result.append(norm)
    return result


def _prepend_env_path(env, key, paths):
    """返回`prepend`环境变量路径。"""
    existing = str((env or {}).get(key) or "").strip()
    parts = [part for part in existing.split(os.pathsep) if part]
    for path in reversed(_unique_existing_dirs(paths)):
        if path in parts:
            parts.remove(path)
        parts.insert(0, path)
    if parts:
        env[key] = os.pathsep.join(parts)


def _resolve_runtime_libs_dir():
    """解析并返回交付目录中的运行库目录。"""
    if platform.system().lower() == "windows":
        return ""

    candidate = os.path.join(ROOT_DIR, "runtime-libs")
    if os.path.isdir(candidate):
        return os.path.normpath(candidate)
    return ""


def _build_runtime_env(base_env=None):
    """为子进程构建基础运行时环境。"""
    env = dict(base_env or os.environ.copy())
    runtime_libs_dir = _resolve_runtime_libs_dir()
    if runtime_libs_dir:
        _prepend_env_path(env, "LD_LIBRARY_PATH", [runtime_libs_dir])
    return env


def _ensure_media_secret(config_data):
    secret = str(os.environ.get("BEACON_MEDIA_SECRET") or (config_data or {}).get("mediaSecret") or "").strip()
    if not secret:
        secret = secrets.token_urlsafe(24)
    if isinstance(config_data, dict):
        config_data["mediaSecret"] = secret
    return secret


def _resolve_analyzer_localdeps_layout():
    """解析并返回分析器`localdeps``layout`。"""
    if platform.system().lower() == "windows":
        return {}
    return runtime_paths.resolve_analyzer_localdeps_layout(ROOT_DIR) or {}


def _safe_psutil_text(getter):
    """安全读取 psutil 返回的文本字段。"""
    try:
        value = getter()
    except Exception:
        return ""
    return str(value or "")


def _safe_psutil_cmdline(proc):
    """安全读取并截断进程命令行。"""
    try:
        cmdline = " ".join(proc.cmdline() or [])
    except Exception:
        return ""
    if cmdline and len(cmdline) > 300:
        return cmdline[:297] + "..."
    return cmdline


def _fill_process_runtime_info(info, pid):
    """填充进程运行时状态信息。"""
    process = psutil.Process(pid)
    info["status"] = process.status()
    time_array = time.localtime(int(process.create_time()))
    info["started"] = time.strftime("%Y-%m-%d %H:%M:%S", time_array)


def _build_analyzer_env(base_env=None):
    """构建分析器环境变量。"""
    env = dict(base_env or os.environ.copy())
    layout = _resolve_analyzer_localdeps_layout()
    if not layout:
        return _build_runtime_env(env)

    localdeps_dir = layout.get("localdeps_dir") or ""
    sysroot_dir = layout.get("sysroot_dir") or ""
    onnxruntime_dir = layout.get("onnxruntime_dir") or ""
    openvino_runtime_dir = layout.get("openvino_runtime_dir") or ""

    env["BEACON_LOCALDEPS_DIR"] = localdeps_dir
    if sysroot_dir:
        env["BEACON_SYSROOT_DIR"] = sysroot_dir
    if onnxruntime_dir:
        env["BEACON_ONNXRUNTIME_DIR"] = onnxruntime_dir
    if openvino_runtime_dir:
        env["BEACON_OPENVINO_RUNTIME_DIR"] = openvino_runtime_dir

    sysroot_include_dir = os.path.join(sysroot_dir, "usr", "include")
    sysroot_jsoncpp_include_dir = os.path.join(sysroot_include_dir, "jsoncpp")
    sysroot_multiarch_include_dirs = sorted(glob.glob(os.path.join(sysroot_include_dir, "*-linux-gnu")))
    sysroot_lib_dir = os.path.join(sysroot_dir, "usr", "lib")
    sysroot_multiarch_lib_dirs = sorted(glob.glob(os.path.join(sysroot_lib_dir, "*-linux-gnu")))

    onnxruntime_include_dir = os.path.join(onnxruntime_dir, "include") if onnxruntime_dir else ""
    onnxruntime_lib_dir = os.path.join(onnxruntime_dir, "lib") if onnxruntime_dir else ""
    openvino_include_dir = os.path.join(openvino_runtime_dir, "include") if openvino_runtime_dir else ""
    openvino_arch_lib_dirs = (
        sorted(glob.glob(os.path.join(openvino_runtime_dir, "lib", "*"))) if openvino_runtime_dir else []
    )
    openvino_tbb_include_dir = (
        os.path.join(openvino_runtime_dir, "3rdparty", "tbb", "include") if openvino_runtime_dir else ""
    )
    openvino_tbb_lib_dir = (
        os.path.join(openvino_runtime_dir, "3rdparty", "tbb", "lib") if openvino_runtime_dir else ""
    )

    _prepend_env_path(
        env,
        "CPATH",
        [
            sysroot_include_dir,
            sysroot_jsoncpp_include_dir,
            *sysroot_multiarch_include_dirs,
            onnxruntime_include_dir,
            openvino_include_dir,
            openvino_tbb_include_dir,
        ],
    )
    library_paths = [
        *sysroot_multiarch_lib_dirs,
        onnxruntime_lib_dir,
        *openvino_arch_lib_dirs,
        openvino_tbb_lib_dir,
    ]
    _prepend_env_path(env, "LIBRARY_PATH", library_paths)
    _prepend_env_path(env, "LD_LIBRARY_PATH", library_paths)
    return _build_runtime_env(env)

def _read_text_file_with_fallbacks(path, encodings=("utf-8", "gbk")):
    last_error = None
    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read(), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    with open(path, "r", encoding="utf-8") as f:
        return f.read(), "utf-8"


def _write_text_file_if_changed(path, content, encoding="utf-8"):
    try:
        with open(path, "r", encoding=encoding) as f:
            if f.read() == content:
                return
    except (OSError, UnicodeDecodeError):
        pass
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(content)


def _build_media_server_runtime_config(config_path, config_data):
    if not config_path or not os.path.exists(config_path) or not config_data:
        return config_path

    resolved_config_path = os.path.realpath(config_path)
    try:
        config_text, _encoding = _read_text_file_with_fallbacks(resolved_config_path)
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string(config_text)
    except Exception as exc:
        logging.getLogger().warning("load media server config failed, using template: %s", exc)
        return config_path

    overrides = {
        ("api", "secret"): str(os.environ.get("BEACON_MEDIA_SECRET") or (config_data or {}).get("mediaSecret") or "").strip(),
        ("http", "port"): str(_clamp_int((config_data or {}).get("mediaHttpPort") or 9992, default=9992, min_value=1, max_value=65535)),
        ("http", "sslport"): "0",
        ("rtsp", "port"): str(_clamp_int((config_data or {}).get("mediaRtspPort") or 9994, default=9994, min_value=1, max_value=65535)),
        ("rtmp", "port"): str(_clamp_int((config_data or {}).get("mediaRtmpPort") or 9995, default=9995, min_value=1, max_value=65535)),
    }
    for (section, key), value in overrides.items():
        if not value:
            continue
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, value)

    runtime_config_path = os.path.join(
        os.path.dirname(resolved_config_path),
        MEDIA_SERVER_RUNTIME_CONFIG_INI,
    )
    try:
        buffer = io.StringIO()
        parser.write(buffer, space_around_delimiters=False)
        _write_text_file_if_changed(runtime_config_path, buffer.getvalue(), encoding="utf-8")
    except Exception as exc:
        logging.getLogger().warning("write media server runtime config failed, using template: %s", exc)
        return config_path
    return runtime_config_path


def _build_media_server_args(config_data=None):
    """构建媒体服务端`args`。"""
    is_windows = platform.system().lower() == "windows"
    if is_windows:
        media_bin = _pick_first_existing([
            os.path.join(ROOT_DIR, "MediaServer", "bin", "bin.x86.windows10", "MediaServer.exe"),
            os.path.join(ROOT_DIR, "MediaServer", "MediaServer.exe"),
        ], require_file=True)
        config_path = _pick_first_existing([
            os.path.join(ROOT_DIR, "MediaServer", "bin", "bin.x86.windows10", MEDIA_SERVER_CONFIG_INI),
            os.path.join(ROOT_DIR, "MediaServer", MEDIA_SERVER_CONFIG_INI),
        ], require_file=True)
    else:
        arch = platform.machine().lower()
        if "aarch64" in arch or "arm" in arch:
            bin_dir = os.path.join(ROOT_DIR, "MediaServer", "bin", "bin.arm.gcc9.4")
        else:
            bin_dir = os.path.join(ROOT_DIR, "MediaServer", "bin", "bin.x86.gcc9.4")
        media_bin = _pick_first_existing([
            os.path.join(bin_dir, "MediaServer"),
        ], require_file=True)
        config_path = _pick_first_existing([
            os.path.join(bin_dir, MEDIA_SERVER_CONFIG_INI),
        ], require_file=True)

    if not media_bin:
        return []
    args = [media_bin]
    runtime_config_path = _build_media_server_runtime_config(config_path, config_data)
    if runtime_config_path and os.path.exists(runtime_config_path):
        args += ["-c", runtime_config_path]
    return args

def _write_ascii_file_if_changed(path, lines):
    content = "\n".join(lines) + "\n"
    try:
        with open(path, "r", encoding="ascii") as f:
            if f.read() == content:
                return
    except (OSError, UnicodeDecodeError):
        pass
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(content)


def _prepare_packaged_python_runtime():
    if platform.system().lower() != "windows":
        return False

    venv_dir = os.path.join(BASE_DIR, "venv")
    runtime_dir = os.path.join(BASE_DIR, "python-runtime")
    venv_python = os.path.join(venv_dir, "Scripts", WINDOWS_PYTHON_EXE)
    runtime_python = os.path.join(runtime_dir, WINDOWS_PYTHON_EXE)
    pyvenv_cfg = os.path.join(venv_dir, "pyvenv.cfg")
    if not (
        os.path.isfile(venv_python)
        and os.path.isfile(runtime_python)
        and os.path.isdir(runtime_dir)
    ):
        return False

    try:
        _write_ascii_file_if_changed(pyvenv_cfg, [
            "home = %s" % runtime_dir,
            "include-system-site-packages = false",
            "version = 3.11.7",
            "executable = %s" % runtime_python,
            "command = python -m venv Admin\\venv",
        ])

        for pth_file in glob.glob(os.path.join(runtime_dir, "python*._pth")):
            zip_name = os.path.splitext(os.path.basename(pth_file))[0] + ".zip"
            _write_ascii_file_if_changed(pth_file, [
                zip_name,
                ".",
                "..",
                "..\\venv\\Lib\\site-packages",
                "import site",
            ])
        return True
    except Exception as exc:
        logging.getLogger().warning("prepare packaged python runtime failed: %s", exc)
        return False


def _build_admin_args(admin_port):
    """构建管理员`args`。"""
    _prepare_packaged_python_runtime()
    manage_py = os.path.join(BASE_DIR, "manage.py")
    packaged_python = _pick_first_existing([
        os.path.join(BASE_DIR, "venv", "Scripts", WINDOWS_PYTHON_EXE),
        os.path.join(BASE_DIR, "venv", "bin", "python"),
    ], require_file=True)
    if packaged_python and os.path.exists(manage_py):
        return [packaged_python, manage_py, "runserver", "0.0.0.0:%s" % admin_port, "--noreload"]

    manage_exe = _pick_first_existing([
        os.path.join(BASE_DIR, WINDOWS_MANAGE_EXE),
        os.path.join(BASE_DIR, "dist", "manage", WINDOWS_MANAGE_EXE),
        os.path.join(BASE_DIR, "manage", WINDOWS_MANAGE_EXE),
    ], require_file=True)
    if manage_exe:
        return [manage_exe, "runserver", "0.0.0.0:%s" % admin_port, "--noreload"]
    python_exec = sys.executable or "python3"
    return [python_exec, manage_py, "runserver", "0.0.0.0:%s" % admin_port, "--noreload"]

def _build_analyzer_args():
    """构建分析器`args`。"""
    is_windows = platform.system().lower() == "windows"
    if is_windows:
        analyzer_bin = _pick_first_existing([
            os.path.join(ROOT_DIR, "Analyzer", "Analyzer.exe"),
            os.path.join(ROOT_DIR, "Analyzer", "x64", "Release", "Analyzer.exe"),
        ], require_file=True)
    else:
        analyzer_bin = _pick_first_existing([
            os.path.join(ROOT_DIR, "Analyzer", "Analyzer"),
            os.path.join(ROOT_DIR, "Analyzer", "x64", "Release", "Analyzer"),
            os.path.join(ROOT_DIR, "Analyzer", "build", "Analyzer"),
            os.path.join(ROOT_DIR, "Analyzer", "build", "Analyzer", "Analyzer"),
        ], require_file=True)
    if not analyzer_bin:
        return []
    config_path = os.path.join(ROOT_DIR, "config.json")
    return [analyzer_bin, "-f", config_path]


def _config_value(config_data, env_key: str, json_key: str, default=None):
    """返回配置值。"""
    if env_key in os.environ:
        return os.environ.get(env_key)
    if isinstance(config_data, dict):
        return config_data.get(json_key, default)
    return default


def _config_text(config_data, env_key: str, json_key: str, default: str = "") -> str:
    """处理配置文本。"""
    raw = _config_value(config_data, env_key, json_key, default)
    return str(raw or "").strip()


def _config_bool(config_data, env_key: str, json_key: str, default: bool = False) -> bool:
    """处理配置布尔值。"""
    raw = _config_value(config_data, env_key, json_key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return int(raw) != 0
    return str(raw or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _config_int(config_data, env_key: str, json_key: str, default: int = 0, min_value: int = 0, max_value: int = 0) -> int:
    """处理配置整数值。"""
    raw = _config_value(config_data, env_key, json_key, default)
    return _clamp_int(raw, default=default, min_value=min_value, max_value=max_value)


def _resolve_internal_host(config_data) -> str:
    """解析并返回`internal`主机。"""
    raw_host = str((config_data or {}).get("host") or "").strip()
    if raw_host in ("", "0.0.0.0", "::"):
        return "127.0.0.1"
    return raw_host


def _normalize_usb_camera_video_size(raw_value, default: str = "1280x720") -> str:
    """执行归一化`usb`摄像头`video`大小。"""
    value = str(raw_value or "").strip().lower()
    parts = value.split("x")
    if len(parts) != 2:
        return default
    try:
        width = int(parts[0])
        height = int(parts[1])
    except Exception:
        return default
    if width <= 0 or height <= 0:
        return default
    return "%dx%d" % (width, height)


def _build_usb_camera_bridge_args(config_data):
    """构建`usb`摄像头`bridge``args`。"""
    if not _config_bool(config_data, "BEACON_USB_CAMERA_ENABLED", "usbCameraEnabled", default=False):
        return []

    ffmpeg_bin = _config_text(config_data, "BEACON_USB_CAMERA_FFMPEG_BIN", "usbCameraFfmpegBin", default="ffmpeg") or "ffmpeg"
    input_driver = _config_text(config_data, "BEACON_USB_CAMERA_INPUT_DRIVER", "usbCameraInputDriver", default="v4l2") or "v4l2"
    input_format = _config_text(config_data, "BEACON_USB_CAMERA_INPUT_FORMAT", "usbCameraInputFormat", default="mjpeg")
    video_size = _normalize_usb_camera_video_size(
        _config_text(config_data, "BEACON_USB_CAMERA_VIDEO_SIZE", "usbCameraVideoSize", default="1280x720"),
        default="1280x720",
    )
    framerate = _config_int(
        config_data,
        "BEACON_USB_CAMERA_FRAMERATE",
        "usbCameraFramerate",
        default=25,
        min_value=1,
        max_value=120,
    )
    device = _config_text(config_data, "BEACON_USB_CAMERA_DEVICE", "usbCameraDevice", default="/dev/video0") or "/dev/video0"
    publish_url = _config_text(config_data, "BEACON_USB_CAMERA_PUBLISH_URL", "usbCameraPublishUrl", default="")

    if not publish_url:
        publish_host = _resolve_internal_host(config_data)
        publish_port = _clamp_int((config_data or {}).get("mediaRtmpPort") or 9995, default=9995, min_value=1, max_value=65535)
        publish_app = _config_text(config_data, "BEACON_USB_CAMERA_APP", "usbCameraApp", default="live").strip("/") or "live"
        publish_name = _config_text(
            config_data,
            "BEACON_USB_CAMERA_STREAM_NAME",
            "usbCameraStreamName",
            default="usbcam",
        ).strip("/") or "usbcam"
        publish_url = "rtmp://%s:%d/%s/%s" % (publish_host, publish_port, publish_app, publish_name)

    args = [ffmpeg_bin, "-hide_banner", "-nostdin", "-f", input_driver]
    if input_format:
        args.extend(["-input_format", input_format])
    if video_size:
        args.extend(["-video_size", video_size])
    if framerate > 0:
        args.extend(["-framerate", str(framerate)])
    args.extend(
        [
            "-i",
            device,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(max(2, framerate * 2)),
            "-f",
            "flv",
            publish_url,
        ]
    )
    return args


def _publish_target_from_url(config_data, publish_url: str):
    """从推流地址解析目标主机和端口。"""
    parsed = urllib.parse.urlparse(str(publish_url or "").strip())
    host = parsed.hostname or _resolve_internal_host(config_data)
    if parsed.port:
        return host, int(parsed.port)
    if parsed.scheme == "rtmps":
        return host, 443
    port = _clamp_int((config_data or {}).get("mediaRtmpPort") or 9995, default=9995, min_value=1, max_value=65535)
    return host, port


def _wait_tcp_port(host: str, port: int, *, timeout_seconds: int = 15, interval_seconds: float = 0.2) -> bool:
    """等待TCP端口可连接。"""
    deadline = time.monotonic() + max(0, int(timeout_seconds or 0))
    while True:
        try:
            with socket.create_connection((host, int(port)), timeout=1):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(max(0.05, float(interval_seconds or 0.2)))


def _wait_for_usb_camera_publish_target(config_data, publish_url: str) -> bool:
    """等待USB摄像头推流目标就绪。"""
    host, port = _publish_target_from_url(config_data, publish_url)
    timeout_seconds = _config_int(
        config_data,
        "BEACON_USB_CAMERA_PUBLISH_WAIT_SECONDS",
        "usbCameraPublishWaitSeconds",
        default=15,
        min_value=0,
        max_value=120,
    )
    if _wait_tcp_port(host, port, timeout_seconds=timeout_seconds):
        return True
    logger.warning("skip initial UsbCameraBridge start: publish target not ready: %s:%s", host, port)
    return False


def _read_pid_from_lock(lock_path):
    """读取PID`from``lock`。"""
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        pid_str = content.split(",")[0].strip()
        return int(pid_str)
    except Exception:
        return None

def _write_lock(lock_path):
    """写入`lock`。"""
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w") as f:
        f.write("%d,%d\n" % (os.getpid(), int(time.time())))

def _remove_lock(lock_path):
    """处理`remove``lock`。"""
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass

def ensure_single_instance(lock_path):
    """处理`ensure``single``instance`。"""
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)

    for _ in range(2):
        try:
            _write_lock(lock_path)
            atexit.register(_remove_lock, lock_path)
            return True
        except FileExistsError:
            pid = _read_pid_from_lock(lock_path)
            if pid and _pid_exists(pid):
                logger.error("startup check failed: another instance is running (pid=%d)", pid)
                return False
            _remove_lock(lock_path)
        except Exception as e:
            logger.error("startup check failed: %s", str(e))
            return False
    return False

def _safe_process_detail(pid):
    """处理安全进程详情。"""
    detail = {"pid": pid}
    if not pid:
        return detail
    try:
        proc = psutil.Process(pid)
    except Exception:
        return detail
    detail["name"] = _safe_psutil_text(proc.name)
    detail["exe"] = _safe_psutil_text(proc.exe)
    detail["cmdline"] = _safe_psutil_cmdline(proc)
    return detail


def _format_process_detail(detail):
    """处理`format`进程详情。"""
    if not isinstance(detail, dict):
        return ""
    parts = []
    pid = detail.get("pid")
    if pid:
        parts.append("pid=%s" % pid)
    name = (detail.get("name") or "").strip()
    if name:
        parts.append("name=%s" % name)
    exe = (detail.get("exe") or "").strip()
    if exe:
        parts.append("exe=%s" % exe)
    cmdline = (detail.get("cmdline") or "").strip()
    if cmdline:
        parts.append("cmd=%s" % cmdline)
    return " ".join(parts).strip()


def _find_port_owner(port):
    """查找端口所属进程。"""
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception:
        return []
    owners = []
    for conn in conns:
        if not conn.laddr or conn.laddr.port != port or not conn.pid:
            continue
        owners.append(_safe_process_detail(conn.pid))

    # de-duplicate by pid
    seen = set()
    uniq = []
    for item in owners:
        pid = item.get("pid")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        uniq.append(item)
    return uniq

def _check_port_free(port):
    """检查端口`free`。"""
    if not port or port <= 0:
        return True, ""
    s = socket.socket(  # nosemgrep: python.lang.security.audit.network.bind.avoid-bind-to-all-interfaces
        socket.AF_INET,
        socket.SOCK_STREAM,
    )
    if os.name == "posix":
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
    try:
        # This socket is only a transient availability probe and is never put
        # into listening mode. Binding all interfaces mirrors Analyzer's real
        # listener, so an interface-specific conflict is not missed.
        # nosemgrep: python.lang.security.audit.network.bind.avoid-bind-to-all-interfaces
        s.bind(("0.0.0.0", int(port)))
        return True, ""
    except OSError:
        owners = _find_port_owner(int(port))
        if owners:
            details = "; ".join([_format_process_detail(item) for item in owners if _format_process_detail(item)])
            if details:
                return False, details
        return False, "in use"
    finally:
        try:
            s.close()
        except Exception:
            pass

def _get_configured_max_controls(config_data) -> int:
    """获取`configured`最大值`controls`。"""
    try:
        return int((config_data or {}).get("maxControls") or 0)
    except Exception:
        return 0


def _store_startup_recommended_max_controls(config_data, recommended: int) -> None:
    """缓存`startup``recommended`最大值`controls`。"""
    if not isinstance(config_data, dict):
        return
    try:
        config_data["_startup_recommended_max_controls"] = int(recommended)
    except Exception:
        pass


def _apply_framepool_budget_hint(cpu_mem_info: dict) -> None:
    # Weak machine safeguard: if memory is small and user didn't override FramePool env,
    # tighten the default budget to reduce OOM risk under backpressure.
    """处理应用`framepool``budget``hint`。"""
    try:
        mem_gb = float(cpu_mem_info.get("mem_total_gb") or 0.0)
    except Exception:
        mem_gb = 0.0
    if mem_gb <= 0:
        return
    if "BEACON_FRAMEPOOL_BUDGET_MB" in os.environ:
        return

    if mem_gb <= 4.5:
        os.environ["BEACON_FRAMEPOOL_BUDGET_MB"] = "64"
    elif mem_gb <= 8.5:
        os.environ["BEACON_FRAMEPOOL_BUDGET_MB"] = "96"


def check_cpu_support(config_data):
    """检查`cpu``support`。"""
    try:
        info = _get_cpu_mem_info()
        configured = _get_configured_max_controls(config_data)
        recommended = compute_recommended_max_controls(
            cpu_physical_cores=info.get("cpu_physical_cores") or 0,
            cpu_logical_cores=info.get("cpu_logical_cores") or 0,
            mem_total_gb=info.get("mem_total_gb") or 0.0,
            configured_max_controls=configured if configured > 0 else 20,
        )

        # Store tuning hint for post-start apply (best effort).
        _store_startup_recommended_max_controls(config_data, int(recommended))
        _apply_framepool_budget_hint(info)

        logger.info(
            "startup check: cpu/mem: physical=%s logical=%s mem=%.1fGB => recommend maxControls=%s",
            info.get("cpu_physical_cores"),
            info.get("cpu_logical_cores"),
            float(info.get("mem_total_gb") or 0.0),
            recommended,
        )
    except Exception:
        pass
    return True, ""


def check_gpu_support():
    """检查`gpu``support`。"""
    try:
        gpu = _get_gpu_info()
        if gpu.get("nvidia_smi_ok"):
            logger.info("startup check: gpu: nvidia-smi OK (%s)", gpu.get("nvidia_summary") or "nvidia")
        elif gpu.get("gpu_names"):
            logger.info("startup check: gpu: detected=%s", ", ".join(gpu.get("gpu_names") or []))
        else:
            # degrade mode: allow startup, but warn for missing GPU acceleration
            return False, "no GPU detected (will run in CPU mode)"
    except Exception:
        pass
    return True, ""


def _clamp_int(value, *, default=0, min_value=0, max_value=0):
    """限制整数值。"""
    try:
        v = int(value)
    except Exception:
        v = int(default)
    if int(min_value) and v < int(min_value):
        v = int(min_value)
    if int(max_value) and v > int(max_value):
        v = int(max_value)
    return int(v)


def _parse_float(value, default=0.0) -> float:
    """解析浮点数。"""
    try:
        return float(value)
    except Exception:
        return float(default)


def _cap_by_mem_gb(mem_gb: float, current: int) -> int:
    """限制`by``mem``gb`。"""
    if mem_gb > 0 and mem_gb <= 4.5:
        return min(current, 4)
    if mem_gb > 0 and mem_gb <= 8.5:
        return min(current, 8)
    if mem_gb > 0 and mem_gb <= 16.5:
        return min(current, 16)
    return current


def _cap_by_physical_cores(physical: int, current: int) -> int:
    """限制`by``physical``cores`。"""
    if physical > 0 and physical <= 2:
        return min(current, 4)
    if physical > 0 and physical <= 4:
        return min(current, 8)
    return current


def compute_recommended_max_controls(*, cpu_physical_cores, cpu_logical_cores, mem_total_gb, configured_max_controls):
    """
    工业部署默认策略：不强制改用户配置，但在“弱机”时给出更保守的 maxControls 建议，
    以降低大规模布控导致的崩溃风险。
    """
    configured = _clamp_int(configured_max_controls, default=10, min_value=1, max_value=100)
    physical = _clamp_int(cpu_physical_cores or 0, default=0)
    logical = _clamp_int(cpu_logical_cores or 0, default=0)
    mem_gb = _parse_float(mem_total_gb or 0.0, default=0.0)

    # Unknown hardware -> keep configured, but clamp to sane range.
    if physical <= 0 and logical <= 0 and mem_gb <= 0:
        return configured

    recommended = configured

    # Heuristics: weak CPU or low memory => tighten admission upper bound.
    recommended = _cap_by_mem_gb(mem_gb, recommended)
    recommended = _cap_by_physical_cores(physical, recommended)
    return max(1, int(recommended))

def _get_cpu_mem_info():
    """获取`cpu``mem`信息。"""
    cpu_physical = None
    cpu_logical = None
    mem_total_gb = None

    try:
        cpu_physical = psutil.cpu_count(logical=False)
        cpu_logical = psutil.cpu_count(logical=True)
        vm = psutil.virtual_memory()
        mem_total_gb = float(getattr(vm, "total", 0) or 0) / (1024.0 ** 3)
    except Exception:
        pass

    if cpu_logical is None:
        try:
            cpu_logical = os.cpu_count()
        except Exception:
            cpu_logical = None

    if cpu_physical is None:
        cpu_physical = cpu_logical

    if mem_total_gb is None:
        # best-effort fallback (posix)
        try:
            if hasattr(os, "sysconf"):
                page_size = int(os.sysconf("SC_PAGE_SIZE"))
                phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
                total = float(page_size * phys_pages)
                mem_total_gb = total / (1024.0 ** 3)
        except Exception:
            mem_total_gb = None

    return {
        "cpu_physical_cores": cpu_physical,
        "cpu_logical_cores": cpu_logical,
        "mem_total_gb": mem_total_gb,
    }

def _run_cmd(cmd, timeout_seconds=3):
    """执行`cmd`。"""
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=int(timeout_seconds),
            text=True,
            shell=isinstance(cmd, str),
        )
        return int(completed.returncode), str(completed.stdout or ""), str(completed.stderr or "")
    except Exception as e:
        return 127, "", str(e)


def _split_nonempty_lines(text: str) -> list:
    """拆分非空`lines`。"""
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _detect_nvidia_smi():
    """处理检测`nvidia``smi`。"""
    rc, out, _ = _run_cmd(["nvidia-smi", "-L"], timeout_seconds=2)
    lines = _split_nonempty_lines(out)
    if rc == 0 and lines:
        return {
            "gpu_names": lines,
            "nvidia_smi_ok": True,
            "nvidia_summary": lines[0],
        }
    return None


def _detect_windows_gpu_names() -> list:
    """处理检测`windows``gpu``names`。"""
    rc, out, _ = _run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ],
        timeout_seconds=3,
    )
    if rc == 0:
        return _split_nonempty_lines(out)
    return []


def _detect_linux_gpu_names() -> list:
    """处理检测Linux`gpu``names`。"""
    rc, out, _ = _run_cmd(["lspci"], timeout_seconds=3)
    lines = _split_nonempty_lines(out)
    if rc != 0 or not lines:
        return []
    names = []
    for line in lines:
        lower = line.lower()
        if " vga " in lower or "3d controller" in lower:
            names.append(line)
    return names


def _get_gpu_info():
    """获取`gpu`信息。
    
    Best-effort GPU detection for startup diagnostics.
        Returns:
          - gpu_names: list[str]
          - nvidia_smi_ok: bool
          - nvidia_summary: str
    """
    result = {"gpu_names": [], "nvidia_smi_ok": False, "nvidia_summary": ""}

    # NVIDIA: prefer nvidia-smi (most actionable for CUDA/TensorRT deployments)
    nvidia = _detect_nvidia_smi()
    if nvidia:
        result.update(nvidia)
        return result

    # Windows: WMI
    if platform.system().lower() == "windows":
        result["gpu_names"] = _detect_windows_gpu_names()
        return result

    # Linux: lspci (optional)
    result["gpu_names"] = _detect_linux_gpu_names()
    return result

def _http_post_json(url, payload, *, token="", timeout_seconds=2):
    """返回HTTP`post`JSON。"""
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False, "only a local HTTP Analyzer endpoint is allowed"
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("X-Beacon-Token", str(token))
    try:
        # The URL was restricted above to the local Analyzer endpoint.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(req, timeout=float(timeout_seconds)) as resp:
            raw = resp.read()
            try:
                return True, raw.decode("utf-8", errors="replace")
            except Exception:
                return True, str(raw)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        return False, "http %s: %s" % (getattr(e, "code", "error"), body)
    except Exception as e:
        return False, str(e)

def _apply_analyzer_startup_tuning(config_data):
    """处理应用分析器`startup``tuning`。
    
    Degrade strategy (B):
        - Startup always continues (unless fatal checks like port occupied).
        - Apply best-effort tuning after Analyzer is started (e.g., maxControls).
    """
    try:
        cfg = config_data or {}
        recommended = int(cfg.get("_startup_recommended_max_controls") or 0)
        configured = int(cfg.get("maxControls") or 0)
        if recommended <= 0 or configured <= 0:
            return
        if recommended >= configured:
            return

        analyzer_port = int(cfg.get("analyzerPort") or 0)
        if analyzer_port <= 0:
            return

        token = str(cfg.get("openApiToken") or "").strip()
        url = "http://127.0.0.1:%d/api/resource/setmax" % analyzer_port
        payload = {"maxControls": int(recommended)}

        # Analyzer may take a moment to bind; retry briefly.
        for _ in range(1, 11):
            ok, detail = _http_post_json(url, payload, token=token, timeout_seconds=1.5)
            if ok:
                logger.warning("startup tuning applied: maxControls %d -> %d", configured, recommended)
                return
            time.sleep(0.5)

        logger.warning("startup tuning skipped: failed to call Analyzer setmax (%s)", detail)
    except Exception as e:
        try:
            logger.warning("startup tuning error: %s", str(e))
        except Exception:
            pass

def run_environment_check(config_data):
    """执行环境`check`。"""
    errors = []
    warnings = []

    port_items = {
        "adminPort": config_data.get("adminPort"),
        "analyzerPort": config_data.get("analyzerPort"),
        "mediaHttpPort": config_data.get("mediaHttpPort"),
        "mediaRtspPort": config_data.get("mediaRtspPort"),
        "mediaRtmpPort": config_data.get("mediaRtmpPort"),
    }
    for name, port in port_items.items():
        ok, detail = _check_port_free(int(port) if port is not None else 0)
        if not ok:
            errors.append("port %s (%s) is occupied: %s" % (str(port), name, detail))

    ok, detail = check_cpu_support(config_data)
    if not ok:
        warnings.append("cpu support check: %s" % (detail or "unsupported"))

    ok, detail = check_gpu_support()
    if not ok:
        warnings.append("gpu support check: %s" % (detail or "unsupported"))

    if errors:
        for item in errors:
            logger.error("startup check failed: %s", item)
        return False

    for item in warnings:
        logger.warning("startup check warning: %s", item)

    logger.info("startup check passed")
    return True

class App():
    def __init__(self, process_name, process_start_args, ports=None, env=None):
        """处理`init`。"""
        self.__process_name = process_name  # 例 MediaServer
        self.__process_start_args = process_start_args  # 例 ["D:\\bin\\MediaServer.exe","-c","D:\\bin\\config.ini"]
        self.__env = dict(env) if env else None
        self.__ports = []
        if ports:
            try:
                for p in ports:
                    if p is None:
                        continue
                    pv = int(p)
                    if pv > 0:
                        self.__ports.append(pv)
            except Exception:
                self.__ports = []
        self.__proc = None
        self.__pid = None
        self.__last_start_ts = 0
        self.__restart_failures = 0
        self.__min_restart_interval = 60


    def get_info(self):

        """获取信息。"""
        info = {
            "process": self.__process_name,
            "started": None,
            "status": None,
            "pid": None,
            "state": False
        }
        try:
            if self.__proc and self.__proc.poll() is None:
                pid = self.__proc.pid
                self.__pid = pid
                info["pid"] = pid
                _fill_process_runtime_info(info, pid)
                info["state"] = True
                return info
        except Exception:
            pass

        try:
            pid = self.__pid
            if pid and _pid_exists(pid):
                info["pid"] = pid
                _fill_process_runtime_info(info, pid)
                info["state"] = True
                return info
        except Exception:
            pass

        return info

    def __start_process(self):
        """启动进程。"""
        logger.info("start process_name=%s,args=%s" % (self.__process_name, str(self.__process_start_args)))
        state = False
        try:
            self.__last_start_ts = int(time.time())
            creationflags = 0
            if platform.system().lower() == "windows":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            use_shell = isinstance(self.__process_start_args, str)
            self.__proc = subprocess.Popen(
                self.__process_start_args,
                shell=use_shell,
                cwd=ROOT_DIR,
                creationflags=creationflags,
                env=self.__env,
            )
            self.__pid = self.__proc.pid
            state = True if self.__pid else False
        except Exception as e:
            logger.error("start %s error: %s" % (self.__process_name, str(e)))

        return state

    def _resolve_started_pid(self) -> int:
        """解析并返回`started`PID。"""
        pid = None
        try:
            proc = self.__proc
            if proc:
                pid = proc.pid
        except Exception:
            pid = None
        if not pid:
            pid = self.__pid
        try:
            return int(pid or 0)
        except Exception:
            return 0

    def _clear_process_state(self) -> None:
        """清理进程状态。"""
        try:
            self.__proc = None
        except Exception:
            pass
        self.__pid = None

    @staticmethod
    def _is_popen_running(proc) -> bool:
        """判断`popen``running`。"""
        try:
            return bool(proc and proc.poll() is None)
        except Exception:
            return False

    @staticmethod
    def _terminate_popen_best_effort(proc) -> None:
        """尽力处理`terminate``popen`。"""
        try:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
            if proc and proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    @staticmethod
    def _get_psutil_parent_or_none(pid: int):
        """获取`psutil``parent``or``none`。"""
        try:
            return psutil.Process(int(pid))
        except Exception:
            return None

    @staticmethod
    def _collect_psutil_tree(parent):
        """处理`collect``psutil``tree`。"""
        procs = []
        try:
            procs = parent.children(recursive=True)
        except Exception:
            procs = []
        procs.append(parent)
        return procs

    @staticmethod
    def _terminate_psutil_procs_best_effort(procs) -> None:
        """尽力处理`terminate``psutil``procs`。"""
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

    @staticmethod
    def _wait_kill_wait_psutil_procs(procs):
        """等待`kill`等待`psutil``procs`。"""
        try:
            _, alive = psutil.wait_procs(procs, timeout=3)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
            _, alive = psutil.wait_procs(alive, timeout=3)
            return alive
        except Exception:
            return None

    def _kill_process_with_psutil(self, pid: int) -> bool:
        """处理`kill`进程`with``psutil`。"""
        parent = self._get_psutil_parent_or_none(pid)
        if parent is None:
            # Process is already gone.
            self._clear_process_state()
            return True

        procs = self._collect_psutil_tree(parent)
        self._terminate_psutil_procs_best_effort(procs)
        alive = self._wait_kill_wait_psutil_procs(procs)
        if alive is None:
            # If psutil itself fails, do not clobber state; caller can decide what to do next.
            return False
        if alive:
            return False

        self._clear_process_state()
        return True

    def __kill_process(self) -> bool:
        # 工业稳定性：只终止自己启动的进程（pid/进程树），不做全局按名字 kill，避免误杀。
        #
        # Returns:
        # - True: 进程已退出（或原本就不存在）
        # - False: 尝试终止后仍存活（或无法确认）
        """处理`kill`进程。"""
        pid = self._resolve_started_pid()
        if not pid:
            return True
        return self._kill_process_with_psutil(pid)

    def start(self, force=False):
        """
        优化调度：避免频繁重启，支持退避。
        force=True 时跳过退避策略。
        """
        info = self.get_info()
        if info.get("state"):
            logger.info("process %s already running (pid=%s)", self.__process_name, info.get("pid"))
            return True

        now = int(time.time())
        backoff = min(300, self.__min_restart_interval * (self.__restart_failures + 1))
        if not force and (now - self.__last_start_ts) < backoff:
            wait_left = backoff - (now - self.__last_start_ts)
            logger.warning("skip restart %s: backoff %ss remaining", self.__process_name, wait_left)
            return False

        # 端口仍被占用时不重启，避免重启风暴（例如端口被外部进程占用/资源未释放）
        for port in self.__ports:
            ok, detail = _check_port_free(int(port))
            if not ok:
                logger.warning("skip start %s: port %d is occupied: %s", self.__process_name, int(port), detail)
                return False

        # 进程不存在或已退出，尝试重启前先清理残留
        self.__kill_process()
        started = self.__start_process()
        if started:
            self.__restart_failures = 0
        else:
            self.__restart_failures += 1
        return started
class VideoAnalyzer():
    def __init__(self, config_data):
        """处理`init`。"""
        self.__config_data = config_data or {}
        self.__media_secret = _ensure_media_secret(self.__config_data)
        self._admin_port = int(self.__config_data.get("adminPort") or 0)
    def run(self):
        """执行相关数据。"""
        self.__apps = []

        media_args = _build_media_server_args(self.__config_data)
        if not media_args:
            raise FileNotFoundError("MediaServer binary not found")
        media_ports = [
            self.__config_data.get("mediaHttpPort"),
            self.__config_data.get("mediaRtspPort"),
            self.__config_data.get("mediaRtmpPort"),
        ]
        runtime_env = _build_runtime_env()
        runtime_env["BEACON_MEDIA_SECRET"] = self.__media_secret
        app = App("MediaServer", media_args, ports=media_ports, env=runtime_env)
        app.start()
        self.__apps.append(app)

        admin_args = _build_admin_args(self._admin_port)
        app = App("manage", admin_args, ports=[self._admin_port], env=runtime_env)
        app.start()
        self.__apps.append(app)

        analyzer_args = _build_analyzer_args()
        if not analyzer_args:
            logger.warning("Analyzer binary not found, skipping (video analysis features will be unavailable)")
        else:
            analyzer_port = int(self.__config_data.get("analyzerPort") or 0)
            app = App("Analyzer", analyzer_args, ports=[analyzer_port], env=_build_analyzer_env(runtime_env))
            app.start()
            self.__apps.append(app)

        usb_bridge_args = _build_usb_camera_bridge_args(self.__config_data)
        if usb_bridge_args:
            app = App("UsbCameraBridge", usb_bridge_args)
            if _wait_for_usb_camera_publish_target(self.__config_data, usb_bridge_args[-1]):
                app.start()
            self.__apps.append(app)
        try:
            t = threading.Thread(target=_apply_analyzer_startup_tuning, args=(self.__config_data,), daemon=True)
            t.start()
        except Exception:
            pass

        t = threading.Thread(target=self.__record_log, daemon=False)
        t.start()
        try:
            t.join()
        except KeyboardInterrupt:
            logger.info("Received Ctrl+C, shutting down...")
            try:
                self.shutdown()
            except Exception:
                pass

    def shutdown(self):
        """优雅关闭所有子进程。"""
        if not hasattr(self, '_VideoAnalyzer__apps'):
            return
        for app in self.__apps:
            try:
                app._App__kill_process()
                logger.info("Stopped process: %s", app._App__process_name)
            except Exception as e:
                logger.warning("Failed to stop process: %s, error: %s", app._App__process_name, e)
    def __record_log(self):

        """处理`record``log`。"""
        record_log_count = 0
        while True:
            time.sleep(30)

            record_log_count += 1
            for app in self.__apps:
                info = app.get_info()
                info_str = str(info)
                logger.info("recordLog_count=%d,info=%s"%(record_log_count,info_str))
                try:
                    if not info.get("state"):
                        last_start = getattr(app, "_App__last_start_ts", 0) or 0
                        if int(time.time()) - int(last_start) >= 60:
                            logger.warning("process %s not running, restarting...", info.get("process"))
                            app.start()
                except Exception:
                    pass



def get_logger(log_dir, is_show_console=False):
    """获取`logger`。"""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_name = os.path.join(log_dir, "%s.log" % (datetime.now().strftime(LOGFILE_TIMEFMT)))
    level = logging.INFO
    logger = logging.getLogger()
    logger.setLevel(level)
    formatter = logging.Formatter('%(asctime)s %(name)s %(lineno)s %(levelname)s %(message)s')

    # 时间滚动切分
    # when:备份的时间单位，backupCount:备份保存的时间长度
    timed_rotating_file_handler = TimedRotatingFileHandler(file_name,
                                    when=LOGFILE_WHEN,
                                    backupCount=LOGFILE_BACKUPCOUNT,
                                    encoding='utf-8')

    timed_rotating_file_handler.setLevel(level)
    timed_rotating_file_handler.setFormatter(formatter)
    logger.addHandler(timed_rotating_file_handler)

    # 控制台打印
    if is_show_console:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
if __name__ == '__main__':
    """
    
    // 根据 manage.spec 文件，打包程序
    pyinstaller manage.spec

    # 打包成可执行文件

    pyinstaller -F  VideoAnalyzer.py

    """

    logger = get_logger(log_dir=LOG_DIR, is_show_console=True)
    logger.info("Beacon 新一代 AI 视频分析系统 %s", get_project_version(ROOT_DIR))

    try:
        if not ensure_single_instance(LOCK_FILE):
            sys.exit(1)

        filename = os.path.join(ROOT_DIR, "config.json")
        if not os.path.exists(filename):
            raise FileNotFoundError("启动配置文件config.json不存在!")
        config_data = _read_config_json(filename)
        if not run_environment_check(config_data):
            sys.exit(1)

        videoAnalyzer = VideoAnalyzer(config_data)

        def _signal_handler(sig, frame):
            logger.info("Received signal %s, shutting down...", sig)
            try:
                videoAnalyzer.shutdown()
            except Exception:
                pass
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, _signal_handler)

        atexit.register(videoAnalyzer.shutdown)

        videoAnalyzer.run()

    except Exception as e:
        logger.error(str(e))
