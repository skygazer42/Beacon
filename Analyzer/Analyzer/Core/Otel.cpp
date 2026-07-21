#include "Otel.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cstddef>
#include <condition_variable>
#include <cstdlib>
#include <deque>
#include <exception>
#include <mutex>
#include <random>
#include <string>
#include <string_view>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

#include <curl/curl.h>
#include <event2/buffer.h>
#include <event2/http.h>
#include <event2/http_struct.h>
#include <json/json.h>

#if defined(BEACON_ENABLE_OTEL)
#include <opentelemetry/context/propagation/global_propagator.h>
#include <opentelemetry/context/propagation/text_map_propagator.h>
#include <opentelemetry/exporters/otlp/otlp_http_exporter_factory.h>
#include <opentelemetry/exporters/otlp/otlp_http_exporter_options.h>
#include <opentelemetry/sdk/resource/resource.h>
#include <opentelemetry/sdk/trace/batch_span_processor_factory.h>
#include <opentelemetry/sdk/trace/provider.h>
#include <opentelemetry/sdk/trace/samplers/always_off.h>
#include <opentelemetry/sdk/trace/samplers/always_on.h>
#include <opentelemetry/sdk/trace/samplers/parent.h>
#include <opentelemetry/sdk/trace/samplers/trace_id_ratio.h>
#include <opentelemetry/sdk/trace/tracer_provider_factory.h>
#include <opentelemetry/trace/context.h>
#include <opentelemetry/trace/provider.h>
#include <opentelemetry/trace/propagation/http_trace_context.h>
#include <opentelemetry/trace/scope.h>
#include <opentelemetry/trace/span.h>
#include <opentelemetry/trace/span_startoptions.h>
#endif

namespace {

void configure_secure_tls(CURL* curl) { // NOSONAR - libcurl exposes CURL as an opaque handle typedef
    if (curl == nullptr) {
        return;
    }
    long ssl_version = CURL_SSLVERSION_TLSv1_2;
#ifdef CURL_SSLVERSION_MAX_TLSv1_3
    ssl_version |= CURL_SSLVERSION_MAX_TLSv1_3;
#endif
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
    curl_easy_setopt(curl, CURLOPT_SSLVERSION, ssl_version); // NOSONAR - enforce TLS >= 1.2 and allow negotiation up to 1.3 when available
}

void post_zipkin_json(std::string_view endpoint, std::string_view body) {
    CURL* curl = curl_easy_init();
    if (curl == nullptr) {
        return;
    }
    const std::string endpoint_url(endpoint);
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_URL, endpoint_url.c_str());
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.data());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 500L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 2000L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "beacon-analyzer/otel-zipkin");
    configure_secure_tls(curl);

    (void)curl_easy_perform(curl);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
}

class ZipkinExportDispatcher {
public:
    ZipkinExportDispatcher()
        : mWorker([this]() { run(); }) {}

    ~ZipkinExportDispatcher() {
        {
            std::scoped_lock lock(mMutex);
            mStopping = true;
        }
        mCv.notify_one();
        if (mWorker.joinable()) {
            mWorker.join();
        }
    }

    void enqueue(std::string endpoint, std::string body) {
        {
            std::scoped_lock lock(mMutex);
            mTasks.push_back({std::move(endpoint), std::move(body)});
        }
        mCv.notify_one();
    }

private:
    struct Task {
        std::string endpoint;
        std::string body;
    };

    void run() {
        for (;;) {
            Task task;
            {
                std::unique_lock lock(mMutex);
                mCv.wait(lock, [this]() {
                    return mStopping || !mTasks.empty();
                });
                if (mStopping && mTasks.empty()) {
                    return;
                }
                task = std::move(mTasks.front());
                mTasks.pop_front();
            }
            post_zipkin_json(task.endpoint, task.body);
        }
    }

    std::mutex mMutex;
    std::condition_variable mCv;
    std::deque<Task> mTasks;
    std::thread mWorker;
    bool mStopping = false;
};

struct ZipkinExportDispatcherHolder {
    inline static ZipkinExportDispatcher dispatcher{};
};

ZipkinExportDispatcher& zipkin_export_dispatcher() {
    return ZipkinExportDispatcherHolder::dispatcher;
}

std::string get_env_string(const char* name) {
    const char* v = std::getenv(name);
    if (v == nullptr || *v == '\0') {
        return {};
    }
    return std::string(v);
}

