#!/usr/bin/env python3
"""Authenticated Beacon container health and readiness probe."""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import stat
import sys
import time


CHECK_PATHS = {
    "health": "/healthz",
    "ready": "/readyz",
}
MAX_RESPONSE_BYTES = 64 * 1024
MAX_WORKER_HEARTBEAT_BYTES = 16 * 1024


def _contains_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in str(value or ""))


def probe(
    check: str,
    *,
    port: int,
    token: str,
    host_header: str,
    timeout_seconds: float,
) -> tuple[bool, str]:
    """Run one direct loopback probe without consulting proxy variables."""
    path = CHECK_PATHS.get(str(check or "").strip().lower())
    if not path:
        return False, "unsupported check"
    if not str(token or "").strip():
        return False, "probe token is not configured"
    if _contains_control_characters(token) or _contains_control_characters(host_header):
        return False, "probe headers are invalid"

    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=float(timeout_seconds))
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "Connection": "close",
                "Host": str(host_header or "127.0.0.1"),
            },
        )
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception as exc:
        return False, f"request failed: {type(exc).__name__}"
    finally:
        connection.close()

    if int(response.status) != 200:
        return False, f"unexpected HTTP status: {int(response.status)}"
    if len(raw) > MAX_RESPONSE_BYTES:
        return False, "response is too large"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "response is not valid JSON"
    if not isinstance(payload, dict) or payload.get("code") != 1000:
        return False, "response business code is not 1000"
    data = payload.get("data")
    if not isinstance(data, dict):
        return False, "response data is not an object"
    status = str(data.get("status") or "")
    if status != "ok":
        return False, "response status is not ok"
    return True, "ok"


def probe_worker(
    heartbeat_path: str,
    *,
    max_age_seconds: float,
    now=time.time,
) -> tuple[bool, str]:
    """Validate the private heartbeat emitted by the background worker."""
    path = str(heartbeat_path or "").strip()
    if not path or not os.path.isabs(path):
        return False, "worker heartbeat path is invalid"
    try:
        max_age = float(max_age_seconds)
    except (TypeError, ValueError, OverflowError):
        return False, "worker heartbeat max age is invalid"
    if not (2 <= max_age <= 300):
        return False, "worker heartbeat max age is out of range"

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                return False, "worker heartbeat is not a regular file"
            if file_stat.st_size > MAX_WORKER_HEARTBEAT_BYTES:
                return False, "worker heartbeat is too large"
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read(MAX_WORKER_HEARTBEAT_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError as exc:
        return False, f"worker heartbeat unavailable: {type(exc).__name__}"

    if len(raw) > MAX_WORKER_HEARTBEAT_BYTES:
        return False, "worker heartbeat is too large"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "worker heartbeat is not valid JSON"
    if not isinstance(payload, dict):
        return False, "worker heartbeat is not an object"
    if payload.get("schema_version") != 1 or payload.get("role") != "worker":
        return False, "worker heartbeat identity is invalid"

    state = str(payload.get("state") or "")
    background_state = str(payload.get("background_state") or "")
    if state == "leader" and background_state != "running":
        return False, "leader background services are not running"
    if state == "standby" and background_state != "standby":
        return False, "standby worker state is inconsistent"
    if state not in {"leader", "standby"}:
        return False, "worker heartbeat state is unhealthy"

    try:
        updated_at = float(payload.get("updated_at"))
        current_time = float(now())
    except (TypeError, ValueError, OverflowError):
        return False, "worker heartbeat timestamp is invalid"
    if not math.isfinite(updated_at) or not math.isfinite(current_time):
        return False, "worker heartbeat timestamp is invalid"
    age = current_time - updated_at
    if age < -5:
        return False, "worker heartbeat timestamp is in the future"
    if age > max_age:
        return False, "worker heartbeat is stale"
    return True, state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=sorted((*CHECK_PATHS, "worker")))
    args = parser.parse_args(argv)

    if args.check == "worker":
        try:
            max_age_seconds = float(
                str(os.environ.get("BEACON_BACKGROUND_HEARTBEAT_MAX_AGE_SECONDS", "20") or "20")
            )
        except ValueError:
            print("Beacon worker probe configuration is invalid", file=sys.stderr)
            return 2
        ok, message = probe_worker(
            str(
                os.environ.get(
                    "BEACON_BACKGROUND_HEARTBEAT_PATH",
                    "/tmp/beacon-background-worker.json",
                )
                or ""
            ),
            max_age_seconds=max_age_seconds,
        )
        if not ok:
            print(f"Beacon worker probe failed: {message}", file=sys.stderr)
            return 1
        return 0

    try:
        port = int(str(os.environ.get("BEACON_HEALTH_PROBE_PORT", "8000") or "8000"))
        timeout_seconds = float(
            str(os.environ.get("BEACON_HEALTH_PROBE_TIMEOUT_SECONDS", "3") or "3")
        )
    except ValueError:
        print("Beacon probe configuration is invalid", file=sys.stderr)
        return 2
    if not (1 <= port <= 65535) or not (0.1 <= timeout_seconds <= 30):
        print("Beacon probe configuration is out of range", file=sys.stderr)
        return 2

    ok, message = probe(
        args.check,
        port=port,
        token=str(os.environ.get("BEACON_OPEN_API_TOKEN", "") or ""),
        host_header=str(os.environ.get("BEACON_HEALTH_CHECK_HOST", "127.0.0.1") or "127.0.0.1"),
        timeout_seconds=timeout_seconds,
    )
    if not ok:
        print(f"Beacon {args.check} probe failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
