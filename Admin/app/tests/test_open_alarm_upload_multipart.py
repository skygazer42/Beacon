import json
import os
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from app.models import Alarm


class OpenAlarmUploadMultipartTest(TestCase):
    def setUp(self):
        super().setUp()
        os.environ["BEACON_OPEN_API_TOKEN"] = "token-test-001"
        self.addCleanup(os.environ.pop, "BEACON_OPEN_API_TOKEN", None)

    def test_open_alarm_upload_accepts_multipart_files(self):
        image = SimpleUploadedFile("a.jpg", b"\xff\xd8\xffimg-bytes-001", content_type="image/jpeg")
        video = SimpleUploadedFile("v.mp4", b"\x00\x00\x00\x18ftypmp42video-bytes-001", content_type="video/mp4")

        with tempfile.TemporaryDirectory() as tmp:
            # patch g_config.uploadDir to an isolated directory for this test
            from app.views import api as api_view
            old_upload = getattr(api_view.g_config, "uploadDir", "")
            api_view.g_config.uploadDir = tmp
            try:
                res = self.client.post(
                    "/open/alarm/upload",
                    data={
                        "control_code": "C001",
                        "desc": "hello",
                        "image_file": image,
                        "video_file": video,
                    },
                    HTTP_X_BEACON_TOKEN="token-test-001",
                )
            finally:
                api_view.g_config.uploadDir = old_upload

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        data = body.get("data") or {}
        self.assertTrue(str(data.get("image_path") or "").startswith("alarm/"), msg=body)
        self.assertTrue(str(data.get("video_path") or "").startswith("alarm/"), msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertTrue(str(alarm.image_path or "").startswith("alarm/"))
        self.assertTrue(str(alarm.video_path or "").startswith("alarm/"))

    def test_open_alarm_upload_rejects_active_content_with_image_extension(self):
        image = SimpleUploadedFile("attack.png", b"<svg onload=alert(1)>", content_type="image/png")

        with tempfile.TemporaryDirectory() as tmp:
            from app.views import api as api_view

            old_upload = getattr(api_view.g_config, "uploadDir", "")
            api_view.g_config.uploadDir = tmp
            try:
                response = self.client.post(
                    "/open/alarm/upload",
                    data={"control_code": "C001", "desc": "unsafe", "image_file": image},
                    HTTP_X_BEACON_TOKEN="token-test-001",
                )
            finally:
                api_view.g_config.uploadDir = old_upload

            body = json.loads(response.content.decode("utf-8"))
            self.assertEqual(body.get("code"), 0)
            self.assertEqual(Alarm.objects.count(), 0)
            self.assertEqual([path for path in Path(tmp).rglob("*") if path.is_file()], [])