std::string to_lower_copy(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return s;
}

bool env_truthy(const char* name) {
    std::string v = to_lower_copy(get_env_string(name));
    if (v.empty()) {
        return false;
    }
    return v == "1" || v == "true" || v == "yes" || v == "on";
}

std::string trim_copy(std::string s) {
    auto is_ws = [](unsigned char c) { return std::isspace(c) != 0; };
    while (!s.empty() && is_ws(static_cast<unsigned char>(s.front()))) {
        s.erase(s.begin());
    }
    while (!s.empty() && is_ws(static_cast<unsigned char>(s.back()))) {
        s.pop_back();
    }
    return s;
}

bool ends_with(std::string_view s, std::string_view suffix) {
    if (s.size() < suffix.size()) {
        return false;
    }
    return std::equal(suffix.rbegin(), suffix.rend(), s.rbegin());
}

std::string normalize_otlp_http_traces_endpoint(std::string endpoint) {
    endpoint = trim_copy(std::move(endpoint));
    if (endpoint.empty()) {
        return endpoint;
    }
    // Accept either a base endpoint (e.g. http://host:4318) or a full traces endpoint
    // (e.g. http://host:4318/v1/traces).
    if (ends_with(endpoint, "/v1/traces")) {
        return endpoint;
    }
    if (ends_with(endpoint, "/v1/traces/")) {
        endpoint.pop_back();
        return endpoint;
    }
    if (!endpoint.empty() && endpoint.back() == '/') {
        endpoint.pop_back();
    }
    endpoint += "/v1/traces";
    return endpoint;
}

}  // namespace

