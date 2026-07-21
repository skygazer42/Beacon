import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from app.utils.Security import resolve_under_base, validate_upload_rel_path
from app.utils.StreamRecording import StreamRecorder, StreamSnapshotter, _safe_join, _validate_stream_url
from app.utils.UploadPath import looks_like_windows_drive_path, resolve_upload_url_to_abs_path, split_paired_path


class _BrokenPipeStdin:
    def write(self, _data):
        raise BrokenPipeError("pipe closed")

    def flush(self):
        raise BrokenPipeError("pipe closed")


class _ExitedProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdin = _BrokenPipeStdin()
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


class StreamRecordingLifecycleTest(SimpleTestCase):
    def _recording_info(self):
        return {
            "record_id": "usbcam_20260421103505",
            "stream_code": "usbcam",
            "stream_url": "rtmp://127.0.0.1:9995/live/usbcam",
            "save_path": "/tmp/usbcam.mp4",
            "relative_path": "recordings/usbcam/usbcam_20260421103505.mp4",
            "start_time": datetime.now() - timedelta(seconds=12),
            "duration": 30,
            "format": "mp4",
            "process": _ExitedProcess(returncode=0),
            "status": "recording",
        }

    def test_stop_recording_succeeds_when_ffmpeg_already_exited(self):
        recorder = StreamRecorder("/tmp")
        recorder.active_recordings["usbcam"] = self._recording_info()

        result = recorder.stop_recording("usbcam")

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["save_path"], "recordings/usbcam/usbcam_20260421103505.mp4")
        self.assertNotIn("usbcam", recorder.active_recordings)

    def test_get_recording_status_reaps_finished_process(self):
        recorder = StreamRecorder("/tmp")
        recorder.active_recordings["usbcam"] = self._recording_info()

        status = recorder.get_recording_status("usbcam")

        self.assertIsNone(status)
        self.assertNotIn("usbcam", recorder.active_recordings)

    def test_list_active_recordings_skips_finished_process(self):
        recorder = StreamRecorder("/tmp")
        recorder.active_recordings["usbcam"] = self._recording_info()

        rows = recorder.list_active_recordings()

        self.assertEqual(rows, [])
        self.assertNotIn("usbcam", recorder.active_recordings)

    def test_stream_url_validation_rejects_unsupported_or_malformed_urls(self):
        self.assertEqual(_validate_stream_url(""), "")
        self.assertEqual(_validate_stream_url("ftp://example.com/live"), "")
        self.assertEqual(_validate_stream_url("http://"), "")
        self.assertEqual(_validate_stream_url("http://example.com\nX-Test: injected"), "")
        self.assertEqual(_validate_stream_url("rtsp://127.0.0.1/live"), "rtsp://127.0.0.1/live")
        self.assertEqual(_validate_stream_url("https://example.com/live"), "https://example.com/live")

    def test_safe_join_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as storage_root:
            joined = _safe_join(storage_root, "recordings", "camera.mp4")
            self.assertTrue(joined.startswith(os.path.abspath(storage_root) + os.sep))
            with self.assertRaises(ValueError):
                _safe_join(storage_root, "..", "escape.mp4")

    def test_alarm_upload_paths_stay_under_required_base(self):
        relative_path = "alarm/ctrl001/20260101/main.mp4"
        self.assertEqual(
            validate_upload_rel_path(relative_path, required_prefix="alarm/"),
            relative_path,
        )
        with tempfile.TemporaryDirectory() as storage_root:
            resolved = resolve_under_base(storage_root, "alarm/ctrl001/main.jpg")
            self.assertTrue(resolved.startswith(os.path.abspath(storage_root) + os.sep))
            for value in ("../x", "alarm/../x", "/etc/passwd", "C:\\Windows\\win.ini", "temp/x.txt"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        validate_upload_rel_path(value, required_prefix="alarm/")
            with self.assertRaises(ValueError):
                resolve_under_base(storage_root, "../../etc/passwd")

    def test_upload_model_path_resolution_handles_windows_relative_and_absolute_paths(self):
        self.assertTrue(looks_like_windows_drive_path("C:\\data\\a.onnx"))
        self.assertFalse(looks_like_windows_drive_path("models/a.onnx"))

        with tempfile.TemporaryDirectory() as temp_dir:
            upload_dir = os.path.join(temp_dir, "upload")
            from_www = resolve_upload_url_to_abs_path(
                "/static/upload/models/a.onnx",
                upload_dir=upload_dir,
                upload_www_prefix="/static/upload/",
            )
            relative = resolve_upload_url_to_abs_path("models/a.onnx", upload_dir=upload_dir)
            absolute_source = os.path.join(temp_dir, "outside", "a.onnx")
            absolute = resolve_upload_url_to_abs_path(absolute_source, upload_dir=upload_dir)

        expected = os.path.normpath(os.path.join(upload_dir, "models", "a.onnx"))
        self.assertEqual(from_www, expected)
        self.assertEqual(relative, expected)
        self.assertEqual(absolute, os.path.normpath(absolute_source))

    def test_paired_model_path_keeps_both_nonempty_components(self):
        self.assertEqual(split_paired_path(" model.xml | weights.bin "), ["model.xml", "weights.bin"])
        self.assertEqual(split_paired_path(""), [])

    def test_recorder_rejects_storage_path_escape(self):
        with tempfile.TemporaryDirectory() as storage_root:
            recorder = StreamRecorder(storage_root=storage_root)
            with mock.patch(
                "app.utils.StreamRecording._safe_join",
                side_effect=[os.path.join(storage_root, "recordings", "cam"), ValueError("escape")],
            ):
                result = recorder.start_recording("cam", "rtsp://127.0.0.1/live")

        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("message"), "录像路径非法")

    def test_snapshot_backends_reject_paths_outside_storage_root(self):
        with tempfile.TemporaryDirectory() as storage_root:
            snapshotter = StreamSnapshotter(storage_root=storage_root)
            outside = os.path.join(os.path.dirname(storage_root), "outside.jpg")

            self.assertFalse(snapshotter._capture_with_ffmpeg("rtsp://127.0.0.1/live", outside))
            fake_cv2 = type("FakeCv2", (), {"VideoCapture": mock.Mock()})()
            with mock.patch("app.utils.StreamRecording.cv2", fake_cv2):
                self.assertFalse(snapshotter._capture_with_opencv("rtsp://127.0.0.1/live", outside))


