import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


ADMIN_ROOT = Path(__file__).resolve().parents[2]


class ProductionSettingsSecurityTests(SimpleTestCase):
    @staticmethod
    def _environment(database_path, **updates):
        environment = dict(os.environ)
        for name in tuple(environment):
            if name.startswith("BEACON_DJANGO_") or name == "BEACON_CLOUD_ALLOW_INSECURE_HTTP":
                environment.pop(name, None)
        environment.update(
            {
                "BEACON_DISABLE_BACKGROUND": "1",
                "BEACON_DJANGO_DEBUG": "0",
                "BEACON_DJANGO_SECRET_KEY": "test-only-production-secret-key-000000000000001",
                "BEACON_DJANGO_ALLOWED_HOSTS": "beacon.example.test",
                "BEACON_DJANGO_TRUST_X_FORWARDED_PROTO": "1",
                "BEACON_SQLITE_DB_PATH": str(database_path),
            }
        )
        environment.update(updates)
        return environment

    @staticmethod
    def _load_settings(environment):
        script = """
import json
from framework import settings
print(json.dumps({
    "session": settings.SESSION_COOKIE_SECURE,
    "csrf": settings.CSRF_COOKIE_SECURE,
    "redirect": settings.SECURE_SSL_REDIRECT,
    "hsts": settings.SECURE_HSTS_SECONDS,
    "proxy": settings.SECURE_PROXY_SSL_HEADER,
}))
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=ADMIN_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_production_mode_uses_fail_closed_https_defaults(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = self._environment(Path(temporary_directory) / "settings.sqlite3")
            result = self._load_settings(environment)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        loaded = json.loads(result.stdout)
        self.assertTrue(loaded["session"])
        self.assertTrue(loaded["csrf"])
        self.assertTrue(loaded["redirect"])
        self.assertEqual(loaded["hsts"], 31536000)
        self.assertEqual(loaded["proxy"], ["HTTP_X_FORWARDED_PROTO", "https"])

    def test_production_mode_rejects_an_explicit_insecure_override(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = self._environment(
                Path(temporary_directory) / "settings.sqlite3",
                BEACON_DJANGO_SECURE_SSL_REDIRECT="0",
            )
            result = self._load_settings(environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("production HTTPS settings are required", result.stderr)
        self.assertIn("BEACON_DJANGO_SECURE_SSL_REDIRECT", result.stderr)

    def test_production_mode_requires_trusted_proxy_protocol(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = self._environment(Path(temporary_directory) / "settings.sqlite3")
            environment.pop("BEACON_DJANGO_TRUST_X_FORWARDED_PROTO")
            result = self._load_settings(environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BEACON_DJANGO_TRUST_X_FORWARDED_PROTO", result.stderr)

    def test_loopback_poc_requires_an_explicit_escape_hatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = self._environment(
                Path(temporary_directory) / "settings.sqlite3",
                BEACON_BIND_ADDRESS="127.0.0.1",
                BEACON_DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1",
                BEACON_DJANGO_ALLOW_INSECURE_HTTP="1",
                BEACON_DJANGO_SESSION_COOKIE_SECURE="0",
                BEACON_DJANGO_CSRF_COOKIE_SECURE="0",
                BEACON_DJANGO_SECURE_SSL_REDIRECT="0",
                BEACON_DJANGO_TRUST_X_FORWARDED_PROTO="0",
                BEACON_DJANGO_HSTS_SECONDS="0",
            )
            result = self._load_settings(environment)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        loaded = json.loads(result.stdout)
        self.assertFalse(loaded["session"])
        self.assertFalse(loaded["csrf"])
        self.assertFalse(loaded["redirect"])
        self.assertEqual(loaded["hsts"], 0)
        self.assertIsNone(loaded["proxy"])
