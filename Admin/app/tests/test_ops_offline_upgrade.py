import io
import base64
import json
import os
import tempfile
import zipfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.views import OpsUpgradeView
from framework.settings import PROJECT_VERSION


class OpsOfflineUpgradeTest(TestCase):
    def _make_zip(self, manifest: dict, extra_files: dict = None, signing_key=None) -> bytes:
        buf = io.BytesIO()
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            if signing_key is not None:
                zf.writestr("manifest.sig", base64.b64encode(signing_key.sign(manifest_bytes)).decode("ascii") + "\n")
            for name, content in (extra_files or {}).items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_manifest_signature_is_required_and_verified_when_configured(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        manifest = {
            "package_id": "pkg-signed",
            "target_version": PROJECT_VERSION,
            "compatible": {"min_version": PROJECT_VERSION, "max_version": PROJECT_VERSION},
            "files": {},
        }

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "BEACON_UPGRADE_REQUIRE_SIGNATURE": "1",
                "BEACON_UPGRADE_ED25519_PUBLIC_KEY": base64.b64encode(public_key).decode("ascii"),
            },
            clear=False,
        ):
            unsigned_path = os.path.join(temp_dir, "unsigned.zip")
            with open(unsigned_path, "wb") as handle:
                handle.write(self._make_zip(manifest))
            self.assertEqual(
                OpsUpgradeView._load_manifest_from_zip(unsigned_path)[:2],
                (False, "package signature is required"),
            )

            signed_path = os.path.join(temp_dir, "signed.zip")
            with open(signed_path, "wb") as handle:
                handle.write(self._make_zip(manifest, signing_key=private_key))
            ok, message, loaded_manifest = OpsUpgradeView._load_manifest_from_zip(signed_path)
            self.assertTrue(ok, msg=message)
            self.assertEqual(loaded_manifest, manifest)

            bad_manifest = dict(manifest)
            bad_manifest["files"] = {"Admin/app.bin": "0" * 64}
            bad_path = os.path.join(temp_dir, "bad-payload.zip")
            with open(bad_path, "wb") as handle:
                handle.write(
                    self._make_zip(
                        bad_manifest,
                        extra_files={"Admin/app.bin": b"tampered"},
                        signing_key=private_key,
                    )
                )
            self.assertEqual(
                OpsUpgradeView._load_manifest_from_zip(bad_path)[:2],
                (False, "signed package payload digest verification failed"),
            )

    def test_manifest_and_upload_size_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            oversized_manifest_path = os.path.join(temp_dir, "oversized-manifest.zip")
            with zipfile.ZipFile(oversized_manifest_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    b"{" + b" " * OpsUpgradeView.MAX_UPGRADE_MANIFEST_BYTES + b"}",
                )
            self.assertEqual(
                OpsUpgradeView._load_manifest_from_zip(oversized_manifest_path)[:2],
                (False, "manifest.json is too large"),
            )

        with tempfile.TemporaryDirectory() as root_dir, mock.patch.dict(
            os.environ,
            {
                "BEACON_ROOT_DIR": root_dir,
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_UPGRADE_REQUIRE_SIGNATURE": "0",
                "BEACON_UPGRADE_UPLOAD_MAX_BYTES": "32",
            },
            clear=False,
        ):
            response = self.client.post(
                "/open/ops/upgrade/upload",
                data={"file": SimpleUploadedFile("large.zip", b"x" * 33, content_type="application/zip")},
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN="t1",
            )
            self.assertEqual(response.status_code, 413, msg=response.content)
            self.assertEqual(json.loads(response.content.decode("utf-8"))["msg"], "upgrade package is too large")

    def test_validate_reverifies_package_instead_of_trusting_cached_manifest(self):
        with tempfile.TemporaryDirectory() as root_dir, mock.patch.dict(
            os.environ,
            {
                "BEACON_ROOT_DIR": root_dir,
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_UPGRADE_REQUIRE_SIGNATURE": "0",
            },
            clear=False,
        ):
            package = self._make_zip(
                {
                    "package_id": "pkg-reverify",
                    "target_version": PROJECT_VERSION,
                    "compatible": {"min_version": PROJECT_VERSION, "max_version": PROJECT_VERSION},
                }
            )
            upload_response = self.client.post(
                "/open/ops/upgrade/upload",
                data={"file": SimpleUploadedFile("upgrade.zip", package, content_type="application/zip")},
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN="t1",
            )
            self.assertEqual(upload_response.status_code, 200, msg=upload_response.content)
            package_id = json.loads(upload_response.content.decode("utf-8"))["data"]["package_id"]
            with open(OpsUpgradeView._zip_path(package_id), "wb") as handle:
                handle.write(b"tampered")

            validate_response = self.client.get(
                f"/open/ops/upgrade/validate?package_id={package_id}",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN="t1",
            )

            self.assertEqual(validate_response.status_code, 400, msg=validate_response.content)
            self.assertEqual(json.loads(validate_response.content.decode("utf-8"))["msg"], "invalid zip file")

    def test_safe_extract_enforces_limits_and_rejects_traversal(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_UPGRADE_EXTRACT_MAX_FILES": "bad",
                "BEACON_UPGRADE_EXTRACT_MAX_TOTAL_BYTES": "0",
                "BEACON_UPGRADE_EXTRACT_MAX_FILE_BYTES": str(100 * 1024 * 1024 * 1024),
            },
            clear=False,
        ):
            limits = OpsUpgradeView._get_extract_limits()

        self.assertEqual(limits["max_files"], 5000)
        self.assertEqual(limits["max_total_bytes"], 1)
        self.assertEqual(limits["max_file_bytes"], 50 * 1024 * 1024 * 1024)

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "package.zip")
            extract_dir = os.path.join(temp_dir, "extract")
            with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("Admin/", "")
                archive.writestr("Admin/README.txt", "hello")
                archive.writestr("../bad.txt", "bad")

            result = OpsUpgradeView._extract_zip_safely(zip_path, extract_dir)

            self.assertEqual(result["extracted_files"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertTrue(os.path.exists(os.path.join(extract_dir, "Admin", "README.txt")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "bad.txt")))

    def test_offline_upgrade_roundtrip_upload_validate_apply_rollback(self):
        """
        Roadmap #90: 离线升级包：上传/校验/应用/回滚

        最小闭环：
        - 上传 zip（内含 manifest.json）
        - 校验兼容范围
        - apply 会把包解压到 staging 并记录 state
        - rollback 会回到上一个 state（或清空 applied）
        """
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "BEACON_ROOT_DIR": tmp,
                    "BEACON_OPEN_API_TOKEN": "t1",
                },
                clear=False,
            ):
                # Package A (compatible)
                zip_a = self._make_zip(
                    {
                        "package_id": "pkg-a",
                        "target_version": "4.22.1",
                        "compatible": {"min_version": PROJECT_VERSION, "max_version": PROJECT_VERSION},
                        "components": ["admin"],
                    },
                    extra_files={"Admin/README.txt": "hello"},
                )
                upload_a = SimpleUploadedFile("upgrade_a.zip", zip_a, content_type="application/zip")
                res_a = self.client.post(
                    "/open/ops/upgrade/upload",
                    data={"file": upload_a},
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(res_a.status_code, 200, msg=res_a.content[:2000])
                body_a = json.loads(res_a.content.decode("utf-8"))
                self.assertEqual(body_a.get("code"), 1000, msg=body_a)
                pkg_a = (body_a.get("data") or {}).get("package_id")
                self.assertTrue(str(pkg_a or "").strip())

                # Package B (compatible)
                zip_b = self._make_zip(
                    {
                        "package_id": "pkg-b",
                        "target_version": "4.22.2",
                        "compatible": {"min_version": PROJECT_VERSION, "max_version": PROJECT_VERSION},
                        "components": ["admin"],
                    },
                    extra_files={"Admin/README.txt": "world"},
                )
                upload_b = SimpleUploadedFile("upgrade_b.zip", zip_b, content_type="application/zip")
                res_b = self.client.post(
                    "/open/ops/upgrade/upload",
                    data={"file": upload_b},
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(res_b.status_code, 200, msg=res_b.content[:2000])
                body_b = json.loads(res_b.content.decode("utf-8"))
                self.assertEqual(body_b.get("code"), 1000, msg=body_b)
                pkg_b = (body_b.get("data") or {}).get("package_id")
                self.assertTrue(str(pkg_b or "").strip())

                # validate B
                v = self.client.get(
                    f"/open/ops/upgrade/validate?package_id={pkg_b}",
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(v.status_code, 200, msg=v.content[:2000])
                v_body = json.loads(v.content.decode("utf-8"))
                self.assertEqual(v_body.get("code"), 1000, msg=v_body)
                self.assertTrue(((v_body.get("data") or {}).get("ok")) is True, msg=v_body)

                # apply A then apply B (so rollback returns to A)
                a1 = self.client.post(
                    "/open/ops/upgrade/apply",
                    data=json.dumps({"package_id": pkg_a}),
                    content_type="application/json",
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(a1.status_code, 200, msg=a1.content[:2000])
                a1_body = json.loads(a1.content.decode("utf-8"))
                self.assertEqual(a1_body.get("code"), 1000, msg=a1_body)

                a2 = self.client.post(
                    "/open/ops/upgrade/apply",
                    data=json.dumps({"package_id": pkg_b}),
                    content_type="application/json",
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(a2.status_code, 200, msg=a2.content[:2000])
                a2_body = json.loads(a2.content.decode("utf-8"))
                self.assertEqual(a2_body.get("code"), 1000, msg=a2_body)

                if os.name != "nt":
                    package_dir = os.path.join(tmp, "upgrade", "packages", pkg_b)
                    stage_dir = os.path.join(tmp, "upgrade", "staging", pkg_b)
                    self.assertEqual(os.stat(package_dir).st_mode & 0o777, 0o700)
                    self.assertEqual(os.stat(os.path.join(package_dir, "package.zip")).st_mode & 0o777, 0o600)
                    self.assertEqual(os.stat(os.path.join(package_dir, "meta.json")).st_mode & 0o777, 0o600)
                    self.assertEqual(os.stat(stage_dir).st_mode & 0o777, 0o700)
                    self.assertEqual(os.stat(os.path.join(stage_dir, "Admin", "README.txt")).st_mode & 0o777, 0o600)
                    self.assertEqual(os.stat(os.path.join(tmp, "upgrade", "state.json")).st_mode & 0o777, 0o600)

                # rollback should go back to pkg_a
                rb = self.client.post(
                    "/open/ops/upgrade/rollback",
                    data=json.dumps({}),
                    content_type="application/json",
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(rb.status_code, 200, msg=rb.content[:2000])
                rb_body = json.loads(rb.content.decode("utf-8"))
                self.assertEqual(rb_body.get("code"), 1000, msg=rb_body)
                self.assertEqual(((rb_body.get("data") or {}).get("applied_package_id")), pkg_a, msg=rb_body)

    def test_upgrade_validate_rejects_incompatible_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "BEACON_ROOT_DIR": tmp,
                    "BEACON_OPEN_API_TOKEN": "t1",
                },
                clear=False,
            ):
                zip_bytes = self._make_zip(
                    {
                        "package_id": "pkg-bad",
                        "target_version": "9.9.9",
                        # incompatible: current version is below 9.x.
                        "compatible": {"min_version": "9.0.0", "max_version": "9.9.9"},
                    }
                )
                upload = SimpleUploadedFile("bad.zip", zip_bytes, content_type="application/zip")
                res = self.client.post(
                    "/open/ops/upgrade/upload",
                    data={"file": upload},
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(res.status_code, 200, msg=res.content[:2000])
                body = json.loads(res.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 1000, msg=body)
                pkg_id = (body.get("data") or {}).get("package_id")

                v = self.client.get(
                    f"/open/ops/upgrade/validate?package_id={pkg_id}",
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )
                self.assertEqual(v.status_code, 200, msg=v.content[:2000])
                v_body = json.loads(v.content.decode("utf-8"))
                self.assertEqual(v_body.get("code"), 1000, msg=v_body)
                self.assertFalse(((v_body.get("data") or {}).get("ok")) is True, msg=v_body)

    def test_upgrade_validate_missing_package_returns_sanitized_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "BEACON_ROOT_DIR": tmp,
                    "BEACON_OPEN_API_TOKEN": "t1",
                },
                clear=False,
            ):
                res = self.client.get(
                    "/open/ops/upgrade/validate?package_id=missing-package",
                    REMOTE_ADDR="8.8.8.8",
                    HTTP_X_BEACON_TOKEN="t1",
                )

        self.assertEqual(res.status_code, 404, msg=res.content[:2000])
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0, msg=body)
        self.assertEqual(body.get("msg"), "package not found", msg=body)