class RecordingPlanStopStateTest(SimpleTestCase):
    def _service_with_active_plan(self, plan_code="plan-a", recorder_key="plan_plan-a"):
        from app.utils.RecordingPlanService import RecordingPlanService

        service = RecordingPlanService(SimpleNamespace(storageRootPath="/tmp/recordings"))
        service._active[plan_code] = recorder_key
        return service

    def test_stop_plan_keeps_active_state_for_exception_malformed_and_rejected_results(self):
        cases = (
            RuntimeError("recorder unavailable"),
            None,
            {"success": "yes", "message": "录像已停止"},
            {"success": True, "message": 7},
            {"success": False, "message": "停止录像失败"},
        )

        for stop_result in cases:
            with self.subTest(stop_result=repr(stop_result)):
                service = self._service_with_active_plan()
                recorder = mock.Mock()
                if isinstance(stop_result, Exception):
                    recorder.stop_recording.side_effect = stop_result
                else:
                    recorder.stop_recording.return_value = stop_result

                with mock.patch(
                    "app.utils.RecordingPlanService.get_stream_recorder",
                    return_value=recorder,
                ):
                    result = service._stop_plan("plan-a")

                self.assertIsInstance(result, tuple)
                ok, message = result
                self.assertFalse(ok)
                self.assertIsInstance(message, str)
                self.assertEqual(service._active, {"plan-a": "plan_plan-a"})

    def test_stop_plan_clears_active_only_for_success_or_exact_not_recording_result(self):
        cases = (
            {"success": True, "message": "录像已停止"},
            {"success": False, "message": "该视频流未在录像"},
        )

        for stop_result in cases:
            with self.subTest(stop_result=stop_result):
                service = self._service_with_active_plan()
                recorder = mock.Mock()
                recorder.stop_recording.return_value = stop_result

                with mock.patch(
                    "app.utils.RecordingPlanService.get_stream_recorder",
                    return_value=recorder,
                ):
                    result = service._stop_plan("plan-a")

                self.assertIsInstance(result, tuple)
                ok, message = result
                self.assertTrue(ok, msg=message)
                self.assertEqual(service._active, {})

    def test_stop_plan_does_not_treat_approximate_not_recording_message_as_success(self):
        for message in (" 该视频流未在录像", "该视频流未在录像。", "该视频流未在录像\n"):
            with self.subTest(message=repr(message)):
                service = self._service_with_active_plan()
                recorder = mock.Mock()
                recorder.stop_recording.return_value = {"success": False, "message": message}

                with mock.patch(
                    "app.utils.RecordingPlanService.get_stream_recorder",
                    return_value=recorder,
                ):
                    result = service._stop_plan("plan-a")

                self.assertIsInstance(result, tuple)
                ok, _ = result
                self.assertFalse(ok)
                self.assertEqual(service._active, {"plan-a": "plan_plan-a"})

    def test_shutdown_removes_successes_keeps_failures_and_retries_on_second_call(self):
        from app.utils.RecordingPlanService import RecordingPlanService

        service = RecordingPlanService(SimpleNamespace(storageRootPath="/tmp/recordings"))
        service._active.update({"plan-a": "plan_plan-a", "plan-b": "plan_plan-b"})
        recorder = mock.Mock()
        recorder.stop_recording.side_effect = (
            {"success": True, "message": "录像已停止"},
            {"success": False, "message": "停止录像失败"},
            {"success": True, "message": "录像已停止"},
        )

        with mock.patch(
            "app.utils.RecordingPlanService.get_stream_recorder",
            return_value=recorder,
        ):
            service.shutdown()
            self.assertEqual(service._active, {"plan-b": "plan_plan-b"})

            service.shutdown()

        self.assertEqual(service._active, {})
        self.assertEqual(
            recorder.stop_recording.call_args_list,
            [mock.call("plan_plan-a"), mock.call("plan_plan-b"), mock.call("plan_plan-b")],
        )
