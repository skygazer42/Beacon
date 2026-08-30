import hashlib
import hmac
import os
from unittest import TestCase, mock

from app.utils.ApiKeyHash import hash_api_key_token, legacy_hash_api_key_token
from app.utils.OutboundUrl import OutboundUrlError, validate_outbound_http_url
from app.utils.SafeLog import safe_json_dumps, safe_log_text
from app.utils.Security import resolve_direct_child, resolve_under_base
from app.views.api import _sanitize_stream_code_for_path
from app.views.AlarmView import _safe_alarm_redirect_target


def _resolved(address: str, port: int = 443):
    family = 10 if ":" in address else 2
    return [(family, 1, 6, "", (address, port))]


class OutboundUrlSecurityTests(TestCase):
    @mock.patch("app.utils.OutboundUrl.socket.getaddrinfo", return_value=_resolved("93.184.216.34"))
    def test_public_http_url_is_canonicalized(self, _getaddrinfo):
        self.assertEqual(
            validate_outbound_http_url(" HTTPS://Example.COM:443/infer?q=1 "),
            "https://example.com/infer?q=1",
        )

    def test_private_and_metadata_addresses_are_rejected_by_default(self):
        with self.assertRaises(OutboundUrlError):
            validate_outbound_http_url("http://10.0.0.2/infer")
        with self.assertRaises(OutboundUrlError):
            validate_outbound_http_url("http://169.254.169.254/latest/meta-data")

    def test_explicit_host_allows_private_address_but_not_metadata(self):
        with mock.patch.dict(os.environ, {"BEACON_TEST_ALLOWED_HOSTS": "edge.internal"}, clear=False):
            with mock.patch("app.utils.OutboundUrl.socket.getaddrinfo", return_value=_resolved("10.2.3.4", 80)):
                self.assertEqual(
                    validate_outbound_http_url(
                        "http://edge.internal/api",
                        allowed_hosts_env="BEACON_TEST_ALLOWED_HOSTS",
                    ),
                    "http://edge.internal/api",
                )
            with mock.patch("app.utils.OutboundUrl.socket.getaddrinfo", return_value=_resolved("169.254.169.254", 80)):
                with self.assertRaises(OutboundUrlError):
                    validate_outbound_http_url(
                        "http://edge.internal/api",
                        allowed_hosts_env="BEACON_TEST_ALLOWED_HOSTS",
                    )

    def test_loopback_requires_an_explicit_allowlist(self):
        with self.assertRaises(OutboundUrlError):
            validate_outbound_http_url("http://127.0.0.1:9000/infer")
        with mock.patch.dict(os.environ, {"BEACON_TEST_ALLOWED_HOSTS": "127.0.0.1"}, clear=False):
            self.assertEqual(
                validate_outbound_http_url(
                    "http://127.0.0.1:9000/infer",
                    allowed_hosts_env="BEACON_TEST_ALLOWED_HOSTS",
                ),
                "http://127.0.0.1:9000/infer",
            )

    def test_expected_onvif_host_cannot_pivot(self):
        self.assertEqual(
            validate_outbound_http_url("http://192.168.1.20/onvif/media", expected_host="192.168.1.20"),
            "http://192.168.1.20/onvif/media",
        )
        with self.assertRaises(OutboundUrlError):
            validate_outbound_http_url("http://192.168.1.21/onvif/media", expected_host="192.168.1.20")

    def test_credentials_controls_and_loopback_are_rejected(self):
        for value in (
            "https://user:pass@example.com/path",
            "https://example.com\\@evil.test/path",
            "https://example.com/path\nX-Test: injected",
            "https://example.com/path#fragment",
            "http://127.0.0.1/admin",
        ):
            with self.subTest(value=value), self.assertRaises(OutboundUrlError):
                validate_outbound_http_url(value)

    def test_entire_address_space_allowlist_and_mapped_metadata_are_rejected(self):
        with mock.patch.dict(os.environ, {"BEACON_TEST_ALLOWED_CIDRS": "0.0.0.0/0"}, clear=False):
            with self.assertRaises(OutboundUrlError):
                validate_outbound_http_url(
                    "http://10.0.0.2/infer",
                    allowed_cidrs_env="BEACON_TEST_ALLOWED_CIDRS",
                )
        with self.assertRaises(OutboundUrlError):
            validate_outbound_http_url("http://[::ffff:169.254.169.254]/latest/meta-data")


class SecurityPrimitiveTests(TestCase):
    def test_api_key_digest_is_keyed_and_legacy_digest_remains_available(self):
        with mock.patch.dict(os.environ, {"BEACON_API_KEY_PEPPER": "pepper"}, clear=False):
            current = hash_api_key_token("token")
            legacy = legacy_hash_api_key_token("token")
        self.assertEqual(current, hmac.new(b"pepper", b"token", hashlib.sha256).hexdigest())
        self.assertEqual(legacy, hashlib.sha256(b"peppertoken").hexdigest())
        self.assertNotEqual(current, legacy)

    def test_log_values_are_single_line_and_redacted(self):
        self.assertEqual(safe_log_text("alpha\r\nbeta\x00"), "alpha\\r\\nbeta\\x00")
        preview = safe_json_dumps({"password": "secret\nvalue", "name": "a\nb"})
        self.assertNotIn("secret", preview)
        self.assertNotIn("\n", preview)
        self.assertIn("\\\\n", preview)

    def test_direct_child_rejects_path_components(self):
        base = os.path.abspath("/tmp/beacon-security-test")
        self.assertEqual(resolve_direct_child(base, "camera-01"), os.path.join(base, "camera-01"))
        for value in ("", ".", "..", "../escape", "nested/name", "bad\\name", "x" * 256):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_direct_child(base, value)
        with self.assertRaisesRegex(ValueError, "base_dir is required"):
            resolve_under_base("", "camera-01")

    def test_recording_stream_code_is_reduced_to_one_safe_component(self):
        self.assertEqual(_sanitize_stream_code_for_path("camera/../一号"), "camera____一号")
        self.assertEqual(_sanitize_stream_code_for_path("x" * 129), "")

    def test_alarm_redirects_are_strictly_local(self):
        fallback = "/alarms"
        self.assertEqual(_safe_alarm_redirect_target("/alarm/review?p=1", fallback=fallback), "/alarm/review?p=1")
        for value in ("https://evil.example", "//evil.example", "/\\evil.example", "/ok\nLocation: evil"):
            with self.subTest(value=value):
                self.assertEqual(_safe_alarm_redirect_target(value, fallback=fallback), fallback)
