import base64
import json
import os
import time
from urllib.parse import parse_qs, urlparse
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase


def _b64url_json(obj) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


_TEST_JWKS_URI = "https://idp.example.com/jwks-test-default"
_TEST_JWT_KID = "test-default-kid"
_TEST_PRIVATE_KEY = None


def _get_test_private_key():
    global _TEST_PRIVATE_KEY
    if _TEST_PRIVATE_KEY is None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        _TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    return _TEST_PRIVATE_KEY


def _make_unverified_jwt(payload: dict) -> str:
    # Minimal JWT-like token for tests. Signature is intentionally empty.
    header = {"alg": "none", "typ": "JWT"}
    return f"{_b64url_json(header)}.{_b64url_json(payload)}."


def _make_fake_jwt(payload: dict) -> str:
    signed_payload = dict(payload or {})
    signed_payload.setdefault("exp", int(time.time()) + 3600)
    return _make_rs256_jwt(signed_payload, kid=_TEST_JWT_KID, private_key=_get_test_private_key())


def _b64url_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _make_rs256_jwt(payload: dict, *, kid: str, private_key) -> str:
    """
    Create a real RS256 signed JWT for verification tests.
    `private_key` is a cryptography RSA private key.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": "RS256", "typ": "JWT", "kid": str(kid)}
    h = _b64url_json(header)
    p = _b64url_json(payload)
    signing_input = f"{h}.{p}".encode("ascii")
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{_b64url_bytes(sig)}"


def _jwks_from_public_key(public_key, *, kid: str) -> dict:
    """
    Build a JWKS document from an RSA public key.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa

    if not isinstance(public_key, rsa.RSAPublicKey):
        raise TypeError("public_key must be RSAPublicKey")
    numbers = public_key.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": str(kid),
                "n": _b64url_bytes(n),
                "e": _b64url_bytes(e),
            }
        ]
    }


