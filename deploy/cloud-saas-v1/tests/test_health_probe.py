import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "health_probe.py"
SPEC = importlib.util.spec_from_file_location("beacon_health_probe", SCRIPT_PATH)
health_probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(health_probe)


class _ProbeHandler(BaseHTTPRequestHandler):
    status_code = 200
    payload = {"code": 1000, "data": {"status": "ok"}}
    received = {}

    def do_GET(self):
        type(self).received = {
            "authorization": self.headers.get("Authorization"),
            "host": self.headers.get("Host"),
            "path": self.path,
            "x_forwarded_proto": self.headers.get("X-Forwarded-Proto"),
        }
        body = json.dumps(type(self).payload).encode("utf-8")
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class HealthProbeTest(unittest.TestCase):
    def setUp(self):
        _ProbeHandler.status_code = 200
        _ProbeHandler.payload = {"code": 1000, "data": {"status": "ok"}}
        _ProbeHandler.received = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _probe(self, check="ready", token="probe-token"):
        return health_probe.probe(
            check,
            port=self.server.server_port,
            token=token,
            host_header="beacon-cloud.example.test",
            timeout_seconds=2,
        )

    def test_probe_requires_authenticated_success_payload(self):
        ok, message = self._probe()

        self.assertTrue(ok, msg=message)
        self.assertEqual(_ProbeHandler.received["path"], "/readyz")
        self.assertEqual(_ProbeHandler.received["authorization"], "Bearer probe-token")
        self.assertEqual(_ProbeHandler.received["host"], "beacon-cloud.example.test")
        self.assertEqual(_ProbeHandler.received["x_forwarded_proto"], "https")

    def test_probe_rejects_non_success_business_code(self):
        _ProbeHandler.payload = {"code": 0, "data": {"status": "fail"}}

        ok, message = self._probe()

        self.assertFalse(ok)
        self.assertIn("business code", message)

    def test_probe_rejects_missing_token_without_request(self):
        ok, message = self._probe(token="")

        self.assertFalse(ok)
        self.assertIn("not configured", message)
        self.assertEqual(_ProbeHandler.received, {})

    def test_probe_rejects_malformed_data(self):
        _ProbeHandler.payload = {"code": 1000, "data": ["not", "an", "object"]}

        ok, message = self._probe()

        self.assertFalse(ok)
        self.assertIn("not an object", message)

    def test_worker_probe_accepts_fresh_leader_and_standby(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            for state, background_state in (
                ("leader", "running"),
                ("standby", "standby"),
            ):
                with self.subTest(state=state):
                    path.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "role": "worker",
                                "state": state,
                                "background_state": background_state,
                                "updated_at": 100.0,
                            }
                        ),
                        encoding="utf-8",
                    )
                    ok, message = health_probe.probe_worker(
                        str(path),
                        max_age_seconds=20,
                        now=lambda: 110.0,
                    )

                    self.assertTrue(ok, msg=message)
                    self.assertEqual(message, state)

    def test_worker_probe_rejects_stale_or_degraded_leader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            base = {
                "schema_version": 1,
                "role": "worker",
                "state": "leader",
                "background_state": "running",
                "updated_at": 100.0,
            }
            path.write_text(json.dumps(base), encoding="utf-8")
            ok, message = health_probe.probe_worker(
                str(path),
                max_age_seconds=20,
                now=lambda: 121.0,
            )
            self.assertFalse(ok)
            self.assertIn("stale", message)

            base["background_state"] = "degraded"
            base["updated_at"] = 120.0
            path.write_text(json.dumps(base), encoding="utf-8")
            ok, message = health_probe.probe_worker(
                str(path),
                max_age_seconds=20,
                now=lambda: 121.0,
            )
            self.assertFalse(ok)
            self.assertIn("not running", message)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_worker_probe_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            link = Path(directory) / "worker.json"
            target.write_text("{}", encoding="utf-8")
            os.symlink(target, link)

            ok, message = health_probe.probe_worker(
                str(link),
                max_age_seconds=20,
            )

        self.assertFalse(ok)
        self.assertIn("unavailable", message)


if __name__ == "__main__":
    unittest.main()
