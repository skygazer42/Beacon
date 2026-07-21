#!/usr/bin/env python3
"""
Beacon cloud remote control acceptance check.

This is a repository-local helper that validates the minimum edge OpenAPI
surfaces required by the Cloud remote control plane. When cloud console
credentials are provided, it also validates the browser-usable recording
playback proxies used by the local edge console and the cloud remote console.
"""

import argparse
import base64
import io
import json
import sys
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests


ROOT = Path(__file__).resolve().parents[1]
ADMIN_ROOT = ROOT / "Admin"
if str(ADMIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADMIN_ROOT))

from app.utils.CloudEdgeClient import CloudEdgeClient, CloudEdgeClientError  # noqa: E402

EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL = "edge alarm evidence export zip"


def _is_http_url(value: str) -> bool:
    """判断 HTTP URL。"""
    parsed = urlsplit(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_base_url(value: str) -> str:
    """规范化基础 URL。"""
    return str(value or "").strip().rstrip("/")


def _normalize_rel_path(value: str) -> str:
    """规范化相对路径。"""
    return str(value or "").strip().lstrip("/")


def _console_validation_requested(args: argparse.Namespace) -> bool:
    """判断是否请求控制台代理验证。"""
    return bool(
        str(getattr(args, "cloud_admin", "") or "").strip()
        or str(getattr(args, "console_username", "") or "").strip()
        or str(getattr(args, "console_password", "") or "").strip()
    )


def _console_validation_enabled(args: argparse.Namespace) -> bool:
    """判断是否启用控制台代理验证。"""
    return bool(
        str(getattr(args, "cloud_admin", "") or "").strip()
        and str(getattr(args, "console_username", "") or "").strip()
        and str(getattr(args, "console_password", "") or "").strip()
    )


def _alarm_validation_enabled(args: argparse.Namespace) -> bool:
    """判断是否启用告警截图校验。"""
    return bool(
        str(getattr(args, "alarm_control_code", "") or "").strip()
        and _console_validation_enabled(args)
    )


def _arg_text(args: argparse.Namespace, name: str) -> str:
    """Return a stripped argparse string value."""
    return str(getattr(args, name, "") or "").strip()


def _build_url(base_url: str, path: str, *, params: dict | None = None) -> str:
    """拼接请求 URL。"""
    url = _normalize_base_url(base_url) + "/" + str(path or "").lstrip("/")
    if not params:
        return url
    return url + "?" + urlencode(params, doseq=True)


def build_parser() -> argparse.ArgumentParser:
    """构建 `parser`。"""
    parser = argparse.ArgumentParser(description="Beacon cloud remote control acceptance check")
    parser.add_argument("--edge-admin", required=True, help="Edge Admin base URL, e.g. http://127.0.0.1:9991")
    parser.add_argument("--token", required=True, help="Edge OpenAPI token")
    parser.add_argument("--stream-code", required=True, help="A stream code to validate detail and recordings")
    parser.add_argument("--recordings-page-size", type=int, default=20, help="Recording page size used during validation")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout seconds per remote request")
    parser.add_argument("--cloud-admin", default="", help="Optional Cloud Admin base URL for browser-proxy recording validation")
    parser.add_argument("--console-username", default="", help="Optional shared console username for edge/cloud session validation")
    parser.add_argument("--console-password", default="", help="Optional shared console password for edge/cloud session validation")
    parser.add_argument("--alarm-control-code", default="", help="Optional control code used to validate callback alarm screenshots on edge/cloud")
    parser.add_argument("--dry-run", action="store_true", help="Print the expected remote-control validation plan as JSON")
    return parser


def _build_steps(args: argparse.Namespace) -> list[str]:
    """构建 `steps`。"""
    steps = [
        f"Validate streams list from edge admin `{args.edge_admin}`.",
        f"Validate one stream detail for `{args.stream_code}`.",
        f"Validate recordings list, playback URL, and direct file stream for `{args.stream_code}`.",
        "Validate algorithm flows enumeration.",
        "Validate core-process information enumeration.",
    ]
    if _console_validation_enabled(args):
        steps.append(f"Validate edge console session playback URL for `{args.stream_code}`.")
        steps.append(f"Validate cloud remote recording proxy for `{args.stream_code}`.")
        steps.append(f"Validate recording snapshot capture for `{args.stream_code}` on edge console.")
    if _alarm_validation_enabled(args):
        steps.append(f"Validate callback alarm image capture for `{args.alarm_control_code}` on edge console.")
        steps.append(f"Validate edge alarm detail media for `{args.alarm_control_code}` on edge console.")
        steps.append(f"Validate edge evidence export zip for `{args.alarm_control_code}` on edge console.")
        steps.append(f"Validate cloud alarm detail media for `{args.alarm_control_code}`.")
        steps.append(f"Validate cloud alarm image proxy for `{args.alarm_control_code}`.")
    return steps


def _validate_positive_input(errors: list[str], value, label: str, *, as_int: bool = False) -> None:
    """Validate a positive numeric input."""
    number = int(value or 0) if as_int else float(value or 0)
    if number <= 0:
        errors.append(f"{label} must be greater than 0")


def _append_https_warning(warnings: list[str], url: str, label: str) -> None:
    """Warn when a non-local admin URL does not use HTTPS."""
    parsed = urlsplit(str(url or "").strip())
    host = parsed.hostname or ""
    if host not in {"127.0.0.1", "localhost"} and str(parsed.scheme or "").lower() != "https":
        warnings.append(f"non-local {label} should prefer https:// for safer remote control traffic")


def _validate_console_inputs(args: argparse.Namespace, errors: list[str], warnings: list[str]) -> None:
    """Validate optional console and cloud admin inputs."""
    if _console_validation_requested(args) and not _console_validation_enabled(args):
        errors.append("cloud-admin, console-username, and console-password must be provided together")
    if _arg_text(args, "alarm_control_code") and not _console_validation_enabled(args):
        errors.append("alarm-control-code requires cloud-admin, console-username, and console-password")

    cloud_admin = _arg_text(args, "cloud_admin")
    if not cloud_admin:
        return
    if not _is_http_url(cloud_admin):
        errors.append("cloud-admin must be a valid http/https URL")
    _append_https_warning(warnings, cloud_admin, "cloud admin")


def _validate_inputs(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    """校验 `inputs`。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not _is_http_url(args.edge_admin):
        errors.append("edge-admin must be a valid http/https URL")
    if not _arg_text(args, "token"):
        errors.append("token is required")
    if not _arg_text(args, "stream_code"):
        errors.append("stream-code is required")
    _validate_positive_input(errors, args.timeout, "timeout")
    _validate_positive_input(errors, args.recordings_page_size, "recordings-page-size", as_int=True)

    _append_https_warning(warnings, args.edge_admin, "edge admin")
    _validate_console_inputs(args, errors, warnings)
    return errors, warnings


def _check_ok(name: str, detail: str, extra: dict | None = None) -> dict:
    """返回通过的检查结果。"""
    payload = {"name": name, "ok": True, "detail": detail}
    if extra:
        payload.update(extra)
    return payload


def _check_fail(name: str, detail: str) -> dict:
    """返回失败的检查结果。"""
    return {"name": name, "ok": False, "detail": detail}


def _try_append_check(checks: list[dict], name: str, fn) -> bool:
    """尝试追加一项检查结果。"""
    try:
        payload = fn()
    except Exception as e:
        checks.append(_check_fail(name, str(e)))
        return False
    checks.append(payload)
    return bool(payload.get("ok"))


def _close_quietly(obj) -> None:
    """静默关闭资源。"""
    close = getattr(obj, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _require_json_body(response, *, label: str) -> dict:
    """校验并返回 JSON 响应体。"""
    if int(getattr(response, "status_code", 0) or 0) != 200:
        text = ""
        try:
            text = str(getattr(response, "text", "") or "").strip()
        except Exception:
            text = ""
        raise CloudEdgeClientError(f"{label} http {response.status_code}: {text}".strip())

    try:
        body = response.json()
    except Exception:
        raise CloudEdgeClientError(f"{label} did not return JSON")

    if not isinstance(body, dict):
        raise CloudEdgeClientError(f"{label} response is not a JSON object")
    if int(body.get("code") or 0) != 1000:
        raise CloudEdgeClientError(str(body.get("msg") or f"{label} failed"))
    return body


def _login_console_session(
    base_url: str,
    username: str,
    password: str,
    *,
    timeout_seconds: float,
    session_factory=requests.Session,
):
    """登录控制台会话。"""
    session = session_factory()
    login_url = _build_url(base_url, "/login")

    try:
        page = session.get(login_url, timeout=timeout_seconds)
    except Exception as e:
        _close_quietly(session)
        raise CloudEdgeClientError(f"console login page request failed: {e}")

    if int(getattr(page, "status_code", 0) or 0) != 200:
        _close_quietly(session)
        raise CloudEdgeClientError(f"console login page http {getattr(page, 'status_code', 0) or 0}")

    csrf_token = str(getattr(getattr(session, "cookies", None), "get", lambda *_args, **_kwargs: "")("csrftoken") or "").strip()
    if not csrf_token:
        _close_quietly(session)
        raise CloudEdgeClientError("console csrf token is missing")

    try:
        response = session.post(
            login_url,
            data={
                "username": str(username or "").strip(),
                "password": str(password or ""),
                "csrfmiddlewaretoken": csrf_token,
            },
            headers={
                "Referer": login_url,
                "X-CSRFToken": csrf_token,
            },
            timeout=timeout_seconds,
        )
    except Exception as e:
        _close_quietly(session)
        raise CloudEdgeClientError(f"console login request failed: {e}")

    body = _require_json_body(response, label="console login")
    if int(body.get("code") or 0) != 1000:
        _close_quietly(session)
        raise CloudEdgeClientError(str(body.get("msg") or "console login failed"))
    return session


def _session_json_post(session, base_url: str, path: str, payload: dict, *, timeout_seconds: float) -> dict:
    """发送控制台会话 JSON POST。"""
    url = _build_url(base_url, path)
    csrf_token = str(getattr(getattr(session, "cookies", None), "get", lambda *_args, **_kwargs: "")("csrftoken") or "").strip()
    response = session.post(
        url,
        json=payload or {},
        headers={
            "Referer": url,
            "X-CSRFToken": csrf_token,
        },
        timeout=timeout_seconds,
        allow_redirects=False,
    )
    if int(getattr(response, "status_code", 0) or 0) in (301, 302, 303, 307, 308):
        raise CloudEdgeClientError(f"session POST redirected for {path}")
    return _require_json_body(response, label=path)


def _session_json_get(session, base_url: str, path: str, *, params: dict | None, timeout_seconds: float) -> dict:
    """发送控制台会话 JSON GET。"""
    url = _build_url(base_url, path)
    response = session.get(
        url,
        params=params,
        timeout=timeout_seconds,
        allow_redirects=False,
    )
    if int(getattr(response, "status_code", 0) or 0) in (301, 302, 303, 307, 308):
        raise CloudEdgeClientError(f"session GET redirected for {path}")
    return _require_json_body(response, label=path)


def _stream_first_chunk(response, *, label: str) -> bytes:
    """读取流式响应的首个有效数据块。"""
    try:
        iterator = response.iter_content(chunk_size=64 * 1024)
    except Exception as e:
        raise CloudEdgeClientError(f"{label} stream iteration failed: {e}")

    for chunk in iterator:
        if chunk:
            return chunk
    raise CloudEdgeClientError(f"{label} stream returned no data")


def _session_stream_url(session, url: str, *, timeout_seconds: float):
    """通过控制台会话流式访问 URL。"""
    response = session.get(
        str(url or "").strip(),
        timeout=timeout_seconds,
        stream=True,
        allow_redirects=False,
    )
    if int(getattr(response, "status_code", 0) or 0) != 200:
        text = ""
        try:
            text = str(getattr(response, "text", "") or "").strip()
        except Exception:
            text = ""
        _close_quietly(response)
        raise CloudEdgeClientError(f"session stream http {response.status_code}: {text}".strip())
    return response


def _absolute_url(base_url: str, value: str) -> str:
    """返回绝对 URL。"""
    url = str(value or "").strip()
    if not url:
        return ""
    if _is_http_url(url):
        return url
    return _build_url(base_url, url)


def _upload_image_url(base_url: str, rel_path: str) -> str:
    """根据相对路径拼接上传图片 URL。"""
    path = _normalize_rel_path(rel_path)
    if not path:
        return ""
    return _build_url(base_url, f"/static/upload/{path}")


def _normalize_admin_match_url(value: str) -> str:
    """规范化用于匹配集群的管理地址。"""
    parsed = urlsplit(_normalize_base_url(value))
    scheme = str(parsed.scheme or "").lower()
    netloc = str(parsed.netloc or "").lower()
    path = str(parsed.path or "").rstrip("/")
    return f"{scheme}://{netloc}{path}"


def _cluster_id_for_admin_row(row, target: str) -> int:
    """Return a cluster id when an edge-cluster row matches the target admin URL."""
    current = _normalize_admin_match_url(str((row or {}).get("edge_admin_base_url") or ""))
    if not current or current != target:
        return 0
    try:
        return int((row or {}).get("id") or 0)
    except Exception:
        return 0


def _resolve_cloud_cluster_id(session, cloud_admin: str, edge_admin: str, *, timeout_seconds: float) -> int:
    """根据 edge 管理地址解析云端集群 ID。"""
    payload = _session_json_get(
        session,
        cloud_admin,
        "/api/app-shell/cloud/edge-clusters",
        params=None,
        timeout_seconds=timeout_seconds,
    )
    rows = list(((payload.get("data") or {}).get("rows") or []))
    target = _normalize_admin_match_url(edge_admin)
    for row in rows:
        cluster_id = _cluster_id_for_admin_row(row, target)
        if cluster_id > 0:
            return cluster_id
    raise CloudEdgeClientError(f"cloud cluster for edge admin `{_normalize_base_url(edge_admin)}` was not found")


def _step_streams_list(client: CloudEdgeClient) -> dict:
    """处理步骤 streams_list。"""
    streams = client.list_streams()
    return _check_ok("streams_list", f"loaded {len(streams)} streams", {"count": len(streams)})


def _step_stream_detail(client: CloudEdgeClient, stream_code: str) -> dict:
    """处理步骤 stream_detail。"""
    detail = client.get_stream(str(stream_code or "").strip())
    return _check_ok("stream_detail", f"loaded stream `{detail.get('code') or stream_code}`")


def _first_recording_rel_path(recordings) -> tuple[list, str]:
    """Return recording rows and the first row's normalized rel_path."""
    rows = list((recordings or {}).get("data") or [])
    first_row = next(iter(rows), None)
    if not first_row:
        raise CloudEdgeClientError("no recording files returned for the selected stream")

    rel_path = _normalize_rel_path((first_row or {}).get("rel_path") or "")
    if not rel_path:
        raise CloudEdgeClientError("recording rel_path is empty")
    return rows, rel_path


def _read_direct_recording_stream(client: CloudEdgeClient, rel_path: str) -> tuple[str, str]:
    """Validate direct recording stream bytes and return response metadata."""
    direct_stream = client.stream_file(rel_path)
    try:
        first_chunk = _stream_first_chunk(direct_stream, label="edge open recording file")
        if not first_chunk:
            raise CloudEdgeClientError("edge open recording file returned empty bytes")
        content_length = str((getattr(direct_stream, "headers", {}) or {}).get("Content-Length") or "").strip()
        content_type = str((getattr(direct_stream, "headers", {}) or {}).get("Content-Type") or "").strip()
        return content_length, content_type
    finally:
        _close_quietly(direct_stream)


def _step_recordings(client: CloudEdgeClient, stream_code: str, *, page_size: int) -> dict:
    """处理步骤 recordings。"""
    recordings = client.list_recording_files(
        str(stream_code or "").strip(),
        page_size=int(page_size or 20),
    )
    rows, rel_path = _first_recording_rel_path(recordings)

    play = client.get_recording_play_url(rel_path)
    play_url = str((play or {}).get("play_url") or "").strip()
    if not play_url:
        raise CloudEdgeClientError("recording play URL is empty")

    content_length, content_type = _read_direct_recording_stream(client, rel_path)

    return _check_ok(
        "recordings",
        f"validated {len(rows)} recordings, one playback URL, and one direct file stream",
        {
            "rel_path": rel_path,
            "play_url": play_url,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _step_algorithm_flows(client: CloudEdgeClient) -> dict:
    """处理步骤 algorithm_flows。"""
    algorithms = client.list_algorithm_flows()
    return _check_ok("algorithm_flows", f"loaded {len(algorithms)} algorithm flows")


def _step_core_processes(client: CloudEdgeClient) -> dict:
    """处理步骤 core_processes。"""
    core = client.list_core_processes() or {}
    info = core.get("info") or {}
    data = core.get("data") or []
    return _check_ok(
        "core_processes",
        f"loaded {len(data)} core-process rows",
        {"processNum": int(info.get("processNum") or 0)},
    )


def _verify_proxy_stream_response(
    response,
    *,
    label: str,
    expected_content_length: str = "",
) -> tuple[str, str]:
    """验证代理流响应。"""
    try:
        first_chunk = _stream_first_chunk(response, label=label)
        if not first_chunk:
            raise CloudEdgeClientError(f"{label} returned empty bytes")
        content_length = str((getattr(response, "headers", {}) or {}).get("Content-Length") or "").strip()
        content_type = str((getattr(response, "headers", {}) or {}).get("Content-Type") or "").strip()
        if expected_content_length and content_length and expected_content_length != content_length:
            raise CloudEdgeClientError(
                f"{label} content length mismatch: expected {expected_content_length}, got {content_length}"
            )
        return content_length, content_type
    finally:
        _close_quietly(response)


def _read_binary_response(
    response,
    *,
    label: str,
    max_bytes: int = 1024 * 1024,
) -> tuple[bytes, str, str]:
    """读取并返回较小的二进制响应。"""
    try:
        chunks: list[bytes] = []
        total = 0
        iterator = response.iter_content(chunk_size=64 * 1024)
        for chunk in iterator:
            if not chunk:
                continue
            total += len(chunk)
            if total > int(max_bytes or 0):
                raise CloudEdgeClientError(f"{label} exceeded {max_bytes} bytes")
            chunks.append(chunk)
        if not chunks:
            raise CloudEdgeClientError(f"{label} returned no data")
        content = b"".join(chunks)
        content_length = str((getattr(response, "headers", {}) or {}).get("Content-Length") or "").strip()
        content_type = str((getattr(response, "headers", {}) or {}).get("Content-Type") or "").strip()
        return content, content_length, content_type
    finally:
        _close_quietly(response)


def _alarm_row_matches(row, *, desc: str, control_code: str) -> bool:
    """Return whether an alarm row matches the expected control and description."""
    if str((row or {}).get("control_code") or "").strip() != str(control_code or "").strip():
        return False
    return str((row or {}).get("desc") or "").strip() == str(desc or "").strip()


def _poll_alarm_row(
    session,
    base_url: str,
    path: str,
    *,
    desc: str,
    control_code: str,
    timeout_seconds: float,
):
    """轮询告警列表并返回匹配行。"""
    deadline = time.time() + max(float(timeout_seconds or 0), 5.0)
    while time.time() <= deadline:
        payload = _session_json_get(
            session,
            base_url,
            path,
            params={"ps": 20},
            timeout_seconds=timeout_seconds,
        )
        rows = list(((payload.get("data") or {}).get("rows") or []))
        for row in rows:
            if _alarm_row_matches(row, desc=desc, control_code=control_code):
                return row
        time.sleep(0.5)
    raise CloudEdgeClientError(f"alarm `{desc}` for control `{control_code}` was not found in {path}")


def _step_edge_callback_alarm_image(
    session,
    edge_admin: str,
    control_code: str,
    *,
    timeout_seconds: float,
) -> dict:
    """处理步骤 edge_callback_alarm_image。"""
    suffix = uuid.uuid4().hex[:12]
    desc = f"e2e_alarm_{suffix}"
    image_bytes = f"beacon-e2e-image-{suffix}".encode("utf-8")
    payload = {
        "control_code": str(control_code or "").strip(),
        "frame_index": 1,
        "timestamp": int(time.time()),
        "trigger_alarm": True,
        "detections": [{"class_name": desc, "confidence": 0.99, "bbox": [1, 2, 3, 4]}],
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
    }
    _session_json_post(
        session,
        edge_admin,
        "/api/app-shell/developer/action/algorithmCallback",
        payload,
        timeout_seconds=timeout_seconds,
    )

    row = _poll_alarm_row(
        session,
        edge_admin,
        "/api/app-shell/alarms",
        desc=desc,
        control_code=control_code,
        timeout_seconds=timeout_seconds,
    )
    image_url = _absolute_url(edge_admin, str((row or {}).get("image_url") or "").strip())
    if not image_url:
        raise CloudEdgeClientError("edge callback alarm did not return image_url")

    response = _session_stream_url(session, image_url, timeout_seconds=timeout_seconds)
    content, content_length, content_type = _read_binary_response(
        response,
        label="edge callback alarm image",
    )
    if content != image_bytes:
        raise CloudEdgeClientError("edge callback alarm image bytes mismatch")

    return _check_ok(
        "edge_callback_alarm_image",
        f"validated callback alarm image capture for `{control_code}`",
        {
            "alarm_id": int((row or {}).get("id") or 0),
            "desc": desc,
            "image_url": image_url,
            "content_length": content_length,
            "content_type": content_type,
            "expected_bytes": image_bytes.decode("utf-8"),
        },
    )


def _step_edge_recording_snapshot(
    session,
    edge_admin: str,
    stream_code: str,
    *,
    timeout_seconds: float,
) -> dict:
    """处理步骤 edge_recording_snapshot。"""
    snapshot_timeout_seconds = max(float(timeout_seconds or 0), 20.0)
    payload = _session_json_post(
        session,
        edge_admin,
        "/api/app-shell/recording/action/captureSnapshot",
        {
            "stream_code": str(stream_code or "").strip(),
            "method": "ffmpeg",
        },
        timeout_seconds=snapshot_timeout_seconds,
    )
    data = payload.get("data") or {}
    image_path = _normalize_rel_path(data.get("image_path") or "")
    if not image_path:
        raise CloudEdgeClientError("recording snapshot did not return image_path")

    image_url = _absolute_url(
        edge_admin,
        str(data.get("image_url") or "").strip() or _upload_image_url(edge_admin, image_path),
    )
    if not image_url:
        raise CloudEdgeClientError("recording snapshot did not return image_url")

    response = _session_stream_url(session, image_url, timeout_seconds=snapshot_timeout_seconds)
    content, content_length, content_type = _read_binary_response(
        response,
        label="edge recording snapshot",
    )
    if not content:
        raise CloudEdgeClientError("edge recording snapshot returned empty bytes")
    if str(content_type or "").lower().startswith("text/html"):
        raise CloudEdgeClientError("edge recording snapshot returned html instead of image bytes")

    return _check_ok(
        "edge_recording_snapshot",
        f"validated recording snapshot capture for `{stream_code}`",
        {
            "image_path": image_path,
            "image_url": image_url,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _read_json_from_zip(zf: zipfile.ZipFile, member: str, *, label: str) -> dict:
    """读取 ZIP 内 JSON 文件。"""
    try:
        raw = zf.read(member)
    except KeyError:
        raise CloudEdgeClientError(f"{label} missing `{member}`")
    except Exception as e:
        raise CloudEdgeClientError(f"{label} read `{member}` failed: {e}")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise CloudEdgeClientError(f"{label} parse `{member}` failed: {e}")

    if not isinstance(payload, dict):
        raise CloudEdgeClientError(f"{label} `{member}` is not a JSON object")
    return payload


def _mapping(value) -> dict:
    """Return a dictionary value or an empty dictionary."""
    return value if isinstance(value, dict) else {}


def _payload_text(payload: dict, key: str) -> str:
    """Return a stripped text value from a payload."""
    return str(payload.get(key) or "").strip()


def _payload_int(payload: dict, key: str) -> int:
    """Return an integer value from a payload."""
    return int(payload.get(key) or 0)


def _expected_alarm_id(alarm_id: int) -> int:
    """Return an integer alarm id for comparisons."""
    return int(alarm_id or 0)


def _require_detail_found(data: dict, *, alarm_id: int, label: str) -> None:
    """Validate that an alarm detail payload found the requested alarm."""
    if bool(data.get("found")):
        return
    raise CloudEdgeClientError(f"{label} did not find alarm `{alarm_id}`")


def _validate_alarm_identity(alarm: dict, *, alarm_id: int, control_code: str, desc: str, label: str) -> None:
    """Validate common alarm identity fields."""
    if _payload_int(alarm, "id") != _expected_alarm_id(alarm_id):
        raise CloudEdgeClientError(f"{label} returned unexpected alarm id: {alarm.get('id')}")
    if _payload_text(alarm, "control_code") != str(control_code or "").strip():
        raise CloudEdgeClientError(f"{label} returned unexpected control_code")
    if _payload_text(alarm, "desc") != str(desc or "").strip():
        raise CloudEdgeClientError(f"{label} returned unexpected desc")


def _validate_edge_alarm_detail_data(data, *, alarm_id: int, control_code: str, desc: str) -> tuple[dict, str, str]:
    """Validate edge alarm detail payload and return media/evidence URLs."""
    data = _mapping(data)
    _require_detail_found(data, alarm_id=alarm_id, label="edge alarm detail")
    alarm = _mapping(data.get("alarm"))
    _validate_alarm_identity(alarm, alarm_id=alarm_id, control_code=control_code, desc=desc, label="edge alarm detail")
    media = _mapping(data.get("media"))
    downloads = _mapping(data.get("downloads"))
    return alarm, _payload_text(media, "image_url"), _payload_text(downloads, "evidence_url")


def _download_expected_alarm_image(session, image_url: str, expected_bytes: bytes, *, label: str, timeout_seconds: float):
    """Download an alarm image and verify its bytes when expected bytes are supplied."""
    response = _session_stream_url(session, image_url, timeout_seconds=timeout_seconds)
    content, content_length, content_type = _read_binary_response(response, label=label)
    if expected_bytes and content != expected_bytes:
        raise CloudEdgeClientError(f"{label} bytes mismatch")
    return content_length, content_type


def _step_edge_alarm_detail(
    session,
    edge_admin: str,
    *,
    alarm_id: int,
    control_code: str,
    desc: str,
    expected_bytes: bytes,
    timeout_seconds: float,
) -> dict:
    """处理步骤 edge_alarm_detail。"""
    detail = _session_json_get(
        session,
        edge_admin,
        "/api/app-shell/alarm/detail",
        params={"id": int(alarm_id or 0)},
        timeout_seconds=timeout_seconds,
    )
    data = detail.get("data") or {}
    _, image_url_value, evidence_url_value = _validate_edge_alarm_detail_data(
        data,
        alarm_id=alarm_id,
        control_code=control_code,
        desc=desc,
    )
    image_url = _absolute_url(edge_admin, image_url_value)
    if not image_url:
        raise CloudEdgeClientError("edge alarm detail did not return media.image_url")

    evidence_url = _absolute_url(edge_admin, evidence_url_value)
    if not evidence_url:
        raise CloudEdgeClientError("edge alarm detail did not return downloads.evidence_url")

    content_length, content_type = _download_expected_alarm_image(
        session,
        image_url,
        expected_bytes,
        label="edge alarm detail image",
        timeout_seconds=timeout_seconds,
    )

    return _check_ok(
        "edge_alarm_detail",
        f"validated edge alarm detail media for `{control_code}`",
        {
            "alarm_id": int(alarm_id or 0),
            "image_url": image_url,
            "evidence_url": evidence_url,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _snapshot_entry_from_manifest(manifest: dict) -> dict:
    """Return the snapshot entry from an evidence export manifest."""
    files = list((manifest or {}).get("files") or [])
    snapshot_entry = next(
        (
            item
            for item in files
            if isinstance(item, dict) and str(item.get("kind") or "").strip() == "snapshot"
        ),
        None,
    )
    if not snapshot_entry:
        raise CloudEdgeClientError("edge alarm evidence export manifest missing snapshot entry")
    return snapshot_entry


def _validate_evidence_zip(content: bytes, *, alarm_id: int, expected_bytes: bytes) -> tuple[list[str], str]:
    """Validate edge evidence ZIP content and return its entries and snapshot path."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except Exception as e:
        raise CloudEdgeClientError(f"{EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL} is invalid: {e}")

    with zf:
        names = zf.namelist()
        base_dir = f"alarm_{int(alarm_id or 0)}"
        metadata_path = f"{base_dir}/metadata.json"
        manifest_path = f"{base_dir}/manifest.json"
        for member in (metadata_path, manifest_path):
            if member not in names:
                raise CloudEdgeClientError(f"{EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL} missing `{member}`")

        metadata = _read_json_from_zip(zf, metadata_path, label=EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL)
        manifest = _read_json_from_zip(zf, manifest_path, label=EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL)
        if int(metadata.get("alarm_id") or 0) != int(alarm_id or 0):
            raise CloudEdgeClientError("edge alarm evidence export metadata alarm_id mismatch")

        snapshot_entry = _snapshot_entry_from_manifest(manifest)
        snapshot_path = str((snapshot_entry or {}).get("path") or "").strip()
        if not snapshot_path:
            raise CloudEdgeClientError("edge alarm evidence export snapshot path is empty")
        if snapshot_path not in names:
            raise CloudEdgeClientError(f"{EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL} missing `{snapshot_path}`")

        snapshot_bytes = zf.read(snapshot_path)
        if expected_bytes and snapshot_bytes != expected_bytes:
            raise CloudEdgeClientError("edge alarm evidence export snapshot bytes mismatch")
        return names, snapshot_path


def _step_edge_alarm_evidence_export(
    session,
    edge_admin: str,
    *,
    alarm_id: int,
    control_code: str,
    evidence_url: str,
    expected_bytes: bytes,
    timeout_seconds: float,
) -> dict:
    """处理步骤 edge_alarm_evidence_export。"""
    zip_url = _absolute_url(edge_admin, evidence_url)
    if not zip_url:
        raise CloudEdgeClientError("edge alarm evidence export URL is empty")

    response = _session_stream_url(session, zip_url, timeout_seconds=timeout_seconds)
    content, content_length, content_type = _read_binary_response(
        response,
        label=EDGE_ALARM_EVIDENCE_EXPORT_ZIP_LABEL,
        max_bytes=10 * 1024 * 1024,
    )
    names, snapshot_path = _validate_evidence_zip(
        content,
        alarm_id=alarm_id,
        expected_bytes=expected_bytes,
    )

    return _check_ok(
        "edge_alarm_evidence_export",
        f"validated edge evidence export zip for `{control_code}`",
        {
            "alarm_id": int(alarm_id or 0),
            "evidence_url": zip_url,
            "zip_entries": len(names),
            "snapshot_path": snapshot_path,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _validate_cloud_alarm_detail_data(
    detail_data: dict,
    *,
    cloud_admin: str,
    alarm_id: int,
    control_code: str,
    desc: str,
    expected_bytes: bytes,
) -> tuple[str, str]:
    """Validate cloud alarm detail JSON data and return preview mode and image URL."""
    detail_data = _mapping(detail_data)
    _require_detail_found(detail_data, alarm_id=alarm_id, label="cloud alarm detail")
    if _payload_int(detail_data, "alarm_id") != _expected_alarm_id(alarm_id):
        raise CloudEdgeClientError("cloud alarm detail alarm_id mismatch")

    alarm = _mapping(detail_data.get("alarm"))
    _validate_alarm_identity(alarm, alarm_id=alarm_id, control_code=control_code, desc=desc, label="cloud alarm detail")

    preview_mode = _payload_text(detail_data, "image_preview_mode")
    if expected_bytes and preview_mode not in {"proxy", "presigned_get"}:
        raise CloudEdgeClientError(f"cloud alarm detail returned unexpected image_preview_mode: {preview_mode}")
    if expected_bytes and not bool(detail_data.get("has_image")):
        raise CloudEdgeClientError("cloud alarm detail returned has_image=false")

    detail_image_url = _absolute_url(cloud_admin, _payload_text(detail_data, "image_url"))
    if expected_bytes and not detail_image_url:
        raise CloudEdgeClientError("cloud alarm detail did not return image_url")
    if preview_mode == "proxy" and detail_image_url and "/cloud/alarm/image" not in detail_image_url:
        raise CloudEdgeClientError(f"cloud alarm detail returned unexpected proxy image_url: {detail_image_url}")
    return preview_mode, detail_image_url


def _read_cloud_alarm_detail_image(session, detail_image_url: str, expected_bytes: bytes, *, timeout_seconds: float):
    """Read cloud alarm detail image bytes when a detail image URL is present."""
    if not detail_image_url:
        return "", ""
    detail_response = _session_stream_url(session, detail_image_url, timeout_seconds=timeout_seconds)
    detail_content, content_length, content_type = _read_binary_response(
        detail_response,
        label="cloud alarm detail image",
    )
    if detail_content != expected_bytes:
        raise CloudEdgeClientError("cloud alarm detail image bytes mismatch")
    return content_length, content_type


def _step_cloud_alarm_detail(
    session,
    cloud_admin: str,
    control_code: str,
    *,
    desc: str,
    expected_bytes: bytes,
    timeout_seconds: float,
) -> dict:
    """处理步骤 cloud_alarm_detail。"""
    row = _poll_alarm_row(
        session,
        cloud_admin,
        "/api/app-shell/cloud/alarms",
        desc=desc,
        control_code=control_code,
        timeout_seconds=timeout_seconds,
    )
    alarm_id = int((row or {}).get("id") or 0)
    if alarm_id <= 0:
        raise CloudEdgeClientError("cloud alarm row id is invalid")

    detail = _session_json_get(
        session,
        cloud_admin,
        "/api/app-shell/cloud/alarm/detail",
        params={"id": alarm_id},
        timeout_seconds=timeout_seconds,
    )
    preview_mode, detail_image_url = _validate_cloud_alarm_detail_data(
        detail.get("data") or {},
        cloud_admin=cloud_admin,
        alarm_id=alarm_id,
        control_code=control_code,
        desc=desc,
        expected_bytes=expected_bytes,
    )
    content_length, content_type = _read_cloud_alarm_detail_image(
        session,
        detail_image_url,
        expected_bytes,
        timeout_seconds=timeout_seconds,
    )

    return _check_ok(
        "cloud_alarm_detail",
        f"validated cloud alarm detail media for `{control_code}`",
        {
            "alarm_id": alarm_id,
            "desc": desc,
            "detail_image_url": detail_image_url,
            "image_preview_mode": preview_mode,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _step_cloud_alarm_image_proxy(
    session,
    cloud_admin: str,
    *,
    alarm_id: int,
    control_code: str,
    desc: str,
    expected_bytes: bytes,
    timeout_seconds: float,
) -> dict:
    """处理步骤 cloud_alarm_image_proxy。"""
    proxy_url = _build_url(cloud_admin, "/api/app-shell/cloud/action/alarm-image", params={"id": alarm_id})
    proxy_response = _session_stream_url(session, proxy_url, timeout_seconds=timeout_seconds)
    proxy_content, content_length, content_type = _read_binary_response(
        proxy_response,
        label="cloud alarm image proxy",
    )
    if proxy_content != expected_bytes:
        raise CloudEdgeClientError("cloud alarm image proxy bytes mismatch")

    return _check_ok(
        "cloud_alarm_image_proxy",
        f"validated cloud alarm image proxy for `{control_code}`",
        {
            "alarm_id": alarm_id,
            "desc": desc,
            "proxy_url": proxy_url,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _step_edge_console_recording_proxy(
    session,
    edge_admin: str,
    rel_path: str,
    *,
    expected_content_length: str,
    timeout_seconds: float,
) -> dict:
    """处理步骤 edge_console_recording_proxy。"""
    payload = _session_json_post(
        session,
        edge_admin,
        "/api/app-shell/recording/action/file/playUrl",
        {"relPath": rel_path},
        timeout_seconds=timeout_seconds,
    )
    play_url = str((payload.get("data") or {}).get("play_url") or "").strip()
    if not play_url:
        raise CloudEdgeClientError("edge console recording play URL is empty")
    if "/recording/file/" not in play_url:
        raise CloudEdgeClientError(f"edge console returned unexpected playback URL: {play_url}")

    response = _session_stream_url(session, play_url, timeout_seconds=timeout_seconds)
    content_length, content_type = _verify_proxy_stream_response(
        response,
        label="edge console recording proxy",
        expected_content_length=expected_content_length,
    )
    return _check_ok(
        "edge_console_recording_proxy",
        f"validated edge console session playback URL for `{Path(rel_path).name}`",
        {
            "play_url": play_url,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _step_cloud_remote_recording_proxy(
    session,
    cloud_admin: str,
    edge_admin: str,
    stream_code: str,
    rel_path: str,
    *,
    expected_content_length: str,
    timeout_seconds: float,
) -> dict:
    """处理步骤 cloud_remote_recording_proxy。"""
    cluster_id = _resolve_cloud_cluster_id(
        session,
        cloud_admin,
        edge_admin,
        timeout_seconds=timeout_seconds,
    )
    payload = _session_json_get(
        session,
        cloud_admin,
        "/api/app-shell/cloud/remote/recordings",
        params={
            "cluster_id": int(cluster_id or 0),
            "stream_code": str(stream_code or "").strip(),
        },
        timeout_seconds=timeout_seconds,
    )
    rows = list(((payload.get("data") or {}).get("rows") or []))
    matched = next(
        (
            row
            for row in rows
            if _normalize_rel_path((row or {}).get("rel_path") or "") == _normalize_rel_path(rel_path)
        ),
        None,
    )
    if not matched:
        raise CloudEdgeClientError(f"cloud remote recordings did not return `{rel_path}`")

    play_url = str((matched or {}).get("play_url") or "").strip()
    if not play_url:
        raise CloudEdgeClientError("cloud remote recording proxy URL is empty")
    expected_path = f"/cloud/remote/recordings/file/{int(cluster_id or 0)}/"
    if expected_path not in play_url:
        raise CloudEdgeClientError(f"cloud remote recording proxy URL is unexpected: {play_url}")

    response = _session_stream_url(session, play_url, timeout_seconds=timeout_seconds)
    content_length, content_type = _verify_proxy_stream_response(
        response,
        label="cloud remote recording proxy",
        expected_content_length=expected_content_length,
    )
    return _check_ok(
        "cloud_remote_recording_proxy",
        f"validated cloud remote recording proxy for `{Path(rel_path).name}` on cluster `{cluster_id}`",
        {
            "cluster_id": int(cluster_id or 0),
            "play_url": play_url,
            "content_length": content_length,
            "content_type": content_type,
        },
    )


def _append_checked(checks: list[dict], all_ok: bool, name: str, fn) -> bool:
    """Append a check while preserving previous failure state."""
    return _try_append_check(checks, name, fn) and all_ok


def _run_base_checks(client: CloudEdgeClient, args: argparse.Namespace, checks: list[dict]) -> tuple[bool, dict]:
    """Run checks that only require the edge OpenAPI client."""
    recording_meta: dict = {}
    all_ok = _append_checked(checks, True, "streams_list", lambda: _step_streams_list(client))
    all_ok = _append_checked(
        checks,
        all_ok,
        "stream_detail",
        lambda: _step_stream_detail(client, _arg_text(args, "stream_code")),
    )

    def _run_recordings():
        result = _step_recordings(
            client,
            _arg_text(args, "stream_code"),
            page_size=int(args.recordings_page_size or 20),
        )
        recording_meta.update(
            {
                "rel_path": _normalize_rel_path(result.get("rel_path") or ""),
                "content_length": str(result.get("content_length") or "").strip(),
            }
        )
        return result

    all_ok = _append_checked(checks, all_ok, "recordings", _run_recordings)
    all_ok = _append_checked(checks, all_ok, "algorithm_flows", lambda: _step_algorithm_flows(client))
    all_ok = _append_checked(checks, all_ok, "core_processes", lambda: _step_core_processes(client))
    return all_ok, recording_meta


def _append_missing_recording_proxy_checks(checks: list[dict]) -> None:
    """Append failures for console recording checks when recording metadata is missing."""
    checks.append(_check_fail("edge_console_recording_proxy", "recordings step did not return rel_path"))
    checks.append(_check_fail("cloud_remote_recording_proxy", "recordings step did not return rel_path"))


def _run_edge_console_checks(args: argparse.Namespace, checks: list[dict], edge_session, rel_path: str, content_length: str) -> bool:
    """Run edge console recording checks."""
    edge_admin = _normalize_base_url(args.edge_admin)
    all_ok = _append_checked(
        checks,
        True,
        "edge_console_recording_proxy",
        lambda: _step_edge_console_recording_proxy(
            edge_session,
            edge_admin,
            rel_path,
            expected_content_length=content_length,
            timeout_seconds=float(args.timeout or 5.0),
        ),
    )
    return _append_checked(
        checks,
        all_ok,
        "edge_recording_snapshot",
        lambda: _step_edge_recording_snapshot(
            edge_session,
            edge_admin,
            _arg_text(args, "stream_code"),
            timeout_seconds=float(args.timeout or 5.0),
        ),
    )


def _run_cloud_recording_check(args: argparse.Namespace, checks: list[dict], cloud_session, rel_path: str, content_length: str) -> bool:
    """Run the cloud remote recording proxy check."""
    return _append_checked(
        checks,
        True,
        "cloud_remote_recording_proxy",
        lambda: _step_cloud_remote_recording_proxy(
            cloud_session,
            _normalize_base_url(args.cloud_admin),
            _normalize_base_url(args.edge_admin),
            _arg_text(args, "stream_code"),
            rel_path,
            expected_content_length=content_length,
            timeout_seconds=float(args.timeout or 5.0),
        ),
    )


def _append_missing_edge_alarm_checks(checks: list[dict], detail: str) -> None:
    """Append edge alarm checks that cannot run because required metadata is missing."""
    checks.append(_check_fail("edge_alarm_detail", detail))
    checks.append(_check_fail("edge_alarm_evidence_export", detail))


def _edge_alarm_timeout(args: argparse.Namespace) -> float:
    """Return the alarm check timeout."""
    return float(args.timeout or 5.0)


def _edge_alarm_id(alarm_meta: dict) -> int:
    """Return the alarm id stored in alarm metadata."""
    return int(alarm_meta.get("alarm_id") or 0)


def _edge_alarm_expected_bytes(alarm_meta: dict) -> bytes:
    """Return the expected snapshot bytes stored in alarm metadata."""
    return alarm_meta.get("expected_bytes") or b""


def _edge_alarm_evidence_url(alarm_meta: dict) -> str:
    """Return the evidence URL stored in alarm metadata."""
    return str(alarm_meta.get("evidence_url") or "").strip()


def _edge_alarm_desc(alarm_meta: dict) -> str:
    """Return the alarm description stored in alarm metadata."""
    return str(alarm_meta.get("desc") or "").strip()


def _edge_alarm_meta_from_result(result: dict) -> dict:
    """Build alarm metadata from the callback step result."""
    result = _mapping(result)
    return {
        "alarm_id": _payload_int(result, "alarm_id"),
        "desc": _payload_text(result, "desc"),
        "expected_bytes": _payload_text(result, "expected_bytes").encode("utf-8"),
    }


def _run_edge_alarm_callback_step(args: argparse.Namespace, edge_session, edge_admin: str, alarm_meta: dict) -> dict:
    """Run the edge alarm callback step and store returned metadata."""
    result = _step_edge_callback_alarm_image(
        edge_session,
        edge_admin,
        _arg_text(args, "alarm_control_code"),
        timeout_seconds=_edge_alarm_timeout(args),
    )
    alarm_meta.update(_edge_alarm_meta_from_result(result))
    return result


def _run_edge_alarm_detail_step(args: argparse.Namespace, edge_session, edge_admin: str, alarm_meta: dict) -> dict:
    """Run the edge alarm detail step and store the evidence URL."""
    result = _step_edge_alarm_detail(
        edge_session,
        edge_admin,
        alarm_id=_edge_alarm_id(alarm_meta),
        control_code=_arg_text(args, "alarm_control_code"),
        desc=_edge_alarm_desc(alarm_meta),
        expected_bytes=_edge_alarm_expected_bytes(alarm_meta),
        timeout_seconds=_edge_alarm_timeout(args),
    )
    alarm_meta["evidence_url"] = _payload_text(_mapping(result), "evidence_url")
    return result


def _run_edge_alarm_evidence_step(args: argparse.Namespace, edge_session, edge_admin: str, alarm_meta: dict) -> dict:
    """Run the edge alarm evidence export step."""
    return _step_edge_alarm_evidence_export(
        edge_session,
        edge_admin,
        alarm_id=_edge_alarm_id(alarm_meta),
        control_code=_arg_text(args, "alarm_control_code"),
        evidence_url=_edge_alarm_evidence_url(alarm_meta),
        expected_bytes=_edge_alarm_expected_bytes(alarm_meta),
        timeout_seconds=_edge_alarm_timeout(args),
    )


def _run_edge_alarm_checks(args: argparse.Namespace, checks: list[dict], edge_session) -> tuple[bool, dict]:
    """Run edge alarm callback, detail, and evidence export checks."""
    alarm_meta: dict = {}
    edge_admin = _normalize_base_url(args.edge_admin)

    all_ok = _append_checked(
        checks,
        True,
        "edge_callback_alarm_image",
        lambda: _run_edge_alarm_callback_step(args, edge_session, edge_admin, alarm_meta),
    )
    if _edge_alarm_id(alarm_meta) <= 0:
        _append_missing_edge_alarm_checks(checks, "edge callback alarm step did not return alarm_id")
        return False, alarm_meta

    all_ok = _append_checked(
        checks,
        all_ok,
        "edge_alarm_detail",
        lambda: _run_edge_alarm_detail_step(args, edge_session, edge_admin, alarm_meta),
    )
    if not _edge_alarm_evidence_url(alarm_meta):
        checks.append(_check_fail("edge_alarm_evidence_export", "edge alarm detail step did not return evidence_url"))
        return False, alarm_meta

    all_ok = _append_checked(
        checks,
        all_ok,
        "edge_alarm_evidence_export",
        lambda: _run_edge_alarm_evidence_step(args, edge_session, edge_admin, alarm_meta),
    )
    return all_ok, alarm_meta


def _last_check_named(checks: list[dict], name: str) -> dict:
    """Return the most recent check payload with the requested name."""
    return next((item for item in reversed(checks) if str(item.get("name") or "") == name), {})


def _run_cloud_alarm_checks(args: argparse.Namespace, checks: list[dict], cloud_session, alarm_meta: dict) -> bool:
    """Run cloud alarm detail and image proxy checks."""
    desc = str(alarm_meta.get("desc") or "").strip()
    if not desc:
        checks.append(_check_fail("cloud_alarm_detail", "edge callback alarm step did not return desc"))
        checks.append(_check_fail("cloud_alarm_image_proxy", "edge callback alarm step did not return desc"))
        return False

    cloud_admin = _normalize_base_url(args.cloud_admin)
    all_ok = _append_checked(
        checks,
        True,
        "cloud_alarm_detail",
        lambda: _step_cloud_alarm_detail(
            cloud_session,
            cloud_admin,
            _arg_text(args, "alarm_control_code"),
            desc=desc,
            expected_bytes=alarm_meta.get("expected_bytes") or b"",
            timeout_seconds=float(args.timeout or 5.0),
        ),
    )
    cloud_alarm_id = int((_last_check_named(checks, "cloud_alarm_detail") or {}).get("alarm_id") or 0)
    if cloud_alarm_id <= 0:
        checks.append(_check_fail("cloud_alarm_image_proxy", "cloud alarm detail step did not return alarm_id"))
        return False

    return _append_checked(
        checks,
        all_ok,
        "cloud_alarm_image_proxy",
        lambda: _step_cloud_alarm_image_proxy(
            cloud_session,
            cloud_admin,
            alarm_id=cloud_alarm_id,
            control_code=_arg_text(args, "alarm_control_code"),
            desc=desc,
            expected_bytes=alarm_meta.get("expected_bytes") or b"",
            timeout_seconds=float(args.timeout or 5.0),
        ),
    )


def _run_alarm_checks(args: argparse.Namespace, checks: list[dict], edge_session, cloud_session) -> bool:
    """Run all alarm validation checks."""
    edge_ok, alarm_meta = _run_edge_alarm_checks(args, checks, edge_session)
    cloud_ok = _run_cloud_alarm_checks(args, checks, cloud_session, alarm_meta)
    return edge_ok and cloud_ok


def _run_console_checks(
    args: argparse.Namespace,
    checks: list[dict],
    recording_meta: dict,
    session_factory,
) -> bool:
    """Run optional console and cloud remote checks."""
    if not _console_validation_enabled(args):
        return True

    rel_path = _normalize_rel_path(recording_meta.get("rel_path") or "")
    if not rel_path:
        _append_missing_recording_proxy_checks(checks)
        return False

    edge_session = None
    cloud_session = None
    try:
        edge_session = _login_console_session(
            _normalize_base_url(args.edge_admin),
            _arg_text(args, "console_username"),
            str(args.console_password or ""),
            timeout_seconds=float(args.timeout or 5.0),
            session_factory=session_factory,
        )
        all_ok = _run_edge_console_checks(
            args,
            checks,
            edge_session,
            rel_path,
            str(recording_meta.get("content_length") or "").strip(),
        )
        cloud_session = _login_console_session(
            _normalize_base_url(args.cloud_admin),
            _arg_text(args, "console_username"),
            str(args.console_password or ""),
            timeout_seconds=float(args.timeout or 5.0),
            session_factory=session_factory,
        )
        all_ok = _run_cloud_recording_check(
            args,
            checks,
            cloud_session,
            rel_path,
            str(recording_meta.get("content_length") or "").strip(),
        ) and all_ok
        if _alarm_validation_enabled(args):
            all_ok = _run_alarm_checks(args, checks, edge_session, cloud_session) and all_ok
        return all_ok
    finally:
        _close_quietly(edge_session)
        _close_quietly(cloud_session)


def _initial_payload(args: argparse.Namespace, errors: list[str], warnings: list[str]) -> dict:
    """Build the top-level run_check payload."""
    payload = {
        "ok": False,
        "mode": "dry-run" if bool(args.dry_run) else "validate",
        "edge_admin": _normalize_base_url(args.edge_admin),
        "stream_code": _arg_text(args, "stream_code"),
        "warnings": warnings,
        "errors": errors,
        "steps": _build_steps(args),
        "checks": [],
    }
    if _console_validation_enabled(args):
        payload["cloud_admin"] = _normalize_base_url(args.cloud_admin)
    return payload


def run_check(args: argparse.Namespace, client_cls=CloudEdgeClient, session_factory=requests.Session) -> dict:
    """执行 `check`。"""
    errors, warnings = _validate_inputs(args)
    payload = _initial_payload(args, errors, warnings)
    if errors:
        return payload
    if args.dry_run:
        payload["ok"] = True
        return payload

    client = client_cls(
        base_url=_normalize_base_url(args.edge_admin),
        open_api_token=_arg_text(args, "token"),
        timeout_seconds=float(args.timeout or 5.0),
    )
    checks: list[dict] = []
    base_ok, recording_meta = _run_base_checks(client, args, checks)
    console_ok = _run_console_checks(args, checks, recording_meta, session_factory)

    payload["checks"] = checks
    payload["ok"] = bool(base_ok and console_ok)
    return payload


def main(argv: list[str] | None = None) -> int:
    """处理 `main`。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = run_check(args)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if bool(payload.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