class OidcSsoLoginTest(TestCase):
    def setUp(self):
        super().setUp()
        # Ensure test isolation.
        self._old_env = dict(os.environ)
        os.environ["BEACON_OIDC_ENABLED"] = "1"
        os.environ["BEACON_OIDC_CLIENT_ID"] = "cid_test"
        os.environ["BEACON_OIDC_CLIENT_SECRET"] = "sec_test"
        os.environ["BEACON_OIDC_AUTHORIZATION_ENDPOINT"] = "https://idp.example.com/authorize"
        os.environ["BEACON_OIDC_TOKEN_ENDPOINT"] = "https://idp.example.com/token"
        os.environ["BEACON_OIDC_SCOPE"] = "openid email profile"
        os.environ["BEACON_OIDC_JWKS_URI"] = _TEST_JWKS_URI
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"

        from app.utils import OidcAuth

        OidcAuth._JWKS_CACHE.clear()
        OidcAuth._JWKS_CACHE[_TEST_JWKS_URI] = {
            "expires_at": time.time() + 3600,
            "jwks": _jwks_from_public_key(_get_test_private_key().public_key(), kid=_TEST_JWT_KID),
        }

    def tearDown(self):
        from app.utils import OidcAuth

        OidcAuth._JWKS_CACHE.clear()
        os.environ.clear()
        os.environ.update(self._old_env)
        super().tearDown()

    def test_oidc_start_redirects_to_authorization_endpoint(self):
        res = self.client.get("/login/oidc/start")
        self.assertEqual(res.status_code, 302)

        location = str(res.get("Location") or "")
        self.assertTrue(location.startswith("https://idp.example.com/authorize"), msg=location)

        parsed = urlparse(location)
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("client_id"), ["cid_test"])
        self.assertEqual(qs.get("response_type"), ["code"])
        self.assertEqual(qs.get("scope"), ["openid email profile"])

        redirect_uri = (qs.get("redirect_uri") or [""])[0]
        self.assertTrue(redirect_uri.endswith("/login/oidc/callback"), msg=redirect_uri)

    def test_login_template_registers_submit_handler_once(self):
        res = self.client.get("/login")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content.count(b"form.addEventListener('submit'"), 1)
        self.assertIn(b'autocomplete="username"', res.content)
        self.assertIn(b'autocomplete="current-password"', res.content)

    def test_oidc_start_rejects_invalid_provider_id(self):
        res = self.client.get("/login/oidc/start?provider=../bad")
        self.assertEqual(res.status_code, 400)
        self.assertIn("provider invalid", str(res.content.decode("utf-8")).lower())

    def test_oidc_callback_rejects_invalid_provider_id(self):
        res = self.client.get("/login/oidc/callback?provider=bad/../x")
        self.assertEqual(res.status_code, 400)
        self.assertIn("provider invalid", str(res.content.decode("utf-8")).lower())

    def test_oidc_callback_normalizes_quoted_error_code(self):
        res = self.client.get('/login/oidc/callback?error=%22access_denied%22')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.content.decode("utf-8"), "oidc error: access_denied")

    def test_oidc_merge_claims_keeps_non_empty_identity_fields(self):
        from app.views import web as web_views

        claims = {
            "sub": "sub-1",
            "preferred_username": "user_from_id_token",
            "email": "id@example.com",
        }
        userinfo = {
            "sub": "",
            "preferred_username": "   ",
            "email": "ui@example.com",
        }

        merged = web_views._web_oidc_merge_claims(claims, userinfo, prefer_userinfo=True)

        self.assertEqual(merged.get("sub"), "sub-1")
        self.assertEqual(merged.get("preferred_username"), "user_from_id_token")
        self.assertEqual(merged.get("email"), "ui@example.com")

    def test_oidc_callback_exchanges_code_and_creates_user_session(self):
        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-1",
                "email": "u_oidc@example.com",
                "preferred_username": "u_oidc",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        def fake_post(url, data=None, timeout=None, **kwargs):
            self.assertEqual(url, "https://idp.example.com/token")
            self.assertEqual(str(data.get("grant_type")), "authorization_code")
            self.assertEqual(str(data.get("code")), "code-1")
            self.assertIn("redirect_uri", data)
            self.assertEqual(str(data.get("client_id")), "cid_test")
            self.assertEqual(str(data.get("client_secret")), "sec_test")
            return FakeResp({"access_token": "at-1", "id_token": id_token, "token_type": "Bearer"})

        with mock.patch("requests.post", side_effect=fake_post):
            cb = self.client.get(f"/login/oidc/callback?code=code-1&state={state}")

        self.assertEqual(cb.status_code, 302)
        self.assertEqual(cb.get("Location"), "/")

        user = User.objects.filter(username="u_oidc").first()
        self.assertIsNotNone(user)
        self.assertEqual(str(getattr(user, "email", "") or ""), "u_oidc@example.com")

        session_user = self.client.session.get("user") or {}
        self.assertEqual(int(session_user.get("id") or 0), int(getattr(user, "id") or 0))
        self.assertEqual(str(session_user.get("username") or ""), "u_oidc")

    def test_oidc_claims_are_nfkc_normalized_and_email_lowercased(self):
        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-norm-1",
                "email": "User.Name@Example.COM",
                "preferred_username": "ｕｓｅｒ＿ｏｉｄｃ",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-norm-1", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-norm-1&state={state}")
        self.assertEqual(cb.status_code, 302)

        user = User.objects.filter(username="user_oidc").first()
        self.assertIsNotNone(user)
        self.assertEqual(str(getattr(user, "email", "") or ""), "user.name@example.com")

    def test_oidc_callback_sanitizes_local_username_from_claims(self):
        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-sanitize-1",
                "email": "sanitize1@example.com",
                "preferred_username": "bad user/\\name",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-sanitize-1", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-sanitize-1&state={state}")
        self.assertEqual(cb.status_code, 302)

        user = User.objects.filter(email__iexact="sanitize1@example.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(str(getattr(user, "username", "") or ""), "bad_user_name")

    def test_oidc_callback_denies_when_link_mode_is_deny_and_identity_missing(self):
        os.environ["BEACON_OIDC_ACCOUNT_LINK_MODE"] = "deny"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-deny-1",
                "email": "deny@example.com",
                "preferred_username": "deny_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-deny", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-deny&state={state}")
        self.assertEqual(cb.status_code, 403)

    def test_oidc_callback_denies_when_required_group_missing(self):
        os.environ["BEACON_OIDC_REQUIRED_GROUPS"] = "beacon_allowed"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-rg-1",
                "email": "rg@example.com",
                "preferred_username": "rg_user",
                "groups": ["other"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-rg", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-rg&state={state}")
        self.assertEqual(cb.status_code, 403)

    def test_oidc_callback_create_mode_does_not_link_existing_user_by_username(self):
        from app.models import UserOidcIdentity

        os.environ["BEACON_OIDC_ACCOUNT_LINK_MODE"] = "create"

        existing = User.objects.create_user(username="u_oidc", password="pass12345", email="exist@example.com")

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-create-1",
                "email": "new@example.com",
                "preferred_username": "u_oidc",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-create", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-create&state={state}")
        self.assertEqual(cb.status_code, 302)

        session_user = self.client.session.get("user") or {}
        self.assertNotEqual(int(session_user.get("id") or 0), int(existing.id))

        identity = UserOidcIdentity.objects.filter(provider_id="default", subject="sub-create-1").first()
        self.assertIsNotNone(identity)
        self.assertEqual(int(getattr(identity, "user_id") or 0), int(session_user.get("id") or 0))

    def test_oidc_callback_uses_existing_identity_mapping_even_in_deny_mode(self):
        from app.models import UserOidcIdentity

        os.environ["BEACON_OIDC_ACCOUNT_LINK_MODE"] = "deny"

        u1 = User.objects.create_user(username="local1", password="pass12345", email="local1@example.com")
        UserOidcIdentity.objects.create(user=u1, provider_id="default", subject="sub-linked-1", email="local1@example.com")

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        # preferred_username differs, but sub matches existing mapping.
        id_token = _make_fake_jwt(
            {
                "sub": "sub-linked-1",
                "email": "local1@example.com",
                "preferred_username": "someone_else",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-linked", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-linked&state={state}")
        self.assertEqual(cb.status_code, 302)

        session_user = self.client.session.get("user") or {}
        self.assertEqual(int(session_user.get("id") or 0), int(u1.id))

    def test_oidc_callback_links_existing_user_by_email_case_insensitive(self):
        existing = User.objects.create_user(
            username="email_case_local_1",
            password="pass12345",
            email="CaseUser@Example.COM",
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-email-case-1",
                "email": "caseuser@example.com",
                "preferred_username": "totally_different_name",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-email-case", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-email-case&state={state}")
        self.assertEqual(cb.status_code, 302)

        session_user = self.client.session.get("user") or {}
        self.assertEqual(int(session_user.get("id") or 0), int(existing.id))
        self.assertEqual(User.objects.filter(email__iexact="caseuser@example.com").count(), 1)

    def test_oidc_callback_links_existing_user_by_username_case_insensitive(self):
        existing = User.objects.create_user(
            username="CaseOidcUser1",
            password="pass12345",
            email="case_oidc_user1@example.com",
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-case-oidc-1",
                "email": "another_email@example.com",
                "preferred_username": "caseoidcuser1",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-case-oidc", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-case-oidc&state={state}")
        self.assertEqual(cb.status_code, 302)

        session_user = self.client.session.get("user") or {}
        self.assertEqual(int(session_user.get("id") or 0), int(existing.id))
        self.assertEqual(User.objects.filter(username__iexact="caseoidcuser1").count(), 1)

    def test_oidc_start_and_callback_support_multi_provider_config(self):
        os.environ["BEACON_OIDC_PROVIDERS_JSON"] = json.dumps(
            {
                "p1": {
                    "client_id": "cid_p1",
                    "client_secret": "sec_p1",
                    "authorization_endpoint": "https://p1.example.com/authorize",
                    "token_endpoint": "https://p1.example.com/token",
                    "scope": "openid email profile",
                },
                "p2": {
                    "client_id": "cid_p2",
                    "client_secret": "sec_p2",
                    "authorization_endpoint": "https://p2.example.com/authorize",
                    "token_endpoint": "https://p2.example.com/token",
                    "scope": "openid email profile",
                },
            },
            ensure_ascii=False,
        )
        os.environ["BEACON_OIDC_PROVIDER_DEFAULT"] = "p1"

        start = self.client.get("/login/oidc/start?provider=p2")
        self.assertEqual(start.status_code, 302)
        location = str(start.get("Location") or "")
        self.assertTrue(location.startswith("https://p2.example.com/authorize"), msg=location)

        parsed = urlparse(location)
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("client_id"), ["cid_p2"])
        redirect_uri = (qs.get("redirect_uri") or [""])[0]
        self.assertIn("/login/oidc/callback", redirect_uri)
        self.assertIn("provider=p2", redirect_uri)

        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-mp-1",
                "email": "mp@example.com",
                "preferred_username": "mp_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_p2",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        def fake_post(url, data=None, timeout=None, **kwargs):
            self.assertEqual(url, "https://p2.example.com/token")
            self.assertEqual(str(data.get("client_id")), "cid_p2")
            self.assertEqual(str(data.get("client_secret")), "sec_p2")
            return FakeResp({"access_token": "at-mp", "id_token": id_token, "token_type": "Bearer"})

        with mock.patch("requests.post", side_effect=fake_post):
            cb = self.client.get(f"/login/oidc/callback?code=code-mp&state={state}&provider=p2")
        self.assertEqual(cb.status_code, 302)
        self.assertEqual(cb.get("Location"), "/")

        user = User.objects.filter(username="mp_user").first()
        self.assertIsNotNone(user)

    def test_oidc_start_ignores_invalid_provider_ids_in_config(self):
        os.environ["BEACON_OIDC_PROVIDERS_JSON"] = json.dumps(
            {
                "../bad": {
                    "client_id": "cid_bad",
                    "client_secret": "sec_bad",
                    "authorization_endpoint": "https://bad.example.com/authorize",
                    "token_endpoint": "https://bad.example.com/token",
                },
                "p1": {
                    "client_id": "cid_p1",
                    "client_secret": "sec_p1",
                    "authorization_endpoint": "https://p1.example.com/authorize",
                    "token_endpoint": "https://p1.example.com/token",
                    "scope": "openid email profile",
                },
            },
            ensure_ascii=False,
        )
        os.environ["BEACON_OIDC_PROVIDER_DEFAULT"] = "../bad"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        location = str(start.get("Location") or "")
        self.assertTrue(location.startswith("https://p1.example.com/authorize"), msg=location)

    def test_oidc_provider_blank_scope_falls_back_to_global_scope(self):
        os.environ["BEACON_OIDC_SCOPE"] = "openid email profile groups"
        os.environ["BEACON_OIDC_PROVIDERS_JSON"] = json.dumps(
            {
                "p1": {
                    "client_id": "cid_p1",
                    "client_secret": "sec_p1",
                    "authorization_endpoint": "https://p1.example.com/authorize",
                    "token_endpoint": "https://p1.example.com/token",
                    "scope": "   ",
                },
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start?provider=p1")
        self.assertEqual(start.status_code, 302)
        location = str(start.get("Location") or "")
        self.assertTrue(location.startswith("https://p1.example.com/authorize"), msg=location)
        qs = parse_qs(urlparse(location).query)
        self.assertEqual((qs.get("scope") or [""])[0], "openid email profile groups")

    def test_oidc_provider_clock_skew_seconds_is_clamped(self):
        from app.utils import OidcAuth

        os.environ["BEACON_OIDC_PROVIDERS_JSON"] = json.dumps(
            {
                "p1": {"clock_skew_seconds": -5},
                "p2": {"clock_skew_seconds": 999999},
                "p3": {"clock_skew_seconds": "bad"},
            },
            ensure_ascii=False,
        )

        self.assertEqual(OidcAuth._get_clock_skew_seconds_for_provider("p1"), 0)
        self.assertEqual(OidcAuth._get_clock_skew_seconds_for_provider("p2"), 3600)
        self.assertEqual(OidcAuth._get_clock_skew_seconds_for_provider("p3"), OidcAuth._get_clock_skew_seconds())

    def test_oidc_provider_jwks_cache_seconds_is_clamped(self):
        from app.utils import OidcAuth

        os.environ["BEACON_OIDC_PROVIDERS_JSON"] = json.dumps(
            {
                "p1": {"jwks_cache_seconds": -1},
                "p2": {"jwks_cache_seconds": 999999},
                "p3": {"jwks_cache_seconds": "bad"},
            },
            ensure_ascii=False,
        )

        self.assertEqual(OidcAuth._get_jwks_cache_seconds_for_provider("p1"), 0)
        self.assertEqual(OidcAuth._get_jwks_cache_seconds_for_provider("p2"), 86400)
        self.assertEqual(
            OidcAuth._get_jwks_cache_seconds_for_provider("p3"),
            OidcAuth._get_jwks_cache_seconds(),
        )

    def test_oidc_callback_can_map_groups_to_staff_and_permissions(self):
        os.environ["BEACON_OIDC_STAFF_GROUPS"] = "beacon_admin"
        os.environ["BEACON_OIDC_SYNC_USER_FLAGS"] = "1"
        os.environ["BEACON_OIDC_SYNC_USER_PERMISSIONS"] = "1"
        os.environ["BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON"] = json.dumps(
            {
                "beacon_viewer": {"streams": True},
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        # This user should NOT become staff (group is viewer), but should get a permission allowlist.
        id_token = _make_fake_jwt(
            {
                "sub": "sub-map-1",
                "email": "map@example.com",
                "preferred_username": "map_user",
                "groups": ["beacon_viewer"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-map", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-map&state={state}")
        self.assertEqual(cb.status_code, 302)

        user = User.objects.filter(username="map_user").first()
        self.assertIsNotNone(user)
        self.assertFalse(bool(getattr(user, "is_staff", False)))

        # streams should be allowed, system should be denied by permission allowlist.
        res_ok = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res_ok.status_code, 200)
        body_ok = json.loads(res_ok.content.decode("utf-8"))
        self.assertEqual(body_ok.get("code"), 1000)

        res_denied = self.client.get("/config/system")
        self.assertEqual(res_denied.status_code, 200)
        self.assertIn("权限不足", res_denied.content.decode("utf-8"))

    def test_oidc_staff_group_matching_is_case_insensitive(self):
        os.environ["BEACON_OIDC_STAFF_GROUPS"] = "BEACON_ADMIN"
        os.environ["BEACON_OIDC_SYNC_USER_FLAGS"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-staff-case-1",
                "email": "staffcase1@example.com",
                "preferred_username": "staff_case_user_1",
                "groups": ["beacon_admin"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-staff-case-1", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-staff-case-1&state={state}")
        self.assertEqual(cb.status_code, 302)

        user = User.objects.filter(username="staff_case_user_1").first()
        self.assertIsNotNone(user)
        self.assertTrue(bool(getattr(user, "is_staff", False)))

    def test_oidc_permission_mapping_group_match_is_case_insensitive(self):
        os.environ["BEACON_OIDC_SYNC_USER_PERMISSIONS"] = "1"
        os.environ["BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON"] = json.dumps(
            {
                "BEACON_VIEWER": {"streams": True},
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-perm-case-1",
                "email": "permcase1@example.com",
                "preferred_username": "perm_case_user_1",
                "groups": ["beacon_viewer"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-perm-case-1", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-perm-case-1&state={state}")
        self.assertEqual(cb.status_code, 302)

        res_ok = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res_ok.status_code, 200)
        body_ok = json.loads(res_ok.content.decode("utf-8"))
        self.assertEqual(body_ok.get("code"), 1000)

    def test_oidc_permission_mapping_accepts_permission_keys_case_insensitive(self):
        os.environ["BEACON_OIDC_SYNC_USER_PERMISSIONS"] = "1"
        os.environ["BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON"] = json.dumps(
            {
                "beacon_viewer": {
                    "STREAMS": True,
                },
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-perm-key-case-1",
                "email": "permkeycase1@example.com",
                "preferred_username": "perm_key_case_user_1",
                "groups": ["beacon_viewer"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-perm-key-case-1", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-perm-key-case-1&state={state}")
        self.assertEqual(cb.status_code, 302)

        res_ok = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res_ok.status_code, 200)
        body_ok = json.loads(res_ok.content.decode("utf-8"))
        self.assertEqual(body_ok.get("code"), 1000)

    def test_oidc_required_groups_matching_is_case_insensitive(self):
        os.environ["BEACON_OIDC_REQUIRED_GROUPS"] = "BEACON_ALLOWED"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-rg-case-1",
                "email": "rgcase1@example.com",
                "preferred_username": "rg_case_user_1",
                "groups": ["beacon_allowed"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-rg-case-1", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-rg-case-1&state={state}")
        self.assertEqual(cb.status_code, 302)

    def test_oidc_permission_sync_drops_unknown_permission_keys(self):
        from app.models import UserPermission

        os.environ["BEACON_OIDC_SYNC_USER_PERMISSIONS"] = "1"
        os.environ["BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON"] = json.dumps(
            {
                "beacon_viewer": {
                    "streams": True,
                    "unknown_feature_x": True,
                },
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-map-2",
                "email": "map2@example.com",
                "preferred_username": "map_user_2",
                "groups": ["beacon_viewer"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-map-2", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-map-2&state={state}")
        self.assertEqual(cb.status_code, 302)

        user = User.objects.filter(username="map_user_2").first()
        self.assertIsNotNone(user)
        perm_obj = UserPermission.objects.filter(user=user).first()
        self.assertIsNotNone(perm_obj)

        loaded = json.loads(str(getattr(perm_obj, "permissions_json", "") or "{}"))
        self.assertTrue(bool(loaded.get("streams")))
        self.assertNotIn("unknown_feature_x", loaded)

    def test_oidc_permission_sync_can_clear_stale_permissions_when_mapped_empty(self):
        from app.models import UserPermission

        existing = User.objects.create_user(username="map_user_3", password="pass12345")
        UserPermission.objects.create(user=existing, permissions_json=json.dumps({"streams": True}, ensure_ascii=False))

        os.environ["BEACON_OIDC_SYNC_USER_PERMISSIONS"] = "1"
        os.environ["BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON"] = json.dumps(
            {
                "beacon_unknown_group": {
                    "unknown_feature_only": True,
                },
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-map-3",
                "email": "map3@example.com",
                "preferred_username": "map_user_3",
                "groups": ["beacon_unknown_group"],
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-map-3", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-map-3&state={state}")
        self.assertEqual(cb.status_code, 302)

        perm_obj = UserPermission.objects.filter(user=existing).first()
        self.assertIsNotNone(perm_obj)
        loaded = json.loads(str(getattr(perm_obj, "permissions_json", "") or "{}"))
        self.assertEqual(loaded, {}, msg=loaded)

    def test_logout_redirects_to_oidc_end_session_when_configured(self):
        os.environ["BEACON_OIDC_END_SESSION_ENDPOINT"] = "https://idp.example.com/logout"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-2",
                "email": "u2_oidc@example.com",
                "preferred_username": "u2_oidc",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-2", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-2&state={state}")
        self.assertEqual(cb.status_code, 302)

        out = self.client.get("/logout")
        self.assertEqual(out.status_code, 302)
        location = str(out.get("Location") or "")
        self.assertTrue(location.startswith("https://idp.example.com/logout"), msg=location)

        logout_qs = parse_qs(urlparse(location).query)
        self.assertEqual(logout_qs.get("id_token_hint"), [id_token])
        self.assertEqual(logout_qs.get("post_logout_redirect_uri"), ["http://testserver/login"])

    def test_oidc_callback_rejects_unverified_id_token_by_default(self):

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_unverified_jwt(
            {
                "sub": "sub-default-secure",
                "email": "default-secure@example.com",
                "preferred_username": "default_secure",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "exp": int(time.time()) + 3600,
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-default", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-default&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("invalid id_token", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_rejects_unverified_id_token_when_env_disables_verification(self):
        os.environ["BEACON_OIDC_" + "VERIFY_ID_TOKEN"] = "0"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_unverified_jwt(
            {
                "sub": "sub-env-disable",
                "email": "env-disable@example.com",
                "preferred_username": "env_disable",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "exp": int(time.time()) + 3600,
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-env-disable", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-env-disable&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("invalid id_token", cb.content.decode("utf-8", errors="ignore"))
        self.assertFalse(User.objects.filter(username="env_disable").exists())

    def test_oidc_callback_rejects_unverified_id_token_when_provider_disables_verification(self):
        os.environ["BEACON_OIDC_PROVIDERS_JSON"] = json.dumps(
            {
                "p1": {
                    "client_id": "cid_test",
                    "client_secret": "sec_test",
                    "authorization_endpoint": "https://idp.example.com/authorize",
                    "token_endpoint": "https://idp.example.com/token",
                    "scope": "openid email profile",
                    "verify_" + "id_token": False,
                }
            },
            ensure_ascii=False,
        )

        start = self.client.get("/login/oidc/start?provider=p1")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_unverified_jwt(
            {
                "sub": "sub-provider-disable",
                "email": "provider-disable@example.com",
                "preferred_username": "provider_disable",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "exp": int(time.time()) + 3600,
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with mock.patch("requests.post", return_value=FakeResp({"access_token": "at-provider-disable", "id_token": id_token, "token_type": "Bearer"})):
            cb = self.client.get(f"/login/oidc/callback?code=code-provider-disable&state={state}&provider=p1")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("invalid id_token", cb.content.decode("utf-8", errors="ignore"))
        self.assertFalse(User.objects.filter(username="provider_disable").exists())

    def test_oidc_callback_rejects_alg_none_when_verification_enabled(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        # Under strict verification, alg=none must be rejected.
        id_token = _make_unverified_jwt(
            {
                "sub": "sub-bad",
                "email": "bad@example.com",
                "preferred_username": "bad",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "exp": int(time.time()) + 3600,
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-bad", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp({"keys": []})),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-bad&state={state}")
        self.assertEqual(cb.status_code, 400)

    def test_oidc_callback_rejects_rs256_id_token_without_exp_by_default(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-no-exp-default"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-no-exp-default")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-no-exp-default",
                "email": "no-exp-default@example.com",
                "preferred_username": "no_exp_default",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
            },
            kid="k-no-exp-default",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-no-exp-default", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-no-exp-default&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_exp_missing", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_accepts_rs256_id_token_without_exp_when_disabled(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-no-exp-optional"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"
        os.environ["BEACON_OIDC_REQUIRE_EXP"] = "0"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-no-exp-optional")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-no-exp-optional",
                "email": "no-exp-optional@example.com",
                "preferred_username": "no_exp_optional",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
            },
            kid="k-no-exp-optional",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-no-exp-optional", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-no-exp-optional&state={state}")

        self.assertEqual(cb.status_code, 302, msg=cb.content)
        user = User.objects.filter(username="no_exp_optional").first()
        self.assertIsNotNone(user)

    def test_oidc_callback_accepts_valid_rs256_id_token_when_verification_enabled(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        # Smaller key size for test speed.
        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k1")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-good",
                "email": "good@example.com",
                "preferred_username": "good",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "exp": int(time.time()) + 3600,
            },
            kid="k1",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        def fake_get(url, headers=None, timeout=None, **kwargs):
            self.assertEqual(url, "https://idp.example.com/jwks")
            return FakeResp(jwks)

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-good", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", side_effect=fake_get),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-good&state={state}")

        self.assertEqual(cb.status_code, 302)
        self.assertEqual(cb.get("Location"), "/")

        user = User.objects.filter(username="good").first()
        self.assertIsNotNone(user)
        self.assertEqual(str(getattr(user, "email", "") or ""), "good@example.com")

    def test_oidc_callback_rejects_rs256_id_token_with_future_nbf(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-nbf"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"
        os.environ["BEACON_OIDC_CLOCK_SKEW_SECONDS"] = "0"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k2")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-nbf",
                "email": "nbf@example.com",
                "preferred_username": "nbf_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "nbf": int(time.time()) + 180,
                "exp": int(time.time()) + 3600,
            },
            kid="k2",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-nbf", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-nbf&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_not_yet_valid", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_rejects_rs256_id_token_when_nbf_after_exp(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-nbf-exp"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-nbf-exp")
        now_ts = int(time.time())

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-nbf-exp",
                "email": "nbf-exp@example.com",
                "preferred_username": "nbf_exp_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "nbf": now_ts + 120,
                "exp": now_ts + 60,
            },
            kid="k-nbf-exp",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-nbf-exp", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-nbf-exp&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_nbf_after_exp", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_rejects_rs256_id_token_with_future_iat(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-iat"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"
        os.environ["BEACON_OIDC_CLOCK_SKEW_SECONDS"] = "0"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k3")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-iat",
                "email": "iat@example.com",
                "preferred_username": "iat_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "iat": int(time.time()) + 180,
                "exp": int(time.time()) + 3600,
            },
            kid="k3",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-iat", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-iat&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_issued_in_future", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_rejects_rs256_id_token_when_iat_after_exp(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-iat-exp"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-iat-exp")
        now_ts = int(time.time())

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-iat-exp",
                "email": "iat-exp@example.com",
                "preferred_username": "iat_exp_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "iat": now_ts + 120,
                "exp": now_ts + 60,
            },
            kid="k-iat-exp",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-iat-exp", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-iat-exp&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_iat_after_exp", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_rejects_rs256_id_token_when_older_than_max_age(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-iat-age"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"
        os.environ["BEACON_OIDC_CLOCK_SKEW_SECONDS"] = "0"
        os.environ["BEACON_OIDC_MAX_TOKEN_AGE_SECONDS"] = "60"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-iat-age")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-iat-age",
                "email": "iat-age@example.com",
                "preferred_username": "iat_age_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "iat": int(time.time()) - 120,
                "exp": int(time.time()) + 3600,
            },
            kid="k-iat-age",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-iat-age", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-iat-age&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_too_old", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_rejects_rs256_id_token_without_iat_when_max_age_enabled(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-iat-required"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"
        os.environ["BEACON_OIDC_MAX_TOKEN_AGE_SECONDS"] = "60"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-iat-required")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-iat-required",
                "email": "iat-required@example.com",
                "preferred_username": "iat_required_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "exp": int(time.time()) + 3600,
            },
            kid="k-iat-required",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-iat-required", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-iat-required&state={state}")

        self.assertEqual(cb.status_code, 400, msg=cb.content)
        self.assertIn("jwt_iat_missing_for_max_age", cb.content.decode("utf-8", errors="ignore"))

    def test_oidc_callback_accepts_rs256_id_token_without_iat_when_override_disabled(self):
        os.environ["BEACON_OIDC_JWKS_URI"] = "https://idp.example.com/jwks-iat-optional"
        os.environ["BEACON_OIDC_ISSUER"] = "https://idp.example.com/"
        os.environ["BEACON_OIDC_REQUIRE_NONCE"] = "1"
        os.environ["BEACON_OIDC_MAX_TOKEN_AGE_SECONDS"] = "60"
        os.environ["BEACON_OIDC_REQUIRE_IAT_WHEN_MAX_AGE"] = "0"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)
        nonce = str(self.client.session.get("oidc_nonce") or "")
        self.assertTrue(nonce)

        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        jwks = _jwks_from_public_key(priv.public_key(), kid="k-iat-optional")

        id_token = _make_rs256_jwt(
            {
                "sub": "sub-iat-optional",
                "email": "iat-optional@example.com",
                "preferred_username": "iat_optional_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "nonce": nonce,
                "exp": int(time.time()) + 3600,
            },
            kid="k-iat-optional",
            private_key=priv,
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-iat-optional", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", return_value=FakeResp(jwks)),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-iat-optional&state={state}")

        self.assertEqual(cb.status_code, 302, msg=cb.content)
        user = User.objects.filter(username="iat_optional_user").first()
        self.assertIsNotNone(user)

    def test_oidc_callback_can_use_userinfo_to_fill_email_when_enabled(self):
        os.environ["BEACON_OIDC_USERINFO_ENDPOINT"] = "https://idp.example.com/userinfo"
        os.environ["BEACON_OIDC_USERINFO_ENABLED"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-ui",
                "preferred_username": "ui_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "exp": int(time.time()) + 3600,
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        def fake_get(url, headers=None, timeout=None, **kwargs):
            self.assertEqual(url, "https://idp.example.com/userinfo")
            self.assertTrue(str((headers or {}).get("Authorization") or "").startswith("Bearer "))
            return FakeResp({"email": "ui_user@example.com"})

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-ui", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", side_effect=fake_get),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-ui&state={state}")

        self.assertEqual(cb.status_code, 302)
        user = User.objects.filter(username="ui_user").first()
        self.assertIsNotNone(user)
        self.assertEqual(str(getattr(user, "email", "") or ""), "ui_user@example.com")

    def test_oidc_callback_userinfo_empty_identity_does_not_override_id_token(self):
        os.environ["BEACON_OIDC_USERINFO_ENDPOINT"] = "https://idp.example.com/userinfo"
        os.environ["BEACON_OIDC_USERINFO_ENABLED"] = "1"

        start = self.client.get("/login/oidc/start")
        self.assertEqual(start.status_code, 302)
        qs = parse_qs(urlparse(str(start.get("Location") or "")).query)
        state = (qs.get("state") or [""])[0]
        self.assertTrue(state)

        id_token = _make_fake_jwt(
            {
                "sub": "sub-ui-keep",
                "email": "keep@example.com",
                "preferred_username": "ui_keep_user",
                "iss": "https://idp.example.com/",
                "aud": "cid_test",
                "exp": int(time.time()) + 3600,
            }
        )

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        def fake_get(url, headers=None, timeout=None, **kwargs):
            self.assertEqual(url, "https://idp.example.com/userinfo")
            self.assertTrue(str((headers or {}).get("Authorization") or "").startswith("Bearer "))
            return FakeResp({"sub": "", "preferred_username": "", "email": "ui_keep_user@example.com"})

        with (
            mock.patch("requests.post", return_value=FakeResp({"access_token": "at-ui-keep", "id_token": id_token, "token_type": "Bearer"})),
            mock.patch("requests.get", side_effect=fake_get),
        ):
            cb = self.client.get(f"/login/oidc/callback?code=code-ui-keep&state={state}")

        self.assertEqual(cb.status_code, 302, msg=cb.content)
        user = User.objects.filter(username="ui_keep_user").first()
        self.assertIsNotNone(user)
        self.assertEqual(str(getattr(user, "email", "") or ""), "ui_keep_user@example.com")

    def test_oidc_group_parser_accepts_standard_claim_shapes_only(self):
        from app.utils import OidcAuth

        groups = OidcAuth.extract_groups_from_claims(
            {
                "groups": ["viewer"],
                "realm_access": {"roles": ["operator"]},
                "resource_access": {"beacon": {"roles": ["admin"]}},
                "roles": '["serialized-role"]',
                "GROUPS": ["wrong-case"],
            }
        )

        self.assertEqual(groups, ["viewer", '["serialized-role"]', "operator", "admin"])
        self.assertEqual(OidcAuth._csv_set("viewer,operator"), {"viewer", "operator"})
        self.assertEqual(OidcAuth._csv_set("viewer|operator"), {"viewer|operator"})
