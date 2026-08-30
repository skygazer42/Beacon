import json
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock, skipIf

from django.test import SimpleTestCase

import runtime_permissions
import settings_store
from app.utils import Config as ConfigModule
from app.views import SystemConfigView


@skipIf(os.name == "nt", "POSIX file modes are not available on Windows")
class RuntimePermissionTests(SimpleTestCase):
    def _mode(self, path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    def test_existing_private_file_permissions_are_tightened(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "config.json"
            target.write_text('{"openApiToken":"secret"}\n', encoding="utf-8")
            target.chmod(0o664)

            changed = runtime_permissions.ensure_private_regular_file(target)

            self.assertTrue(changed)
            self.assertEqual(self._mode(target), 0o600)
            self.assertFalse(runtime_permissions.ensure_private_regular_file(target))

    def test_non_regular_runtime_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaisesRegex(
                runtime_permissions.RuntimeFilePermissionError,
                "not a regular file",
            ):
                runtime_permissions.ensure_private_regular_file(temporary_dir)

    def test_windows_mode_is_left_to_platform_acls(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "config.json"
            target.write_text("{}\n", encoding="utf-8")
            target.chmod(0o644)

            changed = runtime_permissions.ensure_private_regular_file(
                target,
                platform_name="nt",
            )

            self.assertFalse(changed)
            self.assertEqual(self._mode(target), 0o644)

    def test_placeholder_values_are_not_treated_as_embedded_secrets(self):
        self.assertFalse(
            runtime_permissions.config_contains_embedded_secrets(
                {"mediaSecret": "CHANGE_ME", "openApiToken": ""}
            )
        )
        self.assertTrue(
            runtime_permissions.config_contains_embedded_secrets(
                {"openApiToken": "real-token"}
            )
        )
        self.assertTrue(
            runtime_permissions.config_contains_embedded_secrets(
                {"openApiToken": "CHANGE_ME_but_real"}
            )
        )

    def test_cloud_placeholder_config_can_remain_read_only(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "config.json"
            target.write_text('{"mediaSecret":"CHANGE_ME"}\n', encoding="utf-8")
            target.chmod(0o644)

            changed = runtime_permissions.ensure_runtime_config_private(
                target,
                {"mediaSecret": "CHANGE_ME"},
                environ={"BEACON_DEPLOYMENT_MODE": "cloud"},
            )

            self.assertFalse(changed)
            self.assertEqual(self._mode(target), 0o644)

    def test_edge_placeholder_config_is_still_private(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "config.json"
            target.write_text('{"mediaSecret":"CHANGE_ME"}\n', encoding="utf-8")
            target.chmod(0o644)

            changed = runtime_permissions.ensure_runtime_config_private(
                target,
                {"mediaSecret": "CHANGE_ME"},
                environ={"BEACON_DEPLOYMENT_MODE": "edge"},
            )

            self.assertTrue(changed)
            self.assertEqual(self._mode(target), 0o600)

    def test_cloud_config_with_embedded_secret_is_private(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "config.json"
            target.write_text('{"openApiToken":"real-token"}\n', encoding="utf-8")
            target.chmod(0o644)

            changed = runtime_permissions.ensure_runtime_config_private(
                target,
                {"openApiToken": "real-token"},
                environ={"BEACON_DEPLOYMENT_MODE": "cloud"},
            )

            self.assertTrue(changed)
            self.assertEqual(self._mode(target), 0o600)

    def test_config_loader_secures_embedded_token(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "config.json"
            target.write_text(
                json.dumps(
                    {
                        "host": "127.0.0.1",
                        "adminPort": 9991,
                        "analyzerPort": 9993,
                        "mediaHttpPort": 9992,
                        "mediaRtspPort": 9994,
                        "openApiToken": "real-token",
                    }
                ),
                encoding="utf-8",
            )
            target.chmod(0o644)

            with mock.patch.dict(
                os.environ,
                {
                    "BEACON_CONFIG_PATH": os.fspath(target),
                    "BEACON_ROOT_DIR": temporary_dir,
                    "BEACON_DEPLOYMENT_MODE": "edge",
                },
                clear=False,
            ):
                ConfigModule.Config()

            self.assertEqual(self._mode(target), 0o600)

    def test_atomic_private_writer_replaces_permissive_file(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "settings.json"
            target.write_text("old\n", encoding="utf-8")
            target.chmod(0o666)

            runtime_permissions.write_private_text_atomic(target, "new\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertEqual(self._mode(target), 0o600)
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_atomic_private_writer_cleans_temporary_file_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "settings.json"
            with mock.patch(
                "runtime_permissions.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    runtime_permissions.write_private_text_atomic(target, "new\n")

            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])

    def test_sqlite_database_and_sidecars_are_private(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            database = Path(temporary_dir) / "Admin.sqlite3"
            candidates = [
                Path(os.fspath(database) + suffix)
                for suffix in ("", "-wal", "-shm", "-journal")
            ]
            for candidate in candidates:
                candidate.write_bytes(b"sqlite-state")
                candidate.chmod(0o644)

            changed = runtime_permissions.ensure_sqlite_files_private(database)

            self.assertEqual(set(changed), {os.fspath(path) for path in candidates})
            self.assertTrue(all(self._mode(path) == 0o600 for path in candidates))

    def test_config_and_settings_writers_use_private_atomic_files(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_target = Path(temporary_dir) / "config.json"
            settings_target = Path(temporary_dir) / "settings.json"

            SystemConfigView._write_json_file_atomic(
                os.fspath(config_target),
                {"openApiToken": "secret"},
            )
            settings_store._write_json_file_atomic(
                os.fspath(settings_target),
                {"siteName": "Beacon"},
            )

            self.assertEqual(self._mode(config_target), 0o600)
            self.assertEqual(self._mode(settings_target), 0o600)
