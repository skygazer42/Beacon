import json
import os
import tempfile
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, TestCase
import settings_store  # type: ignore

from app.context_processors import branding
from app.models import SystemConfig


class SystemSettingsTest(TestCase):
    def setUp(self):
        super().setUp()
        self._temp_root = tempfile.TemporaryDirectory()
        self._root_patcher = mock.patch.dict(os.environ, {"BEACON_ROOT_DIR": self._temp_root.name}, clear=False)
        self._root_patcher.start()
        if hasattr(settings_store, "_CACHE") and isinstance(settings_store._CACHE, dict):
            settings_store._CACHE.clear()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def tearDown(self):
        if hasattr(settings_store, "_CACHE") and isinstance(settings_store._CACHE, dict):
            settings_store._CACHE.clear()
        self._root_patcher.stop()
        self._temp_root.cleanup()
        super().tearDown()

    def test_branding_context_is_overridden_by_system_config(self):
        SystemConfig.objects.create(key="siteName", value="MyBeacon", remark="系统名称")
        SystemConfig.objects.create(key="siteTitle", value="MyBeacon Title", remark="系统标题")
        SystemConfig.objects.create(key="siteLogo", value="/static/images/custom.png", remark="系统 Logo")
        SystemConfig.objects.create(key="authorName", value="ACME", remark="作者名称")
        SystemConfig.objects.create(key="authorLink", value="https://acme.example.com", remark="作者链接")
        SystemConfig.objects.create(key="siteIcp", value="粤ICP备000000号", remark="ICP备案")
        SystemConfig.objects.create(key="customCss", value=".demo{color:red;}", remark="自定义CSS")
        SystemConfig.objects.create(key="customScript", value="console.log('demo')", remark="自定义脚本")
        SystemConfig.objects.create(key="loginBg", value="/static/images/bg.png", remark="登录背景")

        rf = RequestFactory()
        req = rf.get("/")
        # This test verifies DB(SystemConfig) overrides config.json defaults.
        # settings.json has higher precedence by design, so isolate root dir to ensure
        # no ambient settings.json leaks into this test run.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {"BEACON_ROOT_DIR": tmp, "BEACON_DEPLOYMENT_MODE": "edge"},
                clear=False,
            ):
                if hasattr(settings_store, "_CACHE") and isinstance(settings_store._CACHE, dict):
                    settings_store._CACHE.clear()
                ctx = branding(req)
        self.assertEqual(ctx.get("site_name"), "MyBeacon")
        self.assertEqual(ctx.get("site_title"), "MyBeacon Title")
        self.assertEqual(ctx.get("project_version"), settings.PROJECT_VERSION)
        self.assertEqual(ctx.get("site_logo"), "/static/images/custom.png")
        self.assertEqual(ctx.get("author_name"), "ACME")
        self.assertEqual(ctx.get("author_link"), "https://acme.example.com")
        self.assertEqual(ctx.get("site_icp"), "粤ICP备000000号")
        self.assertEqual(ctx.get("custom_css"), ".demo{color:red;}")
        self.assertEqual(ctx.get("custom_script"), "console.log('demo')")
        self.assertEqual(ctx.get("login_bg"), "/static/images/bg.png")
        self.assertEqual(ctx.get("deployment_mode"), "edge")

    def test_save_system_settings_persists_db_and_updates_config_json(self):
        payload = {
            "siteName": "BeaconX",
            "siteTitle": "BeaconX Title",
            "siteLogo": "/static/images/logo-x.png",
            "authorName": "Beacon Team X",
            "authorLink": "https://example.com/x",
            "siteIcp": "京ICP备123456号",
            "customCss": "body{background:#000;}",
            "customScript": "window.__beacon=1;",
            "loginBg": "/static/images/login.png",
            "alarmVideoSeconds": "7",
            "alarmSegmentMaxSeconds": "120",
            "alarmPushDelaySeconds": "2",
            "modelCacheSeconds": "120",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()

        self.assertEqual(SystemConfig.objects.filter(key="siteName").first().value, "BeaconX")
        self.assertEqual(SystemConfig.objects.filter(key="alarmVideoSeconds").first().value, "7")
        self.assertEqual(SystemConfig.objects.filter(key="alarmSegmentMaxSeconds").first().value, "120")
        self.assertEqual(SystemConfig.objects.filter(key="siteIcp").first().value, "京ICP备123456号")
        self.assertEqual(SystemConfig.objects.filter(key="customCss").first().value, "body{background:#000;}")
        self.assertEqual(SystemConfig.objects.filter(key="modelCacheSeconds").first().value, "120")

        runtime_values = mocked_update.call_args[0][0]
        self.assertEqual(runtime_values.get("alarmSegmentMaxSeconds"), 120)

    def test_save_system_settings_persists_software_auto_start_to_config_json(self):
        payload = {
            # Include at least one existing runtime key so _update_config_json is called.
            "stream_auto_start": "0",
            # New key we expect to be persisted to config.json.
            "software_auto_start": "1",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()

        # Ensure the new key is included in the runtime_values passed to config.json writer.
        runtime_values = mocked_update.call_args[0][0]
        self.assertIn("software_auto_start", runtime_values)
        self.assertEqual(runtime_values.get("software_auto_start"), 1)

    def test_save_system_settings_persists_screen_login_required_to_config_json(self):
        payload = {
            # Include at least one existing runtime key so _update_config_json is called.
            "stream_auto_start": "0",
            # v4.711: big screen page login restriction toggle.
            "screenLoginRequired": "0",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()

        runtime_values = mocked_update.call_args[0][0]
        self.assertIn("screenLoginRequired", runtime_values)
        self.assertEqual(runtime_values.get("screenLoginRequired"), 0)

    def test_save_system_settings_persists_webrtc_nat_fields_to_config_json(self):
        payload = {
            "stream_auto_start": "0",
            "webrtcStunUrls": "stun:stun.example.com:3478,stun:stun2.example.com:3478",
            "webrtcTurnUrl": "turn:turn.example.com:3478?transport=tcp",
            "webrtcTurnUsername": "turn-user",
            "webrtcTurnPassword": "turn-pass",
            "webrtcSelfCheckTimeoutSeconds": "5",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()

        runtime_values = mocked_update.call_args[0][0]
        self.assertEqual(runtime_values.get("webrtcStunUrls"), "stun:stun.example.com:3478,stun:stun2.example.com:3478")
        self.assertEqual(runtime_values.get("webrtcTurnUrl"), "turn:turn.example.com:3478?transport=tcp")
        self.assertEqual(runtime_values.get("webrtcTurnUsername"), "turn-user")
        self.assertEqual(runtime_values.get("webrtcTurnPassword"), "turn-pass")
        self.assertEqual(runtime_values.get("webrtcSelfCheckTimeoutSeconds"), 5)

    def test_save_system_settings_persists_openapi_gateway_fields_to_config_json(self):
        payload = {
            "stream_auto_start": "0",
            "openApiRateLimitEnabled": "1",
            "openApiRateLimitPerMinute": "120",
            "openApiRateLimitBurst": "20",
            "openApiWafEnabled": "1",
            "openApiWafMaxBodyBytes": "2048",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()

        runtime_values = mocked_update.call_args[0][0]
        self.assertEqual(runtime_values.get("openApiRateLimitEnabled"), 1)
        self.assertEqual(runtime_values.get("openApiRateLimitPerMinute"), 120)
        self.assertEqual(runtime_values.get("openApiRateLimitBurst"), 20)
        self.assertEqual(runtime_values.get("openApiWafEnabled"), 1)
        self.assertEqual(runtime_values.get("openApiWafMaxBodyBytes"), 2048)

    def test_save_cloud_connection_reuses_system_config_without_returning_token(self):
        from app.views.ViewsBase import g_config

        original = {
            "cloudEnabled": getattr(g_config, "cloudEnabled", False),
            "cloudBaseUrl": getattr(g_config, "cloudBaseUrl", ""),
            "cloudEdgeToken": getattr(g_config, "cloudEdgeToken", ""),
        }
        payload = {
            "cloudEnabled": True,
            "cloudBaseUrl": "https://cloud.example.com",
            "cloudEdgeToken": "edge-token",
        }
        try:
            with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
                res = self.client.post(
                    "/api/app-shell/config/action/system/save",
                    data=json.dumps(payload),
                    content_type="application/json",
                )

            body = json.loads(res.content.decode("utf-8"))
            self.assertEqual(body.get("code"), 1000)
            self.assertNotIn("cloudEdgeToken", body.get("data") or {})
            self.assertTrue((body.get("data") or {}).get("cloudEdgeTokenConfigured"))
            runtime_values = mocked_update.call_args[0][0]
            self.assertEqual(runtime_values.get("cloudBaseUrl"), "https://cloud.example.com")
            self.assertEqual(runtime_values.get("cloudEdgeToken"), "edge-token")
            self.assertTrue(getattr(g_config, "cloudEnabled", False))
        finally:
            for key, value in original.items():
                setattr(g_config, key, value)

    def test_save_cloud_connection_rejects_non_http_address(self):
        res = self.client.post(
            "/api/app-shell/config/action/system/save",
            data={
                "cloudEnabled": "1",
                "cloudBaseUrl": "file:///tmp/cloud",
                "cloudEdgeToken": "edge-token",
            },
        )

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0)
        self.assertIn("http://", body.get("msg") or "")

    def test_save_system_settings_persists_face_default_feature_algorithm_code(self):
        payload = {
            "stream_auto_start": "0",
            "faceDefaultFeatureAlgorithmCode": "on_xcfacenet",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()

        runtime_values = mocked_update.call_args[0][0]
        self.assertEqual(runtime_values.get("faceDefaultFeatureAlgorithmCode"), "on_xcfacenet")
        self.assertEqual(
            SystemConfig.objects.filter(key="faceDefaultFeatureAlgorithmCode").first().value,
            "on_xcfacenet",
        )

        from app.views.ViewsBase import g_config

        self.assertEqual(getattr(g_config, "faceDefaultFeatureAlgorithmCode", ""), "on_xcfacenet")

    def test_save_system_settings_applies_os_autostart_when_posted(self):
        payload = {
            "stream_auto_start": "0",
            "software_auto_start": "1",
        }
        with mock.patch("app.views.SystemConfigView._update_config_json") as mocked_update:
            with mock.patch(
                "app.utils.AutoStart.apply_autostart",
                return_value=(True, "enabled"),
            ) as mocked_apply:
                res = self.client.post("/api/app-shell/config/action/system/save", data=payload)

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)
        mocked_update.assert_called()
        mocked_apply.assert_called_once_with(enabled=True)
