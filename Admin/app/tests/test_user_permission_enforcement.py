import json

from django.contrib.auth.models import User
from django.test import TestCase

from app.models import UserPermission


class UserPermissionEnforcementTest(TestCase):
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

    def test_non_admin_without_permission_record_is_allowed(self):
        u = User.objects.create_user(username="u1", password="pass12345")
        self._login_as(u)

        res = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)

    def test_non_admin_with_permission_denied_streams_api(self):
        u = User.objects.create_user(username="u2", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(streams=False, **{"streams.view": False}),
                ensure_ascii=False,
            ),
        )

        res = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403)

    def test_non_admin_with_permission_denied_streams_page(self):
        u = User.objects.create_user(username="u3", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(streams=False, **{"streams.view": False}),
                ensure_ascii=False,
            ),
        )

        res = self.client.get("/stream/index")
        self.assertEqual(res.status_code, 200)
        self.assertIn("权限不足", res.content.decode("utf-8"))

    def test_non_admin_with_onvif_permission_denied_cannot_access_app_shell_onvif_action(self):
        u = User.objects.create_user(username="onvif-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(onvif=False),
                ensure_ascii=False,
            ),
        )

        res = self.client.post(
            "/api/app-shell/onvif/action/discover",
            data={"timeout": "1"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_invalid_permission_json_is_denied(self):
        u = User.objects.create_user(username="u4", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json="{invalid-json",
        )

        res = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_string_false_permission_is_denied(self):
        u = User.objects.create_user(username="u5", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps({"streams": "false"}, ensure_ascii=False),
        )

        res = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_string_true_permission_is_allowed(self):
        u = User.objects.create_user(username="u6", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps({"streams": "true"}, ensure_ascii=False),
        )

        res = self.client.get("/stream/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

    def test_non_admin_with_audit_view_permission_but_export_denied_cannot_export(self):
        u = User.objects.create_user(username="audit-view-only", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(
                    ops=True,
                    **{
                        "ops.audit.view": True,
                        "ops.audit.export": False,
                    }
                ),
                ensure_ascii=False,
            ),
        )

        res_page = self.client.get("/ops/audit", HTTP_ACCEPT="text/html")
        self.assertEqual(res_page.status_code, 200, msg=res_page.content)
        self.assertIn("audit", res_page.content.decode("utf-8").lower())

        res_export = self.client.get("/api/app-shell/ops/action/audit/export", HTTP_ACCEPT="application/json")
        self.assertEqual(res_export.status_code, 200, msg=res_export.content)
        content = res_export.content.decode("utf-8", errors="ignore")
        self.assertIn("权限不足", content)

    def test_non_admin_with_config_view_permission_but_manage_denied_cannot_save_system_config(self):
        u = User.objects.create_user(username="config-view-only", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(
                    system=True,
                    **{
                        "config.view": True,
                        "config.export": True,
                        "config.manage": False,
                    }
                ),
                ensure_ascii=False,
            ),
        )

        res_page = self.client.get("/config/system", HTTP_ACCEPT="text/html")
        self.assertEqual(res_page.status_code, 200, msg=res_page.content)
        self.assertIn("siteName", res_page.content.decode("utf-8"))

        res_save = self.client.post(
            "/api/app-shell/config/action/system/save",
            data={"siteName": "Locked"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res_save.status_code, 200, msg=res_save.content)
        body = json.loads(res_save.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_config_view_permission_but_export_denied_cannot_export_config(self):
        u = User.objects.create_user(username="config-no-export", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(
                    system=True,
                    **{
                        "config.view": True,
                        "config.export": False,
                        "config.manage": True,
                    }
                ),
                ensure_ascii=False,
            ),
        )

        res_page = self.client.get("/config/export", HTTP_ACCEPT="text/html")
        self.assertEqual(res_page.status_code, 200, msg=res_page.content)

        res_export = self.client.post(
            "/api/app-shell/config/action/export",
            data={"export_type": "full"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res_export.status_code, 200, msg=res_export.content)
        body = json.loads(res_export.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_alarm_view_permission_does_not_gain_stream_view_access(self):
        u = User.objects.create_user(username="alarm-only-view", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(
                    streams=True,
                    alarms=True,
                    **{
                        "streams.view": False,
                        "alarms.view": True,
                    }
                ),
                ensure_ascii=False,
            ),
        )

        res_alarm = self.client.get("/alarms", HTTP_ACCEPT="text/html")
        self.assertEqual(res_alarm.status_code, 200, msg=res_alarm.content)
        self.assertIn("alarm", res_alarm.content.decode("utf-8").lower())

        res_stream = self.client.get("/stream/index", HTTP_ACCEPT="application/json")
        self.assertEqual(res_stream.status_code, 200, msg=res_stream.content)
        body = json.loads(res_stream.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_alarm_view_denied_cannot_save_alarm_preset(self):
        u = User.objects.create_user(username="alarm-preset-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(alarms=False, **{"alarms.view": False}),
                ensure_ascii=False,
            ),
        )

        res = self.client.post(
            "/alarm/preset/save",
            data={
                "name": "Should not save",
                "target_mode": "list",
                "redirect_to": "/alarms",
            },
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_stream_permission_denied_cannot_call_app_shell_stream_action(self):
        u = User.objects.create_user(username="stream-app-shell-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(streams=False, **{"streams.view": False}),
                ensure_ascii=False,
            ),
        )

        res = self.client.get("/api/app-shell/stream/action/getAutoStartConfig", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_talkback_permission_denied_cannot_call_app_shell_talkback_action(self):
        u = User.objects.create_user(username="talkback-app-shell-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(talkback=False, streams=True, **{"streams.view": True}),
                ensure_ascii=False,
            ),
        )

        res = self.client.get(
            "/api/app-shell/stream/action/talkback/status?session_id=sess-1",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_controls_permission_denied_cannot_call_app_shell_control_action(self):
        u = User.objects.create_user(username="control-app-shell-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(controls=False),
                ensure_ascii=False,
            ),
        )

        res = self.client.get("/api/app-shell/control/action/openIndex", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_alarm_view_denied_cannot_call_app_shell_alarm_poll_action(self):
        u = User.objects.create_user(username="alarm-app-shell-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(alarms=False, **{"alarms.view": False}),
                ensure_ascii=False,
            ),
        )

        res = self.client.get("/api/app-shell/alarm/action/poll", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)

    def test_non_admin_with_algorithms_permission_denied_cannot_call_app_shell_algorithm_action(self):
        u = User.objects.create_user(username="alg-app-shell-denied", password="pass12345")
        self._login_as(u)

        UserPermission.objects.create(
            user=u,
            permissions_json=json.dumps(
                self._all_permissions(algorithms=False),
                ensure_ascii=False,
            ),
        )

        res = self.client.post("/api/app-shell/algorithm/action/openAnalyzerLoad", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)
