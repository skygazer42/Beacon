import json
import os
import sys
import types
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from app.utils import LdapAuth


class LdapAuthUnitTest(SimpleTestCase):
    def _install_fake_ldap3(self, *, bind_email="user@example.com", found_dn="uid=alice,dc=example"):
        ldap3_mod = types.ModuleType("ldap3")
        ldap3_mod.AUTO_BIND_TLS_BEFORE_BIND = 1
        ldap3_mod.AUTO_BIND_NO_TLS = 0
        ldap3_mod.NONE = object()
        ldap3_mod.BASE = object()

        class _TLS:
            def __init__(self, validate=None, version=None):
                self.validate = validate
                self.version = version

        class _Server:
            def __init__(self, url, use_ssl=False, tls=None, connect_timeout=None, get_info=None):
                self.url = url
                self.use_ssl = use_ssl
                self.tls = tls
                self.connect_timeout = connect_timeout
                self.get_info = get_info

        class _Attr:
            def __init__(self, value):
                self.value = value

        class _Entry:
            def __init__(self, dn, email_attr, email_value):
                self.entry_dn = dn
                self._attrs = {email_attr: _Attr(email_value)}

            def __contains__(self, key):
                return key in self._attrs

            def __getitem__(self, key):
                return self._attrs[key]

        class _Connection:
            def __init__(self, server, user="", password="", auto_bind=None):
                self.server = server
                self.user = user
                self.password = password
                self.auto_bind = auto_bind
                self.entries = []

            def search(self, base, _filter, search_scope=None, attributes=None, size_limit=None):
                email_attr = (attributes or ["mail"])[0]
                self.entries = [_Entry(found_dn if "dc=" in str(base) else base, email_attr, bind_email)]

        ldap3_mod.TLS = _TLS
        ldap3_mod.Server = _Server
        ldap3_mod.Connection = _Connection

        utils_mod = types.ModuleType("ldap3.utils")
        conv_mod = types.ModuleType("ldap3.utils.conv")
        conv_mod.escape_filter_chars = lambda value: str(value).replace("*", r"\2a")
        utils_mod.conv = conv_mod
        return ldap3_mod, utils_mod, conv_mod

    def test_authenticate_is_disabled_by_default(self):
        env = {
            "BEACON_LDAP_ENABLED": "",
            "BEACON_LDAP_URL": "",
            "BEACON_LDAP_USER_DN_TEMPLATE": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            ok, info = LdapAuth.authenticate("alice", "pwd")

        self.assertFalse(ok)
        self.assertEqual(info.get("reason"), "disabled")

    def test_authenticate_supports_direct_bind(self):
        ldap3_mod, utils_mod, conv_mod = self._install_fake_ldap3(bind_email="a@example.com")
        with (
            mock.patch.dict(sys.modules, {"ldap3": ldap3_mod, "ldap3.utils": utils_mod, "ldap3.utils.conv": conv_mod}),
            mock.patch.dict(
                os.environ,
                {
                    "BEACON_LDAP_ENABLED": "1",
                    "BEACON_LDAP_URL": "ldap://ldap.example",
                    "BEACON_LDAP_USER_DN_TEMPLATE": "uid={username},dc=example",
                    "BEACON_LDAP_EMAIL_ATTR": "mail",
                },
                clear=False,
            ),
        ):
            ok, info = LdapAuth.authenticate("alice", "pwd")

        self.assertTrue(ok, msg=info)
        self.assertEqual(info.get("username"), "alice")
        self.assertEqual(info.get("email"), "a@example.com")
        self.assertIn("dn", info)

    def test_search_bind_rejects_missing_bind_configuration(self):
        ldap3_mod, utils_mod, conv_mod = self._install_fake_ldap3()
        with (
            mock.patch.dict(sys.modules, {"ldap3": ldap3_mod, "ldap3.utils": utils_mod, "ldap3.utils.conv": conv_mod}),
            mock.patch.dict(
                os.environ,
                {
                    "BEACON_LDAP_ENABLED": "1",
                    "BEACON_LDAP_URL": "ldap://ldap.example",
                    "BEACON_LDAP_USER_DN_TEMPLATE": "",
                    "BEACON_LDAP_BIND_DN": "",
                    "BEACON_LDAP_BIND_PASSWORD": "",
                    "BEACON_LDAP_SEARCH_BASE": "",
                },
                clear=False,
            ),
        ):
            ok, info = LdapAuth.authenticate("alice", "pwd")

        self.assertFalse(ok)
        self.assertEqual(info.get("reason"), "missing_bind_config")


class LdapLoginTest(TestCase):
    def _post_login(self, **data):
        res = self.client.post("/login", data=data)
        self.assertEqual(res.status_code, 200)
        return json.loads(res.content.decode("utf-8"))

    def test_login_falls_back_to_ldap_when_user_not_found(self):
        """
        Roadmap: 100x-4 LDAP/AD 登录

        Minimal acceptance for repo evidence:
        - /login can fall back to LDAP when local user does not exist
        - successful LDAP auth can auto-provision a local Django user
        """
        fake_ldap = mock.Mock()
        fake_ldap.is_enabled.return_value = True
        fake_ldap.authenticate.return_value = (True, {"username": "u1", "email": "u1@example.com"})

        with (
            mock.patch("app.views.web._is_login_captcha_enabled", return_value=False),
            mock.patch("app.views.web.LdapAuth", fake_ldap, create=True),
        ):
            data = self._post_login(username="u1", password="ldap_pw")

        self.assertEqual(data.get("code"), 1000, msg=data)
        user = User.objects.filter(username="u1").first()
        self.assertIsNotNone(user, "Expected LDAP auto-provisioned user")
        self.assertEqual(str(getattr(user, "email", "") or ""), "u1@example.com")

    def test_login_falls_back_to_ldap_when_local_password_wrong(self):
        User.objects.create_user(username="u2", password="local_pw", email="u2@local")

        fake_ldap = mock.Mock()
        fake_ldap.is_enabled.return_value = True
        fake_ldap.authenticate.return_value = (True, {"username": "u2", "email": "u2@example.com"})

        with (
            mock.patch("app.views.web._is_login_captcha_enabled", return_value=False),
            mock.patch("app.views.web.LdapAuth", fake_ldap, create=True),
        ):
            data = self._post_login(username="u2", password="ldap_pw")

        self.assertEqual(data.get("code"), 1000, msg=data)
        user = User.objects.filter(username="u2").first()
        self.assertIsNotNone(user)
        # Email should be best-effort updated on successful LDAP login.
        self.assertEqual(str(getattr(user, "email", "") or ""), "u2@example.com")

    def test_ldap_login_stores_canonical_username_in_session(self):
        User.objects.create_user(username="u3", password="local_pw", email="u3@local")

        fake_ldap = mock.Mock()
        fake_ldap.is_enabled.return_value = True
        fake_ldap.authenticate.return_value = (True, {"username": "u3", "email": "u3@example.com"})

        with (
            mock.patch("app.views.web._is_login_captcha_enabled", return_value=False),
            mock.patch("app.views.web.LdapAuth", fake_ldap, create=True),
        ):
            data = self._post_login(username="alias_u3", password="ldap_pw")

        self.assertEqual(data.get("code"), 1000, msg=data)
        session_user = self.client.session.get("user") or {}
        self.assertEqual(str(session_user.get("username") or ""), "u3")

    def test_ldap_login_links_existing_user_by_email_case_insensitive(self):
        existing = User.objects.create_user(
            username="local_u4",
            password="local_pw",
            email="CaseUser4@Example.com",
        )

        fake_ldap = mock.Mock()
        fake_ldap.is_enabled.return_value = True
        fake_ldap.authenticate.return_value = (True, {"username": "ldap_u4", "email": "caseuser4@example.COM"})

        with (
            mock.patch("app.views.web._is_login_captcha_enabled", return_value=False),
            mock.patch("app.views.web.LdapAuth", fake_ldap, create=True),
        ):
            data = self._post_login(username="alias_u4", password="ldap_pw")

        self.assertEqual(data.get("code"), 1000, msg=data)
        self.assertEqual(User.objects.filter(email__iexact="caseuser4@example.com").count(), 1)
        session_user = self.client.session.get("user") or {}
        self.assertEqual(int(session_user.get("id") or 0), int(existing.id))

    def test_ldap_login_links_existing_user_by_username_case_insensitive(self):
        existing = User.objects.create_user(
            username="LocalU5",
            password="local_pw",
            email="localu5@example.com",
        )

        fake_ldap = mock.Mock()
        fake_ldap.is_enabled.return_value = True
        fake_ldap.authenticate.return_value = (True, {"username": "localu5", "email": "localu5@example.com"})

        with (
            mock.patch("app.views.web._is_login_captcha_enabled", return_value=False),
            mock.patch("app.views.web.LdapAuth", fake_ldap, create=True),
        ):
            data = self._post_login(username="alias_u5", password="ldap_pw")

        self.assertEqual(data.get("code"), 1000, msg=data)
        self.assertEqual(User.objects.filter(username__iexact="localu5").count(), 1)
        session_user = self.client.session.get("user") or {}
        self.assertEqual(int(session_user.get("id") or 0), int(existing.id))
