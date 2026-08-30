import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "deploy" / "cloud-saas-v1" / "scripts" / "runtime_preflight.py"
SPEC = importlib.util.spec_from_file_location("beacon_cloud_runtime_preflight", MODULE_PATH)
RUNTIME_PREFLIGHT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNTIME_PREFLIGHT)


class RuntimePreflightTest(unittest.TestCase):
    @staticmethod
    def valid_environment():
        return {
            "BEACON_DEPLOYMENT_MODE": "cloud",
            "BEACON_DJANGO_DEBUG": "0",
            "BEACON_REQUIRE_OPEN_API_TOKEN": "1",
            "BEACON_BACKGROUND_ROLE": "web",
            "BEACON_DJANGO_ALLOWED_HOSTS": "beacon.example.test",
            "BEACON_DJANGO_SESSION_COOKIE_SECURE": "1",
            "BEACON_DJANGO_CSRF_COOKIE_SECURE": "1",
            "BEACON_OPEN_API_TOKEN": "OpenApi-9vQ2mL7xR4kN8pT6sW3z-Prod-2026",
            "BEACON_DJANGO_SECRET_KEY": "Django-4xN8qV2mL7pR9sT5wK3z-Prod-2026",
            "BEACON_CLOUD_EDGE_TOKEN_PEPPER": "aaaaabbbbbcccccdddddeeeeefffff11111",
            "BEACON_BOOTSTRAP_ADMIN_PASSWORD": "Admin-5qL8vN2mR7xT",
            "BEACON_CLOUD_S3_ACCESS_KEY_ID": "beacon-object-access",
            "BEACON_CLOUD_S3_SECRET_ACCESS_KEY": "Object-8nQ3xV7mL2pR",
            "BEACON_CLOUD_S3_BUCKET": "beacon-cloud",
            "BEACON_BOOTSTRAP_ADMIN_USERNAME": "admin",
            "BEACON_CLOUD_DB_URL": (
                "postgresql://beacon:Database-6vN2qL9xR4mT@database.example/beacon"
            ),
        }

    def test_postgres_target_comes_from_database_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            target = RUNTIME_PREFLIGHT.postgres_target(
                "postgresql://beacon:p%40ss@database.example:5544/beacon"
            )

        self.assertEqual(target, ("database.example", 5544))

    def test_postgres_target_honors_explicit_connectivity_override(self):
        with mock.patch.dict(
            os.environ,
            {"BEACON_PG_HOST": "proxy.internal", "BEACON_PG_PORT": "6432"},
            clear=True,
        ):
            target = RUNTIME_PREFLIGHT.postgres_target(
                "postgresql://beacon:secret@database.example/beacon"
            )

        self.assertEqual(target, ("proxy.internal", 6432))

    def test_postgres_target_rejects_non_postgres_or_incomplete_urls(self):
        invalid_urls = (
            "sqlite:///tmp/beacon.db",
            "postgresql://database.example/beacon",
            "postgresql://beacon:secret@database.example:70000/beacon",
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            for database_url in invalid_urls:
                with self.subTest(database_url=database_url):
                    with self.assertRaises(SystemExit):
                        RUNTIME_PREFLIGHT.postgres_target(database_url)

    def test_validation_rejects_reused_secrets(self):
        shared = "Shared-Secret-9xQ2mV7kL4pR8sT6wN3z"
        environment = self.valid_environment()
        environment.update({name: shared for name in RUNTIME_PREFLIGHT.REQUIRED_SECRETS})

        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(SystemExit, "must be unique"):
                RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_validation_accepts_hardened_cloud_environment(self):
        with mock.patch.dict(os.environ, self.valid_environment(), clear=True):
            database_url = RUNTIME_PREFLIGHT.validate_runtime_environment()

        self.assertIn("database.example", database_url)

    def test_web_role_does_not_receive_bootstrap_credentials(self):
        environment = self.valid_environment()
        environment.pop("BEACON_BOOTSTRAP_ADMIN_PASSWORD")
        environment.pop("BEACON_BOOTSTRAP_ADMIN_USERNAME")

        with mock.patch.dict(os.environ, environment, clear=True):
            RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_init_role_requires_bootstrap_credentials(self):
        environment = self.valid_environment()
        environment["BEACON_BACKGROUND_ROLE"] = "init"
        environment.pop("BEACON_BOOTSTRAP_ADMIN_PASSWORD")

        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(SystemExit, "BOOTSTRAP_ADMIN_PASSWORD"):
                RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_external_transports_require_tls(self):
        cases = (
            (
                {
                    "BEACON_REQUIRE_DATABASE_TLS": "1",
                },
                "external PostgreSQL requires sslmode",
            ),
            (
                {
                    "BEACON_CLOUD_S3_ENDPOINT_URL": "http://objects.example.test",
                },
                "insecure object storage",
            ),
        )
        for updates, expected_error in cases:
            with self.subTest(updates=updates):
                environment = self.valid_environment()
                environment.update(updates)
                with mock.patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(SystemExit, expected_error):
                        RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_external_transports_accept_explicit_tls(self):
        environment = self.valid_environment()
        environment.update(
            {
                "BEACON_REQUIRE_DATABASE_TLS": "1",
                "BEACON_CLOUD_DB_URL": (
                    "postgresql://beacon:Database-6vN2qL9xR4mT@database.example/beacon"
                    "?sslmode=verify-full"
                ),
                "BEACON_CLOUD_S3_ENDPOINT_URL": "https://objects.example.test",
            }
        )

        with mock.patch.dict(os.environ, environment, clear=True):
            RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_bundled_object_storage_requires_explicit_http_exception(self):
        environment = self.valid_environment()
        environment.update(
            {
                "BEACON_CLOUD_S3_ENDPOINT_URL": "http://minio:9000",
                "BEACON_ALLOW_INSECURE_OBJECT_STORAGE": "1",
            }
        )

        with mock.patch.dict(os.environ, environment, clear=True):
            RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_validation_rejects_unsafe_cloud_modes(self):
        cases = (
            ({"BEACON_DJANGO_DEBUG": "1"}, "DEBUG must be disabled"),
            ({"BEACON_REQUIRE_OPEN_API_TOKEN": "0"}, "must be enabled"),
            ({"BEACON_DJANGO_ALLOWED_HOSTS": "*"}, "must be explicit"),
            ({"BEACON_DJANGO_SESSION_COOKIE_SECURE": "0"}, "insecure cookies"),
            ({"BEACON_DJANGO_CSRF_COOKIE_SECURE": "sometimes"}, "explicit boolean"),
            ({"BEACON_BACKGROUND_ROLE": "all"}, "must explicitly select"),
        )
        for updates, expected_error in cases:
            with self.subTest(updates=updates):
                environment = self.valid_environment()
                environment.update(updates)
                with mock.patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(SystemExit, expected_error):
                        RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_validation_allows_explicit_loopback_http_poc(self):
        environment = self.valid_environment()
        environment.update(
            {
                "BEACON_CLOUD_ALLOW_INSECURE_HTTP": "1",
                "BEACON_DJANGO_SESSION_COOKIE_SECURE": "0",
                "BEACON_DJANGO_CSRF_COOKIE_SECURE": "0",
            }
        )
        with mock.patch.dict(os.environ, environment, clear=True):
            RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_validation_rejects_weak_or_reused_database_password(self):
        for password, expected_error in (
            ("aaaaaaaaaaaaaaaa", "strong secret"),
            (self.valid_environment()["BEACON_OPEN_API_TOKEN"], "must be unique"),
        ):
            with self.subTest(password=password):
                environment = self.valid_environment()
                environment["BEACON_CLOUD_DB_URL"] = (
                    f"postgresql://beacon:{password}@database.example/beacon"
                )
                with mock.patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(SystemExit, expected_error):
                        RUNTIME_PREFLIGHT.validate_runtime_environment()

    def test_wait_for_postgres_closes_successful_connection(self):
        connection = mock.Mock()
        with mock.patch.object(
            RUNTIME_PREFLIGHT.socket,
            "create_connection",
            return_value=connection,
        ) as create_connection:
            RUNTIME_PREFLIGHT.wait_for_postgres("database.example", 5432, attempts=1)

        create_connection.assert_called_once_with(("database.example", 5432), timeout=2)
        connection.close.assert_called_once_with()

    def test_wait_for_postgres_fails_after_bounded_attempts(self):
        with (
            mock.patch.object(
                RUNTIME_PREFLIGHT.socket,
                "create_connection",
                side_effect=OSError("unavailable"),
            ) as create_connection,
            mock.patch.object(RUNTIME_PREFLIGHT.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(SystemExit, "not reachable"):
                RUNTIME_PREFLIGHT.wait_for_postgres("database.example", 5432, attempts=3)

        self.assertEqual(create_connection.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
