import json
import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase


class LoginLockoutPolicyTest(TestCase):
    def test_split_proxy_header_list_keeps_quoted_comma_hops_together(self):
        from app.views import web

        self.assertEqual(
            web._split_proxy_header_list('"unknown,still", 33.33.33.33'),
            ['"unknown,still"', "33.33.33.33"],
        )

    def test_forwarded_for_field_ip_strips_nested_quotes_and_port(self):
        from app.views import web

        self.assertEqual(
            web._forwarded_for_field_ip('for="\'[2001:db8::12]:443\'"'),
            "2001:db8::12",
        )

    def test_login_is_locked_out_after_too_many_failures(self):
        User.objects.create_user(username="u1", password="Correct12345")

        # Enable lockout with small thresholds to keep test fast.
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "3",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
            },
            clear=False,
        ):
            for _ in range(3):
                res = self.client.post(
                    "/login",
                    data={"username": "u1", "password": "wrong"},
                    REMOTE_ADDR="1.2.3.4",
                )
                self.assertEqual(res.status_code, 200)
                body = json.loads(res.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 0)

            # After reaching the threshold, even correct password should be blocked until unlocked.
            res2 = self.client.post(
                "/login",
                data={"username": "u1", "password": "Correct12345"},
                REMOTE_ADDR="1.2.3.4",
            )
            self.assertEqual(res2.status_code, 200)
            body2 = json.loads(res2.content.decode("utf-8"))
            self.assertEqual(body2.get("code"), 0)

    def test_login_lockout_counts_case_variants_as_same_user(self):
        user = User.objects.create_user(username="CaseUserA", password="Correct12345", email="case01@abc.com")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "3",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
            },
            clear=False,
        ):
            for input_username in ("caseusera", "CASEUSERA", "CaseUserA"):
                res = self.client.post(
                    "/login",
                    data={"username": input_username, "password": "wrong"},
                    REMOTE_ADDR="2.2.2.2",
                )
                self.assertEqual(res.status_code, 200)
                body = json.loads(res.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 0)

            blocked = self.client.post(
                "/login",
                data={"username": "CaseUserA", "password": "Correct12345"},
                REMOTE_ADDR="2.2.2.2",
            )
            body_blocked = json.loads(blocked.content.decode("utf-8"))
            self.assertEqual(body_blocked.get("code"), 0, msg=body_blocked)

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(source_ip="2.2.2.2").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "username", "")), f"user:{user.id}")

    def test_login_lockout_counts_username_and_email_alias_for_same_user(self):
        user = User.objects.create_user(username="alias_user_1", password="Correct12345", email="alias01@abc.com")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "3",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
            },
            clear=False,
        ):
            for input_username in ("alias_user_1", "alias01@abc.com", "alias_user_1"):
                res = self.client.post(
                    "/login",
                    data={"username": input_username, "password": "wrong"},
                    REMOTE_ADDR="3.3.3.3",
                )
                self.assertEqual(res.status_code, 200)
                body = json.loads(res.content.decode("utf-8"))
                self.assertEqual(body.get("code"), 0)

            blocked = self.client.post(
                "/login",
                data={"username": "alias_user_1", "password": "Correct12345"},
                REMOTE_ADDR="3.3.3.3",
            )
            body_blocked = json.loads(blocked.content.decode("utf-8"))
            self.assertEqual(body_blocked.get("code"), 0, msg=body_blocked)

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(source_ip="3.3.3.3").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "username", "")), f"user:{user.id}")

    def test_lockout_uses_xff_when_explicitly_enabled(self):
        User.objects.create_user(username="xff_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_u1", "password": "wrong"},
                REMOTE_ADDR="10.10.10.10",
                HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "1.1.1.1")

    def test_lockout_uses_remote_addr_when_xff_trust_disabled(self):
        User.objects.create_user(username="xff_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "0",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_u2", "password": "wrong"},
                REMOTE_ADDR="10.10.10.11",
                HTTP_X_FORWARDED_FOR="1.1.1.2, 2.2.2.3",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "10.10.10.11")

    def test_success_login_clears_current_ip_only_by_default(self):
        user = User.objects.create_user(username="clr1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "5",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_CLEAR_ALL_IPS_ON_SUCCESS": "0",
            },
            clear=False,
        ):
            _ = self.client.post("/login", data={"username": "clr1", "password": "wrong"}, REMOTE_ADDR="10.0.0.1")
            _ = self.client.post("/login", data={"username": "clr1", "password": "wrong"}, REMOTE_ADDR="10.0.0.2")
            ok = self.client.post("/login", data={"username": "clr1", "password": "Correct12345"}, REMOTE_ADDR="10.0.0.1")
            ok_body = json.loads(ok.content.decode("utf-8"))
            self.assertEqual(ok_body.get("code"), 1000, msg=ok_body)

        from app.models import LoginLockout

        key = f"user:{user.id}"
        self.assertEqual(LoginLockout.objects.filter(username=key, source_ip="10.0.0.1").count(), 0)
        self.assertEqual(LoginLockout.objects.filter(username=key, source_ip="10.0.0.2").count(), 1)

    def test_success_login_can_clear_all_ips_when_enabled(self):
        user = User.objects.create_user(username="clr2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "5",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_CLEAR_ALL_IPS_ON_SUCCESS": "1",
            },
            clear=False,
        ):
            _ = self.client.post("/login", data={"username": "clr2", "password": "wrong"}, REMOTE_ADDR="10.0.1.1")
            _ = self.client.post("/login", data={"username": "clr2", "password": "wrong"}, REMOTE_ADDR="10.0.1.2")
            ok = self.client.post("/login", data={"username": "clr2", "password": "Correct12345"}, REMOTE_ADDR="10.0.1.1")
            ok_body = json.loads(ok.content.decode("utf-8"))
            self.assertEqual(ok_body.get("code"), 1000, msg=ok_body)

        from app.models import LoginLockout

        key = f"user:{user.id}"
        self.assertEqual(LoginLockout.objects.filter(username=key).count(), 0)

    def test_lockout_uses_x_real_ip_when_enabled(self):
        User.objects.create_user(username="realip_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "realip_u1", "password": "wrong"},
                REMOTE_ADDR="10.20.30.40",
                HTTP_X_REAL_IP="7.7.7.7",
                HTTP_X_FORWARDED_FOR="1.1.1.1",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "7.7.7.7")

    def test_lockout_uses_remote_addr_when_x_real_ip_disabled(self):
        User.objects.create_user(username="realip_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "0",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "realip_u2", "password": "wrong"},
                REMOTE_ADDR="10.20.30.41",
                HTTP_X_REAL_IP="7.7.7.8",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "10.20.30.41")

    def test_stale_lockout_row_is_gced_before_new_attempt(self):
        from datetime import timedelta
        from django.utils import timezone
        from app.models import LoginLockout

        user = User.objects.create_user(username="gc_u1", password="Correct12345")
        key = f"user:{user.id}"
        now_ts = timezone.now()
        stale = LoginLockout.objects.create(
            username=key,
            source_ip="11.11.11.11",
            failures=9,
            first_failure_at=now_ts - timedelta(days=40),
            last_failure_at=now_ts - timedelta(days=40),
            locked_until=now_ts - timedelta(days=39),
        )

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "5",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS": str(3600),
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "gc_u1", "password": "wrong"},
                REMOTE_ADDR="11.11.11.11",
            )

        current = LoginLockout.objects.filter(username=key, source_ip="11.11.11.11").order_by("-id").first()
        self.assertIsNotNone(current)
        self.assertNotEqual(int(current.id), int(stale.id))
        self.assertEqual(int(getattr(current, "failures", 0) or 0), 1)

    def test_stale_lockout_alias_rows_are_gced_before_new_attempt(self):
        from datetime import timedelta
        from django.utils import timezone
        from app.models import LoginLockout

        user = User.objects.create_user(
            username="gc_alias_u1",
            password="Correct12345",
            email="gc_alias_u1@example.com",
        )
        now_ts = timezone.now()
        stale = LoginLockout.objects.create(
            username="gc_alias_u1@example.com",
            source_ip="11.11.11.12",
            failures=7,
            first_failure_at=now_ts - timedelta(days=40),
            last_failure_at=now_ts - timedelta(days=40),
            locked_until=now_ts - timedelta(days=39),
        )

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "5",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS": str(3600),
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "gc_alias_u1@example.com", "password": "wrong"},
                REMOTE_ADDR="11.11.11.12",
            )

        current = LoginLockout.objects.filter(username=f"user:{user.id}", source_ip="11.11.11.12").order_by("-id").first()
        self.assertIsNotNone(current)
        self.assertEqual(int(getattr(current, "failures", 0) or 0), 1)
        self.assertEqual(
            LoginLockout.objects.filter(username="gc_alias_u1@example.com", source_ip="11.11.11.12").count(),
            0,
        )
        self.assertFalse(LoginLockout.objects.filter(id=stale.id).exists())

    def test_lockout_ignores_invalid_xff_and_falls_back_remote_addr(self):
        User.objects.create_user(username="ipvalid_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "ipvalid_u1", "password": "wrong"},
                REMOTE_ADDR="12.12.12.12",
                HTTP_X_FORWARDED_FOR="not-an-ip",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "12.12.12.12")

    def test_lockout_accepts_xff_ipv4_with_port_when_enabled(self):
        User.objects.create_user(username="ipport_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "ipport_u1", "password": "wrong"},
                REMOTE_ADDR="12.12.12.20",
                HTTP_X_FORWARDED_FOR="21.21.21.21:4567",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "21.21.21.21")

    def test_lockout_uses_first_valid_ip_from_xff_list(self):
        User.objects.create_user(username="xff_valid_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_valid_u1", "password": "wrong"},
                REMOTE_ADDR="12.12.12.22",
                HTTP_X_FORWARDED_FOR="unknown, 22.22.22.22, 23.23.23.23",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "22.22.22.22")

    def test_lockout_accepts_quoted_x_real_ip(self):
        User.objects.create_user(username="realip_q_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "realip_q_u1", "password": "wrong"},
                REMOTE_ADDR="12.12.12.23",
                HTTP_X_REAL_IP='"24.24.24.24"',
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "24.24.24.24")

    def test_lockout_accepts_nested_quoted_x_real_ip(self):
        User.objects.create_user(username="realip_q_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "realip_q_u2", "password": "wrong"},
                REMOTE_ADDR="12.12.12.26",
                HTTP_X_REAL_IP='\'"24.24.24.25"\'',
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "24.24.24.25")

    def test_lockout_accepts_nested_quoted_xff_token(self):
        User.objects.create_user(username="xff_q_u3", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_q_u3", "password": "wrong"},
                REMOTE_ADDR="12.12.12.27",
                HTTP_X_FORWARDED_FOR='\'"25.25.25.26"\'',
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "25.25.25.26")

    def test_lockout_ignores_oversized_xff_token_and_falls_back_remote_addr(self):
        User.objects.create_user(username="xff_big_u1", password="Correct12345")
        oversized = "9" * 300

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_big_u1", "password": "wrong"},
                REMOTE_ADDR="25.25.25.25",
                HTTP_X_FORWARDED_FOR=f"{oversized},26.26.26.26",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "26.26.26.26")

    def test_lockout_uses_forwarded_for_when_enabled(self):
        User.objects.create_user(username="fwd_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_FORWARDED": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "fwd_u1", "password": "wrong"},
                REMOTE_ADDR="27.27.27.27",
                HTTP_FORWARDED="for=31.31.31.31;proto=https;by=10.0.0.1",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "31.31.31.31")

    def test_lockout_xff_max_hops_limits_scan_range(self):
        User.objects.create_user(username="xff_hops_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
                "BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_hops_u1", "password": "wrong"},
                REMOTE_ADDR="28.28.28.28",
                HTTP_X_FORWARDED_FOR="unknown, 32.32.32.32",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        # second token is out of scan range (max_hops=1), fallback to remote addr.
        self.assertEqual(str(getattr(row, "source_ip", "")), "28.28.28.28")

    def test_lockout_xff_max_hops_counts_quoted_comma_as_single_hop(self):
        User.objects.create_user(username="xff_hops_q_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
                "BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS": "2",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_hops_q_u1", "password": "wrong"},
                REMOTE_ADDR="28.28.28.30",
                HTTP_X_FORWARDED_FOR='"unknown,still-unknown", 33.33.33.33',
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "33.33.33.33")

    def test_lockout_xff_max_hops_handles_escaped_quote_in_quoted_hop(self):
        User.objects.create_user(username="xff_hops_q_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
                "BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS": "2",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "xff_hops_q_u2", "password": "wrong"},
                REMOTE_ADDR="28.28.28.32",
                HTTP_X_FORWARDED_FOR='"bad\\",still", 35.35.35.35',
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "35.35.35.35")

    def test_lockout_xff_max_hops_env_is_clamped(self):
        from app.views import web

        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS": "0"}, clear=False):
            self.assertEqual(web._login_lockout_xff_max_hops(), 1)
        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS": "999"}, clear=False):
            self.assertEqual(web._login_lockout_xff_max_hops(), 64)

    def test_lockout_forwarded_max_hops_limits_scan_range(self):
        User.objects.create_user(username="fwd_hops_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_FORWARDED": "1",
                "BEACON_LOGIN_LOCKOUT_FORWARDED_MAX_HOPS": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "fwd_hops_u1", "password": "wrong"},
                REMOTE_ADDR="28.28.28.29",
                HTTP_FORWARDED="for=unknown;proto=https, for=32.32.32.33;proto=https",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        # second hop is out of scan range (max_hops=1), fallback to remote addr.
        self.assertEqual(str(getattr(row, "source_ip", "")), "28.28.28.29")

    def test_lockout_forwarded_max_hops_counts_quoted_comma_as_single_hop(self):
        User.objects.create_user(username="fwd_hops_q_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_FORWARDED": "1",
                "BEACON_LOGIN_LOCKOUT_FORWARDED_MAX_HOPS": "2",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "fwd_hops_q_u1", "password": "wrong"},
                REMOTE_ADDR="28.28.28.31",
                HTTP_FORWARDED='for="unknown,still";proto=https, for=34.34.34.34;proto=https',
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "34.34.34.34")

    def test_lockout_forwarded_max_hops_env_is_clamped(self):
        from app.views import web

        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_FORWARDED_MAX_HOPS": "0"}, clear=False):
            self.assertEqual(web._login_lockout_forwarded_max_hops(), 1)
        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_FORWARDED_MAX_HOPS": "999"}, clear=False):
            self.assertEqual(web._login_lockout_forwarded_max_hops(), 64)

    def test_lockout_ignores_forwarded_when_not_enabled(self):
        User.objects.create_user(username="fwd_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_FORWARDED": "0",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "fwd_u2", "password": "wrong"},
                REMOTE_ADDR="27.27.27.28",
                HTTP_FORWARDED="for=31.31.31.32;proto=https",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "27.27.27.28")

    def test_lockout_ignores_invalid_x_real_ip_and_uses_xff(self):
        User.objects.create_user(username="ipvalid_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "1",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "ipvalid_u2", "password": "wrong"},
                REMOTE_ADDR="12.12.12.13",
                HTTP_X_REAL_IP="bad-real-ip",
                HTTP_X_FORWARDED_FOR="13.13.13.13",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "13.13.13.13")

    def test_lockout_accepts_x_real_ip_ipv6_with_port_when_enabled(self):
        User.objects.create_user(username="ipport_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "ipport_u2", "password": "wrong"},
                REMOTE_ADDR="12.12.12.21",
                HTTP_X_REAL_IP="[2001:db8::12]:443",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "2001:db8::12")

    def test_lockout_accepts_x_real_ip_ipv6_with_zone_id_when_enabled(self):
        User.objects.create_user(username="ipzone_u1", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "ipzone_u1", "password": "wrong"},
                REMOTE_ADDR="12.12.12.24",
                HTTP_X_REAL_IP="fe80::abcd%eth0",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "fe80::abcd")

    def test_lockout_accepts_xff_ipv6_with_zone_id_when_enabled(self):
        User.objects.create_user(username="ipzone_u2", password="Correct12345")

        with mock.patch.dict(
            os.environ,
            {
                "BEACON_LOGIN_LOCKOUT_ENABLED": "1",
                "BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS": "1",
                "BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS": "300",
                "BEACON_LOGIN_LOCKOUT_SECONDS": "60",
                "BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR": "1",
            },
            clear=False,
        ):
            _ = self.client.post(
                "/login",
                data={"username": "ipzone_u2", "password": "wrong"},
                REMOTE_ADDR="12.12.12.25",
                HTTP_X_FORWARDED_FOR="fe80::dcba%ens18",
            )

        from app.models import LoginLockout

        row = LoginLockout.objects.filter(username__startswith="user:").order_by("-id").first()
        self.assertIsNotNone(row)
        self.assertEqual(str(getattr(row, "source_ip", "")), "fe80::dcba")

    def test_login_accepts_nfkc_normalized_username(self):
        User.objects.create_user(username="nfkc_user1", password="Correct12345")
        full_width = "ｎｆｋｃ＿ｕｓｅｒ１"

        res = self.client.post(
            "/login",
            data={"username": full_width, "password": "Correct12345"},
            REMOTE_ADDR="14.14.14.14",
        )
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

    def test_login_accepts_email_case_insensitive(self):
        User.objects.create_user(username="email_case_u1", password="Correct12345", email="CaseUser@Example.com")

        res = self.client.post(
            "/login",
            data={"username": "caseuser@example.COM", "password": "Correct12345"},
            REMOTE_ADDR="14.14.14.15",
        )
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

    def test_login_accepts_username_case_insensitive(self):
        User.objects.create_user(username="CaseUserLogin1", password="Correct12345")

        res = self.client.post(
            "/login",
            data={"username": "caseuserlogin1", "password": "Correct12345"},
            REMOTE_ADDR="14.14.14.16",
        )
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

    def test_lockout_retention_seconds_default_and_invalid_fallback(self):
        from app.views import web

        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS": ""}, clear=False):
            self.assertEqual(web._login_lockout_retention_seconds(), 30 * 24 * 3600)

        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS": "not-a-number"}, clear=False):
            self.assertEqual(web._login_lockout_retention_seconds(), 30 * 24 * 3600)

    def test_lockout_retention_seconds_is_clamped_to_min_and_max(self):
        from app.views import web

        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS": "30"}, clear=False):
            self.assertEqual(web._login_lockout_retention_seconds(), 3600)

        with mock.patch.dict(os.environ, {"BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS": str(999999999)}, clear=False):
            self.assertEqual(web._login_lockout_retention_seconds(), 365 * 24 * 3600)
