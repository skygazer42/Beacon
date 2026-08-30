#!/usr/bin/env python3
"""Run repeatable, self-cleaning Beacon Edge acceptance checks.

Secrets and source URLs are read from environment variables and are never
included in the JSON report. Every mutable fixture receives a random code and
cleanup always targets that exact code; this tool never uses bulk-delete APIs.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import requests

if __package__:
    from tools.rtsp_simulator import RtspSimulator
else:  # pragma: no cover - exercised by the CLI smoke test
    from rtsp_simulator import RtspSimulator


SCHEMA = "beacon.edge-e2e.v1"
SUCCESS_CODE = 1000
MAX_ERROR_LENGTH = 500
SUPPORTED_SOURCE_SCHEMES = frozenset({"rtsp", "rtmp", "http", "https", "srt"})


class AcceptanceError(RuntimeError):
    """Raised when an acceptance invariant is not satisfied."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_service_url(value: str, *, label: str, schemes: frozenset[str]) -> str:
    raw = str(value or "").strip()
    if not raw or any(character in raw for character in ("\x00", "\r", "\n")):
        raise AcceptanceError(f"{label} must be a non-empty absolute URL")
    try:
        parsed = urlsplit(raw)
        parsed.port
    except ValueError as exc:
        raise AcceptanceError(f"{label} is invalid") from exc
    if (
        parsed.scheme.lower() not in schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise AcceptanceError(
            f"{label} must be an absolute service URL without credentials, path, query, or fragment"
        )
    return raw.rstrip("/")


def _validate_source_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 4096 or any(character in raw for character in ("\x00", "\r", "\n")):
        raise AcceptanceError("BEACON_E2E_RTSP_URL must contain one valid stream URL")
    try:
        parsed = urlsplit(raw)
        parsed.port
    except ValueError as exc:
        raise AcceptanceError("BEACON_E2E_RTSP_URL is invalid") from exc
    if parsed.scheme.lower() not in SUPPORTED_SOURCE_SCHEMES or not parsed.hostname:
        raise AcceptanceError(
            "BEACON_E2E_RTSP_URL must use rtsp, rtmp, http, https, or srt"
        )
    return raw


def _bounded_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AcceptanceError("timeout must be numeric") from exc
    if not 5 <= timeout <= 120:
        raise AcceptanceError("timeout must be between 5 and 120 seconds")
    return timeout


def _request_json(
    method: str,
    url: str,
    *,
    session: requests.Session,
    headers: Mapping[str, str],
    timeout: float,
    json_body: Optional[Mapping[str, Any]] = None,
    form_body: Optional[Mapping[str, Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], int]:
    kwargs: Dict[str, Any] = {
        "headers": dict(headers),
        "timeout": timeout,
    }
    if json_body is not None:
        kwargs["json"] = dict(json_body)
    if form_body is not None:
        kwargs["data"] = dict(form_body)
    if params is not None:
        kwargs["params"] = dict(params)
    try:
        response = session.request(method, url, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AcceptanceError(f"{method.upper()} request failed") from exc
    if not isinstance(payload, dict):
        raise AcceptanceError(f"{method.upper()} request returned a non-object JSON payload")
    return payload, int(response.status_code)


def _require_code(payload: Mapping[str, Any], expected: int, *, label: str) -> None:
    try:
        code = int(payload.get("code"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AcceptanceError(f"{label} returned an invalid application code") from exc
    if code != expected:
        message = str(payload.get("msg", "") or "")[:200]
        raise AcceptanceError(f"{label} failed: code={code}, msg={message}")


def _tcp_check(service_url: str, timeout: float) -> Dict[str, Any]:
    parsed = urlsplit(service_url)
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    port = parsed.port or default_port
    try:
        with socket.create_connection((str(parsed.hostname), int(port)), timeout=min(timeout, 5.0)):
            pass
    except OSError as exc:
        raise AcceptanceError("MediaServer TCP endpoint is not reachable") from exc
    return {"mode": "tcp", "status": "passed"}


def _probe_rtsp(stream_url: str, timeout: float) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height",
                    "-of",
                    "json",
                    stream_url,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=min(8.0, max(1.0, timeout)),
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            try:
                streams = json.loads(result.stdout).get("streams") or []
            except (TypeError, ValueError, json.JSONDecodeError):
                streams = []
            if streams and isinstance(streams[0], dict) and streams[0].get("codec_name"):
                stream = streams[0]
                return {
                    "status": "passed",
                    "codec": str(stream.get("codec_name") or ""),
                    "width": int(stream.get("width") or 0),
                    "height": int(stream.get("height") or 0),
                }
        time.sleep(0.5)
    raise AcceptanceError("MediaServer RTSP output did not become readable before timeout")


def _contains_code(value: Any, expected_code: str) -> bool:
    if isinstance(value, dict):
        if str(value.get("code", "") or "") == expected_code:
            return True
        return any(_contains_code(item, expected_code) for item in value.values())
    if isinstance(value, list):
        return any(_contains_code(item, expected_code) for item in value)
    return False


@dataclass(frozen=True)
class AcceptanceConfig:
    admin_url: str
    analyzer_url: str
    media_http_url: str
    media_rtsp_base_url: str
    token: str = ""
    media_secret: str = ""
    source_mode: str = "none"
    source_url: str = ""
    alarm_workflow: bool = False
    algorithm_code: str = ""
    object_code: str = ""
    timeout: float = 30.0


class EdgeAcceptanceRunner:
    def __init__(
        self,
        config: AcceptanceConfig,
        *,
        request_json: Callable[..., Tuple[Dict[str, Any], int]] = _request_json,
        tcp_check: Callable[[str, float], Dict[str, Any]] = _tcp_check,
        probe_rtsp: Callable[[str, float], Dict[str, Any]] = _probe_rtsp,
        simulator_factory: Callable[..., Any] = RtspSimulator,
        session: Optional[requests.Session] = None,
    ):
        self.config = config
        self.request_json = request_json
        self.tcp_check = tcp_check
        self.probe_rtsp = probe_rtsp
        self.simulator_factory = simulator_factory
        self.session = session or requests.Session()
        self.session.trust_env = False
        fixture_suffix = uuid.uuid4().hex[:12]
        self.stream_code = f"beacon-e2e-{fixture_suffix}"
        self.control_code = f"beacon-e2e-control-{fixture_suffix}"
        self.stream_created = False
        self.proxy_started = False
        self.control_created = False
        self.control_started = False
        self.cleanup_errors: list[str] = []
        self.report: Dict[str, Any] = {
            "schema": SCHEMA,
            "status": "running",
            "started_at": _utc_now(),
            "checks": {},
        }

    @property
    def headers(self) -> Dict[str, str]:
        if not self.config.token:
            return {}
        return {"Authorization": f"Bearer {self.config.token}"}

    def _redact(self, value: Any) -> str:
        text = str(value or "")
        for secret in (
            self.config.token,
            self.config.media_secret,
            self.config.source_url,
        ):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text[:MAX_ERROR_LENGTH]

    def _api(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        json_body: Optional[Mapping[str, Any]] = None,
        form_body: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        use_token: bool = True,
    ) -> Tuple[Dict[str, Any], int]:
        return self.request_json(
            method,
            f"{base_url}{path}",
            session=self.session,
            headers=self.headers if use_token else {},
            timeout=self.config.timeout,
            json_body=json_body,
            form_body=form_body,
            params=params,
        )

    def _check_l0(self) -> None:
        checks = self.report["checks"]
        for name, base_url, path in (
            ("admin_health", self.config.admin_url, "/healthz"),
            ("admin_ready", self.config.admin_url, "/readyz"),
            ("analyzer_health", self.config.analyzer_url, "/api/health"),
        ):
            payload, status = self._api("GET", base_url, path)
            _require_code(payload, SUCCESS_CODE, label=name)
            checks[name] = {"status": "passed", "http_status": status}

        if self.config.media_secret:
            payload, status = self._api(
                "GET",
                self.config.media_http_url,
                "/index/api/getServerConfig",
                params={"secret": self.config.media_secret},
                use_token=False,
            )
            _require_code(payload, 0, label="media_api")
            checks["media_health"] = {
                "mode": "authenticated_api",
                "status": "passed",
                "http_status": status,
            }
        else:
            checks["media_health"] = self.tcp_check(
                self.config.media_http_url,
                self.config.timeout,
            )

    def _source_context(self):
        if self.config.source_mode == "synthetic":
            return self.simulator_factory(
                path=self.stream_code,
                width=320,
                height=180,
                rate=5,
            )
        if self.config.source_mode == "external":
            return contextlib.nullcontext(self.config.source_url)
        return contextlib.nullcontext("")

    def _create_stream_and_proxy(self, source_url: str) -> None:
        payload, _status = self._api(
            "POST",
            self.config.admin_url,
            "/stream/openAdd",
            json_body={
                "code": self.stream_code,
                "app": "live",
                "pull_stream_url": source_url,
                "pull_stream_type": 1,
                "nickname": "Beacon disposable E2E stream",
            },
        )
        _require_code(payload, SUCCESS_CODE, label="stream registration")
        self.stream_created = True

        payload, _status = self._api(
            "POST",
            self.config.admin_url,
            "/stream/openAddStreamProxy",
            json_body={"code": self.stream_code},
        )
        _require_code(payload, SUCCESS_CODE, label="stream proxy")
        self.proxy_started = True

        probe = self.probe_rtsp(
            f"{self.config.media_rtsp_base_url}/live/{self.stream_code}",
            self.config.timeout,
        )
        payload, _status = self._api(
            "GET",
            self.config.admin_url,
            "/stream/openGet",
            params={"code": self.stream_code},
        )
        _require_code(payload, SUCCESS_CODE, label="stream query")
        try:
            forward_state = int((payload.get("data") or {}).get("forward_state", 0))
        except (TypeError, ValueError, AttributeError) as exc:
            raise AcceptanceError("stream query returned an invalid forward_state") from exc
        if forward_state != 1:
            raise AcceptanceError("Admin did not persist the active stream proxy state")

        self.report["checks"]["video_l1"] = {
            "status": "passed",
            "source": self.config.source_mode,
            "codec": str(probe.get("codec") or ""),
            "width": int(probe.get("width") or 0),
            "height": int(probe.get("height") or 0),
        }

    def _create_control(self) -> None:
        algorithm_code = self.config.algorithm_code or "acceptance-placeholder"
        object_code = self.config.object_code or "acceptance-object"
        stream_name = self.stream_code if self.stream_created else f"{self.control_code}-stream"
        payload, _status = self._api(
            "POST",
            self.config.admin_url,
            "/api/postAddControl",
            form_body={
                "controlCode": self.control_code,
                "streamApp": "live",
                "streamName": stream_name,
                "streamVideo": "video",
                "streamAudio": "audio",
                "algorithmCode": algorithm_code,
                "objectCode": object_code,
            },
        )
        _require_code(payload, SUCCESS_CODE, label="control creation")
        self.control_created = True

    def _start_and_verify_control(self) -> None:
        payload, _status = self._api(
            "POST",
            self.config.admin_url,
            "/control/openStartControl",
            json_body={"code": self.control_code},
        )
        _require_code(payload, SUCCESS_CODE, label="control start")
        self.control_started = True

        deadline = time.monotonic() + self.config.timeout
        while time.monotonic() < deadline:
            payload, status = self._api(
                "POST",
                self.config.analyzer_url,
                "/api/controls",
                json_body={},
            )
            _require_code(payload, SUCCESS_CODE, label="analyzer controls")
            if _contains_code(payload.get("data"), self.control_code):
                self.report["checks"]["control_l1"] = {
                    "status": "passed",
                    "http_status": status,
                    "algorithm_code": self.config.algorithm_code,
                    "object_code": self.config.object_code,
                }
                return
            time.sleep(0.5)
        raise AcceptanceError("Analyzer did not report the disposable control before timeout")

    def _run_alarm_workflow(self) -> None:
        if not self.control_created:
            self._create_control()
        payload, status = self._api(
            "POST",
            self.config.admin_url,
            "/alarm/openAdd",
            json_body={
                "control_code": self.control_code,
                "desc": "Disposable Beacon acceptance alarm",
            },
        )
        _require_code(payload, SUCCESS_CODE, label="alarm ingest")
        self.report["checks"]["alarm_workflow"] = {
            "status": "passed",
            "mode": "simulated_external_event",
            "http_status": status,
        }

    def _cleanup_call(self, label: str, path: str, payload: Mapping[str, Any]) -> None:
        try:
            response, _status = self._api(
                "POST",
                self.config.admin_url,
                path,
                json_body=payload,
            )
            _require_code(response, SUCCESS_CODE, label=label)
        except Exception as exc:  # cleanup must continue through every exact fixture
            self.cleanup_errors.append(self._redact(f"{label}: {exc}"))

    def _cleanup(self) -> None:
        if self.control_started:
            self._cleanup_call(
                "control stop",
                "/control/openStopControl",
                {"code": self.control_code},
            )
        if self.control_created:
            self._cleanup_call(
                "control delete",
                "/control/openDel",
                {"code": self.control_code},
            )
        if self.proxy_started:
            self._cleanup_call(
                "stream proxy delete",
                "/stream/openDelStreamProxy",
                {"code": self.stream_code},
            )
        if self.stream_created:
            self._cleanup_call(
                "stream delete",
                "/stream/openDel",
                {"code": self.stream_code, "handle": "one"},
            )

        fixture_count = sum(
            int(value)
            for value in (
                self.control_created,
                self.stream_created,
            )
        )
        self.report["cleanup"] = {
            "status": "failed" if self.cleanup_errors else "passed",
            "fixture_count": fixture_count,
            "errors": list(self.cleanup_errors),
        }

    def run(self) -> Dict[str, Any]:
        primary_error = ""
        try:
            self._check_l0()
            with self._source_context() as source:
                if self.config.source_mode != "none":
                    source_url = (
                        str(getattr(source, "stream_url", "") or "")
                        if self.config.source_mode == "synthetic"
                        else str(source or "")
                    )
                    if not source_url:
                        raise AcceptanceError("acceptance source did not provide a stream URL")
                    self._create_stream_and_proxy(str(source_url))
                if self.config.algorithm_code:
                    self._create_control()
                    self._start_and_verify_control()
                if self.config.alarm_workflow:
                    self._run_alarm_workflow()
        except Exception as exc:
            primary_error = self._redact(exc)
        finally:
            self._cleanup()
            self.session.close()

        if primary_error or self.cleanup_errors:
            self.report["status"] = "failed"
            if primary_error:
                self.report["error"] = primary_error
        else:
            self.report["status"] = "passed"
        self.report["finished_at"] = _utc_now()
        return self.report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Beacon Edge L0/L1 and simulated alarm acceptance checks"
    )
    parser.add_argument("--admin-url", default="http://127.0.0.1:9991")
    parser.add_argument("--analyzer-url", default="http://127.0.0.1:9993")
    parser.add_argument("--media-http-url", default="http://127.0.0.1:9992")
    parser.add_argument("--media-rtsp-base-url", default="rtsp://127.0.0.1:9994")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--synthetic-l1",
        action="store_true",
        help="Start the bundled synthetic RTSP source and verify MediaServer output",
    )
    source.add_argument(
        "--external-l1",
        action="store_true",
        help="Read a real source from BEACON_E2E_RTSP_URL and verify MediaServer output",
    )
    parser.add_argument(
        "--alarm-workflow",
        action="store_true",
        help="Create and remove a disposable control/alarm workflow fixture",
    )
    parser.add_argument(
        "--algorithm-code",
        default="",
        help="Start a real control with this configured algorithm (requires an L1 source)",
    )
    parser.add_argument("--object-code", default="")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser


def _config_from_args(arguments: argparse.Namespace) -> AcceptanceConfig:
    source_mode = "none"
    source_url = ""
    if arguments.synthetic_l1:
        source_mode = "synthetic"
    elif arguments.external_l1:
        source_mode = "external"
        source_url = _validate_source_url(os.environ.get("BEACON_E2E_RTSP_URL", ""))

    algorithm_code = str(arguments.algorithm_code or "").strip()
    object_code = str(arguments.object_code or "").strip()
    if algorithm_code and source_mode == "none":
        raise AcceptanceError("--algorithm-code requires --synthetic-l1 or --external-l1")
    if algorithm_code and not object_code:
        raise AcceptanceError("--object-code is required with --algorithm-code")

    return AcceptanceConfig(
        admin_url=_normalize_service_url(
            arguments.admin_url,
            label="admin URL",
            schemes=frozenset({"http", "https"}),
        ),
        analyzer_url=_normalize_service_url(
            arguments.analyzer_url,
            label="analyzer URL",
            schemes=frozenset({"http", "https"}),
        ),
        media_http_url=_normalize_service_url(
            arguments.media_http_url,
            label="MediaServer HTTP URL",
            schemes=frozenset({"http", "https"}),
        ),
        media_rtsp_base_url=_normalize_service_url(
            arguments.media_rtsp_base_url,
            label="MediaServer RTSP URL",
            schemes=frozenset({"rtsp"}),
        ),
        token=str(os.environ.get("BEACON_OPEN_API_TOKEN", "") or "").strip(),
        media_secret=str(os.environ.get("BEACON_MEDIA_SECRET", "") or "").strip(),
        source_mode=source_mode,
        source_url=source_url,
        alarm_workflow=bool(arguments.alarm_workflow),
        algorithm_code=algorithm_code,
        object_code=object_code,
        timeout=_bounded_timeout(arguments.timeout_seconds),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        report = EdgeAcceptanceRunner(_config_from_args(arguments)).run()
    except AcceptanceError as exc:
        report = {
            "schema": SCHEMA,
            "status": "failed",
            "error": str(exc)[:MAX_ERROR_LENGTH],
            "finished_at": _utc_now(),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
