import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from app.utils import AutoStart


class LinuxAutoStartTest(SimpleTestCase):
    def _patch_layout(self, home: str, root: str, argv):
        return (
            mock.patch.object(AutoStart, "_home_dir", return_value=home),
            mock.patch.object(AutoStart, "_root_dir", return_value=root),
            mock.patch.object(AutoStart, "resolve_autostart_command_argv", return_value=list(argv)),
        )

    def test_systemd_enable_checks_results_and_quotes_install_path(self):
        with tempfile.TemporaryDirectory() as home:
            root = "/srv/Beacon Product"
            argv = ["/usr/bin/python3", f"{root}/Admin/VideoAnalyzer.py"]
            completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            patches = self._patch_layout(home, root, argv)
            with patches[0], patches[1], patches[2], mock.patch.object(
                AutoStart.shutil,
                "which",
                return_value="/usr/bin/systemctl",
            ), mock.patch.object(AutoStart.subprocess, "run", return_value=completed) as run:
                ok, detail = AutoStart._apply_linux_autostart(enabled=True)

            self.assertTrue(ok)
            self.assertEqual(detail, "enabled via systemd --user")
            unit_text = Path(
                home,
                ".config",
                "systemd",
                "user",
                "beacon-videoanalyzer.service",
            ).read_text(encoding="utf-8")
            self.assertIn('WorkingDirectory="/srv/Beacon Product"', unit_text)
            self.assertIn('Environment="BEACON_ROOT_DIR=/srv/Beacon Product"', unit_text)
            self.assertIn(
                'ExecStart="/usr/bin/python3" "/srv/Beacon Product/Admin/VideoAnalyzer.py"',
                unit_text,
            )
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertEqual(call.kwargs.get("timeout"), 15)
                self.assertTrue(call.kwargs.get("capture_output"))

    def test_systemd_nonzero_exit_is_reported_and_not_claimed_as_xdg_success(self):
        with tempfile.TemporaryDirectory() as home:
            root = "/srv/beacon"
            argv = ["/usr/bin/python3", f"{root}/Admin/VideoAnalyzer.py"]
            results = [
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                subprocess.CompletedProcess([], 1, stdout="", stderr="permission denied"),
            ]
            patches = self._patch_layout(home, root, argv)
            with patches[0], patches[1], patches[2], mock.patch.object(
                AutoStart.shutil,
                "which",
                return_value="/usr/bin/systemctl",
            ), mock.patch.object(AutoStart.subprocess, "run", side_effect=results):
                ok, detail = AutoStart._apply_linux_autostart(enabled=True)

            self.assertFalse(ok)
            self.assertIn("systemd enable failed (exit 1)", detail)
            self.assertIn("permission denied", detail)
            self.assertFalse(
                Path(home, ".config", "autostart", "beacon-videoanalyzer.desktop").exists()
            )

    def test_host_without_systemctl_uses_quoted_xdg_desktop_entry(self):
        with tempfile.TemporaryDirectory() as home:
            root = "/srv/Beacon Product"
            argv = ["/usr/bin/python3", f"{root}/Admin/VideoAnalyzer.py"]
            patches = self._patch_layout(home, root, argv)
            with patches[0], patches[1], patches[2], mock.patch.object(
                AutoStart.shutil,
                "which",
                return_value=None,
            ), mock.patch.object(AutoStart.subprocess, "run") as run:
                ok, detail = AutoStart._apply_linux_autostart(enabled=True)

            self.assertTrue(ok)
            self.assertEqual(detail, "enabled via XDG autostart")
            desktop_text = Path(
                home,
                ".config",
                "autostart",
                "beacon-videoanalyzer.desktop",
            ).read_text(encoding="utf-8")
            self.assertIn(
                'Exec="/usr/bin/python3" "/srv/Beacon Product/Admin/VideoAnalyzer.py"',
                desktop_text,
            )
            run.assert_not_called()

    def test_failed_systemd_disable_preserves_unit_for_retry(self):
        with tempfile.TemporaryDirectory() as home:
            unit_path = Path(home, ".config", "systemd", "user", "beacon-videoanalyzer.service")
            unit_path.parent.mkdir(parents=True)
            unit_path.write_text("[Unit]\n", encoding="utf-8")
            patches = self._patch_layout(home, "/srv/beacon", ["/srv/beacon/VideoAnalyzer"])
            failed = subprocess.CompletedProcess([], 1, stdout="", stderr="access denied")
            with patches[0], patches[1], patches[2], mock.patch.object(
                AutoStart.shutil,
                "which",
                return_value="/usr/bin/systemctl",
            ), mock.patch.object(AutoStart.subprocess, "run", return_value=failed):
                ok, detail = AutoStart._apply_linux_autostart(enabled=False)

            self.assertFalse(ok)
            self.assertIn("systemd disable failed (exit 1)", detail)
            self.assertTrue(unit_path.exists())

    def test_successful_systemd_disable_removes_managed_files(self):
        with tempfile.TemporaryDirectory() as home:
            unit_path = Path(home, ".config", "systemd", "user", "beacon-videoanalyzer.service")
            desktop_path = Path(home, ".config", "autostart", "beacon-videoanalyzer.desktop")
            unit_path.parent.mkdir(parents=True)
            desktop_path.parent.mkdir(parents=True)
            unit_path.write_text("[Unit]\n", encoding="utf-8")
            desktop_path.write_text("[Desktop Entry]\n", encoding="utf-8")
            patches = self._patch_layout(home, "/srv/beacon", ["/srv/beacon/VideoAnalyzer"])
            completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with patches[0], patches[1], patches[2], mock.patch.object(
                AutoStart.shutil,
                "which",
                return_value="/usr/bin/systemctl",
            ), mock.patch.object(AutoStart.subprocess, "run", return_value=completed) as run:
                ok, detail = AutoStart._apply_linux_autostart(enabled=False)

            self.assertTrue(ok)
            self.assertEqual(detail, "disabled")
            self.assertFalse(unit_path.exists())
            self.assertFalse(desktop_path.exists())
            self.assertEqual(run.call_count, 2)

    def test_windows_autostart_exception_is_redacted(self):
        with (
            mock.patch.object(AutoStart, "_system_name", return_value="Windows"),
            mock.patch(
                "app.utils.WindowsAutoStart.apply_windows_autostart",
                side_effect=PermissionError("C:\\secret\\startup-path"),
            ),
        ):
            ok, detail = AutoStart.apply_autostart(enabled=True)

        self.assertFalse(ok)
        self.assertEqual(detail, "autostart update failed")
        self.assertNotIn("secret", detail)
