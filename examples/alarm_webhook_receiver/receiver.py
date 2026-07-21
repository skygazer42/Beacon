#!/usr/bin/env python3
"""
Beacon Alarm Webhook Receiver (Example)

Features:
- Optional signature verification: X-Beacon-Signature: sha256=<base64>
- Idempotency by event_id (SQLite)
- Fast ACK (return 200 quickly after dedupe)

This is an integration example for industrial deployments. Customize as needed.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple


def compute_beacon_signature(secret: str, body: bytes) -> str:
    secret_bytes = (secret or "").encode("utf-8")
    digest = hmac.new(secret_bytes, body or b"", hashlib.sha256).digest()
    sig_b64 = base64.b64encode(digest).decode("ascii")
    return f"sha256={sig_b64}"


def _parse_signature_header(value: str) -> Tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if "=" not in raw:
        return "", ""
    alg, sig = raw.split("=", 1)
    return alg.strip().lower(), sig.strip()


def verify_beacon_signature(secret: str, body: bytes, header_value: str) -> bool:
    """
    Verify `X-Beacon-Signature: sha256=<base64>` against raw request body bytes.
    """
    if not secret:
        return True
    alg, sig_b64 = _parse_signature_header(header_value)
    if alg != "sha256" or not sig_b64:
        return False
    expected = compute_beacon_signature(secret, body)
    return hmac.compare_digest(expected, f"{alg}={sig_b64}")


class IdempotencyStore:
    def __init__(self, db_path: str):
        self._db_path = str(db_path or "").strip() or "processed_events.sqlite3"
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS processed_events ("
            "event_id TEXT PRIMARY KEY,"
            "received_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    def mark_processed(self, event_id: str) -> bool:
        eid = str(event_id or "").strip()
        if not eid:
            return False
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO processed_events(event_id, received_at) VALUES(?, ?)",
            (eid, now),
        )
        self._conn.commit()
        return cur.rowcount == 1


class AlarmWebhookHandler(BaseHTTPRequestHandler):
    server_version = "BeaconWebhookReceiver/1.0"

    def _json_response(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        cfg = getattr(self.server, "_beacon_cfg", {})  # type: ignore[attr-defined]
        expected_path = cfg.get("path", "/webhook/alarm")
        secret = cfg.get("secret", "")
        store: IdempotencyStore = cfg["store"]

        if self.path != expected_path:
            self._json_response(404, {"ok": False, "error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
        except Exception:
            length = 0
        body = self.rfile.read(max(0, length))

        if secret:
            sig = self.headers.get("X-Beacon-Signature", "")
            if not verify_beacon_signature(secret, body, sig):
                self._json_response(401, {"ok": False, "error": "bad_signature"})
                return

        try:
            event = json.loads(body.decode("utf-8"))
        except Exception:
            self._json_response(400, {"ok": False, "error": "bad_json"})
            return

        event_id = str(event.get("event_id") or self.headers.get("X-Beacon-Event-Id") or "").strip()
        if not event_id:
            self._json_response(400, {"ok": False, "error": "missing_event_id"})
            return

        is_new = store.mark_processed(event_id)
        if not is_new:
            self._json_response(200, {"ok": True, "duplicate": True})
            return

        # Minimal logging for on-site debugging / integration verification
        event_type = str(event.get("event_type") or "")
        legacy_event = str(event.get("event") or "")
        alarm_id = event.get("alarm_id")
        control_code = str(event.get("control_code") or "")
        print(
            f"[beacon-webhook] event_id={event_id} event_type={event_type} event={legacy_event} "
            f"alarm_id={alarm_id} control_code={control_code}",
            flush=True,
        )

        self._json_response(200, {"ok": True})

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        # Reduce default noisy request logs; use explicit prints above.
        return


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Beacon Alarm Webhook Receiver (Example)")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9000, help="Listen port (default: 9000)")
    parser.add_argument("--path", default="/webhook/alarm", help="Webhook path (default: /webhook/alarm)")
    parser.add_argument(
        "--secret",
        default=os.environ.get("BEACON_ALARM_WEBHOOK_SECRET", ""),
        help="Webhook secret for signature verification (default: env BEACON_ALARM_WEBHOOK_SECRET)",
    )
    parser.add_argument("--db", default="./processed_events.sqlite3", help="SQLite path for event_id dedupe")
    args = parser.parse_args(argv)

    store = IdempotencyStore(args.db)

    httpd = ThreadingHTTPServer((args.host, int(args.port)), AlarmWebhookHandler)
    setattr(httpd, "_beacon_cfg", {"path": args.path, "secret": args.secret, "store": store})

    print(f"[beacon-webhook] listening on http://{args.host}:{args.port}{args.path}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

