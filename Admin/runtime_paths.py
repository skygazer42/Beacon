import glob
import os
import platform
import sys
import tempfile
from typing import Optional


def _env_str(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return ""
    return str(raw).strip()


def _is_frozen() -> bool:
    # PyInstaller sets `sys.frozen = True`. Some builds may only set `_MEIPASS`.
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _repo_root_from_this_file() -> str:
    # Admin/runtime_paths.py -> repo_root/Admin/runtime_paths.py
    admin_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(admin_dir)


def resolve_root_dir() -> str:
    """
    Resolve Beacon product root directory.

    Priority:
      1) BEACON_ROOT_DIR (explicit override)
      2) Frozen build: directory of sys.executable (stable for PyInstaller -F)
      3) Source tree: repo root inferred from this file
    """
    override = _env_str("BEACON_ROOT_DIR")
    if override:
        return os.path.normpath(override)

    if _is_frozen():
        exe = os.path.abspath(sys.executable or "")
        if exe:
            exe_dir = os.path.dirname(exe)
            parent_dir = os.path.dirname(exe_dir)
            if os.path.basename(exe_dir).lower() == "admin" and os.path.exists(os.path.join(parent_dir, "config.json")):
                return os.path.normpath(parent_dir)
            return os.path.normpath(exe_dir)

    return _repo_root_from_this_file()


def resolve_admin_dir(root_dir: Optional[str] = None) -> str:
    root_dir = root_dir or resolve_root_dir()

    if _is_frozen():
        exe = os.path.abspath(sys.executable or "")
        exe_dir = os.path.dirname(exe) if exe else ""
        if os.path.basename(exe_dir).lower() == "admin":
            return os.path.normpath(exe_dir)

        candidate = os.path.join(root_dir, "Admin")
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)

    return os.path.dirname(os.path.abspath(__file__))


def resolve_config_path(root_dir: Optional[str] = None) -> str:
    root_dir = root_dir or resolve_root_dir()
    return os.path.join(root_dir, "config.json")


def resolve_settings_path(root_dir: Optional[str] = None) -> str:
    root_dir = root_dir or resolve_root_dir()
    return os.path.join(root_dir, "settings.json")


def _first_existing_dir(paths) -> str:
    for path in paths:
        if not path:
            continue
        if os.path.isdir(path):
            return os.path.normpath(path)
    return ""


def resolve_localdeps_dir(root_dir: Optional[str] = None) -> str:
    root_dir = root_dir or resolve_root_dir()

    override = _env_str("BEACON_LOCALDEPS_DIR")
    candidates = []
    if override:
        candidates.append(override)
    candidates.extend(
        [
            os.path.join(root_dir, "third_party", "localdeps"),
            os.path.join(root_dir, "deps", "localdeps"),
        ]
    )

    for candidate in candidates:
        if not candidate:
            continue
        sysroot_dir = os.path.join(candidate, "sysroot")
        if os.path.isdir(candidate) and os.path.isdir(sysroot_dir):
            return os.path.normpath(candidate)
    return ""


def resolve_analyzer_localdeps_layout(root_dir: Optional[str] = None) -> dict:
    root_dir = root_dir or resolve_root_dir()
    localdeps_dir = resolve_localdeps_dir(root_dir)
    if not localdeps_dir:
        return {}

    ort_override = _env_str("BEACON_ONNXRUNTIME_DIR")
    openvino_override = _env_str("BEACON_OPENVINO_RUNTIME_DIR")
    sysroot_override = _env_str("BEACON_SYSROOT_DIR")

    sysroot_dir = _first_existing_dir(
        [
            sysroot_override,
            os.path.join(localdeps_dir, "sysroot"),
        ]
    )
    onnxruntime_dir = _first_existing_dir(
        [
            ort_override,
            *sorted(glob.glob(os.path.join(localdeps_dir, "src", "onnxruntime-*-gpu-*"))),
            *sorted(glob.glob(os.path.join(localdeps_dir, "src", "onnxruntime-*"))),
        ]
    )
    openvino_runtime_dir = _first_existing_dir(
        [
            openvino_override,
            *sorted(glob.glob(os.path.join(localdeps_dir, "src", "l_openvino_toolkit_*", "runtime"))),
        ]
    )

    if not sysroot_dir:
        return {}

    return {
        "localdeps_dir": localdeps_dir,
        "sysroot_dir": sysroot_dir,
        "onnxruntime_dir": onnxruntime_dir,
        "openvino_runtime_dir": openvino_runtime_dir,
    }


def _app_data_dir(app_name: str = "Beacon") -> str:
    system = platform.system().lower()
    home = os.path.expanduser("~")

    if system == "windows":
        base = _env_str("LOCALAPPDATA") or _env_str("APPDATA") or home
        return os.path.join(base, app_name)

    if system == "darwin":
        return os.path.join(home, "Library", "Application Support", app_name)

    # linux/others
    xdg = _env_str("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, app_name.lower())
    return os.path.join(home, ".local", "share", app_name.lower())


def _can_write_dir(dir_path: str) -> bool:
    if not dir_path:
        return False
    try:
        os.makedirs(dir_path, exist_ok=True)
    except Exception:
        return False

    # Best-effort write check.
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="._beacon_write_test_", dir=dir_path)
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return True
    except Exception:
        return False


def resolve_log_dir(root_dir: Optional[str] = None) -> str:
    root_dir = root_dir or resolve_root_dir()

    candidate = os.path.join(root_dir, "log")
    if _can_write_dir(candidate):
        return candidate

    fallback = os.path.join(_app_data_dir("Beacon"), "log")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def resolve_lock_path(log_dir: Optional[str] = None) -> str:
    log_dir = log_dir or resolve_log_dir()
    return os.path.join(log_dir, "startup.lock")
