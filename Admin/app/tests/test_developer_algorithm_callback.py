import base64
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from app.models import Alarm, Control
from app.views import DeveloperView as developer_view


class DeveloperAlgorithmCallbackTest(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="admin", password="pass12345")
        session = self.client.session
        session["user"] = {"id": self.user.id, "username": self.user.username}
        session.save()

        self.control = Control.objects.create(
            user_id=self.user.id,
            sort=0,
            code="CTRL_DEV_CB_001",
            stream_app="live",
            stream_name="cam01",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="algo001",
            object_code="person",
            polygon="0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9",
            min_interval=3,
            class_thresh=0.6,
            overlap_thresh=0.4,
            remark="",
            push_stream=False,
            push_stream_app=None,
            push_stream_name=None,
            state=0,
        )

    def test_algorithm_callback_creates_alarm_and_image_when_triggered(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        tmp = temp_dir.name

        old_upload_dir = getattr(developer_view.g_config, "uploadDir", "")
        old_upload_dir_www = getattr(developer_view.g_config, "uploadDir_www", "")
        developer_view.g_config.uploadDir = tmp
        developer_view.g_config.uploadDir_www = "/upload/"
        try:
            payload = {
                "control_code": "CTRL_DEV_CB_001",
                "frame_index": 123,
                "timestamp": 1702700000,
                "detections": [
                    {
                        "class_name": "person",
                        "confidence": 0.97,
                        "bbox": [10, 20, 120, 220],
                    }
                ],
                "trigger_alarm": True,
                "image_base64": base64.b64encode(b"developer-callback-image").decode("utf-8"),
            }
            res = self.client.post(
                "/developer/algorithmCallback",
                data=json.dumps(payload),
                content_type="application/json",
            )
        finally:
            developer_view.g_config.uploadDir = old_upload_dir
            developer_view.g_config.uploadDir_www = old_upload_dir_www

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertEqual(alarm.control_code, "CTRL_DEV_CB_001")
        self.assertEqual(alarm.algorithm_code, "algo001")
        self.assertEqual(alarm.object_code, "person")
        self.assertEqual(alarm.stream_app, "live")
        self.assertEqual(alarm.stream_name, "cam01")
        self.assertEqual(alarm.min_interval, 3)
        self.assertAlmostEqual(alarm.class_thresh, 0.6, places=4)
        self.assertAlmostEqual(alarm.overlap_thresh, 0.4, places=4)
        self.assertTrue(alarm.image_path.startswith("alarm/CTRL_DEV_CB_001/"))

        image_path = Path(tmp) / alarm.image_path
        self.assertTrue(image_path.exists())
        self.assertEqual(image_path.read_bytes(), b"developer-callback-image")

        metadata = json.loads(alarm.metadata or "{}")
        self.assertEqual(int(metadata.get("frame_index") or 0), 123)
        self.assertEqual(int(metadata.get("timestamp") or 0), 1702700000)
        self.assertEqual(metadata.get("detections", [{}])[0].get("class_name"), "person")

    def test_algorithm_callback_creates_alarm_without_image_when_triggered(self):
        payload = {
            "control_code": "CTRL_DEV_CB_001",
            "frame_index": 124,
            "timestamp": 1702700001,
            "detections": [
                {
                    "class_name": "person",
                    "confidence": 0.85,
                    "bbox": [15, 25, 125, 225],
                }
            ],
            "trigger_alarm": True,
        }
        res = self.client.post(
            "/developer/algorithmCallback",
            data=json.dumps(payload),
            content_type="application/json",
        )

        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertEqual(alarm.control_code, "CTRL_DEV_CB_001")
        self.assertEqual(alarm.image_path, "")

        metadata = json.loads(alarm.metadata or "{}")
        self.assertEqual(int(metadata.get("frame_index") or 0), 124)
        self.assertEqual(int(metadata.get("timestamp") or 0), 1702700001)
        self.assertEqual(metadata.get("detections", [{}])[0].get("class_name"), "person")

    def test_callback_payload_parser_and_alarm_description(self):
        payload = {
            "control_code": "CTRL_DEV_CB_001",
            "frame_index": 1,
            "timestamp": 1.0,
            "detections": [{"class_name": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1]}],
            "trigger_alarm": False,
            "image_base64": "",
        }

        parsed, error = developer_view._parse_algorithm_callback_payload(payload)
        self.assertIsNone(error)
        self.assertEqual(parsed[0], "CTRL_DEV_CB_001")

        invalid, invalid_error = developer_view._parse_algorithm_callback_payload({"control_code": ""})
        self.assertIsNone(invalid)
        self.assertTrue(invalid_error)
        self.assertEqual(developer_view._build_callback_alarm_desc([]), "developer callback alarm")
        self.assertEqual(
            developer_view._build_callback_alarm_desc([{"class_name": "person"}, {"class_name": "car"}]),
            "person, car",
        )

    def test_precheck_rejection_removes_staged_callback_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            staged_image = Path(temp_dir) / "staged.jpg"
            staged_image.write_bytes(b"staged")
            with (
                mock.patch.object(developer_view, "_resolve_upload_abs_path", return_value=str(staged_image)),
                mock.patch("app.utils.AlarmPrecheck.should_store_alarm", return_value=(False, "blocked")),
            ):
                allowed = developer_view._allow_store_callback_alarm(
                    self.control,
                    desc="blocked",
                    stream_code="cam01",
                    stream_url="rtsp://127.0.0.1/cam01",
                    image_path="alarm/staged.jpg",
                    image_base64="abc",
                    metadata_obj={},
                )

            self.assertFalse(allowed)
            self.assertFalse(staged_image.exists())

    def _create_alarm_for_event_dispatch(self):
        return Alarm.objects.create(
            sort=0,
            control_code=self.control.code,
            desc="developer callback alarm",
            detail_desc="developer callback alarm",
            alarm_type="developerCallback",
            alarm_level=1,
            algorithm_code=self.control.algorithm_code,
            object_code=self.control.object_code,
            recognition_region=self.control.polygon,
            class_thresh=self.control.class_thresh,
            overlap_thresh=self.control.overlap_thresh,
            min_interval=self.control.min_interval,
            stream_code="cam01",
            stream_app="live",
            stream_name="cam01",
            stream_url="rtsp://127.0.0.1/cam01",
            image_path="",
            metadata="{}",
            state=0,
        )

    def test_callback_event_uses_outbox_when_enabled(self):
        alarm = self._create_alarm_for_event_dispatch()
        old_enabled = getattr(developer_view.g_config, "alarmOutboxEnabled", True)
        developer_view.g_config.alarmOutboxEnabled = True
        self.addCleanup(setattr, developer_view.g_config, "alarmOutboxEnabled", old_enabled)

        with (
            mock.patch("app.utils.AlarmEventBus.build_alarm_created_event", return_value={"id": alarm.id}),
            mock.patch("app.utils.AlarmEventBus.enqueue_alarm_event_outbox") as enqueue,
        ):
            developer_view._emit_alarm_created_event(
                self.control,
                alarm=alarm,
                desc=alarm.desc,
                now_date=alarm.create_time,
                image_path="",
                metadata_obj={},
                detections=[],
            )

        enqueue.assert_called_once()

    def test_callback_event_dispatches_directly_when_outbox_disabled(self):
        alarm = self._create_alarm_for_event_dispatch()
        old_enabled = getattr(developer_view.g_config, "alarmOutboxEnabled", True)
        developer_view.g_config.alarmOutboxEnabled = False
        self.addCleanup(setattr, developer_view.g_config, "alarmOutboxEnabled", old_enabled)
        dispatcher = mock.Mock()

        with (
            mock.patch("app.utils.AlarmEventBus.build_alarm_created_event", return_value={"id": alarm.id}),
            mock.patch("app.utils.BackgroundServices.get_alarm_sink_dispatcher", return_value=dispatcher),
        ):
            developer_view._emit_alarm_created_event(
                self.control,
                alarm=alarm,
                desc=alarm.desc,
                now_date=alarm.create_time,
                image_path="",
                metadata_obj={},
                detections=[],
            )

        dispatcher.enqueue.assert_called_once()
