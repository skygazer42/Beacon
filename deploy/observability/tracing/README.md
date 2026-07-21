# Beacon Tracing Stack (OTel Collector + Jaeger + Tempo)

This folder provides a **local/dev tracing stack** that proves spans are exported into:

- **Jaeger** (UI)
- **Grafana Tempo** (backend, queryable via Grafana)

It is designed to match Beacon's repo conventions:

- Collector OTLP/gRPC: `4317`
- Collector OTLP/HTTP: `4318`
- Collector Zipkin: `9411`
- Jaeger UI: `16686`
- Tempo HTTP: `3200`

## 1) Start

```bash
cd deploy/observability/tracing
export GF_SECURITY_ADMIN_PASSWORD='replace-with-a-strong-password'
docker compose -f compose.yml up -d
docker compose -f compose.yml ps
```

Compose 会在未设置 `GF_SECURITY_ADMIN_PASSWORD` 时拒绝启动。如需更换默认用户名 `admin`，可同时设置 `GF_SECURITY_ADMIN_USER`。

## 2) Access

- Jaeger UI: `http://localhost:16686`
- Tempo HTTP API: `http://localhost:3200`
- Grafana UI: `http://localhost:3000`（使用 `GF_SECURITY_ADMIN_USER` 和 `GF_SECURITY_ADMIN_PASSWORD`）

Collector ingestion endpoints (for apps):

- OTLP gRPC: `localhost:4317`
- OTLP HTTP: `http://localhost:4318` (traces: `POST /v1/traces`)
- Zipkin v2: `http://localhost:9411/api/v2/spans`

## 3) Beacon Environment Variables (quick wiring)

Industrial recommendation: set both endpoints so Admin/Analyzer/MediaServer can all export spans without
arguing about build mode.

```bash
export BEACON_OTEL_ENABLED=1

# Admin (Django) exports OTLP/HTTP here (base is ok; code normalizes to /v1/traces).
export BEACON_OTEL_OTLP_ENDPOINT="http://localhost:4318"

# MediaServer (ZLMediaKit) exports Zipkin v2 JSON here.
#
# Analyzer uses:
# - OTLP/HTTP when built with -DBEACON_ENABLE_OTEL=ON + opentelemetry-cpp
# - otherwise (default/light build): Zipkin v2 JSON fallback here (requires libcurl)
export BEACON_OTEL_ZIPKIN_ENDPOINT="http://localhost:9411"

# Sampling ratio (0..1). For local debugging, use 1. In production, start at 0.1 and adjust.
export BEACON_OTEL_SAMPLE_RATIO="1"
```

Service naming (optional):

```bash
export OTEL_SERVICE_NAME="beacon-admin"    # or beacon-analyzer / beacon-mediaserver
```

## 4) Verify Spans Land In Both Backends

1. Generate some traffic in Beacon (hit any Admin endpoint that triggers Analyzer/ZLM calls).
2. Open Jaeger UI and search for services like `beacon-admin` / `beacon-analyzer`.
3. Open Grafana -> Explore -> Tempo, and query by service name.

### Smoke Test (No Beacon Required)

If you want a quick proof without running Beacon, you can generate a single trace via OTLP/gRPC
and verify it exists in both Jaeger and Tempo.

If your Python environment does not have OTel deps:

```bash
python3 -m pip install --user opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
```

Then run:

```bash
TRACE_ID="$(
python3 - <<'PY'
import time
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create({"service.name": "beacon-tracing-smoke"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint="localhost:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("beacon.smoke")
with tracer.start_as_current_span("smoke-span") as span:
    span.set_attribute("smoke", True)
    span.set_attribute("ts", int(time.time()))
    ctx = span.get_span_context()
    print(format(ctx.trace_id, "032x"))

provider.force_flush(5)
PY
)"

echo "TRACE_ID=$TRACE_ID"
curl -sS "http://localhost:16686/api/traces/${TRACE_ID}" | head
curl -sS "http://localhost:3200/api/traces/${TRACE_ID}" | head
```

### Smoke Test (Zipkin, No Extra Python Deps)

If you don't want to install any OpenTelemetry Python packages, you can also push a single Zipkin v2
span via `curl` (collector exposes a Zipkin receiver at `:9411`):

```bash
TRACE_ID="$(python3 -c 'import os; print(os.urandom(16).hex())')"
SPAN_ID="$(python3 -c 'import os; print(os.urandom(8).hex())')"
TS_US="$(python3 -c 'import time; print(int(time.time()*1_000_000))')"

curl -sS -X POST -H 'Content-Type: application/json' \
  --data "[{\"traceId\":\"${TRACE_ID}\",\"id\":\"${SPAN_ID}\",\"name\":\"zipkin-smoke\",\"kind\":\"SERVER\",\"timestamp\":${TS_US},\"duration\":10000,\"localEndpoint\":{\"serviceName\":\"beacon-tracing-smoke-zipkin\"},\"tags\":{\"smoke\":\"true\"}}]" \
  http://localhost:9411/api/v2/spans

curl -sS "http://localhost:16686/api/traces/${TRACE_ID}" | head
curl -sS "http://localhost:3200/api/traces/${TRACE_ID}" | head
```

## 5) Stop / Clean

```bash
cd deploy/observability/tracing
docker compose -f compose.yml down
```

If you want to delete local trace data too:

```bash
docker compose -f compose.yml down -v
```
