#!/usr/bin/env python3
"""
Beacon tracing stub services (dev/CI helper).

Purpose
-------
Some environments (CI, lightweight dev containers) cannot build/run the full C++
Analyzer + MediaServer binaries due to heavy native dependencies.

This script provides two tiny HTTP servers that mimic only the minimal endpoints
used by Admin's `/control/openIndex` fan-out path:

- MediaServer (ZLM-like): GET /index/api/getMediaList
- Analyzer: POST /api/controls

Both stubs:
- accept incoming W3C `traceparent` headers
- export a Zipkin v2 JSON SERVER span to an OpenTelemetry Collector Zipkin receiver

This enables repo-provable end-to-end trace stitching:
Admin (OTLP/HTTP) -> stub MediaServer (Zipkin) -> stub Analyzer (Zipkin)
into a single trace visible in Jaeger/Tempo via the collector fan-out.

This is NOT a functional replacement for real services. It exists only to
validate tracing pipelines and context propagation.
"""

import argparse
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def _now_us() -> int:
    """处理当前时间`us`。"""
    return int(time.time() * 1_000_000)


def _env_bool(name: str, default: bool = False) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_float(name: str, default: float) -> float:
    """处理环境变量浮点数。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _strip_trailing_slash(url: str) -> str:
    """处理`strip``trailing``slash`。"""
    return str(url or "").strip().rstrip("/")


def _normalize_zipkin_endpoint(raw: str) -> str:
    """执行归一化`zipkin``endpoint`。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    parsed = urlsplit(s)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Zipkin endpoint must use http or https and include a host")
    if s.endswith("/api/v2/spans"):
        return s
    if s.endswith("/"):
        return s + "api/v2/spans"
    return s + "/api/v2/spans"


def _derive_zipkin_from_otlp(otlp_endpoint: str) -> str:
    """从OTLP获取`derive``zipkin`。
    
    Derive Zipkin receiver endpoint from a collector OTLP endpoint.
    
        Example:
          http://127.0.0.1:4318  -> http://127.0.0.1:9411/api/v2/spans
          http://host:4318/v1/traces -> http://host:9411/api/v2/spans
    """
    s = str(otlp_endpoint or "").strip()
    if not s:
        return ""

    scheme = "http"
    host_start = 0
    scheme_pos = s.find("://")
    if scheme_pos != -1:
        scheme = s[:scheme_pos]
        host_start = scheme_pos + 3

    slash_pos = s.find("/", host_start)
    hostport = s[host_start:] if slash_pos == -1 else s[host_start:slash_pos]
    hostport = hostport.strip()
    if not hostport:
        return ""

    # Replace port with 9411.
    host = hostport
    if hostport.startswith("["):
        rb = hostport.find("]")
        if rb != -1:
            host = hostport[: rb + 1]
    else:
        colon = hostport.rfind(":")
        if colon != -1 and colon + 1 < len(hostport):
            host = hostport[:colon]

    return f"{scheme}://{host}:9411/api/v2/spans"


