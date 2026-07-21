from django.test import SimpleTestCase

from app.utils.DbUrl import parse_database_url


class DatabaseUrlTest(SimpleTestCase):
    def test_parses_postgresql_url_and_decodes_credentials(self):
        config = parse_database_url(
            "postgresql://beacon%20user:p%40ss@db.internal:5433/beacon%2Dcloud"
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "beacon-cloud")
        self.assertEqual(config["USER"], "beacon user")
        self.assertEqual(config["PASSWORD"], "p@ss")
        self.assertEqual(config["HOST"], "db.internal")
        self.assertEqual(config["PORT"], "5433")

    def test_accepts_postgres_alias_and_default_port(self):
        config = parse_database_url("postgres://beacon:secret@db.internal/beacon")

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["PORT"], "")

    def test_rejects_unsupported_database_scheme(self):
        with self.assertRaisesRegex(ValueError, "unsupported db scheme: mysql"):
            parse_database_url("mysql://beacon:secret@db.internal/beacon")

    def test_rejects_missing_database_or_host(self):
        with self.assertRaisesRegex(ValueError, "database name is missing"):
            parse_database_url("postgresql://beacon:secret@db.internal")
        with self.assertRaisesRegex(ValueError, "db host is missing"):
            parse_database_url("postgresql:///beacon")

    def test_rejects_invalid_port(self):
        with self.assertRaisesRegex(ValueError, "invalid port"):
            parse_database_url("postgresql://beacon:secret@db.internal:not-a-port/beacon")
