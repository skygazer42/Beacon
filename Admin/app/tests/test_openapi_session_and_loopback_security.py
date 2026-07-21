import json
import os
from unittest import mock

from django.test import TestCase


class OpenApiSessionAndLoopbackSecurityTest(TestCase):
    def _login_session(self):
        session = self.client.session
        session["user"] = {"id": 1, "username": "u1"}
        session.save()

    def test_session_user_does_not_bypass_open_platform_auth(self):
        # A logged-in web session must not implicitly authorize machine OpenAPI endpoints.
        self._login_session()

        res = self.client.get("/open/platform/basicInfo", REMOTE_ADDR="8.8.8.8")
        self.assertEqual(res.status_code, 401, msg=res.content)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 0, msg=body)

    def test_session_user_does_not_bypass_ops_healthz_auth(self):
        self._login_session()

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "t1"}, clear=False):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8")
        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_loopback_unsafe_openapi_blocks_cross_site_origin_without_token(self):
        # When OpenAPI token is not configured, loopback mode should still mitigate browser CSRF.
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": ""}, clear=False):
            with mock.patch("app.views.api._schedule_admin_restart") as m_restart:
                res = self.client.post(
                    "/open/platform/restartSoftware",
                    data=json.dumps({}),
                    content_type="application/json",
                    REMOTE_ADDR="127.0.0.1",
                    HTTP_ORIGIN="http://evil.example",
                )
        self.assertEqual(res.status_code, 401, msg=res.content)
        self.assertFalse(m_restart.called)

