#!/usr/bin/env python3
"""
Beacon tracing smoke test (end-to-end).

Goal: Trigger a request on Admin that fans out to Analyzer + MediaServer, then
verify Jaeger contains a *single trace* with spans from:
  - beacon-admin
  - beacon-analyzer
  - beacon-mediaserver

Tempo verification is best-effort (optional by default).

This script intentionally uses only Python stdlib (no requests/jq dependency).
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


MIME_APPLICATION_JSON = "application/json"


def _now_us() -> int:
    """处理当前时间`us`。"""
    return int(time.time() * 1_000_000)


def _strip_trailing_slash(url: str) -> str:
    """处理`strip``trailing``slash`。"""
    return str(url or "").strip().rstrip("/")


def _join(base: str, path: str) -> str:
    """执行拼接。"""
    b = _strip_trailing_slash(base)
    parsed = urlsplit(b)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("service URL must use http or https and include a host")
    p = str(path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return b + p


def _decode_json_bytes(raw: bytes) -> Any:
    """返回`decode`JSON字节数。"""
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    body: bytes

    def json(self) -> Any:
        """返回JSON。"""
        return _decode_json_bytes(self.body)

    def text(self) -> str:
        """处理文本。"""
        try:
            return self.body.decode("utf-8", errors="replace")
        except Exception:
            return ""


def _http_get(url: str, *, headers: Dict[str, str], timeout_seconds: float) -> HttpResult:
    """处理HTTP`get`。"""
    req = Request(url, headers=headers, method="GET")
    try:
        # All callers construct URLs through _join, which rejects non-HTTP(S)
        # schemes before this request is made.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urlopen(req, timeout=float(timeout_seconds)) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            body = resp.read() or b""
            return HttpResult(url=url, status=status, body=body)
    except HTTPError as e:
        try:
            body = e.read() or b""
        except Exception:
            body = b""
        return HttpResult(url=url, status=int(getattr(e, "code", 0) or 0), body=body)
    except URLError as e:
        # Connection refused / DNS failure / timeout, etc.
        return HttpResult(url=url, status=0, body=str(e).encode("utf-8", errors="replace"))
    except Exception as e:
        # Best-effort: avoid crashing the smoke test on unexpected IO errors.
        return HttpResult(url=url, status=0, body=str(e).encode("utf-8", errors="replace"))


def _build_admin_headers(openapi_token: str) -> Dict[str, str]:
    """构建管理员请求头。"""
    headers = {
        "Accept": MIME_APPLICATION_JSON,
        "User-Agent": "beacon-tracing-smoke-test/1.0",
    }
    token = str(openapi_token or "").strip()
    if token:
        # Admin middleware supports both. Sending both improves compatibility when
        # certain proxies strip Authorization headers.
        headers["Authorization"] = "Bearer " + token
        headers["X-Beacon-Token"] = token
    return headers


def _trigger_admin_openindex(admin_base: str, *, openapi_token: str, timeout_seconds: float, verbose: bool) -> Tuple[bool, str]:
    # Keep response small; we only need it to fan out to ZLM + Analyzer.
    """处理`trigger`管理员`openindex`。"""
    url = _join(admin_base, "/control/openIndex") + "?" + urlencode({"p": 1, "ps": 1})
    res = _http_get(url, headers=_build_admin_headers(openapi_token), timeout_seconds=timeout_seconds)
    if verbose:
        sys.stderr.write(f"[debug] trigger {res.status} {res.url}\n")

    if res.status != 200:
        payload = res.json()
        msg = ""
        if isinstance(payload, dict):
            msg = str(payload.get("msg") or "")
        if not msg:
            msg = res.text().strip()
        if not msg:
            msg = "http_status=%d" % res.status
        return False, f"Admin trigger failed: {msg}"

    payload = res.json()
    if isinstance(payload, dict):
        code = payload.get("code")
        if code not in (1000, "1000"):
            msg = str(payload.get("msg") or "unexpected response")
            return False, f"Admin trigger returned code={code}: {msg}"
    return True, "ok"


def _jaeger_get_services(jaeger_base: str, *, timeout_seconds: float, verbose: bool) -> Set[str]:
    """处理`jaeger``get``services`。"""
    url = _join(jaeger_base, "/api/services")
    res = _http_get(url, headers={"Accept": MIME_APPLICATION_JSON}, timeout_seconds=timeout_seconds)
    if verbose:
        sys.stderr.write(f"[debug] jaeger services {res.status} {res.url}\n")
    if res.status != 200:
        return set()
    payload = res.json()
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return {str(x) for x in data if str(x or "").strip()}
    return set()


def _jaeger_query_traces(jaeger_base: str, *, service: str, lookback: str, limit: int, timeout_seconds: float, verbose: bool) -> List[Dict[str, Any]]:
    """处理`jaeger`查询参数`traces`。"""
    params = {
        "service": str(service or "").strip(),
        "lookback": str(lookback or "").strip() or "10m",
        "limit": int(limit),
    }
    url = _join(jaeger_base, "/api/traces") + "?" + urlencode(params)
    res = _http_get(url, headers={"Accept": MIME_APPLICATION_JSON}, timeout_seconds=timeout_seconds)
    if verbose:
        sys.stderr.write(f"[debug] jaeger traces {res.status} {res.url}\n")
    if res.status != 200:
        return []
    payload = res.json()
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        # Each trace is a dict with keys: traceID, spans, processes, warnings...
        out: List[Dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                out.append(item)
        return out
    return []


def _trace_id(trace_obj: Dict[str, Any]) -> str:
    """返回链路追踪ID。"""
    tid = trace_obj.get("traceID") or trace_obj.get("traceId") or trace_obj.get("trace_id") or ""
    return str(tid or "").strip()


def _trace_services(trace_obj: Dict[str, Any]) -> Set[str]:
    """处理链路追踪`services`。"""
    processes = trace_obj.get("processes")
    if not isinstance(processes, dict):
        return set()
    services = set()
    for _pid, p in processes.items():
        if not isinstance(p, dict):
            continue
        name = str(p.get("serviceName") or "").strip()
        if name:
            services.add(name)
    return services


def _trace_has_recent_span(trace_obj: Dict[str, Any], start_us: int) -> bool:
    """处理链路追踪`has``recent``span`。"""
    spans = trace_obj.get("spans")
    if not isinstance(spans, list):
        return False
    for s in spans:
        if not isinstance(s, dict):
            continue
        try:
            st = int(s.get("startTime") or 0)
        except Exception:
            st = 0
        if st >= int(start_us or 0):
            return True
    return False


def _tempo_try_get_trace(tempo_base: str, trace_id: str, *, timeout_seconds: float, verbose: bool) -> Tuple[bool, str]:
    """处理`tempo``try``get`链路追踪。
    
    Best-effort: Tempo's API surface differs by version/config.
        We try a small set of known endpoints and treat any 200 as success.
    """
    base = _strip_trailing_slash(tempo_base)
    tid = str(trace_id or "").strip()
    if not base or not tid:
        return False, "skipped"

    candidates = [
        _join(base, f"/api/traces/{tid}"),
        _join(base, f"/api/trace/{tid}"),
        _join(base, f"/api/v2/traces/{tid}"),
    ]
    headers = {"Accept": MIME_APPLICATION_JSON}
    for url in candidates:
        try:
            res = _http_get(url, headers=headers, timeout_seconds=timeout_seconds)
        except Exception as e:
            if verbose:
                sys.stderr.write(f"[debug] tempo error {url}: {e}\n")
            continue
        if verbose:
            sys.stderr.write(f"[debug] tempo {res.status} {res.url}\n")
        if res.status == 200 and (res.body or b""):
            return True, "ok"
        # Common: 404 when trace not ingested yet; keep trying other endpoints.
    return False, "not_found"


def _format_bool(ok: bool) -> str:
    """处理`format`布尔值。"""
    return "OK" if ok else "FAIL"


def _pick_trace_with_required_services(
    traces: Iterable[Dict[str, Any]], required_services: Set[str]
) -> Tuple[str, Set[str]]:
    """选择链路追踪`with``required``services`。"""
    for tr in traces:
        services = _trace_services(tr)
        if required_services.issubset(services):
            return _trace_id(tr), services
    return "", set()


def _poll_jaeger_for_trace(
    jaeger_base: str,
    *,
    admin_service: str,
    required_services: Set[str],
    lookback: str,
    start_us: int,
    poll_seconds: float,
    interval_seconds: float,
    timeout_seconds: float,
    verbose: bool,
) -> Tuple[str, Set[str]]:
    """获取链路追踪的轮询`jaeger`。"""
    deadline = time.time() + float(poll_seconds or 0)
    while time.time() < deadline:
        traces = _jaeger_query_traces(
            jaeger_base,
            service=admin_service,
            lookback=str(lookback),
            limit=50,
            timeout_seconds=float(timeout_seconds),
            verbose=bool(verbose),
        )

        recent = [t for t in traces if _trace_has_recent_span(t, int(start_us or 0))]
        trace_id, services = _pick_trace_with_required_services(recent, required_services)
        if trace_id:
            return trace_id, services

        time.sleep(max(0.2, float(interval_seconds or 0)))
    return "", set()


def _maybe_check_tempo(
    tempo_base: str, trace_id: str, *, timeout_seconds: float, verbose: bool
) -> Tuple[bool, str]:
    """按需处理`check``tempo`。"""
    base = _strip_trailing_slash(tempo_base)
    tid = str(trace_id or "").strip()
    if not base or not tid:
        return False, "skipped"
    return _tempo_try_get_trace(base, tid, timeout_seconds=float(timeout_seconds), verbose=bool(verbose))


def _clean_str(value: Any) -> str:
    """处理清理字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _with_default(value: Any, default: str) -> str:
    """处理`with`默认。"""
    cleaned = _clean_str(value)
    if cleaned:
        return cleaned
    return str(default).strip()


