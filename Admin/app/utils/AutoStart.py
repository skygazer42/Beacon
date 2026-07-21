import logging
import os
import platform
import shutil
import subprocess
from typing import List, Tuple



logger = logging.getLogger(__name__)
_LINUX_SYSTEMD_UNIT_NAME = "beacon-videoanalyzer.service"
_MACOS_LAUNCH_AGENT_LABEL = "com.beacon.videoanalyzer"
_MACOS_LAUNCH_AGENT_PLIST = _MACOS_LAUNCH_AGENT_LABEL + ".plist"


def _system_name() -> str:
    """返回系统名称。"""
    try:
        return str(platform.system() or "").strip()
    except Exception:
        return ""


def _home_dir() -> str:
    # Tests patch expanduser. Keep it centralized.
    """返回主目录目录。"""
    return os.path.expanduser("~")


def _root_dir() -> str:
    """返回根目录目录。"""
    import runtime_paths  # type: ignore

    try:
        return runtime_paths.resolve_root_dir()
    except Exception:
        # Fallback: env override only.
        return os.path.normpath(str(os.environ.get("BEACON_ROOT_DIR") or "").strip() or os.getcwd())


def resolve_autostart_command_argv() -> List[str]:
    """解析并返回`autostart``command``argv`。
    
    Resolve a stable launcher command for OS-level auto-start.
    
        Preference order:
          1) <root>/VideoAnalyzer(.exe) (product launcher when distributed)
          2) python <root>/Admin/VideoAnalyzer.py (source tree / fallback)
    """
    root_dir = _root_dir()
    system = _system_name().lower()

    if system == "windows":
        candidate = os.path.join(root_dir, "VideoAnalyzer.exe")
        if os.path.isfile(candidate):
            return [os.path.abspath(candidate)]
    else:
        candidate = os.path.join(root_dir, "VideoAnalyzer")
        if os.path.isfile(candidate):
            return [os.path.abspath(candidate)]

    # Fallback to python script launcher (works for source trees).
    admin_launcher = os.path.join(root_dir, "Admin", "VideoAnalyzer.py")
    python_exec = os.path.abspath(str(getattr(__import__("sys"), "executable", "") or "python3"))
    return [python_exec, os.path.abspath(admin_launcher)]


def _write_text_atomic(path: str, content: str) -> None:
    """写入文本`atomic`。"""
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")
    os.replace(tmp, path)


