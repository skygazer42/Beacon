from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from app.utils.DbUrl import parse_database_url
from app.views import ControlView, StreamView


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
        self.assertEqual(config["OPTIONS"], {"connect_timeout": 10})

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

    def test_preserves_valid_tls_and_failover_options(self):
        config = parse_database_url(
            "postgresql://beacon:secret@db.internal/beacon"
            "?sslmode=verify-full&sslrootcert=%2Fetc%2Fbeacon%2Fca.pem"
            "&connect_timeout=15&target_session_attrs=read-write"
        )

        self.assertEqual(
            config["OPTIONS"],
            {
                "connect_timeout": 15,
                "sslmode": "verify-full",
                "sslrootcert": "/etc/beacon/ca.pem",
                "target_session_attrs": "read-write",
            },
        )

    def test_rejects_unknown_duplicate_or_unsafe_database_options(self):
        invalid_urls = (
            "postgresql://beacon:secret@db.internal/beacon?unknown=value",
            "postgresql://beacon:secret@db.internal/beacon?sslmode=require&sslmode=disable",
            "postgresql://beacon:secret@db.internal/beacon?sslmode=not-real",
            "postgresql://beacon:secret@db.internal/beacon?connect_timeout=0",
            "postgresql://beacon:secret@db.internal/beacon?target_session_attrs=leader",
        )
        for database_url in invalid_urls:
            with self.subTest(database_url=database_url):
                with self.assertRaises(ValueError):
                    parse_database_url(database_url)


class CrossDatabasePaginationTest(SimpleTestCase):
    def test_control_query_uses_portable_limit_offset_syntax(self):
        database = mock.Mock()
        database.select.return_value = []

        with mock.patch.object(ControlView, "g_djangoSql", database):
            ControlView._fetch_control_rows(
                " where stream_app = %s",
                ["live"],
                page=2,
                page_size=20,
            )

        database.select.assert_called_once_with(
            "select * from av_control where stream_app = %s order by id desc limit %s offset %s",
            ["live", 20, 20],
        )

    def test_stream_query_uses_portable_limit_offset_syntax(self):
        database = mock.Mock()
        database.select.side_effect = [[{"count": 1}], []]
        request = RequestFactory().get("/stream/openIndex", {"p": 2, "ps": 20})

        with mock.patch.object(StreamView, "g_djangoSql", database):
            response = StreamView.api_open_index(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            database.select.call_args_list[1],
            mock.call(
                "select * from av_stream order by id desc limit %s offset %s",
                [20, 20],
            ),
        )
