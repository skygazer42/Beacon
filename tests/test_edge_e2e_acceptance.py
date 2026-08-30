import json
import os
import unittest
from unittest import mock
from urllib.parse import urlsplit

from tools import edge_e2e_acceptance as acceptance


class _FakeSession:
    def __init__(self):
        self.trust_env = True
        self.closed = False

    def close(self):
        self.closed = True


class _FakeSimulator:
    stream_url = "rtsp://camera-user:camera-password@source.invalid/live"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True
        return False


class _FakeApi:
    def __init__(self):
        self.calls = []
        self.control_code = ""

    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path
        self.calls.append((method.upper(), path, kwargs))
        if path == "/index/api/getServerConfig":
            return {"code": 0, "msg": "success"}, 200
        if path == "/stream/openGet":
            return {"code": 1000, "data": {"forward_state": 1}}, 200
        if path == "/api/controls":
            return {
                "code": 1000,
                "data": [{"code": self.control_code}],
            }, 200
        return {"code": 1000, "msg": "success"}, 200


def _config(**overrides):
    values = {
        "admin_url": "http://admin.invalid:9991",
        "analyzer_url": "http://analyzer.invalid:9993",
        "media_http_url": "http://media.invalid:9992",
        "media_rtsp_base_url": "rtsp://media.invalid:9994",
        "token": "open-api-secret-token",
        "media_secret": "media-server-secret",
        "source_mode": "synthetic",
        "source_url": "",
        "alarm_workflow": True,
        "algorithm_code": "",
        "object_code": "",
        "timeout": 5.0,
    }
    values.update(overrides)
    return acceptance.AcceptanceConfig(**values)


class EdgeAcceptanceRunnerTest(unittest.TestCase):
    def test_synthetic_video_and_alarm_workflow_are_redacted_and_cleaned(self):
        fake_api = _FakeApi()
        fake_session = _FakeSession()
        simulators = []

        def simulator_factory(**kwargs):
            simulator = _FakeSimulator(**kwargs)
            simulators.append(simulator)
            return simulator

        runner = acceptance.EdgeAcceptanceRunner(
            _config(),
            request_json=fake_api,
            probe_rtsp=lambda _url, _timeout: {
                "status": "passed",
                "codec": "h264",
                "width": 320,
                "height": 180,
            },
            simulator_factory=simulator_factory,
            session=fake_session,
        )

        report = runner.run()

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["schema"], acceptance.SCHEMA)
        self.assertEqual(report["checks"]["video_l1"]["codec"], "h264")
        self.assertEqual(report["checks"]["alarm_workflow"]["status"], "passed")
        self.assertEqual(report["cleanup"]["status"], "passed")
        self.assertTrue(fake_session.closed)
        self.assertTrue(simulators[0].exited)

        serialized = json.dumps(report)
        for secret in (
            "open-api-secret-token",
            "media-server-secret",
            "camera-user",
            "camera-password",
        ):
            self.assertNotIn(secret, serialized)

        paths = [path for _method, path, _kwargs in fake_api.calls]
        self.assertIn("/control/openDel", paths)
        self.assertIn("/stream/openDelStreamProxy", paths)
        self.assertIn("/stream/openDel", paths)
        bulk_delete_calls = [
            kwargs
            for _method, path, kwargs in fake_api.calls
            if path == "/stream/openDel"
        ]
        self.assertEqual(bulk_delete_calls[0]["json_body"]["handle"], "one")

        media_call = next(
            kwargs
            for _method, path, kwargs in fake_api.calls
            if path == "/index/api/getServerConfig"
        )
        self.assertEqual(media_call["headers"], {})

    def test_video_failure_still_cleans_only_created_stream_fixture(self):
        fake_api = _FakeApi()

        def fail_probe(_url, _timeout):
            raise acceptance.AcceptanceError("probe failed")

        runner = acceptance.EdgeAcceptanceRunner(
            _config(alarm_workflow=False),
            request_json=fake_api,
            probe_rtsp=fail_probe,
            simulator_factory=_FakeSimulator,
            session=_FakeSession(),
        )

        report = runner.run()

        self.assertEqual(report["status"], "failed")
        self.assertIn("probe failed", report["error"])
        self.assertEqual(report["cleanup"]["status"], "passed")
        paths = [path for _method, path, _kwargs in fake_api.calls]
        self.assertIn("/stream/openDelStreamProxy", paths)
        self.assertIn("/stream/openDel", paths)
        self.assertNotIn("/control/openDel", paths)

    def test_real_control_is_confirmed_by_analyzer_and_stopped_before_delete(self):
        fake_api = _FakeApi()
        runner = acceptance.EdgeAcceptanceRunner(
            _config(
                alarm_workflow=False,
                algorithm_code="person-detector",
                object_code="person",
            ),
            request_json=fake_api,
            probe_rtsp=lambda _url, _timeout: {
                "status": "passed",
                "codec": "h264",
                "width": 320,
                "height": 180,
            },
            simulator_factory=_FakeSimulator,
            session=_FakeSession(),
        )
        fake_api.control_code = runner.control_code

        report = runner.run()

        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["checks"]["control_l1"]["algorithm_code"],
            "person-detector",
        )
        paths = [path for _method, path, _kwargs in fake_api.calls]
        self.assertLess(
            paths.index("/control/openStopControl"),
            paths.index("/control/openDel"),
        )


class EdgeAcceptanceConfigurationTest(unittest.TestCase):
    def test_service_urls_reject_embedded_credentials(self):
        with self.assertRaisesRegex(acceptance.AcceptanceError, "without credentials"):
            acceptance._normalize_service_url(
                "https://admin:secret@example.invalid",
                label="admin URL",
                schemes=frozenset({"https"}),
            )

    def test_external_source_is_read_only_from_environment(self):
        arguments = acceptance._parser().parse_args(["--external-l1"])
        source = "rtsp://camera-user:camera-password@camera.invalid/live"
        with mock.patch.dict(os.environ, {"BEACON_E2E_RTSP_URL": source}, clear=False):
            config = acceptance._config_from_args(arguments)

        self.assertEqual(config.source_mode, "external")
        self.assertEqual(config.source_url, source)

    def test_algorithm_requires_source_and_object(self):
        arguments = acceptance._parser().parse_args(
            ["--algorithm-code", "person-detector"]
        )
        with self.assertRaisesRegex(acceptance.AcceptanceError, "requires"):
            acceptance._config_from_args(arguments)


if __name__ == "__main__":
    unittest.main()
