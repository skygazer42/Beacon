import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "deploy" / "cloud-saas-v1" / "scripts" / "wait_for_migrations.py"
SPEC = importlib.util.spec_from_file_location("beacon_wait_for_migrations", MODULE_PATH)
WAIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(WAIT)


class WaitForMigrationsTest(unittest.TestCase):
    def test_wait_succeeds_after_pending_schema_is_applied(self):
        run = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess([], 1, "pending"),
                subprocess.CompletedProcess([], 0, "current"),
            ]
        )
        sleep = mock.Mock()

        WAIT.wait_for_migrations(
            attempts=3,
            delay_seconds=0.5,
            run=run,
            sleep=sleep,
        )

        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(0.5)
        command = run.call_args_list[0].args[0]
        self.assertEqual(command[-3:], ["migrate", "--check", "--noinput"])
        self.assertFalse(run.call_args_list[0].kwargs["check"])

    def test_wait_fails_after_bounded_attempts(self):
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 1, "pending"))
        sleep = mock.Mock()

        with self.assertRaisesRegex(SystemExit, "not completed"):
            WAIT.wait_for_migrations(
                attempts=2,
                delay_seconds=1,
                run=run,
                sleep=sleep,
            )

        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_wait_treats_timeout_as_retryable(self):
        run = mock.Mock(side_effect=subprocess.TimeoutExpired(["manage.py"], 60))

        with self.assertRaisesRegex(SystemExit, "not completed"):
            WAIT.wait_for_migrations(
                attempts=1,
                delay_seconds=1,
                run=run,
                sleep=mock.Mock(),
            )
