import json
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.test import TestCase

from app import models as app_models


class Totp2FATest(TestCase):
    def _login_session(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username, "email": user.email}
        session.save()

    def test_rfc_style_totp_verification_works(self):
        from app.utils import Totp

        test_seed = "GEZDGNBVGY3TQOJQ" * 2
        self.assertTrue(Totp.verify_totp(test_seed, "287082", at_time=59, window=0, digits=6))
        self.assertTrue(Totp.verify_totp(test_seed, "081804", at_time=1111111109, window=0, digits=6))
        self.assertFalse(Totp.verify_totp(test_seed, "000000", at_time=59, window=0, digits=6))

    def test_profile_can_generate_enable_and_disable_totp(self):
        from app.utils import Totp

        user = User.objects.create_user(username="u1", password="Correct12345", email="u1@example.com")
        self._login_session(user)

        gen = self.client.post("/profile", data={"action": "totp_generate"})
        self.assertEqual(gen.status_code, 200)

        credential_model = getattr(app_models, "UserTotpCredential", None)
        self.assertIsNotNone(credential_model, "UserTotpCredential missing")
        cred = credential_model.objects.filter(user=user).first()
        self.assertIsNotNone(cred)
        self.assertFalse(bool(getattr(cred, "enabled", False)))
        self.assertTrue(str(getattr(cred, "secret_base32", "") or "").strip())

        code = Totp.generate_totp_code(str(getattr(cred, "secret_base32", "")), for_time=mock.ANY if False else None)
        enable = self.client.post("/profile", data={"action": "totp_enable", "totp_code": code})
        self.assertEqual(enable.status_code, 200)
        cred.refresh_from_db()
        self.assertTrue(bool(getattr(cred, "enabled", False)))

        code2 = Totp.generate_totp_code(str(getattr(cred, "secret_base32", "")))
        disable = self.client.post("/profile", data={"action": "totp_disable", "totp_code": code2})
        self.assertEqual(disable.status_code, 200)
        cred.refresh_from_db()
        self.assertFalse(bool(getattr(cred, "enabled", False)))

    def test_profile_can_generate_recovery_codes_when_totp_enabled(self):
        user = User.objects.create_user(username="u4", password="Correct12345", email="u4@example.com")
        self._login_session(user)

        credential_model = getattr(app_models, "UserTotpCredential", None)
        self.assertIsNotNone(credential_model, "UserTotpCredential missing")
        credential_model.objects.create(
            user=user,
            secret_base32="JBSWY3DPEHPK3PXP",
            enabled=True,
        )

        recovery_model = getattr(app_models, "UserTotpRecoveryCode", None)
        self.assertIsNotNone(recovery_model, "UserTotpRecoveryCode missing")
        self.assertEqual(recovery_model.objects.filter(user=user).count(), 0)

        res = self.client.post("/profile", data={"action": "totp_recovery_generate"})
        self.assertEqual(res.status_code, 200)

        # Codes should be created and all should be unused.
        self.assertGreaterEqual(recovery_model.objects.filter(user=user).count(), 10)
        self.assertEqual(recovery_model.objects.filter(user=user, used_at__isnull=True).count(), recovery_model.objects.filter(user=user).count())

    def test_login_requires_valid_totp_code_when_enabled(self):
        from app.utils import Totp

        user = User.objects.create_user(username="u2", password="Correct12345", email="u2@example.com")
        credential_model = getattr(app_models, "UserTotpCredential", None)
        self.assertIsNotNone(credential_model, "UserTotpCredential missing")
        cred = credential_model.objects.create(
            user=user,
            secret_base32="JBSWY3DPEHPK3PXP",
            enabled=True,
        )

        missing = self.client.post("/login", data={"username": "u2", "password": "Correct12345"})
        self.assertEqual(missing.status_code, 200)
        body_missing = json.loads(missing.content.decode("utf-8"))
        self.assertEqual(body_missing.get("code"), 0)
        self.assertIn("TOTP", str(body_missing.get("msg") or ""))

        wrong = self.client.post("/login", data={"username": "u2", "password": "Correct12345", "totp_code": "000000"})
        self.assertEqual(wrong.status_code, 200)
        body_wrong = json.loads(wrong.content.decode("utf-8"))
        self.assertEqual(body_wrong.get("code"), 0)

        code = Totp.generate_totp_code(str(getattr(cred, "secret_base32", "")))
        ok = self.client.post("/login", data={"username": "u2", "password": "Correct12345", "totp_code": code})
        self.assertEqual(ok.status_code, 200)
        body_ok = json.loads(ok.content.decode("utf-8"))
        self.assertEqual(body_ok.get("code"), 1000, msg=body_ok)

    def test_login_accepts_one_time_recovery_code_when_totp_enabled(self):
        """
        Minimal enterprise 2FA closure:
        - allow a one-time recovery code as fallback when TOTP is enabled
        - recovery code must be consumed after successful login
        """
        user = User.objects.create_user(username="u3", password="Correct12345", email="u3@example.com")

        credential_model = getattr(app_models, "UserTotpCredential", None)
        self.assertIsNotNone(credential_model, "UserTotpCredential missing")
        credential_model.objects.create(
            user=user,
            secret_base32="JBSWY3DPEHPK3PXP",
            enabled=True,
        )

        recovery_model = getattr(app_models, "UserTotpRecoveryCode", None)
        self.assertIsNotNone(recovery_model, "UserTotpRecoveryCode missing")

        # Recovery codes are normalized by stripping separators/spaces and uppercasing.
        code_plain = "ABCD-EFGH-IJKL-MNOP"
        recovery_model.objects.create(
            user=user,
            code_hash=make_password("ABCDEFGHIJKLMNOP"),
        )

        first = self.client.post("/login", data={"username": "u3", "password": "Correct12345", "totp_code": code_plain})
        self.assertEqual(first.status_code, 200)
        body_first = json.loads(first.content.decode("utf-8"))
        self.assertEqual(body_first.get("code"), 1000, msg=body_first)

        row = recovery_model.objects.filter(user=user).first()
        self.assertIsNotNone(row)
        self.assertIsNotNone(getattr(row, "used_at", None), "Recovery code should be consumed")

        # Clear session user, otherwise middleware will redirect /login to /.
        self.client.get("/logout")

        second = self.client.post("/login", data={"username": "u3", "password": "Correct12345", "totp_code": code_plain})
        self.assertEqual(second.status_code, 200)
        body_second = json.loads(second.content.decode("utf-8"))
        self.assertEqual(body_second.get("code"), 0, msg=body_second)
