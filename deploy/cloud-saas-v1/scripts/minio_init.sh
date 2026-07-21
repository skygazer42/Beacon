#!/bin/sh
set -eu

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
user="${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
password="${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
bucket="${BEACON_CLOUD_S3_BUCKET:-beacon-cloud}"

echo "[minio-init] endpoint=$endpoint bucket=$bucket"

# 等待 MinIO 可用
for i in $(seq 1 60); do
  if mc alias set beacon "$endpoint" "$user" "$password" >/dev/null 2>&1; then
    echo "[minio-init] minio reachable"
    break
  fi
  echo "[minio-init] waiting minio (${i}/60)..."
  sleep 1
done

mc mb -p "beacon/$bucket" >/dev/null 2>&1 || true
echo "[minio-init] bucket ready: $bucket"