def _remove_file_quiet(path: str) -> None:
    """处理`remove`文件`quiet`。"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        logger.debug("suppressed exception in app/utils/AutoStart.py:82", exc_info=True)


def _linux_systemd_unit_path() -> str:
    """返回Linux`systemd``unit`路径。"""
    home = _home_dir()
    return os.path.join(home, ".config", "systemd", "user", _LINUX_SYSTEMD_UNIT_NAME)


def _linux_xdg_desktop_path() -> str:
    """返回LinuxXDG桌面路径。"""
    home = _home_dir()
    return os.path.join(home, ".config", "autostart", "beacon-videoanalyzer.desktop")


def _macos_launchagent_plist_path() -> str:
    """返回macOSLaunchAgentplist路径。"""
    home = _home_dir()
    return os.path.join(home, "Library", "LaunchAgents", _MACOS_LAUNCH_AGENT_PLIST)


def _apply_linux_autostart(*, enabled: bool) -> Tuple[bool, str]:
    """处理应用Linux`autostart`。"""
    argv = resolve_autostart_command_argv()
    root_dir = _root_dir()
    unit_path = _linux_systemd_unit_path()

    # systemd user unit (preferred on modern distros)
    systemctl = shutil.which("systemctl")
    if enabled:
        unit_text = "\n".join(
            [
                "[Unit]",
                "Description=Beacon VideoAnalyzer",
                "After=network.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={root_dir}",
                f"Environment=BEACON_ROOT_DIR={root_dir}",
                f"ExecStart={argv[0] if len(argv) == 1 else ' '.join(argv)}",
                "Restart=on-failure",
                "RestartSec=5",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            ]
        )
        _write_text_atomic(unit_path, unit_text)

        if systemctl:
            try:
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                subprocess.run(
                    ["systemctl", "--user", "enable", "--now", _LINUX_SYSTEMD_UNIT_NAME],
                    check=False,
                )
                return True, "enabled via systemd --user"
            except Exception:
                # Fall back to XDG autostart when systemd isn't usable in the current environment.
                logger.debug("suppressed exception in app/utils/AutoStart.py:143", exc_info=True)

        # Fallback: XDG Autostart (.desktop), effective for GUI logins.
        desktop_path = _linux_xdg_desktop_path()
        # Desktop entry Exec is a string; keep it minimal and stable.
        exec_cmd = argv[0] if len(argv) == 1 else " ".join(argv)
        desktop_text = "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Beacon VideoAnalyzer",
                f"Exec={exec_cmd}",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        )
        _write_text_atomic(desktop_path, desktop_text)
        return True, "enabled via XDG autostart"

    # disable
    if systemctl:
        try:
            subprocess.run(["systemctl", "--user", "disable", "--now", _LINUX_SYSTEMD_UNIT_NAME], check=False)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        except Exception:
            logger.debug("suppressed exception in app/utils/AutoStart.py:168", exc_info=True)

    _remove_file_quiet(unit_path)
    _remove_file_quiet(_linux_xdg_desktop_path())
    return True, "disabled"


def _apply_macos_autostart(*, enabled: bool) -> Tuple[bool, str]:
    """处理应用macOS`autostart`。"""
    argv = resolve_autostart_command_argv()
    root_dir = _root_dir()
    plist_path = _macos_launchagent_plist_path()

    if enabled:
        # launchd plist with ProgramArguments array so we don't need quoting rules.
        # Best-effort: writing the plist is enough for login-time autostart. Loading
        # it immediately via launchctl is optional and environment-dependent.
        program_args_xml = "\n".join([f"      <string>{_xml_escape(a)}</string>" for a in argv])
        plist = "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
                '<plist version="1.0">',
                "  <dict>",
                "    <key>Label</key>",
                f"    <string>{_MACOS_LAUNCH_AGENT_LABEL}</string>",
                "    <key>ProgramArguments</key>",
                "    <array>",
                program_args_xml,
                "    </array>",
                "    <key>RunAtLoad</key>",
                "    <true/>",
                "    <key>WorkingDirectory</key>",
                f"    <string>{_xml_escape(root_dir)}</string>",
                "    <key>EnvironmentVariables</key>",
                "    <dict>",
                "      <key>BEACON_ROOT_DIR</key>",
                f"      <string>{_xml_escape(root_dir)}</string>",
                "    </dict>",
                "  </dict>",
                "</plist>",
                "",
            ]
        )
        _write_text_atomic(plist_path, plist)

        # Best-effort: try load/unload, but do not fail the toggle due to runtime limitations.
        try:
            if shutil.which("launchctl"):
                subprocess.run(["launchctl", "unload", plist_path], check=False)
                subprocess.run(["launchctl", "load", plist_path], check=False)
        except Exception:
            logger.debug("suppressed exception in app/utils/AutoStart.py:220", exc_info=True)
        return True, "enabled (LaunchAgent plist written)"

    # disable
    try:
        if shutil.which("launchctl"):
            subprocess.run(["launchctl", "unload", plist_path], check=False)
    except Exception:
        logger.debug("suppressed exception in app/utils/AutoStart.py:228", exc_info=True)
    _remove_file_quiet(plist_path)
    return True, "disabled"


def _xml_escape(value: str) -> str:
    """处理XML转义。"""
    s = str(value or "")
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def apply_autostart(*, enabled: bool) -> Tuple[bool, str]:
    """处理应用`autostart`。
    
    Enable/disable OS-level autostart for the Beacon launcher.
    """
    system = _system_name().lower()
    if system == "windows":
        from app.utils.WindowsAutoStart import apply_windows_autostart

        try:
            return apply_windows_autostart(enabled=enabled)
        except Exception as e:
            return False, str(e)

    if system == "darwin":
        return _apply_macos_autostart(enabled=enabled)

    # linux/others
    return _apply_linux_autostart(enabled=enabled)
