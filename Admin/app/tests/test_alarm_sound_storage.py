import importlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from app.models import AlarmSound
from app.views import AlarmSoundView, Algorithm


class AlarmSoundStorageTest(TestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    @staticmethod
    def _payload(response):
        return json.loads(response.content.decode("utf-8"))

    def test_upload_and_delete_use_configured_runtime_storage(self):
        with tempfile.TemporaryDirectory() as upload_dir, mock.patch.object(
            AlarmSoundView.g_config, "uploadDir", upload_dir
        ), mock.patch.object(
            AlarmSoundView.g_config, "uploadDir_www", "/static/upload/"
        ):
            response = self.client.post(
                "/api/app-shell/alarm-sound/action/upload",
                data={
                    "name": "critical alarm",
                    "sound_file": SimpleUploadedFile("alert.wav", b"RIFF-test", content_type="audio/wav"),
                },
            )

            payload = self._payload(response)
            self.assertEqual(payload["code"], 1000, msg=payload)
            sound = AlarmSound.objects.get()
            self.assertTrue(sound.file_path.startswith("/static/upload/sounds/alarm_"))
            saved_path = AlarmSoundView._resolve_sound_abs_path(sound.file_path)
            self.assertEqual(Path(saved_path).read_bytes(), b"RIFF-test")
            self.assertTrue(os.path.commonpath((upload_dir, saved_path)) == os.path.abspath(upload_dir))

            fetch_response = self.client.get(sound.file_path)
            self.assertEqual(fetch_response.status_code, 200)
            self.assertEqual(b"".join(fetch_response.streaming_content), b"RIFF-test")
            self.assertEqual(fetch_response["Cache-Control"], "private, max-age=300")
            self.assertEqual(fetch_response["X-Content-Type-Options"], "nosniff")

            delete_response = self.client.post(
                "/api/app-shell/alarm-sound/action/delete",
                data={"id": str(sound.id)},
            )
            self.assertEqual(self._payload(delete_response)["code"], 1000)
            self.assertFalse(os.path.exists(saved_path))

    def test_managed_upload_requires_authenticated_session(self):
        with tempfile.TemporaryDirectory() as upload_dir, mock.patch.object(
            AlarmSoundView.g_config, "uploadDir", upload_dir
        ):
            sound_dir = os.path.join(upload_dir, "sounds")
            os.makedirs(sound_dir)
            Path(sound_dir, "alert.wav").write_bytes(b"RIFF")
            response = self.client_class().get("/static/upload/sounds/alert.wav")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login"))

    def test_managed_upload_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as parent_dir:
            upload_dir = os.path.join(parent_dir, "upload")
            sound_dir = os.path.join(upload_dir, "sounds")
            os.makedirs(sound_dir)
            outside_path = os.path.join(parent_dir, "outside.wav")
            Path(outside_path).write_bytes(b"secret")
            os.symlink(outside_path, os.path.join(sound_dir, "escape.wav"))
            with mock.patch.object(AlarmSoundView.g_config, "uploadDir", upload_dir):
                response = self.client.get("/static/upload/sounds/escape.wav")
            self.assertEqual(response.status_code, 404)

    def test_delete_refuses_path_traversal(self):
        with tempfile.TemporaryDirectory() as parent_dir:
            upload_dir = os.path.join(parent_dir, "upload")
            os.makedirs(os.path.join(upload_dir, "sounds"))
            outside_path = os.path.join(parent_dir, "outside.wav")
            Path(outside_path).write_bytes(b"keep")
            with mock.patch.object(AlarmSoundView.g_config, "uploadDir", upload_dir), mock.patch.object(
                AlarmSoundView.g_config, "uploadDir_www", "/static/upload/"
            ):
                AlarmSoundView._remove_sound_file_best_effort(
                    "/static/upload/sounds/../../outside.wav"
                )
            self.assertEqual(Path(outside_path).read_bytes(), b"keep")

    def test_internal_upload_error_does_not_leak_server_path(self):
        with tempfile.TemporaryDirectory() as upload_dir, mock.patch.object(
            AlarmSoundView.g_config, "uploadDir", upload_dir
        ), mock.patch.object(
            AlarmSoundView, "_write_sound_file", side_effect=PermissionError("/secret/server/path")
        ):
            response = self.client.post(
                "/api/app-shell/alarm-sound/action/upload",
                data={"sound_file": SimpleUploadedFile("alert.mp3", b"audio")},
            )
        payload = self._payload(response)
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["msg"], "上传失败，请稍后重试")
        self.assertNotIn("/secret/server/path", response.content.decode("utf-8"))

    def test_streaming_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as upload_dir, mock.patch.object(
            AlarmSoundView.g_config, "uploadDir", upload_dir
        ), mock.patch.object(AlarmSoundView, "MAX_SOUND_FILE_BYTES", 3):
            response = self.client.post(
                "/api/app-shell/alarm-sound/action/upload",
                data={"sound_file": SimpleUploadedFile("alert.mp3", b"1234")},
            )
        payload = self._payload(response)
        self.assertEqual(payload["code"], 0)
        self.assertIn("最大支持 20MB", payload["msg"])
        self.assertFalse(AlarmSound.objects.exists())


class ReadOnlyImageImportTest(TestCase):
    def test_view_imports_do_not_create_upload_directories(self):
        with mock.patch("os.makedirs", side_effect=AssertionError("import-time filesystem write")):
            importlib.reload(AlarmSoundView)
            importlib.reload(Algorithm)

    def test_algorithm_upload_creates_runtime_directory_lazily(self):
        with tempfile.TemporaryDirectory() as parent_dir:
            target_dir = os.path.join(parent_dir, "models")
            with mock.patch.object(Algorithm, "UPLOAD_MODEL_DIR", target_dir):
                url = Algorithm.save_uploaded_file(
                    SimpleUploadedFile("model.onnx", b"model"),
                    "demo_model",
                    target_dir,
                    url_subdir="models",
                )
            self.assertEqual(Path(target_dir, os.path.basename(url)).read_bytes(), b"model")