namespace beacon::otel {

#if !defined(BEACON_ENABLE_OTEL)

namespace {

struct ZipkinFallbackState {
    inline static std::once_flag initOnce{};
    inline static std::atomic<bool> enabled{false};
    inline static std::string zipkinEndpoint{};
    inline static std::string serviceName{};
    inline static double sampleRatio = 1.0;
    inline static thread_local SpanScope::Impl* currentSpan = nullptr;
};

std::once_flag& init_once() {
    return ZipkinFallbackState::initOnce;
}

std::atomic<bool>& enabled() {
    return ZipkinFallbackState::enabled;
}

std::string& zipkin_endpoint() {
    return ZipkinFallbackState::zipkinEndpoint;
}

std::string& service_name() {
    return ZipkinFallbackState::serviceName;
}

double& sample_ratio() {
    return ZipkinFallbackState::sampleRatio;
}

SpanScope::Impl*& current_span() {
    return ZipkinFallbackState::currentSpan;
}

uint64_t now_us() {
    using namespace std::chrono;
    return static_cast<uint64_t>(duration_cast<microseconds>(system_clock::now().time_since_epoch()).count());
}

bool is_lower_hex(const std::string& s) {
    for (unsigned char c : s) {
        if ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
            continue;
        }
        return false;
    }
    return true;
}

std::string to_lower_hex_inplace(std::string s) {
    for (auto& c : s) {
        if (c >= 'A' && c <= 'F') {
            c = static_cast<char>('a' + (c - 'A'));
        } else if (c >= 'A' && c <= 'Z') {
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
    }
    return s;
}

std::string random_hex(size_t bytes) {
    static constexpr char HEX[] = "0123456789abcdef";
    std::string out;
    out.reserve(bytes * 2);

    thread_local std::mt19937_64 rng([]() {
        std::random_device rd;
        std::seed_seq seq{rd(), rd(), rd(), rd(), rd(), rd(), rd(), rd()};
        return std::mt19937_64(seq);
    }());

    for (size_t i = 0; i < bytes; ++i) {
        const auto b = static_cast<std::byte>(rng() & 0xFF);
        const auto hi = std::to_integer<unsigned int>((b >> 4) & static_cast<std::byte>(0x0F));
        const auto lo = std::to_integer<unsigned int>(b & static_cast<std::byte>(0x0F));
        out.push_back(HEX[hi]);
        out.push_back(HEX[lo]);
    }
    return out;
}

bool sample_new_trace(double ratio) {
    if (ratio >= 1.0) {
        return true;
    }
	    if (ratio <= 0.0) {
	        return false;
	    }
	    thread_local std::mt19937 rng(std::random_device{}());
	    std::uniform_real_distribution dist(0.0, 1.0);
	    return dist(rng) < ratio;
	}

bool parse_traceparent(std::string traceparent,
                       std::string& trace_id,
                       std::string& parent_span_id,
                       bool& sampled) {
    trace_id.clear();
    parent_span_id.clear();
    sampled = false;

    traceparent = trim_copy(std::move(traceparent));
    if (traceparent.empty()) {
        return false;
    }

    // Expected format: version-traceid-spanid-flags
    const size_t p1 = traceparent.find('-');
    if (p1 == std::string::npos) {
        return false;
    }
    const size_t p2 = traceparent.find('-', p1 + 1);
    if (p2 == std::string::npos) {
        return false;
    }
    const size_t p3 = traceparent.find('-', p2 + 1);
    if (p3 == std::string::npos) {
        return false;
    }

    std::string version = traceparent.substr(0, p1);
    std::string tid = traceparent.substr(p1 + 1, p2 - (p1 + 1));
    std::string sid = traceparent.substr(p2 + 1, p3 - (p2 + 1));
    std::string flags = traceparent.substr(p3 + 1);

    version = to_lower_hex_inplace(trim_copy(std::move(version)));
    tid = to_lower_hex_inplace(trim_copy(std::move(tid)));
    sid = to_lower_hex_inplace(trim_copy(std::move(sid)));
    flags = to_lower_hex_inplace(trim_copy(std::move(flags)));

    if (version.size() != 2 || tid.size() != 32 || sid.size() != 16 || flags.size() != 2) {
        return false;
    }
    if (!is_lower_hex(version) || !is_lower_hex(tid) || !is_lower_hex(sid) || !is_lower_hex(flags)) {
        return false;
    }
    if (tid == std::string(32, '0') || sid == std::string(16, '0')) {
        return false;
    }

    int flags_int = 0;
    try {
        flags_int = std::stoi(flags, nullptr, 16);
    } catch (const std::invalid_argument&) {
        flags_int = 0;
    } catch (const std::out_of_range&) {
        flags_int = 0;
    }
    sampled = (flags_int & 0x01) != 0;
    trace_id = tid;
    parent_span_id = sid;
    return true;
}

std::string normalize_zipkin_endpoint(std::string endpoint) {
    endpoint = trim_copy(std::move(endpoint));
    if (endpoint.empty()) {
        return endpoint;
    }
    if (ends_with(endpoint, "/api/v2/spans/")) {
        endpoint.pop_back();
        return endpoint;
    }
    if (ends_with(endpoint, "/api/v2/spans")) {
        return endpoint;
    }
    if (!endpoint.empty() && endpoint.back() == '/') {
        endpoint.pop_back();
    }
    endpoint += "/api/v2/spans";
    return endpoint;
}

std::string derive_zipkin_from_otlp(std::string otlp_endpoint) {
    std::string s = trim_copy(std::move(otlp_endpoint));
    if (s.empty()) {
        return {};
    }

	    // Strip path portion if present.
	    size_t host_start = 0;
	    std::string scheme = "http";
	    if (const size_t scheme_pos = s.find("://"); scheme_pos != std::string::npos) {
	        scheme = to_lower_copy(s.substr(0, scheme_pos));
	        host_start = scheme_pos + 3;
	    }
    // This fallback uses libcurl (HTTP). If the OTLP endpoint uses a non-HTTP scheme
    // (e.g. "grpc://"), assume the collector still exposes Zipkin receiver over HTTP.
    if (scheme != "http" && scheme != "https") {
        scheme = "http";
    }

    const size_t slash_pos = s.find('/', host_start);
    std::string hostport = slash_pos == std::string::npos ? s.substr(host_start)
                                                          : s.substr(host_start, slash_pos - host_start);
    hostport = trim_copy(std::move(hostport));
    if (hostport.empty()) {
        return {};
    }

    // Replace port with 9411.
    std::string host = hostport;
    if (!hostport.empty() && hostport.front() == '[') {
        const size_t rb = hostport.find(']');
        if (rb != std::string::npos) {
            host = hostport.substr(0, rb + 1);
        }
    } else {
        const size_t colon_pos = hostport.rfind(':');
        if (colon_pos != std::string::npos && colon_pos + 1 < hostport.size()) {
            host = hostport.substr(0, colon_pos);
        }
    }

    std::string out = scheme + "://" + host + ":9411/api/v2/spans";
    return out;
}

std::string pick_zipkin_endpoint() {
    std::string ep = get_env_string("BEACON_OTEL_ZIPKIN_ENDPOINT");
    if (!ep.empty()) {
        return normalize_zipkin_endpoint(std::move(ep));
    }
    ep = get_env_string("OTEL_EXPORTER_ZIPKIN_ENDPOINT");
    if (!ep.empty()) {
        return normalize_zipkin_endpoint(std::move(ep));
    }

    // Convenience: if only OTLP endpoint is provided, assume collector also exposes Zipkin receiver at :9411.
    ep = get_env_string("BEACON_OTEL_OTLP_ENDPOINT");
    if (ep.empty()) {
        ep = get_env_string("OTEL_EXPORTER_OTLP_ENDPOINT");
    }
    if (!ep.empty()) {
        return normalize_zipkin_endpoint(derive_zipkin_from_otlp(std::move(ep)));
    }
    return {};
}

double parse_sample_ratio() {
    std::string v = trim_copy(get_env_string("BEACON_OTEL_SAMPLE_RATIO"));
    if (v.empty()) {
        return 1.0;
    }
    try {
        double r = std::stod(v);
        if (r < 0.0) r = 0.0;
        if (r > 1.0) r = 1.0;
        return r;
    } catch (const std::invalid_argument&) {
        return 1.0;
    } catch (const std::out_of_range&) {
        return 1.0;
    }
}

std::string pick_service_name() {
    std::string name = get_env_string("BEACON_OTEL_SERVICE_NAME");
    if (name.empty()) {
        name = get_env_string("OTEL_SERVICE_NAME");
    }
    if (name.empty()) {
        name = "beacon-analyzer";
    }
    return name;
}

auto request_command(const struct evhttp_request* req) {
    return evhttp_request_get_command(const_cast<struct evhttp_request*>(req)); // NOSONAR - libevent exposes a non-const request API for read-only accessors
}

const char* request_uri(const struct evhttp_request* req) {
    return evhttp_request_get_uri(const_cast<struct evhttp_request*>(req)); // NOSONAR - libevent exposes a non-const request API for read-only accessors
}

std::string http_method_string(const struct evhttp_request* req) {
    if (req == nullptr) {
        return "UNKNOWN";
    }
    const auto cmd = request_command(req);
    switch (cmd) {
        case EVHTTP_REQ_GET: return "GET";
        case EVHTTP_REQ_POST: return "POST";
        case EVHTTP_REQ_HEAD: return "HEAD";
        case EVHTTP_REQ_PUT: return "PUT";
        case EVHTTP_REQ_DELETE: return "DELETE";
        case EVHTTP_REQ_OPTIONS: return "OPTIONS";
        case EVHTTP_REQ_TRACE: return "TRACE";
        case EVHTTP_REQ_CONNECT: return "CONNECT";
        case EVHTTP_REQ_PATCH: return "PATCH";
        default: break;
    }
    return "OTHER";
}

std::string http_target_string(const struct evhttp_request* req) {
    if (req == nullptr) {
        return "/";
    }
    const char* uri = request_uri(req);
    return uri != nullptr ? std::string(uri) : std::string("/");
}

std::string http_path_from_target(const std::string& target) {
    if (target.empty()) {
        return "/";
    }
    evhttp_uri* parsed = evhttp_uri_parse(target.c_str());
    if (parsed == nullptr) {
        const auto qpos = target.find('?');
        if (qpos == std::string::npos) {
            return target;
        }
        return target.substr(0, qpos);
    }
    const char* path = evhttp_uri_get_path(parsed);
    std::string out = (path != nullptr && *path != '\0') ? std::string(path) : std::string("/");
    evhttp_uri_free(parsed);
    return out;
}

void export_zipkin_json_async(std::string endpoint, std::string body) {
    if (endpoint.empty() || body.empty()) {
        return;
    }
    zipkin_export_dispatcher().enqueue(std::move(endpoint), std::move(body));
}

}  // namespace

struct SpanScope::Impl {
    std::string endpoint;
    std::string service_name;
    std::string trace_id;
    std::string span_id;
    std::string parent_id;
    std::string name;
    std::string http_method;
    std::string http_target;
    uint64_t start_us = 0;
    int http_status = -1;  // unset; populated by SendReply()
    bool sampled = false;
};

SpanScope::SpanScope() noexcept = default;
SpanScope::SpanScope(std::unique_ptr<Impl> impl) noexcept : impl_(std::move(impl)) {}
SpanScope::~SpanScope() noexcept {
    try {
        if (!impl_) {
            return;
        }
        if (current_span() == impl_.get()) {
            current_span() = nullptr;
        }
        if (!impl_->sampled || impl_->endpoint.empty()) {
            return;
        }

        const uint64_t end_us = now_us();
        uint64_t duration_us = 0;
        if (end_us >= impl_->start_us) {
            duration_us = end_us - impl_->start_us;
        }

        Json::Value one(Json::objectValue);
        one["traceId"] = impl_->trace_id;
        one["id"] = impl_->span_id;
        if (!impl_->parent_id.empty()) {
            one["parentId"] = impl_->parent_id;
        }
        one["name"] = impl_->name;
        one["kind"] = "SERVER";
        one["timestamp"] = static_cast<Json::UInt64>(impl_->start_us);
        one["duration"] = static_cast<Json::UInt64>(duration_us);

        Json::Value localEndpoint(Json::objectValue);
        localEndpoint["serviceName"] = impl_->service_name;
        one["localEndpoint"] = localEndpoint;

        Json::Value tags(Json::objectValue);
        tags["http.method"] = impl_->http_method;
        tags["http.target"] = impl_->http_target;
        if (impl_->http_status >= 100) {
            tags["http.status_code"] = std::to_string(impl_->http_status);
        }
        tags["beacon.component"] = "analyzer";
        one["tags"] = tags;

        Json::Value arr(Json::arrayValue);
        arr.append(one);

        Json::StreamWriterBuilder builder;
        builder["indentation"] = "";
        std::string body = Json::writeString(builder, arr);
        export_zipkin_json_async(impl_->endpoint, std::move(body));
    } catch (...) { // NOSONAR
    }
}

SpanScope::SpanScope(SpanScope&& other) noexcept {
    auto* old = other.impl_.get();
    impl_ = std::move(other.impl_);
    if (current_span() == old) {
        current_span() = impl_.get();
    }
}

SpanScope& SpanScope::operator=(SpanScope&& other) noexcept {
    if (this == &other) {
        return *this;
    }
    SpanScope tmp(std::move(other));
    std::swap(impl_, tmp.impl_);
    if (current_span() == tmp.impl_.get()) {
        current_span() = impl_.get();
    }
    return *this;
}

namespace {
void initialize_from_env_once() noexcept {
    if (!env_truthy("BEACON_OTEL_ENABLED")) {
        enabled().store(false);
        return;
    }
    try {
        zipkin_endpoint() = pick_zipkin_endpoint();
        service_name() = pick_service_name();
        sample_ratio() = parse_sample_ratio();
        if (zipkin_endpoint().empty()) {
            enabled().store(false);
            return;
        }
        const CURLcode rc = curl_global_init(CURL_GLOBAL_DEFAULT);
        if (rc != CURLE_OK) {
            enabled().store(false);
            return;
        }
        enabled().store(true);
    } catch (...) { // NOSONAR
        enabled().store(false);
    }
}
}  // namespace

void InitializeFromEnv() noexcept {
    std::call_once(init_once(), initialize_from_env_once);
}

bool IsEnabled() noexcept {
    InitializeFromEnv();
    return enabled().load();
}

SpanScope StartServerSpan(struct evhttp_request* req) noexcept {
    InitializeFromEnv();
    if (!enabled().load() || req == nullptr) {
        return SpanScope{};
    }

    std::string trace_id;
    std::string parent_span_id;
    bool parent_sampled = false;

    const evkeyvalq* in_headers = evhttp_request_get_input_headers(req);
    const char* tp = in_headers ? evhttp_find_header(in_headers, "traceparent") : nullptr;
    if (tp == nullptr && in_headers != nullptr) {
        tp = evhttp_find_header(in_headers, "Traceparent");
    }
    const bool has_parent = tp != nullptr && parse_traceparent(std::string(tp), trace_id, parent_span_id, parent_sampled);

    bool sampled = false;
    if (has_parent) {
        sampled = parent_sampled;
    } else {
        sampled = sample_new_trace(sample_ratio());
    }
    if (!sampled) {
        return SpanScope{};
    }

    const std::string method = http_method_string(req);
    const std::string target = http_target_string(req);
    const std::string path = http_path_from_target(target);
    const std::string span_name = "HTTP " + method + " " + path;

    auto impl = std::make_unique<SpanScope::Impl>();
    impl->endpoint = zipkin_endpoint();
    impl->service_name = service_name();
    impl->http_method = method;
    impl->http_target = target;
    impl->name = span_name;
    impl->sampled = true;
    impl->start_us = now_us();

    if (has_parent) {
        impl->trace_id = trace_id;
        impl->parent_id = parent_span_id;
    } else {
        impl->trace_id = random_hex(16);
    }
    impl->span_id = random_hex(8);

    // Optional: echo trace context back to the caller.
    struct evkeyvalq* out_headers = evhttp_request_get_output_headers(req);
    if (out_headers != nullptr) {
        const std::string resp_tp = "00-" + impl->trace_id + "-" + impl->span_id + "-01";
        evhttp_remove_header(out_headers, "traceparent");
        evhttp_add_header(out_headers, "traceparent", resp_tp.c_str());
    }

    SpanScope scope{std::move(impl)};
    current_span() = scope.impl_.get();
    return scope;
}

void SendReply(struct evhttp_request* req,
               int http_status,
               const char* reason,
               struct evbuffer* databuf) noexcept {
    if (req == nullptr) {
        return;
    }
    if (current_span() != nullptr && current_span()->sampled) {
        current_span()->http_status = http_status;
    }
    evhttp_send_reply(req, http_status, reason, databuf);
}

#else

namespace {

std::once_flag& init_once() {
    static std::once_flag flag;
    return flag;
}

std::atomic<bool>& enabled() {
    static std::atomic<bool> value{false};
    return value;
}

std::shared_ptr<opentelemetry::sdk::trace::TracerProvider>& provider() {
    static std::shared_ptr<opentelemetry::sdk::trace::TracerProvider> value;
    return value;
}

class LibeventHeadersCarrier final : public opentelemetry::context::propagation::TextMapCarrier {
public:
    explicit LibeventHeadersCarrier(const struct evkeyvalq* headers) noexcept
        : in_headers_(headers), out_headers_(nullptr) {}

