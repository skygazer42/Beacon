import logging
import os
import platform
import sys
from typing import Tuple



logger = logging.getLogger(__name__)
_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _is_windows() -> bool:
    """判断`windows`。"""
    try:
        return platform.system().lower() == "windows"
    except Exception:
        return False


def _quote_cmd(path: str) -> str:
    """处理`quote``cmd`。
    
    Quote an executable path for Windows Run registry entry.
        Keep it minimal: wrap with double quotes if it contains spaces or quotes.
    """
    p = str(path or "").strip()
    if not p:
        return ""
    # Escape any embedded quotes defensively (rare).
    p = p.replace('"', '\\"')
    if " " in p or "\t" in p:
        return f"\"{p}\""
    return p


def resolve_autostart_command() -> str:
    """解析并返回`autostart``command`。
    
    Resolve the command to be placed into Windows HKCU Run.
    
        Preference order:
        1) <root>/VideoAnalyzer.exe (product launcher, when present)
        2) sys.executable (frozen or python)
    """
    import runtime_paths

    try:
        root_dir = runtime_paths.resolve_root_dir()
    except Exception:
        root_dir = ""

    if root_dir:
        candidate = os.path.join(root_dir, "VideoAnalyzer.exe")
        if os.path.isfile(candidate):
            return _quote_cmd(os.path.abspath(candidate))

    exe = os.path.abspath(str(sys.executable or "").strip())
    return _quote_cmd(exe)


def apply_windows_autostart(*, enabled: bool, app_name: str = "Beacon") -> Tuple[bool, str]:
    """处理应用`windows``autostart`。
    
    Enable/disable Windows auto-start (current user) via HKCU Run.
    
        Returns: (ok, message)
    """
    if not _is_windows():
        return True, "skip: not windows"

    name = str(app_name or "").strip() or "Beacon"
    try:
        import winreg  # type: ignore
    except ImportError as e:
        return False, f"winreg not available: {e}"

    try:
        if enabled:
            cmd = resolve_autostart_command()
            if not cmd:
                return False, "empty autostart command"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH)
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)
            try:
                winreg.CloseKey(key)
            except Exception:
                logger.debug("suppressed exception in app/utils/WindowsAutoStart.py:85", exc_info=True)
            return True, "enabled"

        # disable
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH)
        try:
            winreg.DeleteValue(key, name)
        except FileNotFoundError:
            # Already removed: treat as success.
            logger.debug("suppressed exception in app/utils/WindowsAutoStart.py:94", exc_info=True)
        except OSError:
            # Some Python/Windows versions raise OSError for missing values.
            logger.debug("suppressed exception in app/utils/WindowsAutoStart.py:97", exc_info=True)
        try:
            winreg.CloseKey(key)
        except Exception:
            logger.debug("suppressed exception in app/utils/WindowsAutoStart.py:101", exc_info=True)
        return True, "disabled"
    except Exception as e:
        return False, str(e)
