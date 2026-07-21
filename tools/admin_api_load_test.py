#!/usr/bin/env python3
"""
Lightweight HTTP load test runner for local Beacon Admin endpoints.

This script avoids external dependencies so it can run in constrained
environments where tools like k6/wrk/hey are not installed.
"""

import argparse
import json
import math
import ssl
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.client import HTTPConnection, HTTPSConnection, HTTPResponse
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse


def _build_arg_parser() -> argparse.ArgumentParser:
    """构建`arg``parser`。"""
    parser = argparse.ArgumentParser(description="Run a lightweight HTTP load test")
    parser.add_argument("--url", required=True, help="Full target URL, e.g. http://127.0.0.1:18080/healthz")
    parser.add_argument("--concurrency", type=int, default=16, help="Number of concurrent workers")
    parser.add_argument("--requests", type=int, default=200, help="Total request count")
    parser.add_argument("--method", default="GET", help="HTTP method")
    parser.add_argument("--timeout-seconds", type=float, default=5.0, help="Per-request timeout")
    parser.add_argument("--warmup-requests", type=int, default=5, help="Warmup requests before timing")
    parser.add_argument("--header", action="append", default=[], help="Extra header, format: Key: Value")
    parser.add_argument("--cookie-file", default="", help="Optional Netscape cookie jar path exported by curl")
    parser.add_argument("--body", default="", help="Optional request body")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    return parser


