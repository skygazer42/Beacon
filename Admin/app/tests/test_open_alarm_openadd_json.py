import json
import os
import tempfile

from django.test import TestCase

from app.models import Control, Alarm, AlgorithmModel


class OpenAlarmOpenAddJsonTest(TestCase):
    def setUp(self):
        super().setUp()
        os.environ["BEACON_OPEN_API_TOKEN"] = "token-test-openadd"
        self.addCleanup(os.environ.pop, "BEACON_OPEN_API_TOKEN", None)

        # Alarm list page requires a session user.
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

        # Minimal Control record (AlarmView.api_openAdd requires it to exist)
        Control.objects.create(
            user_id=1,
            sort=0,
            code="C_OPENADD_001",
            stream_app="live",
            stream_name="cam01",
            stream_video="video",
            stream_audio="audio",
            algorithm_code="on_yolov8n_80",
            object_code="person",
            polygon="0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9",
            min_interval=1,
            class_thresh=0.5,
            overlap_thresh=0.5,
            remark="t",
            push_stream=False,
            push_stream_app=None,
            push_stream_name=None,
            state=0,
        )
        AlgorithmModel.objects.create(
            sort=0,
            code="on_yolov8n_80",
            name="YOLOv8n Test",
            algorithm_type=0,
            algorithm_subtype="detection",
            basic_source="model",
            api_url="",
            model_path="",
            dll_path="",
            builtin_behavior="",
            support_direct_api=False,
            behavior_api_version=1,
            object_count=1,
            object_str="person",
            max_control_count=0,
            license_package="core",
            model_precision="FP16",
            model_concurrency=1,
            input_width=640,
            input_height=640,
            nms_thresh=0.45,
            conf_thresh=0.25,
            remark="",
            state=1,
        )

    def test_alarm_openadd_accepts_json_body(self):
        payload = {
            "control_code": "C_OPENADD_001",
            "desc": "测试报警-json",
        }
        res = self.client.post(
            "/alarm/openAdd",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_BEACON_TOKEN="token-test-openadd",
        )
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertEqual(alarm.control_code, "C_OPENADD_001")
        self.assertEqual(alarm.desc, "测试报警-json")

    def test_alarm_openadd_persists_stream_fields_and_draw_type(self):
        payload = {
            "control_code": "C_OPENADD_001",
            "desc": "测试报警-扩展字段",
            "stream_code": "S100",
            "stream_app": "live",
            "stream_name": "cam100",
            "algorithm_code": "ALG_TEST",
            "object_code": "person",
            "recognition_region": "0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9",
            "region_index": 2,
            "class_thresh": 0.6,
            "overlap_thresh": 0.4,
            "min_interval": 1000,
            "draw_type": 0,
        }
        res = self.client.post(
            "/alarm/openAdd",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_BEACON_TOKEN="token-test-openadd",
        )
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertEqual(alarm.stream_code, "S100")
        self.assertEqual(alarm.stream_app, "live")
        self.assertEqual(alarm.stream_name, "cam100")
        self.assertEqual(alarm.algorithm_code, "ALG_TEST")
        self.assertEqual(alarm.object_code, "person")
        self.assertEqual(int(getattr(alarm, "draw_type", -1)), 0)
        self.assertEqual(int(getattr(alarm, "region_index", -1)), 2)

    def test_alarm_openadd_persists_extra_images(self):
        payload = {
            "control_code": "C_OPENADD_001",
            "desc": "测试报警-extra-images",
            "draw_type": 1,
            "extra_images": [
                "alarm/C_OPENADD_001/20260307/main_clean.jpg",
                "alarm/C_OPENADD_001/20260307/extra_1_clean.jpg",
            ],
            "metadata": {
                "detects": [
                    {
                        "x1": 10,
                        "y1": 20,
                        "x2": 110,
                        "y2": 220,
                        "class_id": 0,
                        "class_score": 0.91,
                        "class_name": "person",
                    }
                ]
            },
        }
        res = self.client.post(
            "/alarm/openAdd",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_BEACON_TOKEN="token-test-openadd",
        )
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertEqual(
            json.loads(getattr(alarm, "extra_images", "") or "[]"),
            [
                "alarm/C_OPENADD_001/20260307/main_clean.jpg",
                "alarm/C_OPENADD_001/20260307/extra_1_clean.jpg",
            ],
        )

    def test_alarm_openadd_drops_missing_media_paths_instead_of_persisting_broken_preview_refs(self):
        payload = {
            "control_code": "C_OPENADD_001",
            "desc": "测试报警-丢失素材",
            "image_path": "alarm/C_OPENADD_001/20260307/main.jpg",
            "video_path": "alarm/C_OPENADD_001/20260307/main.mp4",
        }
        res = self.client.post(
            "/alarm/openAdd",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_BEACON_TOKEN="token-test-openadd",
        )
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)

        alarm = Alarm.objects.order_by("-id").first()
        self.assertIsNotNone(alarm)
        self.assertEqual(alarm.image_path, "")
        self.assertEqual(alarm.video_path, "")

    def test_alarm_list_does_not_build_image_url_when_empty(self):
        Alarm.objects.create(
            sort=0,
            control_code="C_OPENADD_001",
            desc="no-image",
            image_path="",
            video_path="",
            state=0,
        )

        res = self.client.get("/alarms")
        self.assertEqual(res.status_code, 200)

        ctx_data = (res.context or {}).get("data") or []
        self.assertTrue(isinstance(ctx_data, list))
        item = next((x for x in ctx_data if x.get("desc") == "no-image"), None)
        self.assertIsNotNone(item, msg=ctx_data)
        self.assertEqual(item.get("imageUrl") or "", "")

    def test_alarm_detail_hides_urls_for_missing_media(self):
        alarm = Alarm.objects.create(
            sort=0,
            control_code="ctrl-alarm-detail-missing",
            desc="alarm detail missing media",
            detail_desc="detail payload",
            alarm_type="intrusion",
            algorithm_code="alg-alarm-detail",
            stream_code="stream-alarm-detail",
            stream_app="live",
            stream_name="cam-alarm-detail",
            video_path="alarm/missing/detail/main.ts",
            image_path="alarm/missing/detail/main.jpg",
            state=0,
        )

        response = self.client.get(f"/api/app-shell/alarm/detail?id={alarm.id}")
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(payload.get("code"), 1000, msg=payload)
        media = payload["data"]["media"]
        self.assertFalse(media["has_video"])
        self.assertFalse(media["has_image"])
        self.assertEqual(media["video_url"], "")
        self.assertEqual(media["image_url"], "")

    def test_alarm_detail_uses_boxed_metadata_preview(self):
        from app.views.ViewsBase import g_config

        with tempfile.TemporaryDirectory() as upload_dir:
            old_upload_dir = g_config.uploadDir
            g_config.uploadDir = upload_dir
            try:
                relative_path = "alarm/demo/detail-boxed/main.jpg"
                absolute_path = os.path.join(upload_dir, relative_path)
                os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
                with open(absolute_path, "wb") as image_file:
                    image_file.write(b"boxed-detail")
                alarm = Alarm.objects.create(
                    sort=0,
                    control_code="ctrl-alarm-detail-boxed",
                    desc="alarm detail boxed preview",
                    detail_desc="detail payload",
                    alarm_type="intrusion",
                    algorithm_code="alg-alarm-detail",
                    stream_code="stream-alarm-detail",
                    stream_app="live",
                    stream_name="cam-alarm-detail",
                    image_path="",
                    metadata=json.dumps({"image_variants": {"boxed": relative_path}}, ensure_ascii=False),
                    state=0,
                )

                response = self.client.get(f"/api/app-shell/alarm/detail?id={alarm.id}")
            finally:
                g_config.uploadDir = old_upload_dir

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        media = payload["data"]["media"]
        self.assertTrue(media["has_image"])
        self.assertEqual(media["image_url"], "/static/upload/alarm/demo/detail-boxed/main.jpg")

    def test_alarm_openadd_filters_empty_detects_for_plain_detection_controls(self):
        payload = {
            "control_code": "C_OPENADD_001",
            "algorithm_code": "on_yolov8n_80_cpu",
            "object_code": "person",
            "metadata": {
                "detects": [],
            },
        }
        res = self.client.post(
            "/alarm/openAdd",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_BEACON_TOKEN="token-test-openadd",
        )
        body = json.loads(res.content.decode("utf-8"))
        self.assertEqual(body.get("code"), 1000, msg=body)
        self.assertEqual(body.get("msg"), "filtered", msg=body)
        self.assertEqual(Alarm.objects.count(), 0)
