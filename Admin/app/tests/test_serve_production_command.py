from unittest import mock

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from app.management.commands import serve_production


class ServeProductionCommandTests(SimpleTestCase):
    def test_starts_waitress_with_safe_defaults(self):
        with mock.patch.object(serve_production, "serve") as mocked_serve:
            serve_production.Command().handle(
                host="127.0.0.1",
                port=19991,
                threads=6,
                trusted_proxy="",
                trusted_proxy_headers="x-forwarded-proto",
            )

        args, kwargs = mocked_serve.call_args
        self.assertIs(args[0], serve_production.application)
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 19991)
        self.assertEqual(kwargs["threads"], 6)
        self.assertFalse(kwargs["expose_tracebacks"])
        self.assertNotIn("trusted_proxy", kwargs)

    def test_allows_only_explicit_proxy_ip_and_headers(self):
        with mock.patch.object(serve_production, "serve") as mocked_serve:
            serve_production.Command().handle(
                host="0.0.0.0",
                port=9991,
                threads=4,
                trusted_proxy="127.0.0.1",
                trusted_proxy_headers="x-forwarded-proto,x-forwarded-for",
            )

        kwargs = mocked_serve.call_args.kwargs
        self.assertEqual(kwargs["trusted_proxy"], "127.0.0.1")
        self.assertEqual(
            kwargs["trusted_proxy_headers"],
            {"x-forwarded-proto", "x-forwarded-for"},
        )
        self.assertTrue(kwargs["clear_untrusted_proxy_headers"])

    def test_rejects_wildcard_trusted_proxy(self):
        with self.assertRaises(CommandError):
            serve_production.Command().handle(
                host="0.0.0.0",
                port=9991,
                threads=4,
                trusted_proxy="*",
                trusted_proxy_headers="x-forwarded-proto",
            )
