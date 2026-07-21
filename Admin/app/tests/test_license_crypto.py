import base64
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from django.test import TestCase


class LicenseCryptoTest(TestCase):
    def _build_signed_license(
        self,
        *,
        cluster_id: str,
        not_after: datetime,
        package_limits: Optional[dict] = None,
        edition: str = "",
        thread_priority_policy: Optional[dict] = None,
    ):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        pub_b64 = base64.b64encode(pub_bytes).decode("ascii")

        payload = {
            "license_id": "LIC-TEST-001",
            "customer": "TEST",
            "cluster_id": cluster_id,
            "issued_at": "2026-02-17T00:00:00Z",
            "not_before": "2026-02-17T00:00:00Z",
            "not_after": not_after.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limits": {
                "max_active_controls": 2,
                "max_nodes": 1,
            },
            "packages": ["core"],
        }
        if package_limits is not None:
            payload["package_limits"] = package_limits
        if edition:
            payload["edition"] = edition
        if thread_priority_policy is not None:
            payload["thread_priority_policy"] = thread_priority_policy

        # The LicenseManager canonicalization must match this.
        message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sig = private_key.sign(message)

        payload["signature"] = {
            "alg": "ed25519",
            "kid": "test",
            "sig": base64.b64encode(sig).decode("ascii"),
        }
        return payload, pub_b64

    def test_missing_signature_rejected(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
        )
        payload.pop("signature", None)

        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "missing_signature")

    def test_bad_signature_base64_rejected(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
        )
        payload["signature"]["sig"] = "not_base64!!!"

        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "bad_signature")

    def test_cluster_mismatch_rejected(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
        )
        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-2")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "cluster_mismatch")

    def test_expired_license_rejected(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "license_expired")

    def test_valid_license_ok(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
        )
        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertTrue(result["ok"])

    def test_package_limits_parsed(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
            package_limits={"ppe": {"max_active_controls": 5}},
        )

        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("package_limits"), {"ppe": {"max_active_controls": 5}})

    def test_ordinary_edition_defaults_thread_priority_policy(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
            edition="ordinary",
        )

        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("edition"), "ordinary")
        self.assertEqual(
            result.get("thread_priority_policy"),
            {"enabled": True, "first_n_active_streams": 20, "nice_value": -5},
        )

    def test_non_ordinary_defaults_disabled_without_explicit_policy(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
            edition="advanced",
        )

        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("edition"), "advanced")
        self.assertEqual(
            result.get("thread_priority_policy"),
            {"enabled": False, "first_n_active_streams": 0, "nice_value": 0},
        )

    def test_explicit_thread_priority_policy_is_sanitized(self):
        from app.utils.LicenseManager import validate_license_payload

        payload, pub_b64 = self._build_signed_license(
            cluster_id="cluster-1",
            not_after=datetime.now(timezone.utc) + timedelta(days=1),
            edition="advanced",
            thread_priority_policy={
                "enabled": "yes",
                "first_n_active_streams": "2048",
                "nice_value": "-99",
            },
        )

        result = validate_license_payload(payload, public_key_b64=pub_b64, expected_cluster_id="cluster-1")
        self.assertTrue(result["ok"])
        self.assertEqual(
            result.get("thread_priority_policy"),
            {"enabled": True, "first_n_active_streams": 1024, "nice_value": -20},
        )
