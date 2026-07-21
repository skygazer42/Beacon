import base64
import binascii
import json
import os
import struct
import time
import uuid
import zlib
from datetime import datetime, timezone

import requests


def _truthy(value: str) -> bool:
    raw = str(value or "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _wait_for_file(path: str, timeout_seconds: int = 120) -> None:
    start = time.time()
    while time.time() - start < timeout_seconds:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return
        time.sleep(1)
    raise RuntimeError(f"timeout waiting token file: {path}")


def _wait_for_http(base_url: str, timeout_seconds: int = 120) -> None:
    start = time.time()
    last_err = ""
    while time.time() - start < timeout_seconds:
        try:
            r = requests.get(f"{base_url}/login", timeout=3)
            if r.status_code in (200, 302):
                return
            last_err = f"status={r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(1)
    raise RuntimeError(f"timeout waiting cloud http ready: {base_url} ({last_err})")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_demo_png_bytes(width: int = 640, height: int = 360) -> bytes:
    """
    生成一张“可见”的 PNG（纯 stdlib），用于 docker POC 验收。

    - RGBA 8-bit
    - 简单渐变 + 条纹，便于肉眼确认预览确实工作
    """
    width = int(width)
    height = int(height)
    if width < 32:
        width = 32
    if height < 32:
        height = 32

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            r = int(x * 255 / max(1, width - 1))
            g = int(y * 255 / max(1, height - 1))
            b = 64
            # 叠加条纹（每 32 像素反相一次）
            if ((x // 32) + (y // 32)) % 2 == 0:
                r = 255 - r
                g = 255 - g
            raw.extend([r & 0xFF, g & 0xFF, b & 0xFF, 255])

    compressed = zlib.compress(bytes(raw), level=9)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def _require_env(name: str) -> str:
    value = str(os.environ.get(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"missing env: {name}")
    return value


def _read_token_file(token_file: str) -> str:
    with open(token_file, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise RuntimeError("edge token file empty")
    return token


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _request_presign(base_url: str, *, headers: dict, event_id: str, content_type: str, ext: str):
    presign_resp = requests.post(
        f"{base_url}/open/cloud/v1/presign/image",
        headers=headers,
        json={"event_id": event_id, "content_type": content_type, "ext": ext},
        timeout=10,
    )
    presign_payload = presign_resp.json()
    if presign_resp.status_code != 200 or presign_payload.get("code") != 1000:
        raise RuntimeError(f"presign failed: status={presign_resp.status_code} body={presign_payload}")

    data = presign_payload.get("data") or {}
    bucket = str(data.get("bucket") or "")
    object_key = str(data.get("object_key") or "")
    upload = data.get("upload") or {}
    put_url = str(upload.get("url") or "")
    put_headers = dict(upload.get("headers") or {})
    if not (bucket and object_key and put_url):
        raise RuntimeError(f"presign response missing fields: {presign_payload}")

    return bucket, object_key, put_url, put_headers


def _upload_bytes(put_url: str, *, put_headers: dict, data: bytes) -> None:
    put_resp = requests.put(put_url, data=data, headers=put_headers, timeout=30)
    if put_resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"put failed: status={put_resp.status_code} body={put_resp.text[:200]}")


def _ingest_alarm_created(base_url: str, *, headers: dict, payload: dict) -> dict:
    ingest_resp = requests.post(
        f"{base_url}/open/cloud/v1/events/alarm-created",
        headers=headers,
        json=payload,
        timeout=10,
    )
    ingest_body = ingest_resp.json() if ingest_resp.content else {}
    if ingest_resp.status_code != 200 or ingest_body.get("code") != 1000:
        raise RuntimeError(f"ingest failed: status={ingest_resp.status_code} body={ingest_body}")
    return ingest_body


def _build_alarm_created_payload(*, event_id: str, bucket: str, object_key: str, content_type: str) -> dict:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "schema": "beacon.event.v1",
        "event_id": event_id,
        "event_type": "alarm.created",
        "event_source": "edge-simulator",
        "timestamp": now,
        "node_code": "edge-simulator",
        "control_code": "demo",
        "desc": "Docker POC demo alarm (edge-simulator)",
        "cloud_image": {"bucket": bucket, "key": object_key, "content_type": content_type},
    }


def main() -> int:
    base_url = _require_env("BEACON_CLOUD_BASE_URL")
    token_file = _require_env("BEACON_BOOTSTRAP_EDGE_TOKEN_FILE")

    print(f"[edge-simulator] base_url={base_url}")
    print(f"[edge-simulator] token_file={token_file}")

    _wait_for_http(base_url)
    _wait_for_file(token_file)

    token = _read_token_file(token_file)

    event_id = f"demo-{uuid.uuid4().hex[:12]}"
    content_type = "image/png"
    ext = ".png"
    img_bytes = make_demo_png_bytes()
    headers = _auth_headers(token)

    print(f"[edge-simulator] presign event_id={event_id}")
    bucket, object_key, put_url, put_headers = _request_presign(
        base_url,
        headers=headers,
        event_id=event_id,
        content_type=content_type,
        ext=ext,
    )

    print(f"[edge-simulator] upload {len(img_bytes)} bytes -> s3://{bucket}/{object_key}")
    _upload_bytes(put_url, put_headers=put_headers, data=img_bytes)

    print("[edge-simulator] ingest...")
    ingest_payload = _build_alarm_created_payload(
        event_id=event_id,
        bucket=bucket,
        object_key=object_key,
        content_type=content_type,
    )
    _ingest_alarm_created(base_url, headers=headers, payload=ingest_payload)

    print("[edge-simulator] success ✅")
    print(json.dumps({"event_id": event_id, "bucket": bucket, "object_key": object_key}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[edge-simulator] failed: {e}")
        raise
