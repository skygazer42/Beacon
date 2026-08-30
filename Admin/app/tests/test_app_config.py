from unittest import mock

from django.test import SimpleTestCase

from app.apps import (
    _schedule_background_services_best_effort,
    _should_skip_background_services,
    _start_background_services_after_registry_ready,
)
from app.utils.BackgroundRoles import get_background_role


class AppConfigBackgroundServiceTests(SimpleTestCase):
    def test_read_only_help_command_does_not_start_background_services(self):
        self.assertTrue(
            _should_skip_background_services(["manage.py", "help", "serve_production"])
        )

    def test_production_server_still_starts_background_services(self):
        self.assertFalse(
            _should_skip_background_services(
                ["manage.py", "serve_production"],
                role="all",
            )
        )

    def test_cloud_worker_and_init_roles_do_not_autostart(self):
        for role in ("worker", "init", "disabled"):
            with self.subTest(role=role):
                self.assertTrue(
                    _should_skip_background_services(
                        ["manage.py", "serve_production"],
                        role=role,
                    )
                )

    def test_invalid_background_role_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "BEACON_BACKGROUND_ROLE"):
            get_background_role({"BEACON_BACKGROUND_ROLE": "typo"})

    def test_legacy_disable_flag_overrides_role(self):
        role = get_background_role(
            {
                "BEACON_BACKGROUND_ROLE": "web",
                "BEACON_DISABLE_BACKGROUND": "1",
            }
        )

        self.assertEqual(role, "disabled")

    def test_background_services_wait_until_registry_is_ready(self):
        registry = mock.Mock(ready=False)

        def mark_ready(_seconds):
            registry.ready = True

        with mock.patch("app.apps._start_background_services_best_effort") as start:
            _start_background_services_after_registry_ready(
                registry,
                mark_ready,
                role="web",
            )

        start.assert_called_once_with(role="web")

    def test_background_service_bootstrap_is_scheduled_once(self):
        thread = mock.Mock()
        with (
            mock.patch("app.apps._background_bootstrap_scheduled", False),
            mock.patch("app.apps.threading.Thread", return_value=thread) as thread_class,
        ):
            _schedule_background_services_best_effort(role="web")
            _schedule_background_services_best_effort(role="web")

        thread_class.assert_called_once_with(
            target=_start_background_services_after_registry_ready,
            name="beacon-background-bootstrap",
            daemon=True,
            kwargs={"role": "web"},
        )
        thread.start.assert_called_once_with()
