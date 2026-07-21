import json

from django.test import TestCase

from app.models import Stream


class StreamOpenGetAndEditApiTest(TestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def test_open_get_returns_stream_details(self):
        Stream.objects.create(
            user_id=1,
            sort=0,
            code="cam001",
            app="live",
            name="cam001",
            pull_stream_url="rtsp://127.0.0.1/a",
            pull_stream_type=1,
            nickname="n1",
            remark="r1",
            site_label="site-a",
            floor_label="F3",
            forward_state=0,
            state=0,
        )

        res = self.client.get("/stream/openGet", data={"code": "cam001"})
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        data = payload.get("data") or {}
        self.assertEqual(data.get("code"), "cam001")
        self.assertEqual(data.get("app"), "live")
        self.assertEqual(data.get("name"), "cam001")
        self.assertEqual(data.get("pull_stream_url"), "rtsp://127.0.0.1/a")
        self.assertEqual(int(data.get("pull_stream_type") or 0), 1)
        self.assertEqual(data.get("nickname"), "n1")
        self.assertEqual(data.get("remark"), "r1")
        self.assertEqual(data.get("site_label"), "site-a")
        self.assertEqual(data.get("floor_label"), "F3")

    def test_open_delete_removes_requested_stream(self):
        Stream.objects.create(
            user_id=1,
            sort=0,
            code="cam-delete",
            app="live",
            name="cam-delete",
            pull_stream_url="rtsp://127.0.0.1/delete",
            pull_stream_type=1,
            nickname="delete me",
            remark="",
            forward_state=0,
            state=0,
        )

        response = self.client.post(
            "/stream/openDel",
            data={"handle": "one", "code": "cam-delete"},
        )
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(payload.get("code"), 1000, msg=payload)
        self.assertFalse(Stream.objects.filter(code="cam-delete").exists())

    def test_open_edit_updates_stream_fields(self):
        Stream.objects.create(
            user_id=1,
            sort=0,
            code="cam002",
            app="live",
            name="cam002",
            pull_stream_url="rtsp://127.0.0.1/b",
            pull_stream_type=1,
            nickname="n2",
            remark="r2",
            forward_state=0,
            state=0,
        )

        res = self.client.post(
            "/stream/openEdit",
            data={
                "code": "cam002",
                "app": "group1",
                "site_label": "site-b",
                "floor_label": "F2",
                "pull_stream_url": "http://127.0.0.1/new",
                "pull_stream_type": "3",
                "nickname": "new name",
                "remark": "new remark",
            },
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        s = Stream.objects.filter(code="cam002").first()
        self.assertIsNotNone(s)
        self.assertEqual(s.app, "group1")
        self.assertEqual(s.name, "cam002")
        self.assertEqual(s.pull_stream_url, "http://127.0.0.1/new")
        self.assertEqual(int(s.pull_stream_type or 0), 3)
        self.assertEqual(s.nickname, "new name")
        self.assertEqual(s.remark, "new remark")
        self.assertEqual(s.site_label, "site-b")
        self.assertEqual(s.floor_label, "F2")

    def test_open_edit_accepts_srt_url(self):
        Stream.objects.create(
            user_id=1,
            sort=0,
            code="cam003",
            app="live",
            name="cam003",
            pull_stream_url="rtsp://127.0.0.1/c",
            pull_stream_type=1,
            nickname="n3",
            remark="r3",
            forward_state=0,
            state=0,
        )

        res = self.client.post(
            "/stream/openEdit",
            data={
                "code": "cam003",
                "app": "live",
                "pull_stream_url": "srt://127.0.0.1:9000?streamid=live/cam003",
                "pull_stream_type": "5",
                "nickname": "new srt",
                "remark": "new",
            },
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        s = Stream.objects.filter(code="cam003").first()
        self.assertIsNotNone(s)
        self.assertEqual(s.pull_stream_url, "srt://127.0.0.1:9000?streamid=live/cam003")
        self.assertEqual(int(s.pull_stream_type or 0), 5)

    def test_open_edit_accepts_rtmps_url(self):
        Stream.objects.create(
            user_id=1,
            sort=0,
            code="cam004",
            app="live",
            name="cam004",
            pull_stream_url="rtsp://127.0.0.1/d",
            pull_stream_type=1,
            nickname="n4",
            remark="r4",
            forward_state=0,
            state=0,
        )

        res = self.client.post(
            "/stream/openEdit",
            data={
                "code": "cam004",
                "app": "live",
                "pull_stream_url": "rtmps://127.0.0.1:1935/live/cam004",
                "pull_stream_type": "2",
                "nickname": "new rtmps",
                "remark": "ssl",
            },
        )
        self.assertEqual(res.status_code, 200, msg=res.content)
        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)

        s = Stream.objects.filter(code="cam004").first()
        self.assertIsNotNone(s)
        self.assertEqual(s.pull_stream_url, "rtmps://127.0.0.1:1935/live/cam004")
        self.assertEqual(int(s.pull_stream_type or 0), 2)
