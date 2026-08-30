from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from app.utils.TranscodeManager import TranscodeManager


class TranscodeManagerLifecycleTest(SimpleTestCase):
    def test_shutdown_stops_cleanup_thread_without_waiting_for_poll_interval(self):
        manager = TranscodeManager(SimpleNamespace(transcodeIdleSeconds=300), mock.Mock())

        manager.start()
        cleanup_thread = manager._thread
        self.assertIsNotNone(cleanup_thread)
        self.assertTrue(cleanup_thread.is_alive())

        manager.shutdown(timeout=1.0)

        self.assertFalse(cleanup_thread.is_alive())