def _zipkin_endpoint() -> str:
    """处理`zipkin``endpoint`。"""
    raw = str(os.environ.get("BEACON_OTEL_ZIPKIN_ENDPOINT") or "").strip()
    if raw:
        return _normalize_zipkin_endpoint(raw)
    raw = str(os.environ.get("OTEL_EXPORTER_ZIPKIN_ENDPOINT") or "").strip()
    if raw:
        return _normalize_zipkin_endpoint(raw)

    raw = str(os.environ.get("BEACON_OTEL_OTLP_ENDPOINT") or "").strip()
    if not raw:
        raw = str(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if raw:
        return _normalize_zipkin_endpoint(_derive_zipkin_from_otlp(raw))
    return ""


def _rand_hex(nbytes: int) -> str:
    """处理`rand``hex`。"""
    return os.urandom(int(nbytes)).hex()


def _is_lower_hex(s: str) -> bool:
    """判断`lower``hex`。"""
    for ch in str(s or ""):
        if ("0" <= ch <= "9") or ("a" <= ch <= "f"):
            continue
        return False
    return True


def _parse_traceparent(value: str) -> Tuple[bool, str, str, bool]:
    """解析`traceparent`。
    
    Returns: (ok, trace_id, parent_span_id, sampled)
    """
    tp = str(value or "").strip().lower()
    if not tp:
        return False, "", "", False
    parts = tp.split("-")
    if len(parts) != 4:
        return False, "", "", False
    version, tid, sid, flags = (p.strip() for p in parts)
    if len(version) != 2 or len(tid) != 32 or len(sid) != 16 or len(flags) != 2:
        return False, "", "", False
    if not (_is_lower_hex(version) and _is_lower_hex(tid) and _is_lower_hex(sid) and _is_lower_hex(flags)):
        return False, "", "", False
    if tid == "0" * 32 or sid == "0" * 16:
        return False, "", "", False
    try:
        flags_int = int(flags, 16)
    except Exception:
        flags_int = 0
    sampled = (flags_int & 0x01) != 0
    return True, tid, sid, sampled


def _sample_without_parent(ratio: float) -> bool:
    """处理`sample``without``parent`。"""
    r = float(ratio)
    if r <= 0.0:
        return False
    if r >= 1.0:
        return True
    return (secrets.randbelow(10_000_000) / 10_000_000) < r


def _export_zipkin_async(endpoint: str, payload: bytes, *, timeout_seconds: float = 2.0) -> None:
    """执行`export``zipkin``async`。"""
    if not endpoint or not payload:
        return

    def _worker() -> None:
        """处理`worker`。"""
        try:
            req = Request(
                url=str(endpoint),
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            # _normalize_zipkin_endpoint restricts this operator-configured URL
            # to HTTP(S), preventing urllib local-file schemes.
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with urlopen(req, timeout=float(timeout_seconds)) as _resp:
                # Best-effort: ignore response body to avoid noisy logs.
                _ = _resp.read()
        except Exception:
            return

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _maybe_export_server_span(
    *,
    service_name: str,
    http_method: str,
    http_target: str,
    http_status: int,
    traceparent: str,
    start_us: int,
    end_us: int,
) -> None:
    """按需执行`export`服务端`span`。"""
    if not _env_bool("BEACON_OTEL_ENABLED", default=False):
        return

    endpoint = _zipkin_endpoint()
    if not endpoint:
        return

    ok, trace_id, parent_span_id, parent_sampled = _parse_traceparent(traceparent)

    if ok:
        sampled = parent_sampled
    else:
        ratio = _env_float("BEACON_OTEL_SAMPLE_RATIO", default=0.1)
        ratio = max(0.0, min(1.0, ratio))
        sampled = _sample_without_parent(ratio)
        trace_id = _rand_hex(16)
        parent_span_id = ""

    if not sampled:
        return

    duration_us = 0
    if end_us >= start_us:
        duration_us = end_us - start_us

    span_id = _rand_hex(8)
    name_path = urlsplit(http_target).path or "/"
    name = f"HTTP {http_method.upper()} {name_path}"

    one: Dict[str, object] = {
        "traceId": trace_id,
        "id": span_id,
        "name": name,
        "kind": "SERVER",
        "timestamp": int(start_us),
        "duration": int(duration_us),
        "localEndpoint": {"serviceName": str(service_name)},
        "tags": {
            "http.method": str(http_method),
            "http.target": str(http_target),
            "http.status_code": str(int(http_status)),
            "beacon.stub": "1",
        },
    }
    if parent_span_id:
        one["parentId"] = parent_span_id

    payload = json.dumps([one], separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    _export_zipkin_async(endpoint, payload)


class _BaseStubHandler(BaseHTTPRequestHandler):
    server_version = "beacon-tracing-stub/1.0"

    stub_service_name: str = "beacon-stub"
    stub_component_tag: str = "stub"

    def log_message(self, format: str, *args) -> None:
        # Keep default logs quiet (industrial default).
        """记录`message`。"""
        if _env_bool("BEACON_TRACING_STUB_VERBOSE", default=False):
            super().log_message(format, *args)

    def _send_json(self, status: int, payload: Dict[str, object]) -> None:
        """返回发送JSON。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _traceparent(self) -> str:
        # BaseHTTPRequestHandler normalizes headers into a mapping with case-insensitive lookups.
        """处理`traceparent`。"""
        return str(self.headers.get("traceparent") or self.headers.get("Traceparent") or "").strip()

    def _handle(self) -> None:
        """处理相关数据。"""
        raise NotImplementedError

    def do_GET(self) -> None:
        """处理 GET 请求。"""
        start_us = _now_us()
        status = 500
        try:
            status = self._handle() or 200
        finally:
            end_us = _now_us()
            _maybe_export_server_span(
                service_name=self.stub_service_name,
                http_method="GET",
                http_target=str(self.path or "/"),
                http_status=int(status),
                traceparent=self._traceparent(),
                start_us=start_us,
                end_us=end_us,
            )

    def do_POST(self) -> None:
        """处理 POST 请求。"""
        start_us = _now_us()
        status = 500
        try:
            status = self._handle() or 200
        finally:
            end_us = _now_us()
            _maybe_export_server_span(
                service_name=self.stub_service_name,
                http_method="POST",
                http_target=str(self.path or "/"),
                http_status=int(status),
                traceparent=self._traceparent(),
                start_us=start_us,
                end_us=end_us,
            )


class MediaServerStubHandler(_BaseStubHandler):
    stub_service_name = "beacon-mediaserver"
    stub_component_tag = "mediaserver"

    def _handle(self) -> int:
        """处理相关数据。"""
        u = urlsplit(self.path or "/")
        if self.command == "GET" and u.path == "/index/api/getMediaList":
            # Minimal ZLM-compatible response: code=0 means success.
            self._send_json(200, {"code": 0, "msg": "success", "data": []})
            return 200

        self._send_json(404, {"code": -1, "msg": "not found"})
        return 404


class AnalyzerStubHandler(_BaseStubHandler):
    stub_service_name = "beacon-analyzer"
    stub_component_tag = "analyzer"

    def _handle(self) -> int:
        """处理相关数据。"""
        u = urlsplit(self.path or "/")
        if self.command == "POST" and u.path == "/api/controls":
            # Minimal Analyzer-compatible response: code=1000 means success.
            self._send_json(200, {"code": 1000, "msg": "ok", "data": []})
            return 200

        if self.command == "GET" and u.path == "/status":
            self._send_json(200, {"code": 1000, "msg": "ok"})
            return 200

        self._send_json(404, {"code": -1, "msg": "not found"})
        return 404


def _serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    """处理`serve``in``thread`。"""
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def main() -> int:
    """处理`main`。"""
    p = argparse.ArgumentParser(description="Beacon tracing stub services (MediaServer + Analyzer)")
    p.add_argument("--mediaserver-port", type=int, default=int(os.environ.get("BEACON_TRACING_STUB_ZLM_PORT", "9992")))
    p.add_argument("--analyzer-port", type=int, default=int(os.environ.get("BEACON_TRACING_STUB_ANALYZER_PORT", "9993")))
    p.add_argument("--service-mediaserver", default=os.environ.get("BEACON_OTEL_SERVICE_MEDIASERVER", "beacon-mediaserver"))
    p.add_argument("--service-analyzer", default=os.environ.get("BEACON_OTEL_SERVICE_ANALYZER", "beacon-analyzer"))
    args = p.parse_args()

    MediaServerStubHandler.stub_service_name = str(args.service_mediaserver or "beacon-mediaserver").strip()
    AnalyzerStubHandler.stub_service_name = str(args.service_analyzer or "beacon-analyzer").strip()

    zlm_server = ThreadingHTTPServer(("0.0.0.0", int(args.mediaserver_port)), MediaServerStubHandler)
    analyzer_server = ThreadingHTTPServer(("0.0.0.0", int(args.analyzer_port)), AnalyzerStubHandler)

    _serve_in_thread(zlm_server)
    _serve_in_thread(analyzer_server)

    # Keep the main thread alive; servers run in daemon threads.
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            zlm_server.shutdown()
        except Exception:
            pass
        try:
            analyzer_server.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
