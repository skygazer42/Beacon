import json
import os
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from app.models import AlgorithmModel


class AlgorithmAnalyzerOpsTest(TestCase):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session["user"] = {"id": 1, "username": "admin"}
        session.save()

    def _create_basic_local_algo(self, *, code="alg-1", model_path="/static/upload/models/a.onnx"):
        return AlgorithmModel.objects.create(
            sort=0,
            code=code,
            name=code,
            algorithm_type=0,
            basic_source="model",
            api_url="",
            model_path=model_path,
            dll_path="",
            builtin_behavior="",
            object_count=2,
            object_str="person,car",
            max_control_count=0,
            model_concurrency=2,
            state=1,
        )

    def _upload_encrypted_model(self, *, code, model_name, model_bytes, paired_name="", paired_bytes=b""):
        from app.views import Algorithm as algorithm_view

        old_values = (
            algorithm_view.UPLOAD_MODEL_DIR,
            algorithm_view.UPLOAD_DLL_DIR,
            getattr(algorithm_view.g_config, "modelEncrypt", False),
            getattr(algorithm_view.g_config, "modelEncryptKey", ""),
            getattr(algorithm_view.g_config, "modelEncryptSuffix", ".enc"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = os.path.join(temp_dir, "models")
            dll_dir = os.path.join(temp_dir, "dlls")
            os.makedirs(model_dir, exist_ok=True)
            os.makedirs(dll_dir, exist_ok=True)
            algorithm_view.UPLOAD_MODEL_DIR = model_dir
            algorithm_view.UPLOAD_DLL_DIR = dll_dir
            algorithm_view.g_config.modelEncrypt = True
            algorithm_view.g_config.modelEncryptKey = "k123"
            algorithm_view.g_config.modelEncryptSuffix = ".enc"
            try:
                form_data = {
                    "handle": "add",
                    "code": code,
                    "name": code,
                    "algorithm_type": "0",
                    "algorithm_subtype": "detection",
                    "basic_source": "model",
                    "object_str": "person",
                    "model_file": SimpleUploadedFile(
                        model_name,
                        model_bytes,
                        content_type="application/octet-stream",
                    ),
                }
                if paired_name:
                    form_data["paired_file"] = SimpleUploadedFile(
                        paired_name,
                        paired_bytes,
                        content_type="application/octet-stream",
                    )
                response = self.client.post("/algorithm/add", data=form_data)
                algorithm = AlgorithmModel.objects.get(code=code)
                model_path = str(algorithm.model_path or "")
                saved_payloads = []
                for url in model_path.split("|"):
                    with open(os.path.join(model_dir, os.path.basename(url)), "rb") as saved_file:
                        saved_payloads.append(saved_file.read())
            finally:
                (
                    algorithm_view.UPLOAD_MODEL_DIR,
                    algorithm_view.UPLOAD_DLL_DIR,
                    algorithm_view.g_config.modelEncrypt,
                    algorithm_view.g_config.modelEncryptKey,
                    algorithm_view.g_config.modelEncryptSuffix,
                ) = old_values
        return response, model_path, saved_payloads

    def test_trt_upload_is_auto_encrypted(self):
        response, model_path, saved = self._upload_encrypted_model(
            code="trt_enc_001",
            model_name="demo.engine",
            model_bytes=b"ENGINE_BYTES_001234",
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        self.assertTrue(model_path.lower().endswith(".engine.enc"), msg=model_path)
        self.assertEqual(saved[0][:8], b"BENCv2\x00\x00")

    def test_pre_encrypted_trt_upload_is_not_encrypted_twice(self):
        encrypted = b"BENCv2\x00\x00" + b"PRE_ENCRYPTED_001"
        response, model_path, saved = self._upload_encrypted_model(
            code="trt_enc_002",
            model_name="demo.engine.enc",
            model_bytes=encrypted,
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        self.assertTrue(model_path.lower().endswith(".engine.enc"), msg=model_path)
        self.assertEqual(saved[0], encrypted)

    def test_openvino_pair_upload_is_auto_encrypted(self):
        response, model_path, saved = self._upload_encrypted_model(
            code="ov_enc_001",
            model_name="demo.xml",
            model_bytes=b"<xml>demo</xml>",
            paired_name="demo.bin",
            paired_bytes=b"BIN_BYTES_001234",
        )

        self.assertEqual(response.status_code, 200, msg=response.content)
        paths = model_path.split("|")
        self.assertEqual(len(paths), 2, msg=model_path)
        self.assertTrue(paths[0].lower().endswith(".xml.enc"), msg=model_path)
        self.assertTrue(paths[1].lower().endswith(".bin.enc"), msg=model_path)
        self.assertEqual([payload[:8] for payload in saved], [b"BENCv2\x00\x00", b"BENCv2\x00\x00"])

    def test_open_analyzer_load_basic_api_returns_error_and_skips_load(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-api",
            name="alg-api",
            algorithm_type=0,
            basic_source="api",
            api_url="http://example.com/detect",
            model_path="",
            dll_path="",
            builtin_behavior="",
            object_count=1,
            object_str="person",
            max_control_count=0,
            model_concurrency=1,
            state=1,
        )

        with mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load:
            res = self.client.post("/algorithm/openAnalyzerLoad", data={"code": "alg-api"})

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0)
        self.assertIn("API", data.get("msg", ""))
        self.assertFalse(mocked_load.called)

    def test_open_analyzer_load_basic_local_calls_analyzer_with_resolved_path(self):
        self._create_basic_local_algo(code="alg-local", model_path="/static/upload/models/a.onnx")

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
        ):
            res = self.client.post("/algorithm/openAnalyzerLoad", data={"code": "alg-local", "device": "GPU"})

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

    def test_open_analyzer_load_returns_reason_when_onnx_gpu_provider_missing(self):
        self._create_basic_local_algo(code="alg-local-gpu-check", model_path="/static/upload/models/a.onnx")

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
        ):
            res = self.client.post(
                "/algorithm/openAnalyzerLoad",
                data={"code": "alg-local-gpu-check", "device": "GPU"},
            )

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 0, msg=data)
        self.assertIn("CUDAExecutionProvider", str(data.get("msg") or ""))
        self.assertTrue(mocked_info.called)
        self.assertFalse(mocked_load.called)

    def test_open_analyzer_load_behavior_plugin_uses_dll_path(self):
        AlgorithmModel.objects.create(
            sort=0,
            code="alg-behavior",
            name="alg-behavior",
            algorithm_type=1,
            algorithm_subtype="behavior",
            basic_source="api",
            api_url="",
            model_path="",
            dll_path="/static/upload/dlls/behavior.so",
            builtin_behavior="count",
            object_count=1,
            object_str="count",
            max_control_count=0,
            model_concurrency=1,
            state=1,
        )

        with mock.patch("app.views.Algorithm.g_analyzer.algorithm_load", return_value=(True, "ok")) as mocked_load:
            res = self.client.post("/algorithm/openAnalyzerLoad", data={"code": "alg-behavior", "device": "CPU"})

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000, msg=data)

        from app.views import Algorithm as AlgorithmView

        expected_path = os.path.normpath(os.path.join(AlgorithmView.g_config.uploadDir, "dlls", "behavior.so"))
        kwargs = mocked_load.call_args.kwargs
        self.assertEqual(kwargs.get("code"), "alg-behavior")
        self.assertEqual(kwargs.get("modelPath"), expected_path)
        self.assertIsNone(kwargs.get("classNames"))
        self.assertEqual(kwargs.get("algorithmSubtype"), "behavior")

    def test_open_analyzer_unload_is_idempotent_for_missing_algorithm(self):
        with mock.patch("app.views.Algorithm.g_analyzer.algorithm_unload", return_value=(False, "not found")) as mocked_unload:
            res = self.client.post("/algorithm/openAnalyzerUnload", data={"code": "alg-missing", "device": "TRT"})

        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data.get("code"), 1000)
        args = mocked_unload.call_args.args
        self.assertEqual(args[0], "alg-missing_trt")
