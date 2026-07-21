#ifndef BEACON_ANALYZER_CORE_OTEL_H
#define BEACON_ANALYZER_CORE_OTEL_H

#include <memory>

struct evhttp_request;
struct evbuffer;

namespace beacon::otel {

// Initialize tracing (idempotent; best-effort; non-fatal).
//
// Build-time behavior:
// - If built with BEACON_ENABLE_OTEL: uses OpenTelemetry (OTLP/HTTP exporter via opentelemetry-cpp).
// - Otherwise: uses a lightweight Zipkin v2 JSON exporter (HTTP POST via libcurl).
//
// Runtime behavior:
// - Disabled by default (requires BEACON_OTEL_ENABLED=1).
void InitializeFromEnv() noexcept;

// Returns true when tracing is enabled and configured at runtime.
// Note: this may return true even when BEACON_ENABLE_OTEL is OFF (Zipkin fallback).
bool IsEnabled() noexcept;

class SpanScope {
public:
    struct Impl;

    SpanScope() noexcept;
    ~SpanScope() noexcept;

    SpanScope(SpanScope&&) noexcept;
    SpanScope& operator=(SpanScope&&) noexcept;

    SpanScope(const SpanScope&) = delete;
    SpanScope& operator=(const SpanScope&) = delete;

private:
    std::unique_ptr<Impl> impl_;

    explicit SpanScope(std::unique_ptr<Impl> impl) noexcept;
    friend SpanScope StartServerSpan(struct evhttp_request* req) noexcept;
};

// Start a SERVER span for an incoming HTTP request.
// - Extracts incoming W3C trace context from "traceparent".
//   When built with BEACON_ENABLE_OTEL, "tracestate" is also supported via the SDK propagator.
// - Sets span attributes/tags: http.method, http.target.
// - Best-effort injects "traceparent" into the response headers (when supported by the build/runtime).
SpanScope StartServerSpan(struct evhttp_request* req) noexcept;

// Wrapper for evhttp_send_reply which also annotates the active span with http.status_code.
void SendReply(struct evhttp_request* req,
               int http_status,
               const char* reason,
               struct evbuffer* databuf) noexcept;

}  // namespace beacon::otel

#endif  // BEACON_ANALYZER_CORE_OTEL_H
