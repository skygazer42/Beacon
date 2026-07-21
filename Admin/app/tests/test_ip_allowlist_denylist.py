import os
from unittest import mock

from django.test import TestCase


class OpenApiIpPolicyTest(TestCase):
    def test_openapi_allowlist_blocks_non_matching_ip_even_with_token(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_IP_ALLOWLIST": "1.2.3.0/24",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res.status_code, 403, msg=res.content)

    def test_openapi_allowlist_allows_matching_ip(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_IP_ALLOWLIST": "1.2.3.0/24",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="1.2.3.4", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_openapi_denylist_blocks_matching_ip(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_OPEN_API_TOKEN": "t1",
                "BEACON_OPEN_API_IP_DENYLIST": "8.8.8.8/32",
            },
            clear=False,
        ):
            res = self.client.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN="t1")
        self.assertEqual(res.status_code, 403, msg=res.content)


class AdminLoginIpPolicyTest(TestCase):
    def test_login_allowlist_blocks_non_matching_ip(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_ADMIN_IP_ALLOWLIST": "1.2.3.0/24",
            },
            clear=False,
        ):
            res = self.client.get("/login", REMOTE_ADDR="8.8.8.8")
        self.assertEqual(res.status_code, 403, msg=res.content)

    def test_login_allowlist_allows_matching_ip(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_ADMIN_IP_ALLOWLIST": "1.2.3.0/24",
            },
            clear=False,
        ):
            res = self.client.get("/login", REMOTE_ADDR="1.2.3.4")
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_login_allowlist_invalid_cidr_fails_closed(self):
        with mock.patch.dict(
            os.environ,
            {
                "BEACON_ADMIN_IP_ALLOWLIST": "bad-cidr",
            },
            clear=False,
        ):
            res = self.client.get("/login", REMOTE_ADDR="1.2.3.4")
        self.assertEqual(res.status_code, 403, msg=res.content)