def _build_jaeger_trace_url(jaeger_base: str, trace_id: str) -> str:
    """构建`jaeger`链路追踪URL。"""
    tid = _clean_str(trace_id)
    if not tid:
        return ""
    return _join(jaeger_base, f"/trace/{tid}")


def _print_trigger_failure(admin_base: str, msg: str) -> None:
    """处理`print``trigger``failure`。"""
    sys.stdout.write("FAIL: could not trigger Admin fan-out request\n")
    sys.stdout.write(f"  admin={admin_base}\n")
    sys.stdout.write(f"  error={msg}\n")
    sys.stdout.write("Hints:\n")
    sys.stdout.write("  - Ensure Admin is running and reachable.\n")
    sys.stdout.write("  - If BEACON_OPEN_API_TOKEN / BEACON_REQUIRE_OPEN_API_TOKEN is set, pass --token.\n")


def _print_jaeger_trace_missing(required_services: Set[str], jaeger_base: str, services_seen: Iterable[str]) -> None:
    """处理`print``jaeger`链路追踪`missing`。"""
    sys.stdout.write("FAIL: Jaeger did not show a single trace containing all required services\n")
    sys.stdout.write(f"  required={','.join(sorted(required_services))}\n")
    sys.stdout.write(f"  jaeger={jaeger_base}\n")
    seen = [s for s in (services_seen or []) if str(s or "").strip()]
    if seen:
        sys.stdout.write("  jaeger_services_seen=" + ",".join(sorted(seen)) + "\n")
    else:
        sys.stdout.write("  jaeger_services_seen=(none; is Jaeger running?)\n")
    sys.stdout.write("Hints:\n")
    sys.stdout.write("  - Ensure tracing is enabled in all 3 components (BEACON_OTEL_ENABLED=1).\n")
    sys.stdout.write("  - Ensure MediaServer is running; Admin only calls Analyzer when ZLM is reachable.\n")
    sys.stdout.write("  - Ensure collector receives both OTLP (4317/4318) and Zipkin (9411) and exports to Jaeger.\n")


