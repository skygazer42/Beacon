import json
import stat
import tempfile
import threading
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from app.management.commands.run_background_worker import (
    BackgroundWorkerRuntimeError,
    run_background_worker_loop,
    write_worker_heartbeat,
)


class BackgroundWorkerCommandTest(SimpleTestCase):
    def test_heartbeat_is_atomic_private_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            write_worker_heartbeat(
                path,
                state="leader",
                background_state="running",
                now=lambda: 1234.5,
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            mode = stat.S_IMODE(path.stat().st_mode)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["role"], "worker")
        self.assertEqual(payload["state"], "leader")
        self.assertEqual(payload["background_state"], "running")
        self.assertEqual(payload["updated_at"], 1234.5)
        self.assertEqual(mode, 0o600)

    def test_standby_never_starts_singleton_services(self):
        lock = mock.Mock(acquired=False)
        lock.try_acquire.return_value = False
        heartbeat = mock.Mock()
        start_services = mock.Mock()

        state = run_background_worker_loop(
            lock,
            threading.Event(),
            heartbeat_path=Path("/tmp/worker.json"),
            heartbeat_interval_seconds=5,
            standby_poll_seconds=5,
            start_services=start_services,
            get_status=mock.Mock(),
            shutdown_services=mock.Mock(),
            write_heartbeat=heartbeat,
            max_cycles=1,
        )

        self.assertEqual(state, "standby")
        start_services.assert_not_called()
        heartbeat.assert_called_once_with(
            Path("/tmp/worker.json"),
            state="standby",
            background_state="standby",
        )

    def test_leader_starts_monitors_and_shuts_down_services(self):
        lock = mock.Mock(acquired=False)

        def acquire():
            lock.acquired = True
            return True

        lock.try_acquire.side_effect = acquire
        start_services = mock.Mock(return_value={"state": "running"})
        get_status = mock.Mock(return_value={"state": "running"})
        shutdown = mock.Mock()
        heartbeat = mock.Mock()

        state = run_background_worker_loop(
            lock,
            threading.Event(),
            heartbeat_path=Path("/tmp/worker.json"),
            heartbeat_interval_seconds=5,
            standby_poll_seconds=5,
            start_services=start_services,
            get_status=get_status,
            shutdown_services=shutdown,
            write_heartbeat=heartbeat,
            max_cycles=1,
        )

        self.assertEqual(state, "leader")
        start_services.assert_called_once_with(role="worker")
        lock.keepalive.assert_called_once_with()
        shutdown.assert_called_once_with()
        self.assertEqual(heartbeat.call_args_list[-1].kwargs["state"], "stopping")

    def test_degraded_leader_fails_closed(self):
        lock = mock.Mock(acquired=False)

        def acquire():
            lock.acquired = True
            return True

        lock.try_acquire.side_effect = acquire
        shutdown = mock.Mock()
        with self.assertRaisesRegex(BackgroundWorkerRuntimeError, "failed to start"):
            run_background_worker_loop(
                lock,
                threading.Event(),
                heartbeat_path=Path("/tmp/worker.json"),
                heartbeat_interval_seconds=5,
                standby_poll_seconds=5,
                start_services=mock.Mock(return_value={"state": "degraded"}),
                get_status=mock.Mock(),
                shutdown_services=shutdown,
                write_heartbeat=mock.Mock(),
                max_cycles=1,
            )

        shutdown.assert_called_once_with()
