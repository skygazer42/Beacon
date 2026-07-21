import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from app.models import LicenseState
from app.views import LicenseView


class LicenseImportPageTest(TestCase):
    def _login(self):
        session = self.client.session
        session["user"] = {"id": 1, "username": "tester"}
        session.save()

    def _build_signed_license_bytes(self, *, cluster_id: str, package_limits: Optional[dict] = None) -> Tuple[bytes, str]:
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
            "license_id": "LIC-TEST-IMPORT-001",
            "customer": "TEST",
            "cluster_id": cluster_id,
            "issued_at": "2026-02-21T00:00:00Z",
            "not_before": "2026-02-21T00:00:00Z",
            "not_after": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limits": {"max_active_controls": 10, "max_nodes": 10},
            "packages": ["core", "ppe"],
        }
        if package_limits is not None:
            payload["package_limits"] = package_limits

        message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sig = private_key.sign(message)
        payload["signature"] = {"alg": "ed25519", "kid": "test", "sig": base64.b64encode(sig).decode("ascii")}

        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return raw, pub_b64

    def test_requires_login(self):
        resp = self.client.get("/license/manager")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith("/login"))

    def test_get_ok_when_logged_in(self):
        self._login()
        resp = self.client.get("/license/manager")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8", errors="ignore")
        self.assertIn("授权管理", content)

    def test_app_shell_upload_reports_malformed_json(self):
        self._login()
        bad = SimpleUploadedFile("license.json", b"not json", content_type="application/json")

        response = self.client.post("/api/app-shell/license/upload", data={"file": bad})
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertEqual(payload["data"]["license_error"]["code"], "malformed_json")

    def test_validate_uploaded_license_payload_reports_missing_public_key(self):
        raw, _pub_b64 = self._build_signed_license_bytes(cluster_id="cluster-1")
        payload = json.loads(raw.decode("utf-8"))

        os.environ["BEACON_CLUSTER_ID"] = "cluster-1"
        os.environ.pop("BEACON_LICENSE_PUBLIC_KEY_B64", None)

        outcome = LicenseView._validate_uploaded_license_payload(payload)

        self.assertEqual(outcome["result"].get("error_code"), "missing_public_key")
        self.assertEqual(outcome["expected_cluster_id"], "cluster-1")
        self.assertFalse(outcome["public_key_configured"])

    def test_parse_uploaded_license_accepts_empty_json_object(self):
        upload = SimpleUploadedFile("license.json", b"{}", content_type="application/json")

        parsed = LicenseView._parse_uploaded_license(upload)

        self.assertEqual(parsed["payload"], {})
        self.assertEqual(parsed["top_msg"], "")
        self.assertIsNone(parsed["license_error"])

    def test_post_valid_license_persists_package_limits(self):
        self._login()

        raw, pub_b64 = self._build_signed_license_bytes(
            cluster_id="cluster-1",
            package_limits={"ppe": {"max_active_controls": 5}},
        )

        os.environ["BEACON_CLUSTER_ID"] = "cluster-1"
        os.environ["BEACON_LICENSE_PUBLIC_KEY_B64"] = pub_b64

        upload = SimpleUploadedFile("license.json", raw, content_type="application/json")
        resp = self.client.post("/license/manager", data={"file": upload})
        self.assertEqual(resp.status_code, 200)

        state = LicenseState.objects.order_by("-update_time", "-id").first()
        self.assertIsNotNone(state)
        # 新增字段：用于按算法包独立路数上限
        self.assertEqual(json.loads(getattr(state, "package_limits_json")), {"ppe": {"max_active_controls": 5}})

    def test_app_shell_upload_reports_missing_public_key(self):
        self._login()

        raw, _pub_b64 = self._build_signed_license_bytes(cluster_id="cluster-1")

        os.environ["BEACON_CLUSTER_ID"] = "cluster-1"
        os.environ.pop("BEACON_LICENSE_PUBLIC_KEY_B64", None)

        upload = SimpleUploadedFile("license.json", raw, content_type="application/json")
        resp = self.client.post("/api/app-shell/license/upload", data={"file": upload})
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content.decode("utf-8"))
        error = (payload.get("data") or {}).get("license_error") or {}
        self.assertEqual(error.get("code"), "missing_public_key")
        self.assertEqual(error.get("expected_cluster_id"), "cluster-1")
        self.assertEqual(error.get("public_key_status"), "未配置")

    def test_get_shows_persisted_cluster_mismatch_details(self):
        self._login()

        raw, pub_b64 = self._build_signed_license_bytes(cluster_id="cluster-a")

        os.environ["BEACON_CLUSTER_ID"] = "cluster-b"
        os.environ["BEACON_LICENSE_PUBLIC_KEY_B64"] = pub_b64

        upload = SimpleUploadedFile("license.json", raw, content_type="application/json")
        post_resp = self.client.post("/api/app-shell/license/upload", data={"file": upload})
        self.assertEqual(post_resp.status_code, 200)

        resp = self.client.get("/api/app-shell/license")
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content.decode("utf-8"))
        error = (payload.get("data") or {}).get("license_error") or {}
        self.assertEqual(error.get("code"), "cluster_mismatch")
        self.assertEqual(error.get("uploaded_cluster_id"), "cluster-a")
        self.assertEqual(error.get("expected_cluster_id"), "cluster-b")
