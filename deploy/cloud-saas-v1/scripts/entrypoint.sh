#!/bin/sh
set -eu

echo "[beacon-cloud] starting Web process (cloud mode)..."

python /app/deploy/cloud-saas-v1/scripts/runtime_preflight.py
python /app/deploy/cloud-saas-v1/scripts/wait_for_migrations.py

echo "[beacon-cloud] gunicorn on 0.0.0.0:8000"
exec gunicorn \
    --chdir /app/Admin \
    --bind 0.0.0.0:8000 \
    --workers "${BEACON_GUNICORN_WORKERS:-2}" \
    --worker-class gthread \
    --threads "${BEACON_GUNICORN_THREADS:-4}" \
    --timeout "${BEACON_GUNICORN_TIMEOUT_SECONDS:-120}" \
    --graceful-timeout "${BEACON_GUNICORN_GRACEFUL_TIMEOUT_SECONDS:-30}" \
    --keep-alive "${BEACON_GUNICORN_KEEPALIVE_SECONDS:-5}" \
    --max-requests "${BEACON_GUNICORN_MAX_REQUESTS:-5000}" \
    --max-requests-jitter "${BEACON_GUNICORN_MAX_REQUESTS_JITTER:-500}" \
    --no-control-socket \
    --access-logfile - \
    --error-logfile - \
    framework.wsgi:application
