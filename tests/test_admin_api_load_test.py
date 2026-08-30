import contextlib
import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from tools import admin_api_load_test


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        status = 503 if self.path.startswith("/fail") else 200
        payload = json.dumps({"status": status}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        return


class AdminApiLoadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    @staticmethod
    def _args(*values):
        return admin_api_load_test._build_arg_parser().parse_args(list(values))

    def test_successful_load_gate(self):
        args = self._args(
            "--url",
            f"{self.base_url}/ok",
            "--requests",
            "20",
            "--concurrency",
            "4",
            "--warmup-requests",
            "2",
            "--max-error-rate",
            "0",
            "--max-p95-ms",
            "1000",
            "--min-rps",
            "0.1",
        )

        report = admin_api_load_test._run_load_test(args)

        self.assertTrue(report["gate"]["passed"])
        self.assertEqual(report["results"]["status_counts"], {"200": 20})
        self.assertEqual(report["gate"]["error_rate"], 0)

    def test_main_returns_two_when_gate_fails(self):
        argv = [
            "admin_api_load_test.py",
            "--url",
            f"{self.base_url}/fail",
            "--requests",
            "5",
            "--concurrency",
            "1",
            "--warmup-requests",
            "0",
            "--max-error-rate",
            "0",
        ]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            exit_code = admin_api_load_test.main()

        self.assertEqual(exit_code, 2)
        report = json.loads(output.getvalue())
        self.assertFalse(report["gate"]["passed"])
        self.assertEqual(report["results"]["status_counts"], {"503": 5})
        self.assertIn("error_rate", report["gate"]["failures"][0])

    def test_report_redacts_sensitive_query_values(self):
        args = self._args(
            "--url",
            f"{self.base_url}/ok?mediaSecret=do-not-log&plain=visible&access_token=hidden",
            "--requests",
            "1",
            "--warmup-requests",
            "0",
        )

        report = admin_api_load_test._run_load_test(args)
        reported_url = report["target"]["url"]

        self.assertNotIn("do-not-log", reported_url)
        self.assertNotIn("hidden", reported_url)
        self.assertIn("plain=visible", reported_url)
        self.assertEqual(reported_url.count("REDACTED"), 2)

    def test_rejects_zero_requests(self):
        args = self._args("--url", f"{self.base_url}/ok", "--requests", "0")
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            admin_api_load_test._run_load_test(args)

    def test_rejects_header_injection(self):
        with self.assertRaisesRegex(ValueError, "invalid HTTP header"):
            admin_api_load_test._parse_headers(["X-Test: safe\r\nInjected: value"])

    def test_rejects_url_userinfo(self):
        args = self._args(
            "--url",
            f"http://user:password@127.0.0.1:{self.server.server_address[1]}/ok",
            "--requests",
            "1",
        )
        with self.assertRaisesRegex(ValueError, "userinfo"):
            admin_api_load_test._run_load_test(args)


if __name__ == "__main__":
    unittest.main()
