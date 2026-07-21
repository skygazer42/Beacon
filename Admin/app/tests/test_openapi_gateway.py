import hashlib
import json
import os
from datetime import timedelta
from unittest import mock

from django.apps import apps
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from app.middleware import SimpleMiddleware


class OpenApiGatewayTest(TestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("BEACON_OPEN_API_TOKEN", None)
        self.addCleanup(os.environ.pop, "BEACON_OPEN_API_TOKEN", None)

        os.environ["BEACON_API_KEY_PEPPER"] = "pepper-test"
        self.addCleanup(os.environ.pop, "BEACON_API_KEY_PEPPER", None)

    def _hash(self, token: str) -> str:
        pepper = str(os.environ.get("BEACON_API_KEY_PEPPER") or "")
        return hashlib.sha256((pepper + token).encode("utf-8")).hexdigest()

    def test_global_openapi_rate_limit_returns_429(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_RATE_LIMIT_ENABLED": "1",
                "BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE": "1",
                "BEACON_OPEN_API_RATE_LIMIT_BURST": "0",
            },
            clear=False,
        ):
            res1 = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
            res2 = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res1.status_code, 200, msg=res1.content)
        self.assertEqual(res2.status_code, 429, msg=res2.content)
        self.assertEqual(str(res2.get("X-RateLimit-Limit") or ""), "1")
        self.assertTrue(int(res2.get("Retry-After") or 0) >= 1)

    def test_api_key_specific_rate_limit_overrides_global(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_rate_1"
        ApiKey.objects.create(
            name="k-rate",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
            rate_limit_per_minute=2,
            burst_limit=0,
        )

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_RATE_LIMIT_ENABLED": "1",
                "BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE": "10",
                "BEACON_OPEN_API_RATE_LIMIT_BURST": "0",
            },
            clear=False,
        ):
            res1 = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token)
            res2 = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token)
            res3 = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token)

        self.assertEqual(res1.status_code, 200, msg=res1.content)
        self.assertEqual(res2.status_code, 200, msg=res2.content)
        self.assertEqual(res3.status_code, 429, msg=res3.content)
        self.assertEqual(str(res3.get("X-RateLimit-Limit") or ""), "2")

    def test_waf_blocks_suspicious_query(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_WAF_ENABLED": "1",
            },
            clear=False,
        ):
            res = self.client.get("/open/ops/health?q=%3Cscript%3E", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res.status_code, 403, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertIn("waf", str(body.get("msg") or "").lower())

    def test_waf_rejects_large_body(self):
        rf = RequestFactory()
        req = rf.post(
            "/open/alarm/upload",
            data="{}",
            content_type="application/json",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN="t1",
            CONTENT_LENGTH="999999",
        )
        req.session = {}

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_WAF_ENABLED": "1",
                "BEACON_OPEN_API_WAF_MAX_BODY_BYTES": "100",
            },
            clear=False,
        ):
            mw = SimpleMiddleware(get_response=lambda r: HttpResponse("ok"))
            res = mw.process_request(req)

        self.assertIsNotNone(res)
        self.assertEqual(res.status_code, 413, msg=getattr(res, "content", b""))

    def test_openapi_ip_allowlist_invalid_cidr_fails_closed(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_IP_ALLOWLIST": "not-a-cidr",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")

        self.assertEqual(res.status_code, 403, msg=res.content)

    def test_rejects_oversized_x_beacon_token_even_if_matching(self):
        oversized = "x" * 80
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": oversized,
                "BEACON_OPEN_API_TOKEN_MAX_LENGTH": "64",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=oversized)

        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_rejects_oversized_bearer_token(self):
        oversized = "y" * 90
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": oversized,
                "BEACON_OPEN_API_TOKEN_MAX_LENGTH": "64",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION=f"Bearer {oversized}")

        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_rejects_x_beacon_token_with_control_char(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t\t1")

        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_rejects_bearer_token_with_control_char(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer t\t1")

        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_ignores_oversized_x_beacon_token_when_authorization_is_valid(self):
        oversized = "z" * 90
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_TOKEN_MAX_LENGTH": "64",
            },
            clear=False,
        ):
            res = self.client.get(
                "/healthz",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN=oversized,
                HTTP_AUTHORIZATION="Bearer t1",
            )

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_ignores_oversized_x_api_key_when_other_alias_is_valid(self):
        oversized = "w" * 90
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_TOKEN_MAX_LENGTH": "64",
            },
            clear=False,
        ):
            res = self.client.get(
                "/healthz",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_API_KEY=oversized,
                HTTP_X_AUTH_TOKEN="t1",
            )

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_quoted_bearer_token(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='Bearer "t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_fully_quoted_authorization_header(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='"Bearer t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_quoted_x_beacon_token(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN='"t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_bearer_token_with_trailing_comma(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer t1,")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_quoted_bearer_token_with_trailing_comma(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='Bearer "t1",')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_x_api_key_header_alias(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_API_KEY="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_quoted_x_api_key_header_alias(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_API_KEY='"t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_x_auth_token_header_alias(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_AUTH_TOKEN="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_quoted_x_auth_token_header_alias(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_AUTH_TOKEN='"t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_scheme(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="ApiKey t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_scheme_with_equals(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="ApiKey=t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_scheme_with_colon(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="ApiKey:t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_scheme_with_semicolon(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="ApiKey; t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_scheme_with_quotes(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='ApiKey "t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_token_scheme(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Token t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_token_scheme_with_equals(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Token=t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_token_scheme_with_colon(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Token:t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_token_scheme_with_semicolon(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Token; t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_token_scheme_with_quotes(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='Token "t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_x_token_header_alias(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_TOKEN="t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_quoted_x_token_header_alias(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_TOKEN='"t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_with_params_suffix(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer t1,foo=bar")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_with_equals(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer=t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_token_param(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='Bearer token="t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_access_token_dash_param(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='Bearer access-token="t1"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_token_param_with_nested_quotes(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='Bearer token="\'t1\'"')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_with_space_equals(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer = t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_with_colon(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer:t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_bearer_with_semicolon(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="Bearer; t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_with_space_equals(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION="ApiKey = t1")

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_accepts_authorization_apikey_with_quoted_params_suffix(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_AUTHORIZATION='ApiKey "t1";foo=bar')

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_token_max_length_env_min_clamp_allows_64_char_token(self):
        token64 = "m" * 64
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": token64,
                "BEACON_OPEN_API_TOKEN_MAX_LENGTH": "1",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token64)

        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_token_max_length_env_max_clamp_allows_large_token(self):
        token3000 = "n" * 3000
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": token3000,
                "BEACON_OPEN_API_TOKEN_MAX_LENGTH": "999999",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token3000)

        self.assertEqual(res.status_code, 200, msg=res.content)
