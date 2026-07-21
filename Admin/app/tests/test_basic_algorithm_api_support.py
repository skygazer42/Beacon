from unittest import mock

from django.test import TestCase

from app.models import AlgorithmModel, Control
from app.views.ControlView import _start_control


class BasicAlgorithmApiSupportTest(TestCase):
    def _create_control(self, *, code: str, algorithm_code: str, state: int = 0) -> Control:
        return Control.objects.create(
            user_id=1,
            sort=0,
            code=code,
            stream_app="live",
            stream_name="cam-1",
            stream_video="video",
            stream_audio="audio",
            algorithm_code=algorithm_code,
            object_code="person",
            polygon="0,0,1,0,1,1,0,1",
            min_interval=1,
            class_thresh=0.5,
            overlap_thresh=0.5,
            remark="",
            patrol_enabled=False,
            push_stream=False,
            push_stream_app="live",
            push_stream_name=code,
            state=state,
        )

    def test_basic_source_model_does_not_pass_api_url_to_analyzer(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-1",
            name="alg-1",
            algorithm_type=0,
            basic_source="model",
            api_url="http://example.com/detect",
            object_count=1,
            object_str="person",
            max_control_count=0,
            state=1,
        )
        control = self._create_control(code="ctrl-1", algorithm_code="alg-1")

        with mock.patch("app.views.ControlView.g_zlm.get_rtspUrl", return_value="rtsp://demo", create=True):
            with mock.patch("app.views.ControlView.g_analyzer.control_add", return_value=(True, "ok")) as mocked_add:
                ok, _ = _start_control(control)

        self.assertTrue(ok)
        self.assertTrue(mocked_add.called)
        passed_api_url = mocked_add.call_args.kwargs.get("api_url")
        self.assertEqual(passed_api_url, "")

    def test_basic_source_api_passes_api_url_to_analyzer(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-api",
            name="alg-api",
            algorithm_type=0,
            basic_source="api",
            api_url="http://example.com/detect",
            object_count=1,
            object_str="person",
            max_control_count=0,
            state=1,
        )
        control = self._create_control(code="ctrl-2", algorithm_code="alg-api")

        with mock.patch("app.views.ControlView.g_zlm.get_rtspUrl", return_value="rtsp://demo", create=True):
            with mock.patch("app.views.ControlView.g_analyzer.control_add", return_value=(True, "ok")) as mocked_add:
                ok, _ = _start_control(control)

        self.assertTrue(ok)
        passed_api_url = mocked_add.call_args.kwargs.get("api_url")
        self.assertEqual(passed_api_url, "http://example.com/detect")

    def test_max_control_count_blocks_start_when_limit_reached(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-limit",
            name="alg-limit",
            algorithm_type=0,
            basic_source="model",
            api_url="",
            object_count=1,
            object_str="person",
            max_control_count=1,
            state=1,
        )
        self._create_control(code="ctrl-a", algorithm_code="alg-limit", state=1)
        pending = self._create_control(code="ctrl-b", algorithm_code="alg-limit", state=0)

        with mock.patch("app.views.ControlView.g_zlm.get_rtspUrl", return_value="rtsp://demo", create=True):
            with mock.patch("app.views.ControlView.g_analyzer.control_add", return_value=(True, "ok")) as mocked_add:
                ok, msg = _start_control(pending)

        self.assertFalse(ok)
        self.assertIn("布控上限", msg)
        self.assertFalse(mocked_add.called)

