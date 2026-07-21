import json
from unittest import mock

from django.test import TestCase

from app.models import Stream
from app.views import StreamView


class StreamGetPlayUrlTest(TestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def test_raw_h265_returns_ws_mp4_url(self):
        stream = {
            "is_online": True,
            "video_codec_name": "H265",
            "video_height": 1080,
        }
        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch("app.views.StreamView.g_zlm.get_wsMp4Url", return_value="ws://demo/live/cam1.live.mp4", create=True):
                with mock.patch("app.views.StreamView.g_zlm.get_wsFlvUrl", return_value="ws://demo/live/cam1.live.flv", create=True):
                    res = self.client.get("/stream/getPlayUrl?app=live&name=cam1&prefer=raw&layout=1")

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        data = payload.get("data") or {}
        self.assertEqual(data.get("mode"), "raw")
        self.assertEqual(data.get("demuxType"), "fmp4")
        self.assertEqual(data.get("codec"), "h265")
        self.assertEqual(data.get("url"), "ws://demo/live/cam1.live.mp4")

    def test_compat_h265_returns_h264_flv_when_transcode_already_online(self):
        stream = {
            "is_online": True,
            "video_codec_name": "h265",
            "video_height": 1080,
        }

        def fake_get_media_info(app, name, schema="rtmp"):
            # treat target transcode stream as already online
            if app == "trans":
                return {"ret": True}
            return {"ret": True}

        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch("app.views.StreamView.g_zlm.getMediaInfo", side_effect=fake_get_media_info, create=True):
                with mock.patch("app.views.StreamView.g_zlm.get_wsFlvUrl", return_value="ws://demo/trans/live_cam1_h264_1080p.live.flv", create=True):
                    res = self.client.get(
                        "/stream/getPlayUrl?app=live&name=cam1&prefer=compat&quality=origin&layout=1"
                    )

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        data = payload.get("data") or {}
        self.assertEqual(data.get("mode"), "compat")
        self.assertEqual(data.get("codec"), "h264")
        self.assertEqual(data.get("demuxType"), "flv")
        self.assertIn("trans", data.get("url", ""))

    def test_cooldown_returns_retry_when_transcode_not_ready(self):
        stream = {
            "is_online": True,
            "video_codec_name": "h264",
            "video_height": 1080,
        }

        class FakeTM:
            def can_start(self, token: str) -> bool:
                return False

            def cooldown_remaining_ms(self, token: str) -> int:
                return 800

            def register_stream(self, stream_id: str, key: str):
                return None

            def touch_stream(self, stream_id: str):
                return None

        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch("app.views.StreamView.g_zlm.getMediaInfo", return_value={"ret": False}, create=True):
                with mock.patch("app.views.StreamView.g_zlm.get_wsFlvUrl", return_value="ws://demo/trans/live_cam1_h264_360p.live.flv", create=True):
                    with mock.patch("app.views.StreamView.get_transcode_manager", return_value=FakeTM(), create=True):
                        res = self.client.get(
                            "/stream/getPlayUrl?app=live&name=cam1&prefer=compat&quality=auto&layout=16"
                        )

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1001)
        self.assertTrue(int(payload.get("retry_after_ms") or 0) > 0)
        data = payload.get("data") or {}
        self.assertEqual(data.get("mode"), "compat")
        self.assertEqual(data.get("demuxType"), "flv")

    def test_transcode_start_failure_returns_retry(self):
        stream = {
            "is_online": True,
            "video_codec_name": "h265",
            "video_height": 1080,
        }

        class FakeTM:
            def can_start(self, token: str) -> bool:
                return True

            def cooldown_remaining_ms(self, token: str) -> int:
                return 800

            def register_stream(self, stream_id: str, key: str):
                return None

            def touch_stream(self, stream_id: str):
                return None

        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch("app.views.StreamView.g_zlm.getMediaInfo", return_value={"ret": False}, create=True):
                with mock.patch("app.views.StreamView.g_zlm.addFFmpegSource", return_value=None, create=True):
                    with mock.patch("app.views.StreamView.g_zlm.get_wsFlvUrl", return_value="ws://demo/trans/not.ready.live.flv", create=True):
                        with mock.patch("app.views.StreamView.get_transcode_manager", return_value=FakeTM(), create=True):
                            res = self.client.get(
                                "/stream/getPlayUrl?app=live&name=cam1&prefer=compat&quality=auto&layout=4"
                            )

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1001)
        self.assertIn("transcod", str(payload.get("msg") or ""))

    def test_prefer_hls_returns_hls_m3u8_url(self):
        stream = {
            "is_online": True,
            "video_codec_name": "h264",
            "video_height": 1080,
        }
        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch(
                "app.views.StreamView.g_zlm.get_hlsUrl",
                return_value="http://demo/live/cam1/hls.m3u8",
                create=True,
            ):
                res = self.client.get("/stream/getPlayUrl?app=live&name=cam1&prefer=hls&layout=1")

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        data = payload.get("data") or {}
        self.assertEqual(data.get("mode"), "hls")
        self.assertEqual(data.get("demuxType"), "hls")
        self.assertEqual(data.get("url"), "http://demo/live/cam1/hls.m3u8")

    def test_prefer_hls_fmp4_returns_hls_fmp4_m3u8_url(self):
        stream = {
            "is_online": True,
            "video_codec_name": "h264",
            "video_height": 1080,
        }
        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch(
                "app.views.StreamView.g_zlm.get_hlsFmp4Url",
                return_value="http://demo/live/cam1/hls.fmp4.m3u8",
                create=True,
            ):
                res = self.client.get("/stream/getPlayUrl?app=live&name=cam1&prefer=hls_fmp4&layout=1")

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        data = payload.get("data") or {}
        self.assertEqual(data.get("mode"), "hls")
        self.assertEqual(data.get("demuxType"), "hls")
        self.assertEqual(data.get("url"), "http://demo/live/cam1/hls.fmp4.m3u8")

    def test_media_list_fallback_returns_embed_url_when_media_info_is_missing(self):
        stream = {
            "is_online": False,
            "video_codec_name": "",
            "video_height": 0,
        }
        fake_media_list = [
            {
                "app": "live",
                "name": "cam1",
                "video": "h264",
            },
        ]
        with mock.patch("app.views.StreamView.GetStream", return_value=stream, create=True):
            with mock.patch("app.views.StreamView.g_zlm.getMediaList", return_value=fake_media_list, create=True):
                with mock.patch("app.views.StreamView.g_zlm.get_wsFlvUrl", return_value="ws://demo/live/cam1.live.flv", create=True):
                    with mock.patch(
                        "app.views.StreamView.g_zlm.get_webrtcDemoUrl",
                        return_value="http://demo/webrtc/index.html?app=live&stream=cam1&type=play",
                        create=True,
                    ):
                        res = self.client.get("/stream/getPlayUrl?app=live&name=cam1&prefer=compat&layout=4")

        payload = json.loads(res.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000)
        data = payload.get("data") or {}
        self.assertEqual(data.get("url"), "ws://demo/live/cam1.live.flv")
        self.assertEqual(data.get("embed_url"), "http://demo/webrtc/index.html?app=live&stream=cam1&type=play")
        self.assertEqual(data.get("embed_type"), "iframe")

    def test_app_shell_uses_live_media_when_database_flags_are_stale(self):
        Stream.objects.create(
            user_id=1,
            sort=0,
            code="cam-live-probe",
            app="traffic",
            name="cam-live-probe",
            pull_stream_url="rtsp://example.invalid/live",
            pull_stream_type=1,
            nickname="Live Probe",
            site_label="site-a",
            remark="",
            forward_state=0,
            state=0,
        )
        with mock.patch(
            "app.views.AppShellView.StreamView.build_online_stream_app_shell_payload",
            return_value=("", [{"app": "traffic", "name": "cam-live-probe"}]),
        ):
            response = self.client.get("/api/app-shell/streams?site=site-a&ps=10&p=1")

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("code"), 1000, msg=payload)
        row = payload["data"]["rows"][0]
        self.assertEqual(row["code"], "cam-live-probe")
        self.assertEqual(payload["data"]["stats"]["online"], 1)

    def test_two_window_layout_uses_720p_auto_target_height(self):
        self.assertEqual(StreamView._playurl_target_height(2, "auto"), 720)
