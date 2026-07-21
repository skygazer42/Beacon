# Tracing Smoke Test (E2E)

This folder contains a **local end-to-end tracing smoke test** for Beacon.

Target: prove a **single trace** contains spans from all 3 components:

- `beacon-admin` (Django)
- `beacon-analyzer` (C++)
- `beacon-mediaserver` (ZLMediaKit)

The script:

1. Calls Admin `GET /control/openIndex` (this fans out to MediaServer and Analyzer in normal deployments).
2. Queries Jaeger HTTP API to find a recent trace that includes all 3 service names.
3. Optionally (best-effort) queries Tempo for that trace id.

## Prereqs

- Admin is running and reachable (default: `http://127.0.0.1:9991`)
- MediaServer (ZLM) is running and reachable by Admin (default: `http://127.0.0.1:9992`)
- Analyzer is running and reachable by Admin (default: `http://127.0.0.1:9993`)
- Tracing stack is already running:
  - Jaeger query/UI: `http://127.0.0.1:16686`
  - Tempo: `http://127.0.0.1:3200`
  - (Collector endpoints are not queried directly by this script)

Important: Admin only calls Analyzer from `/control/openIndex` when MediaServer is reachable, so you need ZLM up for the full 3-service trace.

## Lightweight Mode (No C++ Binaries Required)

If you cannot run the real C++ Analyzer/MediaServer binaries (common in CI or lightweight dev
containers), you can still validate the **end-to-end tracing pipeline** and `traceparent`
propagation by running stub services.

The stub services:
- mimic minimal HTTP APIs used by `/control/openIndex`
- export Zipkin v2 JSON SERVER spans to the collector
- show up as `beacon-mediaserver` + `beacon-analyzer` services in Jaeger/Tempo

Start the stubs (ports 9992/9993 by default):

```bash
export BEACON_OTEL_ENABLED=1
export BEACON_OTEL_ZIPKIN_ENDPOINT="http://127.0.0.1:9411"
export BEACON_OTEL_SAMPLE_RATIO=1

python3 tools/tracing/stub_services.py
```

Then start Admin with OTLP enabled:

```bash
export BEACON_OTEL_ENABLED=1
export BEACON_OTEL_OTLP_ENDPOINT="http://127.0.0.1:4318"
export BEACON_OTEL_SAMPLE_RATIO=1

cd Admin
python3 manage.py migrate
python3 manage.py runserver 0.0.0.0:9991 --noreload
```

Finally run the smoke test:

```bash
python3 tools/tracing/trace_smoke_test.py --require-tempo
```

Note: this validates tracing plumbing, not full Analyzer/MediaServer business behavior.

## OpenAPI Token

`/control/openIndex` is treated as an OpenAPI path by Admin middleware (`control/open*`).

- If you did NOT set `BEACON_OPEN_API_TOKEN` and did NOT set `BEACON_REQUIRE_OPEN_API_TOKEN=1`:
  - requests from loopback (`127.0.0.1`) are allowed by default.
- Otherwise pass the token:
  - `--token <token>`

## Run

```bash
python3 tools/tracing/trace_smoke_test.py
```

With explicit URLs:

```bash
python3 tools/tracing/trace_smoke_test.py \
  --admin http://127.0.0.1:9991 \
  --jaeger http://127.0.0.1:16686 \
  --tempo http://127.0.0.1:3200
```

With OpenAPI token:

```bash
python3 tools/tracing/trace_smoke_test.py --token "$BEACON_OPEN_API_TOKEN"
```

If you customized service names (e.g. via `OTEL_SERVICE_NAME` / `BEACON_OTEL_SERVICE_NAME`), pass explicit names:

```bash
python3 tools/tracing/trace_smoke_test.py \
  --service-admin beacon-admin \
  --service-analyzer beacon-analyzer \
  --service-mediaserver beacon-mediaserver
```

Require Tempo to have the trace (optional strict mode):

```bash
python3 tools/tracing/trace_smoke_test.py --require-tempo
```

## Expected Output

PASS example:

```
PASS: Jaeger trace found with all required services
  trace_id=4bf92f3577b34da6a3ce929d0e0e4736
  services=beacon-admin,beacon-analyzer,beacon-mediaserver
  jaeger_trace_url=http://127.0.0.1:16686/trace/4bf92f3577b34da6a3ce929d0e0e4736
  tempo=OK (ok)
```

FAIL output includes hints (token, services down, collector/export not wired, etc.).
