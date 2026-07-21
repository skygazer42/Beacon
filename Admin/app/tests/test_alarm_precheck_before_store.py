import base64
import json
import os
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from app.models import Alarm
from app.utils import AlarmPrecheck


class AlarmPrecheckBeforeStoreTest(TestCase):
    def setUp(self):
        super().setUp()
        os.environ["BEACON_OPEN_API_TOKEN"] = "token-precheck"
        self.addCleanup(os.environ.pop, "BEACON_OPEN_API_TOKEN", None)

    def test_open_alarm_upload_can_be_filtered_by_precheck(self):
        from app.views import api as api_view

        with tempfile.TemporaryDirectory() as tmp:
            old_upload = getattr(api_view.g_config, "uploadDir", "")
            api_view.g_config.uploadDir = tmp
            try:
                payload = {
                    "control_code": "C001",
                    "desc": "precheck filter",
                    "image_base64": base64.b64encode(b"img-bytes-precheck").decode("utf-8"),
                    "image_ext": "jpg",
                }

                with (
                    mock.patch.object(api_view.g_config, "alarmPrecheckEnabled", True, create=True),
                    mock.patch.object(api_view.g_config, "alarmPrecheckUrl", "http://127.0.0.1:18080/precheck", create=True),
                    mock.patch.object(api_view.g_config, "alarmPrecheckFailOpen", False, create=True),
                    mock.patch("requests.post") as mocked_post,
                ):
                    mocked_post.return_value.status_code = 200
                    mocked_post.return_value.json.return_value = {
                        "code": 1000,
                        "msg": "success",
                        "result": {"allow": False, "reason": "blocked"},
                    }

                    res = self.client.post(
                        "/open/alarm/upload",
                        data=json.dumps(payload),
                        content_type="application/json",
                        HTTP_X_BEACON_TOKEN="token-precheck",
                    )
            finally:
                api_view.g_config.uploadDir = old_upload

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        self.assertEqual((body.get("data") or {}).get("stored"), False, msg=body)
        self.assertEqual(Alarm.objects.count(), 0)

    def test_strict_precheck_fails_closed_for_transport_and_response_failures(self):
        config = SimpleNamespace(
            alarmPrecheckEnabled=True,
            alarmPrecheckUrl="http://127.0.0.1/precheck",
            alarmPrecheckFailOpen=False,
            alarmPrecheckTimeoutSeconds=3,
            code="node-1",
        )

        with mock.patch("app.utils.AlarmPrecheck.requests.post", side_effect=RuntimeError("offline")):
            self.assertEqual(
                AlarmPrecheck.should_store_alarm(config, control_code="c1", desc="alarm"),
                (False, "precheck error: offline"),
            )

        unavailable = SimpleNamespace(status_code=503, json=lambda: {}, text="")
        with mock.patch("app.utils.AlarmPrecheck.requests.post", return_value=unavailable):
            self.assertEqual(
                AlarmPrecheck.should_store_alarm(config, control_code="c1", desc="alarm"),
                (False, "precheck http=503"),
            )

        invalid = SimpleNamespace(status_code=200, json=lambda: {"result": {}}, text="")
        with mock.patch("app.utils.AlarmPrecheck.requests.post", return_value=invalid):
            self.assertEqual(
                AlarmPrecheck.should_store_alarm(config, control_code="c1", desc="alarm"),
                (False, "precheck invalid response"),
            )

    def test_strict_precheck_honors_explicit_deny_and_allow(self):
        config = SimpleNamespace(
            alarmPrecheckEnabled=True,
            alarmPrecheckUrl="http://127.0.0.1/precheck",
            alarmPrecheckFailOpen=False,
            alarmPrecheckTimeoutSeconds=3,
            code="node-1",
        )
        denied = SimpleNamespace(
            status_code=200,
            json=lambda: {"result": {"allow": False, "reason": "blocked"}},
            text="",
        )
        with mock.patch("app.utils.AlarmPrecheck.requests.post", return_value=denied):
            self.assertEqual(
                AlarmPrecheck.should_store_alarm(config, control_code="c1", desc="alarm"),
                (False, "blocked"),
            )

        allowed = SimpleNamespace(
            status_code=200,
            json=lambda: {"data": {"ok": True, "msg": "allowed"}},
            text="",
        )
        with mock.patch("app.utils.AlarmPrecheck.requests.post", return_value=allowed):
            self.assertEqual(
                AlarmPrecheck.should_store_alarm(config, control_code="c1", desc="alarm"),
                (True, "allowed"),
            )
