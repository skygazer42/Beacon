from django.test import SimpleTestCase

from app.views.CloudRemoteRecordingsView import _remote_recording_response


class _RemoteResponse:
    def __init__(self, headers, body=b"content"):
        self.headers = headers
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.body

    def close(self):
        self.closed = True


class CloudRemoteRecordingSecurityTests(SimpleTestCase):
    def test_untrusted_html_and_disposition_are_not_reflected(self):
        upstream = _RemoteResponse(
            {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Disposition": 'inline; filename="attack.html"',
                "Content-Length": "7",
            },
            body=b"payload",
        )

        response = _remote_recording_response(upstream, "recordings/camera/video.mp4")

        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="video.mp4"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("attack", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"payload")
        self.assertTrue(upstream.closed)

    def test_safe_video_type_is_preserved_without_parameters(self):
        upstream = _RemoteResponse({"Content-Type": "video/mp4; charset=binary"})

        response = _remote_recording_response(upstream, "recordings/camera/video.mp4")

        self.assertEqual(response["Content-Type"], "video/mp4")

    def test_invalid_content_lengths_are_not_reflected(self):
        for value in ("-1", "7\r\nX-Evil: yes", "9" * 20):
            with self.subTest(value=value):
                upstream = _RemoteResponse({"Content-Type": "video/mp4", "Content-Length": value})
                response = _remote_recording_response(upstream, "recordings/camera/video.mp4")
                self.assertNotIn("Content-Length", response)
