#!/bin/sh
set -eu

echo "[beacon-cloud] starting (cloud mode)..."

python - <<'PY'
import os
import socket
import time

required_secrets = {
    "BEACON_OPEN_API_TOKEN": 32,
    "BEACON_DJANGO_SECRET_KEY": 32,
    "BEACON_CLOUD_EDGE_TOKEN_PEPPER": 32,
    "BEACON_BOOTSTRAP_ADMIN_PASSWORD": 12,
    "BEACON_CLOUD_S3_SECRET_ACCESS_KEY": 16,
}
secret_values = []
for name, minimum_length in required_secrets.items():
    value = str(os.environ.get(name, "") or "").strip()
    normalized = value.upper().replace("-", "_")
    if len(value) < minimum_length or "CHANGE_ME" in normalized or normalized == "CHANGEME":
        raise SystemExit(f"[beacon-cloud] {name} must be replaced with a strong secret")
    secret_values.append(value)

if len(secret_values) != len(set(secret_values)):
    raise SystemExit("[beacon-cloud] security-sensitive values must be unique")

database_url = str(os.environ.get("BEACON_CLOUD_DB_URL", "") or "").strip()
if not database_url or "CHANGE_ME" in database_url.upper().replace("-", "_"):
    raise SystemExit("[beacon-cloud] BEACON_CLOUD_DB_URL must contain real credentials")

host = os.environ.get("BEACON_PG_HOST", "postgres")
port = int(os.environ.get("BEACON_PG_PORT", "5432"))

for i in range(60):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print(f"[beacon-cloud] postgres reachable: {host}:{port}")
        break
    except OSError as e:
        print(f"[beacon-cloud] waiting postgres ({i+1}/60): {e}")
        time.sleep(1)
else:
    raise SystemExit("[beacon-cloud] postgres not reachable, abort")
PY

echo "[beacon-cloud] migrate..."
python Admin/manage.py migrate --noinput

echo "[beacon-cloud] collect static assets..."
python Admin/manage.py collectstatic --noinput

echo "[beacon-cloud] bootstrap (admin + default tenant/project/cluster)..."
python Admin/manage.py beacon_cloud_bootstrap

echo "[beacon-cloud] gunicorn on 0.0.0.0:8000"
# Keep one worker process because Beacon's scheduler/outbox services currently run
# inside Django. Threads provide request concurrency without duplicating those jobs.
exec gunicorn \
    --chdir /app/Admin \
    --bind 0.0.0.0:8000 \
    --workers 1 \
    --worker-class gthread \
    --threads "${BEACON_GUNICORN_THREADS:-4}" \
    --timeout "${BEACON_GUNICORN_TIMEOUT_SECONDS:-120}" \
    --access-logfile - \
    --error-logfile - \
    framework.wsgi:application
