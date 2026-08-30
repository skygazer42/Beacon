#!/bin/sh
set -eu

echo "[beacon-cloud] validating initialization runtime..."
python /app/deploy/cloud-saas-v1/scripts/runtime_preflight.py

echo "[beacon-cloud] applying serialized migrations and bootstrap..."
exec python /app/Admin/manage.py prepare_cloud_runtime
