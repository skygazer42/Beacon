#!/bin/sh
set -eu

echo "[beacon-cloud] validating background worker runtime..."
python /app/deploy/cloud-saas-v1/scripts/runtime_preflight.py
python /app/deploy/cloud-saas-v1/scripts/wait_for_migrations.py

echo "[beacon-cloud] starting leader-elected background worker..."
exec python /app/Admin/manage.py run_background_worker