def _print_pass_summary(
    jaeger_base: str, trace_id: str, services: Set[str], tempo_ok: bool, tempo_msg: str
) -> None:
    """处理`print``pass``summary`。"""
    jaeger_trace_url = _build_jaeger_trace_url(jaeger_base, trace_id)

    sys.stdout.write("PASS: Jaeger trace found with all required services\n")
    sys.stdout.write(f"  trace_id={trace_id}\n")
    sys.stdout.write(f"  services={','.join(sorted(services))}\n")
    if jaeger_trace_url:
        sys.stdout.write(f"  jaeger_trace_url={jaeger_trace_url}\n")
    sys.stdout.write(f"  tempo={_format_bool(tempo_ok)} ({tempo_msg})\n")


def _tempo_requirement_failed(require_tempo: bool, tempo_ok: bool) -> bool:
    """处理`tempo``requirement``failed`。"""
    if not bool(require_tempo):
        return False
    return not bool(tempo_ok)


def main(argv: Sequence[str]) -> int:
    """处理`main`。"""
    p = argparse.ArgumentParser(description="Beacon end-to-end tracing smoke test (Admin -> Analyzer + MediaServer)")
    p.add_argument("--admin", default=os.environ.get("BEACON_ADMIN_BASE_URL", "http://127.0.0.1:9991"))
    p.add_argument("--token", default=os.environ.get("BEACON_OPEN_API_TOKEN", ""))
    p.add_argument("--jaeger", default=os.environ.get("BEACON_JAEGER_BASE_URL", "http://127.0.0.1:16686"))
    p.add_argument("--tempo", default=os.environ.get("BEACON_TEMPO_BASE_URL", "http://127.0.0.1:3200"))
    p.add_argument("--service-admin", default=os.environ.get("BEACON_OTEL_SERVICE_ADMIN", "beacon-admin"))
    p.add_argument("--service-analyzer", default=os.environ.get("BEACON_OTEL_SERVICE_ANALYZER", "beacon-analyzer"))
    p.add_argument("--service-mediaserver", default=os.environ.get("BEACON_OTEL_SERVICE_MEDIASERVER", "beacon-mediaserver"))
    p.add_argument("--require-tempo", action="store_true", help="Fail the test if Tempo does not have the trace.")
    p.add_argument("--lookback", default="10m", help="Jaeger lookback window (e.g. 2m/10m/1h).")
    p.add_argument("--poll-seconds", type=float, default=45.0, help="Max time to wait for traces to appear in Jaeger.")
    p.add_argument("--interval-seconds", type=float, default=3.0, help="Polling interval.")
    p.add_argument("--http-timeout-seconds", type=float, default=5.0, help="HTTP client timeout per request.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(list(argv))

    admin_base = _strip_trailing_slash(args.admin)
    jaeger_base = _strip_trailing_slash(args.jaeger)
    tempo_base = _strip_trailing_slash(args.tempo)
    token = _clean_str(args.token)

    admin_service = _with_default(args.service_admin, "beacon-admin")
    required_services = {
        admin_service,
        _with_default(args.service_analyzer, "beacon-analyzer"),
        _with_default(args.service_mediaserver, "beacon-mediaserver"),
    }

    t0_us = _now_us()
    ok, msg = _trigger_admin_openindex(
        admin_base,
        openapi_token=token,
        timeout_seconds=float(args.http_timeout_seconds),
        verbose=bool(args.verbose),
    )
    if not ok:
        _print_trigger_failure(admin_base, msg)
        return 2

    # Give batch processors a chance to flush. We still poll below, but this reduces flakiness.
    time.sleep(1.0)

    found_trace_id, found_services = _poll_jaeger_for_trace(
        jaeger_base,
        admin_service=admin_service,
        required_services=required_services,
        lookback=str(args.lookback),
        start_us=t0_us,
        poll_seconds=float(args.poll_seconds),
        interval_seconds=float(args.interval_seconds),
        timeout_seconds=float(args.http_timeout_seconds),
        verbose=bool(args.verbose),
    )

    if not found_trace_id:
        services = _jaeger_get_services(
            jaeger_base,
            timeout_seconds=float(args.http_timeout_seconds),
            verbose=bool(args.verbose),
        )
        _print_jaeger_trace_missing(required_services, jaeger_base, services)
        return 3

    tempo_ok, tempo_msg = _maybe_check_tempo(
        tempo_base,
        found_trace_id,
        timeout_seconds=float(args.http_timeout_seconds),
        verbose=bool(args.verbose),
    )

    _print_pass_summary(jaeger_base, found_trace_id, found_services, tempo_ok, tempo_msg)

    if _tempo_requirement_failed(bool(args.require_tempo), tempo_ok):
        sys.stdout.write("FAIL: --require-tempo was set but Tempo did not return the trace\n")
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
