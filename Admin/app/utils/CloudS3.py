import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from django.utils import timezone


def build_alarm_image_object_key(
    tenant_id: Any,
    project_id: Any,
    cluster_id: Any,
    event_id: str,
    ext: str,
    now: Optional[datetime] = None,
) -> str:
    """构建告警图片`object`键。
    
    Deterministic S3 object key for alarm screenshot.
    
        Spec:
          tenant_<tenant_id>/project_<project_id>/cluster_<cluster_id>/alarms/YYYY/MM/DD/<event_id>/image.<ext>
    """
    if now is None:
        now = timezone.now()

    event_id = str(event_id or "").strip()
    if not event_id:
        raise ValueError("event_id is required")
    # Avoid path injection (defense-in-depth)
    event_id = event_id.replace("/", "_").replace("\\", "_")

    ext = str(ext or "").strip().lower()
    if not ext:
        ext = ".jpg"
    if not ext.startswith("."):
        ext = f".{ext}"

    yyyy = f"{now.year:04d}"
    mm = f"{now.month:02d}"
    dd = f"{now.day:02d}"

    return (
        f"tenant_{tenant_id}/project_{project_id}/cluster_{cluster_id}"
        f"/alarms/{yyyy}/{mm}/{dd}/{event_id}/image{ext}"
    )


def build_digital_human_screenshot_object_key(
    device_id: Any,
    ext: str,
    now: Optional[datetime] = None,
) -> str:
    """构建数字人截图对象键。"""
    if now is None:
        now = timezone.now()

    device_token = str(device_id or "").strip()
    if not device_token:
        raise ValueError("device_id is required")
    device_token = device_token.replace("/", "_").replace("\\", "_")

    ext = str(ext or "").strip().lower()
    if not ext:
        ext = ".jpg"
    if not ext.startswith("."):
        ext = f".{ext}"

    yyyy = f"{now.year:04d}"
    mm = f"{now.month:02d}"
    dd = f"{now.day:02d}"
    leaf = f"{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:12]}"

    return f"digital-human/screenshots/{yyyy}/{mm}/{dd}/device_{device_token}/{leaf}{ext}"


def make_s3_client_from_env():
    """生成`s3``client``from`环境变量。
    
    Create a boto3 S3 client using env config.
    
        Intended for BEACON_DEPLOYMENT_MODE=cloud.
    """
    try:
        import boto3  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"boto3 dependency missing: {e}")

    region = str(os.environ.get("BEACON_CLOUD_S3_REGION", "") or "").strip() or "us-east-1"
    endpoint_url = str(os.environ.get("BEACON_CLOUD_S3_ENDPOINT_URL", "") or "").strip() or None
    access_key_id = str(os.environ.get("BEACON_CLOUD_S3_ACCESS_KEY_ID", "") or "").strip() or None
    secret_access_key = str(os.environ.get("BEACON_CLOUD_S3_SECRET_ACCESS_KEY", "") or "").strip() or None

    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def presign_put_image(bucket: str, key: str, content_type: str, expires_in: int) -> Dict[str, Any]:
    """处理预签名`put`图片。
    
    Presign PUT for uploading an image object.
    
        Returns:
          {
            "url": "...",
            "headers": {"Content-Type": "..."},
            "expires_in_seconds": 900,
          }
    """
    client = make_s3_client_from_env()
    url = client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": str(bucket),
            "Key": str(key),
            "ContentType": str(content_type or "application/octet-stream"),
        },
        ExpiresIn=int(expires_in or 900),
        HttpMethod="PUT",
    )
    return {
        "url": url,
        "headers": {"Content-Type": str(content_type or "application/octet-stream")},
        "expires_in_seconds": int(expires_in or 900),
    }


def presign_get(bucket: str, key: str, expires_in: int) -> Dict[str, Any]:
    """处理预签名`get`。"""
    client = make_s3_client_from_env()
    url = client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": str(bucket), "Key": str(key)},
        ExpiresIn=int(expires_in or 60),
        HttpMethod="GET",
    )
    return {"url": url, "expires_in_seconds": int(expires_in or 60)}