def _parse_headers(header_args: List[str]) -> Dict[str, str]:
    """解析请求头。"""
    headers: Dict[str, str] = {}
    for raw in header_args:
        text = str(raw or "").strip()
        if not text:
            continue
        if ":" not in text:
            raise ValueError(f"invalid header format: {text!r}")
        key, value = text.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def _load_cookie_header(cookie_file: str) -> str:
    """加载`cookie`请求头。"""
    path = Path(str(cookie_file or "").strip())
    if not path:
        return ""
    if not path.is_file():
        raise ValueError(f"cookie file does not exist: {cookie_file!r}")

    cookies: List[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        name = str(parts[5] or "").strip()
        value = str(parts[6] or "").strip()
        if not name:
            continue
        cookies.append(f"{name}={value}")
    return "; ".join(cookies)


def _build_connection(parsed, timeout_seconds: float):
    """构建`connection`。"""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use http or https and include a hostname")
    port = parsed.port
    if parsed.scheme == "https":
        # Certificate and hostname verification are enabled by the default context.
        # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        return HTTPSConnection(
            parsed.hostname,
            port=port or 443,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
    return HTTPConnection(parsed.hostname, port=port or 80, timeout=timeout_seconds)


def _request_once(conn, *, method: str, path: str, headers: Dict[str, str], body: bytes) -> Tuple[int, int]:
    """处理请求一次。"""
    conn.request(method, path, body=body, headers=headers)
    resp: HTTPResponse = conn.getresponse()
    payload = resp.read()
    return int(resp.status), len(payload)


def _percentile(sorted_values: List[float], ratio: float) -> float:
    """处理`percentile`。"""
    if not sorted_values:
        return 0.0
    if ratio <= 0:
        return sorted_values[0]
    if ratio >= 1:
        return sorted_values[-1]
    index = (len(sorted_values) - 1) * ratio
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[lower]
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _worker(
    worker_id: int,
    *,
    url: str,
    method: str,
    headers: Dict[str, str],
    body: bytes,
    timeout_seconds: float,
    request_count: int,
) -> Dict[str, object]:
    """处理`worker`。"""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    latencies_ms: List[float] = []
    status_counts: Counter = Counter()
    exception_counts: Counter = Counter()
    total_bytes = 0

    conn = _build_connection(parsed, timeout_seconds)
    try:
        for _ in range(request_count):
            start = time.perf_counter()
            try:
                status, response_bytes = _request_once(
                    conn,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                latencies_ms.append(elapsed_ms)
                status_counts[str(status)] += 1
                total_bytes += int(response_bytes or 0)
            except Exception as exc:  # pragma: no cover - exercised by live failures
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                latencies_ms.append(elapsed_ms)
                exception_counts[type(exc).__name__] += 1
                try:
                    conn.close()
                except Exception:
                    pass
                conn = _build_connection(parsed, timeout_seconds)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "worker_id": worker_id,
        "latencies_ms": latencies_ms,
        "status_counts": dict(status_counts),
        "exception_counts": dict(exception_counts),
        "bytes": total_bytes,
    }


def _run_load_test(args) -> Dict[str, object]:
    """执行`load``test`。"""
    method = str(args.method or "GET").upper()
    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"unsupported URL: {args.url!r}")

    headers = _parse_headers(args.header)
    cookie_header = _load_cookie_header(args.cookie_file) if args.cookie_file else ""
    if cookie_header and "Cookie" not in headers:
        headers["Cookie"] = cookie_header
    body = str(args.body or "").encode("utf-8")
    if body and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json; charset=utf-8"

    warmup_conn = _build_connection(parsed, args.timeout_seconds)
    warmup_path = parsed.path or "/"
    if parsed.query:
        warmup_path = f"{warmup_path}?{parsed.query}"
    try:
        for _ in range(max(0, int(args.warmup_requests or 0))):
            _request_once(warmup_conn, method=method, path=warmup_path, headers=headers, body=body)
    finally:
        try:
            warmup_conn.close()
        except Exception:
            pass

    total_requests = int(args.requests or 0)
    concurrency = max(1, int(args.concurrency or 1))
    per_worker = [total_requests // concurrency] * concurrency
    for idx in range(total_requests % concurrency):
        per_worker[idx] += 1
    per_worker = [count for count in per_worker if count > 0]

    started_at = time.time()
    monotonic_start = time.perf_counter()
    worker_results = []
    with ThreadPoolExecutor(max_workers=len(per_worker), thread_name_prefix="beacon-load") as pool:
        futures = [
            pool.submit(
                _worker,
                worker_id=index,
                url=args.url,
                method=method,
                headers=headers,
                body=body,
                timeout_seconds=float(args.timeout_seconds),
                request_count=count,
            )
            for index, count in enumerate(per_worker)
        ]
        for future in as_completed(futures):
            worker_results.append(future.result())
    elapsed_seconds = time.perf_counter() - monotonic_start

    all_latencies = []
    status_counts: Counter = Counter()
    exception_counts: Counter = Counter()
    total_bytes = 0
    for result in worker_results:
        all_latencies.extend(result["latencies_ms"])
        status_counts.update(result["status_counts"])
        exception_counts.update(result["exception_counts"])
        total_bytes += int(result["bytes"])
    all_latencies.sort()

    success_count = sum(count for status, count in status_counts.items() if status.startswith("2"))
    response_count = sum(status_counts.values())
    exception_count = sum(exception_counts.values())
    non_2xx_count = response_count - success_count

    return {
        "started_at_epoch": int(started_at),
        "target": {
            "url": args.url,
            "method": method,
        },
        "load": {
            "concurrency": len(per_worker),
            "requests": total_requests,
            "warmup_requests": int(args.warmup_requests or 0),
            "timeout_seconds": float(args.timeout_seconds),
        },
        "results": {
            "elapsed_seconds": round(elapsed_seconds, 3),
            "requests_per_second": round(total_requests / elapsed_seconds, 3) if elapsed_seconds > 0 else 0.0,
            "success_count": int(success_count),
            "non_2xx_count": int(non_2xx_count),
            "exception_count": int(exception_count),
            "status_counts": dict(sorted(status_counts.items(), key=lambda item: item[0])),
            "exception_counts": dict(sorted(exception_counts.items(), key=lambda item: item[0])),
            "total_bytes": int(total_bytes),
            "latency_ms": {
                "min": round(all_latencies[0], 3) if all_latencies else 0.0,
                "avg": round(sum(all_latencies) / len(all_latencies), 3) if all_latencies else 0.0,
                "p50": round(_percentile(all_latencies, 0.50), 3),
                "p90": round(_percentile(all_latencies, 0.90), 3),
                "p95": round(_percentile(all_latencies, 0.95), 3),
                "p99": round(_percentile(all_latencies, 0.99), 3),
                "max": round(all_latencies[-1], 3) if all_latencies else 0.0,
            },
        },
    }


def main() -> int:
    """处理`main`。"""
    parser = _build_arg_parser()
    args = parser.parse_args()
    payload = _run_load_test(args)
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
