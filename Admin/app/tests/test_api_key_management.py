import json
import os

from django.contrib.auth.models import User
from django.test import Client
from django.test import TestCase

from app.models import ApiKey


class ApiKeyManagementTest(TestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("BEACON_OPEN_API_TOKEN", None)
        self.addCleanup(os.environ.pop, "BEACON_OPEN_API_TOKEN", None)

        os.environ["BEACON_API_KEY_PEPPER"] = "pepper-test"
        self.addCleanup(os.environ.pop, "BEACON_API_KEY_PEPPER", None)

    def _login_as(self, user: User):
        session = self.client.session
        session["user"] = {"id": user.id, "username": user.username}
        session.save()

    def test_create_list_revoke_api_key(self):
        admin = User.objects.create_user(username="admin", password="pass12345")
        admin.is_staff = True
        admin.save()
        self._login_as(admin)

        create = self.client.post(
            "/api/app-shell/ops/action/apikeys/create",
            data={
                "name": "k1",
                "scopes": json.dumps(["ops"], ensure_ascii=False),
                "expires_days": "1",
                "rate_limit_per_minute": "15",
                "burst_limit": "3",
            },
        )
        self.assertEqual(create.status_code, 200, msg=create.content)
        body = json.loads(create.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        data = body.get("data") or {}
        key_id = int(data.get("id") or 0)
        token = str(data.get("token") or "")
        self.assertTrue(key_id > 0, msg=body)
        self.assertTrue(len(token) >= 16, msg=body)

        # Newly created key should work for ops endpoints (without a web session).
        anon = Client()
        res = anon.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token)
        self.assertEqual(res.status_code, 200, msg=res.content)

        listing = self.client.post("/api/app-shell/ops/action/apikeys/list", data={})
        self.assertEqual(listing.status_code, 200, msg=listing.content)
        listing_body = json.loads(listing.content.decode("utf-8"))
        self.assertEqual(listing_body.get("code"), 1000, msg=listing_body)
        items = listing_body.get("data") or []
        self.assertTrue(any(int(it.get("id") or 0) == key_id for it in items), msg=items)
        row = next(it for it in items if int(it.get("id") or 0) == key_id)
        self.assertEqual(int(row.get("rate_limit_per_minute") or 0), 15)
        self.assertEqual(int(row.get("burst_limit") or 0), 3)

        # List must never leak plaintext token.
        self.assertNotIn(token, listing.content.decode("utf-8"))

        revoke = self.client.post("/api/app-shell/ops/action/apikeys/revoke", data={"id": str(key_id)})
        self.assertEqual(revoke.status_code, 200, msg=revoke.content)
        revoke_body = json.loads(revoke.content.decode("utf-8"))
        self.assertEqual(revoke_body.get("code"), 1000, msg=revoke_body)

        # Revoked key should stop working immediately.
        res2 = anon.get("/healthz", REMOTE_ADDR="8.8.8.8", HTTP_X_BEACON_TOKEN=token)
        self.assertEqual(res2.status_code, 401, msg=res2.content)

    def test_admin_can_rotate_api_key(self):
        admin = User.objects.create_user(username="rotate-admin", password="pass12345", is_staff=True)
        self._login_as(admin)
        key = ApiKey.objects.create(
            name="rotate-me",
            token_prefix="oldtoken",
            token_hash="a" * 64,
            enabled=False,
        )

        response = self.client.post(
            "/api/app-shell/ops/action/apikeys/rotate",
            data={"id": str(key.id)},
        )
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(payload.get("code"), 1000, msg=payload)
        self.assertTrue(str((payload.get("data") or {}).get("token") or ""))
        key.refresh_from_db()
        self.assertTrue(key.enabled)
        self.assertNotEqual(key.token_hash, "a" * 64)

    def test_non_admin_cannot_rotate_api_key(self):
        viewer = User.objects.create_user(username="rotate-viewer", password="pass12345")
        self._login_as(viewer)
        key = ApiKey.objects.create(
            name="protected-key",
            token_prefix="oldtoken",
            token_hash="b" * 64,
        )

        response = self.client.post(
            "/api/app-shell/ops/action/apikeys/rotate",
            data={"id": str(key.id)},
        )
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(payload.get("code"), 403, msg=payload)
        key.refresh_from_db()
        self.assertEqual(key.token_hash, "b" * 64)
