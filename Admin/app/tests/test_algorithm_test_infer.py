import json
import os
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from app.models import AlgorithmModel


class AlgorithmTestInferViewTest(TestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def test_open_test_infer_local_model_calls_analyzer_load_and_test(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-local",
            name="alg-local",
            algorithm_type=0,
            algorithm_subtype="detection",
            basic_source="model",
            api_url="",
            model_path="/static/upload/models/a.onnx",
            dll_path="",
            builtin_behavior="",
            object_count=2,
            object_str="person,car",
            max_control_count=0,
            conf_thresh=0.33,
            nms_thresh=0.52,
            model_concurrency=2,
            state=1,
        )

        uploaded = SimpleUploadedFile("test.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")

        device_info_payload = {
            "code": 1000,
            "msg": "success",
            "onnxProviders": ["CPUExecutionProvider", "CUDAExecutionProvider"],
            "openvinoDevices": ["CPU"],
        }

        with (
            mock.patch(
                "app.views.Algorithm.g_analyzer.device_info",
                return_value=(True, "ok", device_info_payload),
                create=True,
            ),
            mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load,
            mock.patch(
                "app.views.Algorithm.g_analyzer.algorithm_test_infer",
                return_value=(True, "ok", {"code": 1000, "msg": "success"}),
            ) as mocked_test,
        ):
            res = self.client.post(
                "/algorithm/openTestInfer",
                data={"code": "alg-local", "device": "GPU", "image": uploaded},
            )

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)

        from app.views import Algorithm as AlgorithmView

        expected_path = os.path.normpath(os.path.join(AlgorithmView.g_config.uploadDir, "models", "a.onnx"))
        kwargs = mocked_load.call_args.kwargs
        self.assertEqual(kwargs.get("code"), "alg-local_gpu")
        self.assertEqual(kwargs.get("modelPath"), expected_path)
        self.assertEqual(kwargs.get("device"), "GPU")
        self.assertEqual(kwargs.get("modelConcurrency"), 2)
        self.assertEqual(kwargs.get("classNames"), ["person", "car"])
        self.assertEqual(kwargs.get("algorithmSubtype"), "detection")

        args = mocked_test.call_args.args
        self.assertEqual(args[0], "alg-local_gpu")
        self.assertTrue(isinstance(args[1], str) and len(args[1]) > 0)
        kwargs = mocked_test.call_args.kwargs
        self.assertEqual(kwargs.get("confThresh"), 0.33)
        self.assertEqual(kwargs.get("nmsThresh"), 0.52)

    def test_add_algorithm_persists_model_parameters(self):
        response = self.client.post(
            "/algorithm/add",
            data={
                "handle": "add",
                "code": "alg_api_params_1",
                "name": "ALG API PARAMS 1",
                "algorithm_type": "0",
                "algorithm_subtype": "detection",
                "basic_source": "api",
                "api_url": "http://example.com/infer",
                "object_str": "",
                "max_control_count": "0",
                "model_concurrency": "2",
                "remark": "",
                "license_package": "core",
                "model_precision": "FP16",
                "input_width": "320",
                "input_height": "256",
                "nms_thresh": "0.33",
                "conf_thresh": "0.66",
            },
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        algorithm = AlgorithmModel.objects.get(code="alg_api_params_1")
        self.assertEqual(algorithm.model_precision, "FP16")
        self.assertEqual(algorithm.input_width, 320)
        self.assertEqual(algorithm.input_height, 256)
        self.assertAlmostEqual(algorithm.nms_thresh, 0.33, places=3)
        self.assertAlmostEqual(algorithm.conf_thresh, 0.66, places=3)

    def test_add_algorithm_rejects_unsupported_api_v2_builtin(self):
        response = self.client.post(
            "/algorithm/add",
            data={
                "handle": "add",
                "code": "alg_api_v2_fight",
                "name": "ALG API V2 FIGHT",
                "algorithm_type": "1",
                "api_url": "http://example.com/infer",
                "behavior_api_version": "2",
                "builtin_behavior": "fight",
                "object_str": "person",
                "license_package": "core",
            },
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        self.assertContains(response, "APIv2 不支持内置行为算法：fight")
        self.assertFalse(AlgorithmModel.objects.filter(code="alg_api_v2_fight").exists())

    def test_edit_algorithm_updates_model_parameters(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg_edit_params_1",
            name="ALG EDIT PARAMS 1",
            algorithm_type=0,
            algorithm_subtype="detection",
            basic_source="api",
            api_url="http://example.com/infer",
            object_count=0,
            object_str="",
            max_control_count=0,
            license_package="core",
            model_precision="FP32",
            model_concurrency=1,
            input_width=640,
            input_height=640,
            nms_thresh=0.45,
            conf_thresh=0.25,
            state=0,
        )
        response = self.client.post(
            "/algorithm/edit",
            data={
                "handle": "edit",
                "code": "alg_edit_params_1",
                "name": "ALG EDIT PARAMS 1",
                "algorithm_type": "0",
                "algorithm_subtype": "detection",
                "basic_source": "api",
                "api_url": "http://example.com/infer",
                "object_str": "",
                "max_control_count": "0",
                "model_concurrency": "3",
                "license_package": "core",
                "remark": "",
                "model_precision": "INT8",
                "input_width": "416",
                "input_height": "416",
                "nms_thresh": "0.12",
                "conf_thresh": "0.88",
            },
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        algorithm = AlgorithmModel.objects.get(code="alg_edit_params_1")
        self.assertEqual(algorithm.model_precision, "INT8")
        self.assertEqual(algorithm.input_width, 416)
        self.assertEqual(algorithm.input_height, 416)
        self.assertAlmostEqual(algorithm.nms_thresh, 0.12, places=3)
        self.assertAlmostEqual(algorithm.conf_thresh, 0.88, places=3)

    def test_open_test_infer_blank_subtype_defaults_to_detection(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-local-default-subtype",
            name="alg-local-default-subtype",
            algorithm_type=0,
            algorithm_subtype="",
            basic_source="model",
            api_url="",
            model_path="/static/upload/models/a.onnx",
            dll_path="",
            builtin_behavior="",
            object_count=1,
            object_str="person",
            max_control_count=0,
            model_concurrency=1,
            state=1,
        )

        uploaded = SimpleUploadedFile("test.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")

        with mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load, \
            mock.patch("app.views.Algorithm.g_analyzer.algorithm_test_infer", return_value=(True, "ok", {"code": 1000, "msg": "success"})):
            res = self.client.post(
                "/algorithm/openTestInfer",
                data={"code": "alg-local-default-subtype", "device": "CPU", "image": uploaded},
            )

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)
        self.assertEqual(mocked_load.call_args.kwargs.get("algorithmSubtype"), "detection")

    def test_open_test_infer_returns_reason_when_device_not_supported(self):
        """
        v4.712-4: when requested inference device is not supported by the current
        Analyzer build/runtime, the test tool should return a clear reason instead
        of a generic error.
        """
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-local-2",
            name="alg-local-2",
            algorithm_type=0,
            basic_source="model",
            api_url="",
            model_path="/static/upload/models/a.onnx",
            dll_path="",
            builtin_behavior="",
            object_count=1,
            object_str="person",
            max_control_count=0,
            model_concurrency=1,
            state=1,
        )

        uploaded = SimpleUploadedFile("test.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")

        device_info_payload = {
            "code": 1000,
            "msg": "success",
            "onnxProviders": ["CPUExecutionProvider"],
            "openvinoDevices": ["CPU"],
        }

        with (
            mock.patch(
                "app.views.Algorithm.g_analyzer.device_info",
                return_value=(True, "ok", device_info_payload),
                create=True,
            ) as mocked_info,
            mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load,
            mock.patch(
                "app.views.Algorithm.g_analyzer.algorithm_test_infer",
                return_value=(True, "ok", {"code": 1000, "msg": "success"}),
            ) as mocked_test,
        ):
            res = self.client.post(
                "/algorithm/openTestInfer",
                data={"code": "alg-local-2", "device": "GPU", "image": uploaded},
            )

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0, msg=data)
        self.assertIn("CUDAExecutionProvider", str(data.get("msg") or ""))
        self.assertTrue(mocked_info.called)
        self.assertFalse(mocked_load.called)
        self.assertFalse(mocked_test.called)

    def test_open_test_infer_basic_api_calls_remote_api(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-api",
            name="alg-api",
            algorithm_type=0,
            basic_source="api",
            api_url="http://example.com/infer",
            model_path="",
            dll_path="",
            builtin_behavior="",
            object_count=1,
            object_str="person",
            max_control_count=0,
            model_precision="FP16",
            model_concurrency=3,
            input_width=320,
            input_height=192,
            conf_thresh=0.31,
            nms_thresh=0.47,
            state=1,
        )

        uploaded = SimpleUploadedFile("test.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")

        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"code": 1000, "msg": "success", "result": {"happen": False, "happenScore": 0.0, "detects": []}}

        with mock.patch("app.views.Algorithm.requests.post", return_value=fake_resp) as mocked_post, \
            mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load:
            res = self.client.post(
                "/algorithm/openTestInfer",
                data={"code": "alg-api", "device": "CPU", "image": uploaded},
            )

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)
        self.assertEqual(data.get("msg"), "success")
        self.assertTrue(mocked_post.called)
        self.assertFalse(mocked_load.called)
        payload = json.loads(mocked_post.call_args.kwargs["data"])
        self.assertEqual(payload.get("algorithmCode"), "alg-api")
        self.assertEqual(
            payload.get("algorithmParams"),
            {
                "confThresh": 0.31,
                "nmsThresh": 0.47,
                "modelConcurrency": 3,
                "inputWidth": 320,
                "inputHeight": 192,
                "modelPrecision": "FP16",
            },
        )
        self.assertTrue(payload.get("image_base64"))

    def test_open_test_infer_local_model_requires_object_str_when_not_tracking(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-missing-obj",
            name="alg-missing-obj",
            algorithm_type=0,
            algorithm_subtype="detection",
            basic_source="model",
            api_url="",
            model_path="/static/upload/models/a.onnx",
            dll_path="",
            builtin_behavior="",
            object_count=0,
            object_str="",
            max_control_count=0,
            model_concurrency=1,
            state=1,
        )

        uploaded = SimpleUploadedFile("test.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")

        with (
            mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load,
            mock.patch(
                "app.views.Algorithm.g_analyzer.algorithm_test_infer",
                return_value=(True, "ok", {"code": 1000, "msg": "success"}),
            ) as mocked_test,
        ):
            res = self.client.post(
                "/algorithm/openTestInfer",
                data={"code": "alg-missing-obj", "device": "CPU", "image": uploaded},
            )

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0)
        self.assertIn("object_str", str(data.get("msg") or ""))
        self.assertFalse(mocked_load.called)
        self.assertFalse(mocked_test.called)