    explicit LibeventHeadersCarrier(struct evkeyvalq* headers) noexcept
        : in_headers_(headers), out_headers_(headers) {}

    opentelemetry::nostd::string_view Get(opentelemetry::nostd::string_view key) const noexcept override {
        if (in_headers_ == nullptr) {
            return {};
        }
        std::string k(key.data(), key.size());
        const char* v = evhttp_find_header(in_headers_, k.c_str());
        if (v == nullptr) {
            return {};
        }
        return opentelemetry::nostd::string_view(v);
    }

    void Set(opentelemetry::nostd::string_view key,
             opentelemetry::nostd::string_view value) noexcept override {
        if (out_headers_ == nullptr) {
            return;
        }
        std::string k(key.data(), key.size());
        std::string v(value.data(), value.size());
        // Avoid duplicate headers when handlers add their own headers later.
        evhttp_remove_header(out_headers_, k.c_str());
        evhttp_add_header(out_headers_, k.c_str(), v.c_str());
    }

private:
    const struct evkeyvalq* in_headers_;
    struct evkeyvalq* out_headers_;
};

auto request_command(const struct evhttp_request* req) {
    return evhttp_request_get_command(const_cast<struct evhttp_request*>(req)); // NOSONAR - libevent exposes a non-const request API for read-only accessors
}

const char* request_uri(const struct evhttp_request* req) {
    return evhttp_request_get_uri(const_cast<struct evhttp_request*>(req)); // NOSONAR - libevent exposes a non-const request API for read-only accessors
}

std::string http_method_string(const struct evhttp_request* req) {
    if (req == nullptr) {
        return "UNKNOWN";
    }
    const auto cmd = request_command(req);
    switch (cmd) {
        case EVHTTP_REQ_GET: return "GET";
        case EVHTTP_REQ_POST: return "POST";
        case EVHTTP_REQ_HEAD: return "HEAD";
        case EVHTTP_REQ_PUT: return "PUT";
        case EVHTTP_REQ_DELETE: return "DELETE";
        case EVHTTP_REQ_OPTIONS: return "OPTIONS";
        case EVHTTP_REQ_TRACE: return "TRACE";
        case EVHTTP_REQ_CONNECT: return "CONNECT";
        case EVHTTP_REQ_PATCH: return "PATCH";
        default: break;
    }
    return "OTHER";
}

std::string http_target_string(const struct evhttp_request* req) {
    if (req == nullptr) {
        return "/";
    }
    const char* uri = request_uri(req);
    return uri != nullptr ? std::string(uri) : std::string("/");
}

std::string http_path_from_target(const std::string& target) {
    if (target.empty()) {
        return "/";
    }
    evhttp_uri* parsed = evhttp_uri_parse(target.c_str());
    if (parsed == nullptr) {
        // Fallback: strip query fragment crudely.
        const auto qpos = target.find('?');
        if (qpos == std::string::npos) {
            return target;
        }
        return target.substr(0, qpos);
    }
    const char* path = evhttp_uri_get_path(parsed);
    std::string out = (path != nullptr && *path != '\0') ? std::string(path) : std::string("/");
    evhttp_uri_free(parsed);
    return out;
}

double parse_sample_ratio() {
    std::string v = trim_copy(get_env_string("BEACON_OTEL_SAMPLE_RATIO"));
    if (v.empty()) {
        return 1.0;
    }
    try {
        double r = std::stod(v);
        if (r < 0.0) r = 0.0;
        if (r > 1.0) r = 1.0;
        return r;
    } catch (...) {
        return 1.0;
    }
}

std::string pick_service_name() {
    std::string name = get_env_string("BEACON_OTEL_SERVICE_NAME");
    if (name.empty()) {
        name = get_env_string("OTEL_SERVICE_NAME");
    }
    if (name.empty()) {
        name = "beacon-analyzer";
    }
    return name;
}

std::string pick_otlp_traces_endpoint() {
    std::string ep = get_env_string("BEACON_OTEL_OTLP_ENDPOINT");
    if (ep.empty()) {
        ep = get_env_string("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT");
    }
    if (ep.empty()) {
        ep = get_env_string("OTEL_EXPORTER_OTLP_ENDPOINT");
    }
    return normalize_otlp_http_traces_endpoint(std::move(ep));
}

std::unique_ptr<opentelemetry::sdk::trace::Sampler> make_sampler(double ratio) {
    using opentelemetry::sdk::trace::AlwaysOffSampler;
    using opentelemetry::sdk::trace::AlwaysOnSampler;
    using opentelemetry::sdk::trace::ParentBasedSampler;
    using opentelemetry::sdk::trace::TraceIdRatioBasedSampler;

    std::shared_ptr<opentelemetry::sdk::trace::Sampler> root;
    if (ratio <= 0.0) {
        root = std::make_shared<AlwaysOffSampler>();
    } else if (ratio >= 1.0) {
        root = std::make_shared<AlwaysOnSampler>();
    } else {
        root = std::make_shared<TraceIdRatioBasedSampler>(ratio);
    }
    return std::unique_ptr<opentelemetry::sdk::trace::Sampler>(new ParentBasedSampler(root));
}

}  // namespace

struct SpanScope::Impl {
    opentelemetry::nostd::shared_ptr<opentelemetry::trace::Span> span;
    std::unique_ptr<opentelemetry::trace::Scope> scope;
};

SpanScope::SpanScope() noexcept = default;
SpanScope::SpanScope(std::unique_ptr<Impl> impl) noexcept : impl_(std::move(impl)) {}
SpanScope::~SpanScope() noexcept {
    try {
        if (!impl_) {
            return;
        }
        // Ensure the span is not left active while ending it.
        impl_->scope.reset();
        if (impl_->span) {
            impl_->span->End();
        }
    } catch (...) { // NOSONAR
    }
}

SpanScope::SpanScope(SpanScope&&) noexcept = default;
SpanScope& SpanScope::operator=(SpanScope&&) noexcept = default;

namespace {
void initialize_from_env_once() noexcept {
    if (!env_truthy("BEACON_OTEL_ENABLED")) {
        enabled().store(false);
        return;
    }

    try {
        const std::string service_name = pick_service_name();
        const std::string endpoint = pick_otlp_traces_endpoint();
        const double ratio = parse_sample_ratio();

        opentelemetry::context::propagation::GlobalTextMapPropagator::SetGlobalPropagator(
            opentelemetry::nostd::shared_ptr<opentelemetry::context::propagation::TextMapPropagator>(
                new opentelemetry::trace::propagation::HttpTraceContext()));

        opentelemetry::exporter::otlp::OtlpHttpExporterOptions exporter_opts;
        if (!endpoint.empty()) {
            exporter_opts.url = endpoint;
        }

        auto exporter = opentelemetry::exporter::otlp::OtlpHttpExporterFactory::Create(exporter_opts);

        opentelemetry::sdk::trace::BatchSpanProcessorOptions processor_opts;
        auto processor = opentelemetry::sdk::trace::BatchSpanProcessorFactory::Create(
            std::move(exporter), processor_opts);

        opentelemetry::sdk::resource::ResourceAttributes resource_attrs = {
            {"service.name", service_name},
        };
        auto resource = opentelemetry::sdk::resource::Resource::Create(resource_attrs);

        auto sampler = make_sampler(ratio);

        provider() = opentelemetry::sdk::trace::TracerProviderFactory::Create(
            std::move(processor), resource, std::move(sampler));

        opentelemetry::nostd::shared_ptr<opentelemetry::trace::TracerProvider> api_provider = provider();
        opentelemetry::sdk::trace::Provider::SetTracerProvider(api_provider);

        enabled().store(true);
    } catch (...) {
        enabled().store(false);
    }
}
}  // namespace

void InitializeFromEnv() noexcept {
    std::call_once(init_once(), initialize_from_env_once);
}

bool IsEnabled() noexcept {
    InitializeFromEnv();
    return enabled().load();
}

SpanScope StartServerSpan(struct evhttp_request* req) noexcept {
    InitializeFromEnv();
    if (!enabled().load() || req == nullptr) {
        return SpanScope{};
    }

    auto tp = opentelemetry::trace::Provider::GetTracerProvider();
    auto tracer = tp->GetTracer("beacon-analyzer");

    const std::string method = http_method_string(req);
    const std::string target = http_target_string(req);
    const std::string path = http_path_from_target(target);
    const std::string span_name = "HTTP " + method + " " + path;

    opentelemetry::context::Context parent_ctx;
    if (auto propagator = opentelemetry::context::propagation::GlobalTextMapPropagator::GetGlobalPropagator()) {
        const evkeyvalq* in_headers = evhttp_request_get_input_headers(req);
        LibeventHeadersCarrier in_carrier(in_headers);
        parent_ctx = propagator->Extract(in_carrier, parent_ctx);
    }

    opentelemetry::trace::StartSpanOptions options;
    options.kind = opentelemetry::trace::SpanKind::kServer;
    options.parent = parent_ctx;

    auto span = tracer->StartSpan(span_name, options);
    span->SetAttribute("http.method", method);
    span->SetAttribute("http.target", target);

    // Make span current for downstream helpers (SendReply uses the current span).
    auto scope = std::unique_ptr<opentelemetry::trace::Scope>(new opentelemetry::trace::Scope(span));

    // Optional: echo trace context back to the caller.
    if (auto propagator = opentelemetry::context::propagation::GlobalTextMapPropagator::GetGlobalPropagator()) {
        struct evkeyvalq* out_headers = evhttp_request_get_output_headers(req);
        if (out_headers != nullptr) {
            LibeventHeadersCarrier out_carrier(out_headers);
            opentelemetry::context::Context ctx;
            ctx = opentelemetry::trace::SetSpan(ctx, span);
            propagator->Inject(out_carrier, ctx);
        }
    }

    auto impl = std::unique_ptr<SpanScope::Impl>(new SpanScope::Impl());
    impl->span = span;
    impl->scope = std::move(scope);
    return SpanScope{std::move(impl)};
}

void SendReply(struct evhttp_request* req,
               int http_status,
               const char* reason,
               struct evbuffer* databuf) noexcept {
    if (req == nullptr) {
        return;
    }

    // Annotate the active span (if any) before sending the reply.
    if (enabled().load()) {
        auto span = opentelemetry::trace::Tracer::GetCurrentSpan();
        if (span && span->GetContext().IsValid() && span->IsRecording()) {
            span->SetAttribute("http.status_code", http_status);
            if (http_status >= 500) {
                span->SetStatus(opentelemetry::trace::StatusCode::kError);
            } else {
                span->SetStatus(opentelemetry::trace::StatusCode::kOk);
            }
        }
    }

    evhttp_send_reply(req, http_status, reason, databuf);
}

#endif  // BEACON_ENABLE_OTEL

}  // namespace beacon::otel
