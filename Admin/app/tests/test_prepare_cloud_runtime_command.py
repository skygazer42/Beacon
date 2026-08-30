from unittest import mock

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from app.management.commands import prepare_cloud_runtime


class PrepareCloudRuntimeCommandTest(SimpleTestCase):
    def test_initializer_serializes_migrations_and_bootstrap(self):
        lock = mock.MagicMock()
        lock.wait_acquire.return_value = True
        with (
            mock.patch.object(prepare_cloud_runtime, "get_background_role", return_value="init"),
            mock.patch.dict(
                prepare_cloud_runtime.os.environ,
                {"BEACON_CLOUD_DB_URL": "postgresql://beacon:secret@database/beacon"},
                clear=False,
            ),
            mock.patch.object(
                prepare_cloud_runtime,
                "PostgresAdvisoryLock",
                return_value=lock,
            ),
            mock.patch.object(prepare_cloud_runtime, "call_command") as call_command,
        ):
            prepare_cloud_runtime.Command().handle(
                lock_timeout_seconds=30,
                verbosity=1,
            )

        lock.wait_acquire.assert_called_once_with(30.0, poll_interval_seconds=1.0)
        self.assertEqual(
            call_command.call_args_list,
            [
                mock.call("migrate", interactive=False, verbosity=1),
                mock.call("beacon_cloud_bootstrap", verbosity=1),
            ],
        )

    def test_initializer_rejects_wrong_role_before_connecting(self):
        with mock.patch.object(
            prepare_cloud_runtime,
            "get_background_role",
            return_value="web",
        ):
            with self.assertRaisesRegex(CommandError, "must be init"):
                prepare_cloud_runtime.Command().handle(
                    lock_timeout_seconds=30,
                    verbosity=1,
                )
