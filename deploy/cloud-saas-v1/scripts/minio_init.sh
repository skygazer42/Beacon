#!/bin/sh
set -eu

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
user="${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
password="${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
bucket="${BEACON_CLOUD_S3_BUCKET:-beacon-cloud}"

echo "[minio-init] endpoint=$endpoint bucket=$bucket"

# 等待 MinIO 可用；达到上限后失败，避免把不可用对象存储误报成初始化成功。
attempt=0
until mc alias set beacon "$endpoint" "$user" "$password" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "[minio-init] minio unavailable after 60 attempts" >&2
    exit 1
  fi
  echo "[minio-init] waiting minio (${attempt}/60)..."
  sleep 1
done

echo "[minio-init] minio reachable"
mc mb --ignore-existing "beacon/$bucket" >/dev/null
echo "[minio-init] bucket ready: $bucket"
