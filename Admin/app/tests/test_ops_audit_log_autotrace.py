import json
import os
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from app.models import OpsAuditLog
from app.views import api as api_view


class OpsAuditLogAutotraceTest(TestCase):
    def _login_as(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username}
        session.save()

    def test_mutating_post_requests_are_audited(self):
        u = User.objects.create_user(username="u1", password="pass12345")
        self._login_as(u)

        res = self.client.post("/stream/setAutoStartConfig", data={"auto_start": "1"}, HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000)

        self.assertTrue(
            OpsAuditLog.objects.filter(event_type="stream.setAutoStartConfig.post", operator="u1").exists()
        )


class OpsAuditLogSecurityTraceTest(TestCase):
    def test_trace_ids_strip_crlf_before_audit_use(self):
        self.assertEqual(api_view._sanitize_trace_id("line1\r\nline2", max_len=64), "line1line2")
        request = SimpleNamespace(
            META={
                "HTTP_X_REQUEST_ID": "req-1\r\nInjected: true",
                "HTTP_X_CORRELATION_ID": "corr-1\nInjected: true",
            },
            beacon_request_id="",
            beacon_correlation_id="",
        )

        request_id, correlation_id = api_view._get_ops_trace_ids(request)

        self.assertNotIn("\r", request_id)
        self.assertNotIn("\n", request_id)
        self.assertNotIn("\r", correlation_id)
        self.assertNotIn("\n", correlation_id)

    def test_openapi_unauthorized_request_is_audited(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8")
        self.assertEqual(res.status_code, 401, msg=res.content)

        row = OpsAuditLog.objects.filter(event_type="openapi.auth.unauthorized").order_by("-id").first()
        self.assertIsNotNone(row)
        detail = json.loads(str(getattr(row, "detail_json", "") or "{}"))
        self.assertEqual(str(detail.get("path") or ""), "healthz")
        self.assertEqual(str(detail.get("security_reason") or ""), "token_missing_or_invalid")

    def test_login_ip_policy_block_is_audited(self):
        with mock.patch.dict(os.environ, {"BEACON_ADMIN_IP_ALLOWLIST": "1.2.3.0/24"}, clear=False):
            res = self.client.get("/login", REMOTE_ADDR="8.8.8.8")
        self.assertEqual(res.status_code, 403, msg=res.content)

        row = OpsAuditLog.objects.filter(event_type="security.login_ip_block").order_by("-id").first()
        self.assertIsNotNone(row)
        detail = json.loads(str(getattr(row, "detail_json", "") or "{}"))
        self.assertEqual(str(detail.get("path") or ""), "login")
        self.assertEqual(str(detail.get("security_reason") or ""), "ip_policy")

    def test_login_lockout_trigger_and_block_are_audited(self):
        User.objects.create_user(username="lk1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
            },
            clear=False,
        ):
            first = self.client.post(
                "/login",
                data={"username": "lk1", "password": "wrong"},
                REMOTE_ADDR="9.9.9.9",
            )
            self.assertEqual(first.status_code, 200, msg=first.content)

            second = self.client.post(
                "/login",
                data={"username": "lk1", "password": "Correct12345"},
                REMOTE_ADDR="9.9.9.9",
            )
            self.assertEqual(second.status_code, 200, msg=second.content)
            second_body = json.loads(second.content.decode("utf-8"))
            self.assertEqual(second_body.get("code"), 0, msg=second_body)

        triggered = OpsAuditLog.objects.filter(event_type="security.login_lockout.triggered").order_by("-id").first()
        blocked = OpsAuditLog.objects.filter(event_type="security.login_lockout.blocked").order_by("-id").first()
        self.assertIsNotNone(triggered)
        self.assertIsNotNone(blocked)
