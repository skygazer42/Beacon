from unittest import mock

from django.http import HttpResponse
from django.test import SimpleTestCase

from app.middleware import IframeEmbedMiddleware


class IframeEmbedSecurityTests(SimpleTestCase):
    def _process(self, env, *, csp=""):
        response = HttpResponse()
        response["X-Frame-Options"] = "DENY"
        if csp:
            response["Content-Security-Policy"] = csp
        middleware = IframeEmbedMiddleware(lambda _request: response)
        with mock.patch.dict("os.environ", env, clear=False):
            return middleware.process_response(object(), response)

    def test_iframe_embedding_stays_denied_by_default(self):
        response = self._process({"BEACON_IFRAME_EMBED_ENABLED": "0"})

        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertFalse(response.has_header("Content-Security-Policy"))

    def test_enabled_embedding_without_allowlist_is_same_origin_only(self):
        response = self._process(
            {
                "BEACON_IFRAME_EMBED_ENABLED": "1",
                "BEACON_IFRAME_EMBED_ALLOWED_ORIGINS": "",
            }
        )

        self.assertFalse(response.has_header("X-Frame-Options"))
        self.assertEqual(response["Content-Security-Policy"], "frame-ancestors 'self';")

    def test_explicit_origins_are_merged_into_existing_csp(self):
        response = self._process(
            {
                "BEACON_IFRAME_EMBED_ENABLED": "1",
                "BEACON_IFRAME_EMBED_ALLOWED_ORIGINS": "https://a.example.com, https://b.example.com",
            },
            csp="default-src 'self'; frame-ancestors https://old.example.com;",
        )

        self.assertEqual(
            response["Content-Security-Policy"],
            "default-src 'self'; frame-ancestors 'self' https://a.example.com https://b.example.com;",
        )
