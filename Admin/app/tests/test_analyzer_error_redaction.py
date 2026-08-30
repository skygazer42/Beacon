from types import SimpleNamespace
from unittest import TestCase, mock

from app.utils.Analyzer import Analyzer, _parse_analyzer_json_response


class AnalyzerErrorRedactionTest(TestCase):
    def test_transport_exception_is_not_returned_to_callers(self):
        analyzer = Analyzer("http://127.0.0.1:9993", open_api_token="test-token")

        with mock.patch(
            "app.utils.Analyzer._requests_post",
            side_effect=RuntimeError("secret filesystem path /srv/private/model.onnx"),
        ):
            state, message = analyzer.algorithm_load("algo", model_path="/models/algo.onnx")

        self.assertFalse(state)
        self.assertEqual(message, "analyzer request failed")
        self.assertNotIn("private", message)

    def test_non_json_response_does_not_echo_response_body(self):
        response = SimpleNamespace(
            status_code=500,
            text="Traceback: database password=do-not-return",
            json=mock.Mock(side_effect=ValueError("invalid JSON")),
        )

        data, message = _parse_analyzer_json_response(response)

        self.assertIsNone(data)
        self.assertEqual(message, "Analyzer HTTP 500 non-JSON response")
        self.assertNotIn("password", message)
