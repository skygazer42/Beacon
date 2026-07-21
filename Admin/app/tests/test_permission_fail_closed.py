import json
from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from app.middleware import SimpleMiddleware


class PermissionFailClosedTest(TestCase):
    def test_permission_resolution_exception_denies_access(self):
        rf = RequestFactory()
        req = rf.get(
            "/stream/index",
            REMOTE_ADDR="8.8.8.8",
            HTTP_ACCEPT="application/json",
        )
        req.session = {"user": {"id": 1}}

        mw = SimpleMiddleware(get_response=lambda r: HttpResponse("ok"))
        with mock.patch("app.models.UserPermission.objects.filter", side_effect=Exception("db down")):
            res = mw.process_request(req)

        self.assertIsNotNone(res)
        self.assertEqual(res.status_code, 403, msg=getattr(res, "content", b""))
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 403, msg=body)
