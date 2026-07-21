import json
import hashlib
import os
import tempfile
from unittest import mock

from django.test import TestCase

from app.utils.Analyzer import Analyzer
from app.utils.License import License
from app.views import api as api_views


class _DummyConfig:
    def __init__(self):
        self.licenseType = "machine"
        self.licenseKey = ""
        self.licenseDongleCmd = ""
        self.licenseDongleFile = ""


class LocalLicenseTest(TestCase):
    def _openapi_headers(self):
        token = str(getattr(api_views.g_config, "openApiToken", "") or "").strip()
        if not token:
            return {}
        return {"HTTP_X_BEACON_TOKEN": token}

    def test_community_mode_does_not_require_a_runtime_license(self):
        cfg = _DummyConfig()
        cfg.licenseType = "community"

        info = License(cfg).check()

        self.assertTrue(info.get("ok"))
        self.assertEqual(info.get("type"), "community")
        self.assertEqual(info.get("extra", {}).get("edition"), "community")

    def test_api_license_usage_accepts_community_mode(self):
        analyzer = mock.Mock()
        analyzer.license_info.side_effect = RuntimeError("offline")
        community_info = {"ok": True, "type": "community", "extra": {"edition": "community"}}

        with mock.patch("app.views.api.g_analyzer", analyzer), \
             mock.patch.object(api_views.g_config, "licenseType", "community"), \
             mock.patch("app.views.api.g_license.check", return_value=community_info):
            resp = self.client.get("/open/license/usage", **self._openapi_headers())

        payload = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        self.assertTrue(payload.get("data", {}).get("valid"))
        self.assertEqual(payload.get("data", {}).get("type"), "community")

    def test_dongle_fallback_to_sentinel_when_cmd_errors(self):
        cfg = _DummyConfig()
        cfg.licenseType = "dongle"
        cfg.licenseDongleCmd = "this_command_should_not_exist_12345"

        with tempfile.TemporaryDirectory() as td:
            sentinel = os.path.join(td, "license.dongle")
            with open(sentinel, "w", encoding="utf-8") as f:
                f.write("ok\n")
            cfg.licenseDongleFile = sentinel

            info = License(cfg).check()
            self.assertTrue(info.get("ok"))

    def test_dongle_check_invokes_subprocess_without_shell(self):
        cfg = _DummyConfig()
        cfg.licenseType = "dongle"
        cfg.licenseDongleCmd = "dongle-check --ping"
        cfg.licenseDongleFile = ""

        fake_result = mock.Mock()
        fake_result.returncode = 0

        with mock.patch("app.utils.License.subprocess.run", return_value=fake_result) as mocked_run:
            info = License(cfg).check()

        self.assertTrue(info.get("ok"))
        target_call = None
        for c in mocked_run.call_args_list:
            if "dongle-check" in str(c.args[0]):
                target_call = c
                break
        self.assertIsNotNone(target_call)
        self.assertFalse(bool(target_call.kwargs.get("shell", True)))

    def test_machine_accepts_v1_or_v2_and_strips_key(self):
        cfg = _DummyConfig()
        cfg.licenseType = "machine"

        lic = License(cfg)
        v1 = lic.get_machine_code_v1()
        v2 = lic.get_machine_code_v2()

        # Accept exact code match (with whitespace).
        cfg.licenseKey = "  %s \n" % v2
        self.assertTrue(License(cfg).check().get("ok"))

        # Accept sha256(code) match (with whitespace).
        cfg.licenseKey = "\t%s  " % hashlib.sha256(v1.encode("utf-8")).hexdigest()
        self.assertTrue(License(cfg).check().get("ok"))

    def test_machine_code_v2_prefers_stable_id_inputs(self):
        cfg = _DummyConfig()
        lic = License(cfg)

        with mock.patch.object(lic.os, "getMachineStableId", return_value="stable-id-1"), \
             mock.patch.object(lic.os, "getSystemName", return_value="Linux"), \
             mock.patch.object(lic.os, "getMachineCpu", return_value="cpu-1"), \
             mock.patch.object(lic.os, "getMachineNode", side_effect=AssertionError("v1 path should stay unused")), \
             mock.patch.object(lic, "_get_mac", side_effect=AssertionError("v1 path should stay unused")):
            expected = hashlib.sha256("Linux|stable-id-1|cpu-1".encode("utf-8")).hexdigest()
            self.assertEqual(lic.get_machine_code_v2(), expected)

    def test_machine_code_v2_falls_back_to_v1_when_stable_id_missing(self):
        cfg = _DummyConfig()
        lic = License(cfg)

        with mock.patch.object(lic.os, "getMachineStableId", return_value=""), \
             mock.patch.object(lic, "get_machine_code_v1", return_value="legacy-v1-code") as mocked_v1:
            self.assertEqual(lic.get_machine_code_v2(), "legacy-v1-code")
            self.assertEqual(lic.get_machine_code(), "legacy-v1-code")
            mocked_v1.assert_called_once()

    def test_machine_accepts_exact_legacy_v1_code(self):
        cfg = _DummyConfig()
        cfg.licenseType = "machine"

        lic = License(cfg)
        cfg.licenseKey = lic.get_machine_code_v1()

        self.assertTrue(License(cfg).check().get("ok"))

    def test_analyzer_license_info_calls_license_endpoint(self):
        analyzer = Analyzer("http://analyzer.local", openApiToken="token-1")
        self.assertTrue(hasattr(analyzer, "license_info"))

        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "code": 1000,
            "msg": "success",
            "data": {
                "ok": True,
                "type": "machine",
                "machine_code": "mc",
            },
        }

        with mock.patch("app.utils.Analyzer.requests.get", return_value=response) as mocked_get:
            ok, msg, data = analyzer.license_info(timeout_seconds=1.5)

        self.assertTrue(ok)
        self.assertEqual(msg, "success")
        self.assertEqual(data.get("data", {}).get("type"), "machine")
        mocked_get.assert_called_once()
        _, kwargs = mocked_get.call_args
        self.assertEqual(kwargs.get("url"), "http://analyzer.local/api/license/info")
        self.assertEqual(kwargs.get("headers", {}).get("X-Beacon-Token"), "token-1")

    def test_api_license_info_proxies_machine_type_to_analyzer(self):
        analyzer = mock.Mock()
        analyzer.license_info.return_value = (
            True,
            "success",
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "ok": True,
                    "type": "machine",
                    "machine_code": "machine-code",
                },
            },
        )

        with mock.patch("app.views.api.g_analyzer", analyzer), \
             mock.patch.object(api_views.g_config, "licenseType", "machine"), \
             mock.patch("app.views.api.g_license.check", return_value={"ok": False, "type": "machine"}) as mocked_check:
            resp = self.client.get("/open/license/info", **self._openapi_headers())

        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        self.assertEqual(payload.get("data", {}).get("type"), "machine")
        self.assertEqual(payload.get("data", {}).get("machine_code"), "machine-code")
        analyzer.license_info.assert_called_once()
        mocked_check.assert_not_called()

    def test_api_license_info_keeps_pool_type_on_admin(self):
        analyzer = mock.Mock()
        admin_info = {
            "ok": True,
            "type": "pool",
            "extra": {
                "license_id": "LIC-1",
            },
        }

        with mock.patch("app.views.api.g_analyzer", analyzer), \
             mock.patch.object(api_views.g_config, "licenseType", "pool"), \
             mock.patch("app.views.api.g_license.check", return_value=admin_info) as mocked_check:
            resp = self.client.get("/open/license/info", **self._openapi_headers())

        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        self.assertEqual(payload.get("data", {}).get("type"), "pool")
        self.assertEqual(payload.get("data", {}).get("extra", {}).get("license_id"), "LIC-1")
        analyzer.license_info.assert_not_called()
        mocked_check.assert_called_once()

    def test_api_license_usage_machine_mode_falls_back_to_analyzer(self):
        analyzer = mock.Mock()
        analyzer.license_info.return_value = (
            True,
            "success",
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "ok": True,
                    "type": "machine",
                    "machine_code": "machine-code",
                },
            },
        )

        with mock.patch("app.views.api.g_analyzer", analyzer), \
             mock.patch.object(api_views.g_config, "licenseType", "machine"):
            resp = self.client.get("/open/license/usage", **self._openapi_headers())

        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        self.assertTrue(payload.get("data", {}).get("valid"))
        self.assertEqual(payload.get("data", {}).get("active_controls"), 0)
        self.assertEqual(payload.get("data", {}).get("active_streams"), 0)
        self.assertEqual(payload.get("data", {}).get("active_nodes"), 0)
        analyzer.license_info.assert_called_once()
