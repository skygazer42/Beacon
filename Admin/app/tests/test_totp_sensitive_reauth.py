import json
import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from app import models as app_models


class TotpSensitiveReauthTest(TestCase):
    def setUp(self):
        super().setUp()
        self._old_env = dict(os.environ)
        os.environ["BEACON_TOTP_SENSITIVE_REAUTH_ENABLED"] = "1"
        os.environ["BEACON_TOTP_SENSITIVE_REAUTH_PREFIXES"] = "api/app-shell/users/action/"
        os.environ["BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS"] = "300"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        super().tearDown()

    def _login_session(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username, "email": user.email}
        session.save()

    def test_profile_reauth_window_seconds_clamps_out_of_range_values(self):
        from app.views import web as web_views

        os.environ["BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS"] = "5"
        self.assertEqual(web_views._web_profile_reauth_window_seconds(), 30)

        os.environ["BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS"] = "99999"
        self.assertEqual(web_views._web_profile_reauth_window_seconds(), 3600)

        os.environ["BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS"] = "not-a-number"
        self.assertEqual(web_views._web_profile_reauth_window_seconds(), 300)

    def test_sensitive_api_requires_recent_totp_reauth_when_enabled(self):
        from app.utils import Totp

        admin = User.objects.create_user(username="admin1", password="pass12345", email="a1@example.com")
        admin.is_staff = True
        admin.save()

        target = User.objects.create_user(username="u1", password="pass12345", email="u1@example.com")

        self._login_session(admin)

        credential_model = getattr(app_models, "UserTotpCredential", None)
        self.assertIsNotNone(credential_model, "UserTotpCredential missing")
        credential_model.objects.create(
            user=admin,
            secret_base32="JBSWY3DPEHPK3PXP",
            enabled=True,
        )

        # 1) Without reauth: should be blocked by middleware
        res = self.client.post("/api/app-shell/users/action/permissions/get", data={"user_id": str(target.id)})
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)
        self.assertIn("TOTP", str(body.get("msg") or ""))

        # 2) Do reauth via profile action
        code = Totp.generate_totp_code("JBSWY3DPEHPK3PXP", for_time=mock.ANY if False else None)
        res2 = self.client.post("/profile", data={"action": "totp_reauth", "totp_code": code})
        self.assertEqual(res2.status_code, 200)

        # 3) Now it should pass
        res3 = self.client.post("/api/app-shell/users/action/permissions/get", data={"user_id": str(target.id)})
        self.assertEqual(res3.status_code, 200)
        body3 = json.loads(res3.content.decode("utf-8"))
        self.assertEqual(body3.get("code"), 1000, msg=body3)
