import os
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


@override_settings(DEBUG=False)
class CloudBootstrapSecurityTest(SimpleTestCase):
    def _base_environment(self):
        return {
            "BEACON_DEPLOYMENT_MODE": "cloud",
            "BEACON_CLOUD_EDGE_TOKEN_PEPPER": "test-pepper-value-at-least-32-chars",
        }

    def test_production_bootstrap_requires_admin_password(self):
        with patch.dict(os.environ, self._base_environment(), clear=False):
            os.environ.pop("BEACON_BOOTSTRAP_ADMIN_PASSWORD", None)
            with self.assertRaisesMessage(CommandError, "missing BEACON_BOOTSTRAP_ADMIN_PASSWORD"):
                call_command("beacon_cloud_bootstrap")

    @override_settings(DEBUG=True)
    def test_development_bootstrap_also_requires_admin_password(self):
        with patch.dict(os.environ, self._base_environment(), clear=False):
            os.environ.pop("BEACON_BOOTSTRAP_ADMIN_PASSWORD", None)
            with self.assertRaisesMessage(CommandError, "missing BEACON_BOOTSTRAP_ADMIN_PASSWORD"):
                call_command("beacon_cloud_bootstrap")

    def test_production_bootstrap_rejects_weak_admin_password(self):
        environment = {
            **self._base_environment(),
            "BEACON_BOOTSTRAP_ADMIN_PASSWORD": "short",
        }
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesMessage(CommandError, "is not strong enough"):
                call_command("beacon_cloud_bootstrap")
