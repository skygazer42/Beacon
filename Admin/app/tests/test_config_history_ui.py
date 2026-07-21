import json
import os
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase

from app import models as app_models
from app.models import AlgorithmModel, Control, Stream, UserPermission
from app.utils.SystemConfigHelper import get_value
from app.views import ConfigExportView


class _FakeSettingsStore:
    def __init__(self):
        self.data = {}

    def get_setting(self, key, default=""):
        return self.data.get(key, default)

    def update_settings(self, values):
        self.data.update(dict(values or {}))


class ConfigHistoryUiTest(TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username="config-admin", password="pass12345")
        self.admin.is_staff = True
        self.admin.save()
        self._login_as(self.admin)

        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config_json_path = os.path.join(self.tempdir.name, "config.json")
        with open(self.config_json_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

        self.fake_settings_store = _FakeSettingsStore()
        self._patches = [
            mock.patch("app.views.SystemConfigView._config_json_path", return_value=self.config_json_path),
            mock.patch("app.views.SystemConfigView.settings_store", self.fake_settings_store),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _login_as(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username}
        session.save()

    def _all_permissions(self, **overrides):
        perms = {
            "streams": True,
            "streams.view": True,
            "talkback": True,
            "controls": True,
            "alarms": True,
            "alarms.view": True,
            "algorithms": True,
            "recording": True,
            "face": True,
            "onvif": True,
            "system": True,
            "config.view": True,
            "config.export": True,
            "config.manage": True,
            "license": True,
            "ops": True,
            "ops.audit.view": True,
            "ops.audit.export": True,
            "cloud": True,
            "developer": True,
        }
        perms.update(overrides)
        return perms

    def _save_site_name(self, value: str):
        res = self.client.post("/api/app-shell/config/action/system/save", data={"siteName": value}, HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

    def test_config_import_rejects_invalid_json(self):
        request = RequestFactory().post(
            "/api/app-shell/config/action/import",
            data={
                "merge_mode": "skip",
                "file": SimpleUploadedFile("bad.json", b"{bad"),
            },
        )

        response = ConfigExportView.api_import(request)
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("code"), 0, msg=payload)
        self.assertIn("invalid json", str(payload.get("msg") or ""))

    def test_config_import_skip_and_overwrite_preserve_expected_objects(self):
        algorithm = AlgorithmModel.objects.create(
            sort=1,
            code="alg-existing",
            name="Existing Algorithm",
            algorithm_type=0,
            basic_source="model",
            model_path="/tmp/model.onnx",
            object_count=1,
            object_str="person",
            state=1,
        )
        stream = Stream.objects.create(
            user_id=self.admin.id,
            sort=1,
            code="stream-existing",
            app="live",
            name="cam-existing",
            pull_stream_url="rtsp://127.0.0.1/cam-existing",
            pull_stream_type=0,
            nickname="Existing Stream",
            remark="",
            forward_state=0,
            state=1,
        )
        control = Control.objects.create(
            user_id=self.admin.id,
            sort=0,
            code="ctl-existing",
            stream_app="live",
            stream_name="cam-existing",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="alg-existing",
            object_code="person",
            polygon="0,0,1,0,1,1,0,1",
            min_interval=1,
            class_thresh=0.5,
            overlap_thresh=0.5,
            remark="Existing Control",
            push_stream=False,
            state=0,
        )

        skip = ConfigExportView._import_config_entities(
            {
                "algorithms": [{"code": algorithm.code, "name": "Skip Algorithm"}],
                "streams": [{"code": stream.code, "nickname": "Skip Stream"}],
                "controls": [{"code": control.code, "remark": "Skip Control"}],
            },
            merge_mode="skip",
        )
        algorithm.refresh_from_db()
        stream.refresh_from_db()
        control.refresh_from_db()
        self.assertEqual(skip["algorithms"]["skipped"], 1)
        self.assertEqual(skip["streams"]["skipped"], 1)
        self.assertEqual(skip["controls"]["skipped"], 1)
        self.assertEqual(algorithm.name, "Existing Algorithm")
        self.assertEqual(stream.nickname, "Existing Stream")
        self.assertEqual(control.remark, "Existing Control")

        overwrite = ConfigExportView._import_config_entities(
            {
                "algorithms": [{"code": algorithm.code, "name": "Overwrite Algorithm"}],
                "streams": [{"code": stream.code, "nickname": "Overwrite Stream"}],
                "controls": [{"code": control.code, "remark": "Overwrite Control", "push_stream": True}],
            },
            merge_mode="overwrite",
        )
        algorithm.refresh_from_db()
        stream.refresh_from_db()
        control.refresh_from_db()
        self.assertEqual(overwrite["algorithms"]["success"], 1)
        self.assertEqual(overwrite["streams"]["success"], 1)
        self.assertEqual(overwrite["controls"]["success"], 1)
        self.assertEqual(algorithm.name, "Overwrite Algorithm")
        self.assertEqual(stream.nickname, "Overwrite Stream")
        self.assertEqual(control.remark, "Overwrite Control")
        self.assertTrue(control.push_stream)

    def test_system_save_creates_history_snapshot_and_history_page_lists_it(self):
        history_model = getattr(app_models, "ConfigHistorySnapshot", None)
        self.assertIsNotNone(history_model, "ConfigHistorySnapshot model missing")

        self._save_site_name("Alpha Beacon")

        latest = history_model.objects.order_by("-id").first()
        self.assertIsNotNone(latest, "history snapshot not created")
        snapshot = json.loads(getattr(latest, "snapshot_json", "") or "{}")
        self.assertEqual(snapshot.get("siteName"), "Alpha Beacon", msg=snapshot)

        res = self.client.get("/api/app-shell/config?snapshot_id=%s" % latest.id)
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        data = payload.get("data") or {}
        self.assertEqual((data.get("selected_snapshot") or {}).get("site_name"), "Alpha Beacon")

    def test_history_diff_and_rollback_restore_previous_snapshot(self):
        history_model = getattr(app_models, "ConfigHistorySnapshot", None)
        self.assertIsNotNone(history_model, "ConfigHistorySnapshot model missing")

        self._save_site_name("Alpha Beacon")
        self._save_site_name("Beta Beacon")

        target = None
        for row in history_model.objects.order_by("id"):
            snapshot = json.loads(getattr(row, "snapshot_json", "") or "{}")
            if snapshot.get("siteName") == "Alpha Beacon":
                target = row
        self.assertIsNotNone(target, "target snapshot missing")

        res = self.client.get("/api/app-shell/config?snapshot_id=%s" % target.id)
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        data = payload.get("data") or {}
        self.assertEqual(json.loads(data.get("selected_snapshot_json") or "{}").get("siteName"), "Alpha Beacon")
        self.assertEqual(json.loads(data.get("current_snapshot_json") or "{}").get("siteName"), "Beta Beacon")

        guard = self.client.post(
            "/api/app-shell/config/action/history/rollback",
            data={"snapshot_id": str(target.id)},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(guard.status_code, 200, msg=guard.content)
        guard_body = json.loads(guard.content.decode("utf-8"))
        self.assertEqual(guard_body.get("code"), 0, msg=guard_body)
        self.assertIn("confirm", str(guard_body.get("msg") or "").lower())

        rollback = self.client.post(
            "/api/app-shell/config/action/history/rollback",
            data={"snapshot_id": str(target.id), "confirm": "rollback"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(rollback.status_code, 200, msg=rollback.content)
        rollback_body = json.loads(rollback.content.decode("utf-8"))
        self.assertEqual(rollback_body.get("code"), 1000, msg=rollback_body)
        self.assertEqual(get_value("siteName", ""), "Alpha Beacon")

    def test_history_routes_enforce_view_and_manage_permissions(self):
        history_model = getattr(app_models, "ConfigHistorySnapshot", None)
        self.assertIsNotNone(history_model, "ConfigHistorySnapshot model missing")

        self._save_site_name("Locked Beacon")
        snapshot = history_model.objects.order_by("-id").first()
        self.assertIsNotNone(snapshot, "history snapshot not created")

        denied = User.objects.create_user(username="cfg-denied", password="pass12345")
        self._login_as(denied)
        UserPermission.objects.create(
            user=denied,
            permissions_json=json.dumps(
                self._all_permissions(
                    system=False,
                    **{
                        "config.view": False,
                        "config.manage": False,
                    }
                ),
                ensure_ascii=False,
            ),
        )

        res_denied = self.client.get("/config/history", HTTP_ACCEPT="application/json")
        self.assertEqual(res_denied.status_code, 200, msg=res_denied.content)
        denied_body = json.loads(res_denied.content.decode("utf-8"))
        self.assertEqual(denied_body.get("code"), 403, msg=denied_body)

        view_only = User.objects.create_user(username="cfg-view", password="pass12345")
        self._login_as(view_only)
        UserPermission.objects.create(
            user=view_only,
            permissions_json=json.dumps(
                self._all_permissions(
                    system=True,
                    **{
                        "config.view": True,
                        "config.manage": False,
                    }
                ),
                ensure_ascii=False,
            ),
        )

        res_page = self.client.get("/config/history", HTTP_ACCEPT="text/html")
        self.assertEqual(res_page.status_code, 200, msg=res_page.content)

        rollback = self.client.post(
            "/api/app-shell/config/action/history/rollback",
            data={"snapshot_id": str(snapshot.id), "confirm": "rollback"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(rollback.status_code, 200, msg=rollback.content)
        rollback_body = json.loads(rollback.content.decode("utf-8"))
        self.assertEqual(rollback_body.get("code"), 403, msg=rollback_body)
