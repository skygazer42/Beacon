import json

from django.test import TestCase

from app.models import Stream


class StreamOpenAddApiTest(TestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def test_open_add_stream_creates_stream_row(self):
        res = self.client.post(
            "/stream/openAdd",
            data={
                "code": "cam_open_1",
                "pull_stream_url": "rtsp://127.0.0.1/live/stream001",
                "pull_stream_type": "1",
                "nickname": "Cam 1",
                "remark": "r1",
                "app": "live",
            },
        )

        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        stream = Stream.objects.filter(code="cam_open_1").first()
        self.assertIsNotNone(stream)
        self.assertEqual(stream.app, "live")
        self.assertEqual(stream.name, "cam_open_1")
        self.assertEqual(stream.pull_stream_url, "rtsp://127.0.0.1/live/stream001")
        self.assertEqual(int(stream.pull_stream_type or 0), 1)
        self.assertEqual(stream.nickname, "Cam 1")
        self.assertEqual(stream.remark, "r1")

    def test_open_add_stream_accepts_srt_url(self):
        res = self.client.post(
            "/stream/openAdd",
            data={
                "code": "cam_srt_1",
                "pull_stream_url": "srt://127.0.0.1:9000?streamid=live/cam_srt_1",
                "pull_stream_type": "5",
                "nickname": "Cam SRT",
                "remark": "srt",
                "app": "live",
            },
        )

        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        stream = Stream.objects.filter(code="cam_srt_1").first()
        self.assertIsNotNone(stream)
        self.assertEqual(stream.pull_stream_url, "srt://127.0.0.1:9000?streamid=live/cam_srt_1")
        self.assertEqual(int(stream.pull_stream_type or 0), 5)

    def test_open_add_stream_accepts_rtsps_url(self):
        res = self.client.post(
            "/stream/openAdd",
            data={
                "code": "cam_rtsps_1",
                "pull_stream_url": "rtsps://127.0.0.1:322/live/stream001",
                "pull_stream_type": "1",
                "nickname": "Cam RTSPS",
                "remark": "ssl",
                "app": "live",
            },
        )

        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        stream = Stream.objects.filter(code="cam_rtsps_1").first()
        self.assertIsNotNone(stream)
        self.assertEqual(stream.pull_stream_url, "rtsps://127.0.0.1:322/live/stream001")
