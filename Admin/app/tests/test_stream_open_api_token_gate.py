import json
import os
from django.test import Client, TestCase
from unittest import mock

from app.models import Stream


class StreamOpenApiTokenGateTest(TestCase):
    def _remote_headers(self, token: str | None = None):
        headers = {"REMOTE_ADDR": "8.8.8.8"}
        if token is not None:
            headers["HTTP_X_BEACON_TOKEN"] = token
        return headers

    def _strict_client(self, *, logged_in: bool = False) -> Client:
        client = Client(enforce_csrf_checks=True)
        if logged_in:
            session = client.session
            session["user"] = {"id": 1, "username": "tester"}
            session.save()
        return client

    def test_stream_open_add_and_del_require_openapi_token_for_machine_calls(self):
        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "token-stream-open"}, clear=False):
            res_unauth_add = self.client.post(
                "/stream/openAdd",
                data={
                    "code": "cam_open_1",
                    "pull_stream_url": "rtsp://127.0.0.1/live/stream001",
                    "pull_stream_type": "1",
                    "nickname": "Cam 1",
                    "remark": "r1",
                    "app": "live",
                },
                **self._remote_headers(),
            )

        self.assertEqual(res_unauth_add.status_code, 401, msg=res_unauth_add.content)
        body_unauth_add = json.loads(res_unauth_add.content.decode("utf-8"))
        self.assertEqual(body_unauth_add.get("code"), 0, msg=body_unauth_add)
        self.assertEqual(body_unauth_add.get("msg"), "unauthorized", msg=body_unauth_add)
        self.assertFalse(Stream.objects.filter(code="cam_open_1").exists())

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "token-stream-open"}, clear=False):
            res_add = self.client.post(
                "/stream/openAdd",
                data={
                    "code": "cam_open_1",
                    "pull_stream_url": "rtsp://127.0.0.1/live/stream001",
                    "pull_stream_type": "1",
                    "nickname": "Cam 1",
                    "remark": "r1",
                    "app": "live",
                },
                **self._remote_headers(token="token-stream-open"),
            )

        self.assertEqual(res_add.status_code, 200, msg=res_add.content)
        body_add = json.loads(res_add.content.decode("utf-8"))
        self.assertEqual(body_add.get("code"), 1000, msg=body_add)
        self.assertEqual(body_add.get("msg"), "添加成功", msg=body_add)
        self.assertTrue(Stream.objects.filter(code="cam_open_1").exists())

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "token-stream-open"}, clear=False):
            res_unauth_del = self.client.post(
                "/stream/openDel",
                data={"handle": "one", "code": "cam_open_1"},
                **self._remote_headers(),
            )

        self.assertEqual(res_unauth_del.status_code, 401, msg=res_unauth_del.content)
        body_unauth_del = json.loads(res_unauth_del.content.decode("utf-8"))
        self.assertEqual(body_unauth_del.get("code"), 0, msg=body_unauth_del)
        self.assertEqual(body_unauth_del.get("msg"), "unauthorized", msg=body_unauth_del)
        self.assertTrue(Stream.objects.filter(code="cam_open_1").exists())

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "token-stream-open"}, clear=False):
            with mock.patch("app.views.StreamView.stop_forward_for_stream", return_value=None, create=True):
                res_del = self.client.post(
                    "/stream/openDel",
                    data={"handle": "one", "code": "cam_open_1"},
                    **self._remote_headers(token="token-stream-open"),
                )

        self.assertEqual(res_del.status_code, 200, msg=res_del.content)
        body_del = json.loads(res_del.content.decode("utf-8"))
        self.assertEqual(body_del.get("code"), 1000, msg=body_del)
        self.assertEqual(body_del.get("msg"), "删除成功", msg=body_del)
        self.assertFalse(Stream.objects.filter(code="cam_open_1").exists())

    def test_logged_in_session_does_not_bypass_csrf_for_stream_open_post(self):
        client = self._strict_client(logged_in=True)

        with mock.patch.dict(os.environ, {"BEACON_OPEN_API_TOKEN": "token-stream-open"}, clear=False):
            res = client.post(
                "/stream/openAdd",
                data={
                    "code": "cam_open_1",
                    "pull_stream_url": "rtsp://127.0.0.1/live/stream001",
                    "pull_stream_type": "1",
                    "nickname": "Cam 1",
                    "remark": "r1",
                    "app": "live",
                },
                **self._remote_headers(token="token-stream-open"),
            )

        self.assertEqual(res.status_code, 403, msg=res.content)
        self.assertIn(b"CSRF", res.content)
        self.assertFalse(Stream.objects.filter(code="cam_open_1").exists())
