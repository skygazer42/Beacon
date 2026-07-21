#include "Server.h"
#include "Otel.h"


#ifdef WIN32
#pragma comment(lib, "ws2_32.lib")
#include <WinSock2.h>
#include <WS2tcpip.h>
#endif

#include <event2/event.h>
#include <event2/http.h>
#include <event2/buffer.h>
#include <event2/http_struct.h>
#include <json/json.h>
#include <json/value.h>
#include <thread>
#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cstring>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <stdexcept>
#include <system_error>
#include <limits>
#include <memory>
#include <string>
#include <vector>
#include <onnxruntime_cxx_api.h>
#include <openvino/openvino.hpp>
#include "Control.h"
#include "Config.h"
#include "Scheduler.h"
#include "FaceDb.h"
#include "Algorithm.h"
#include "AlgorithmLoadValidation.h"
#include "AlgorithmTestInferValidation.h"
#include "DetectObjectJson.h"
#include "DecodeStride.h"
#include "FfmpegDecodeDiscard.h"
#include "ControlPerfParams.h"
#include "OverlayStyle.h"
#include "AlarmImageMode.h"
#include "Utils/Log.h"
#include "Utils/Base64.h"
#include "Utils/JsonBool.h"
#include "Utils/Common.h"

using namespace AVSAnalyzer;

constexpr int kRecvBufMaxSize = 1024 * 8;

template <void (*Handler)(struct evhttp_request* req, Scheduler* scheduler)>
static void api_cb(struct evhttp_request* req, void* arg) {  // NOSONAR - libevent callback signature
    Handler(req, static_cast<Scheduler*>(arg));
}

static void api_index(struct evhttp_request* req, Scheduler* scheduler);
static void api_health(struct evhttp_request* req, Scheduler* scheduler);
static void api_controls(struct evhttp_request* req, Scheduler* scheduler);
static void api_control(struct evhttp_request* req, Scheduler* scheduler);
static void api_control_add(struct evhttp_request* req, Scheduler* scheduler);
static void api_control_cancel(struct evhttp_request* req, Scheduler* scheduler);
static void api_algorithm_list(struct evhttp_request* req, Scheduler* scheduler);
static void api_algorithm_load(struct evhttp_request* req, Scheduler* scheduler);
static void api_algorithm_unload(struct evhttp_request* req, Scheduler* scheduler);
static void api_algorithm_test_infer(struct evhttp_request* req, Scheduler* scheduler);
static void api_face_list(struct evhttp_request* req, Scheduler* scheduler);
static void api_face_add(struct evhttp_request* req, Scheduler* scheduler);
static void api_face_delete(struct evhttp_request* req, Scheduler* scheduler);
static void api_face_search(struct evhttp_request* req, Scheduler* scheduler);
static void api_face_enable(struct evhttp_request* req, Scheduler* scheduler);
static void api_face_disable(struct evhttp_request* req, Scheduler* scheduler);
static void api_license_info(struct evhttp_request* req, Scheduler* scheduler);
static void api_resource_info(struct evhttp_request* req, Scheduler* scheduler);
static void api_resource_set_max(struct evhttp_request* req, Scheduler* scheduler);
static void api_device_info(struct evhttp_request* req, Scheduler* scheduler);
static void api_scheduler_info(struct evhttp_request* req, Scheduler* scheduler);
static void api_metrics(struct evhttp_request* req, Scheduler* scheduler);

static void parse_get(const struct evhttp_request* req, struct evkeyvalq* params);
static bool parse_post(struct evhttp_request* req, char* buff);

namespace {
    constexpr const char* kOpenApiTokenHeader = "X-Beacon-Token";
    constexpr const char* kAuthorizationHeader = "Authorization";

    const char* request_uri(const struct evhttp_request* req) {
        return evhttp_request_get_uri(const_cast<struct evhttp_request*>(req)); // NOSONAR - libevent exposes a non-const request API for read-only accessors
    }

    std::string trim_copy(std::string value) {
        auto is_ws = [](unsigned char c) { return std::isspace(c) != 0; };
        while (!value.empty() && is_ws(static_cast<unsigned char>(value.front()))) {
            value.erase(value.begin());
        }
        while (!value.empty() && is_ws(static_cast<unsigned char>(value.back()))) {
            value.pop_back();
        }
        return value;
    }

    bool try_parse_i64(const std::string& s, int64_t& out) {
        errno = 0;
        const char* begin = s.c_str();
        char* end = nullptr;
        const long long v = std::strtoll(begin, &end, 10);
        if (end == begin || end == nullptr) {
            return false;
        }
        while (*end != '\0' && std::isspace(static_cast<unsigned char>(*end)) != 0) {
            ++end;
        }
        if (*end != '\0') {
            return false;
        }
        if (errno == ERANGE) {
            return false;
        }
        out = static_cast<int64_t>(v);
        return true;
    }

    bool try_parse_i32(const std::string& s, int& out) {
        errno = 0;
        const char* begin = s.c_str();
        char* end = nullptr;
        const long v = std::strtol(begin, &end, 10);
        if (end == begin || end == nullptr) {
            return false;
        }
        while (*end != '\0' && std::isspace(static_cast<unsigned char>(*end)) != 0) {
            ++end;
        }
        if (*end != '\0') {
            return false;
        }
        if (errno == ERANGE) {
            return false;
        }
        if (v < std::numeric_limits<int>::min() || v > std::numeric_limits<int>::max()) {
            return false;
        }
        out = static_cast<int>(v);
        return true;
    }

    bool try_parse_f32(const std::string& s, float& out) {
        errno = 0;
        const char* begin = s.c_str();
        char* end = nullptr;
        const float v = std::strtof(begin, &end);
        if (end == begin || end == nullptr) {
            return false;
        }
        while (*end != '\0' && std::isspace(static_cast<unsigned char>(*end)) != 0) {
            ++end;
        }
        if (*end != '\0') {
            return false;
        }
        if (errno == ERANGE) {
            return false;
        }
        out = v;
        return true;
    }

    void send_json(struct evhttp_request* req, int http_status, int code, const std::string& msg) {
        if (req == nullptr) {
            return;
        }
        struct evkeyvalq* out_headers = evhttp_request_get_output_headers(req);
        if (out_headers) {
            evhttp_add_header(out_headers, "Content-Type", "application/json; charset=utf-8");
        }
        Json::Value result;
        result["code"] = code;
        result["msg"] = msg;
        struct evbuffer* buff = evbuffer_new();
        evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
        beacon::otel::SendReply(req, http_status, nullptr, buff);
        evbuffer_free(buff);
    }

    bool require_open_api_token(struct evhttp_request* req, Scheduler* scheduler) {
        if (scheduler == nullptr || scheduler->getConfig() == nullptr) {
            send_json(req, 500, 0, "server not ready");
            return false;
        }

        const std::string expected = scheduler->getConfig()->openApiToken;
        if (expected.empty()) {
            // default: localhost only (enforced by bind host)
            return true;
        }

        const struct evkeyvalq* headers = evhttp_request_get_input_headers(req);
        const char* got = headers ? evhttp_find_header(headers, kOpenApiTokenHeader) : nullptr;
        if (got != nullptr && expected == std::string(got)) {
            return true;
        }

        // Accept standard Bearer auth as well, to support industrial tooling (Prometheus, etc.).
        const char* auth = headers ? evhttp_find_header(headers, kAuthorizationHeader) : nullptr;
        if (auth != nullptr) {
            std::string authStr(auth);
            std::string lower = authStr;
            std::transform(lower.begin(), lower.end(), lower.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            const std::string prefix = "bearer ";
            if (lower.rfind(prefix, 0) == 0) {
                std::string token = authStr.substr(prefix.size());
                token = trim_copy(token);
                if (!token.empty() && token == expected) {
                    return true;
                }
            }
        }

        send_json(req, 401, 0, "unauthorized");
        return false;
    }

    bool read_body_limited(struct evhttp_request* req, size_t maxBytes, std::string& body, std::string& errMsg) {
        body.clear();
        errMsg.clear();
        if (req == nullptr) {
            errMsg = "bad request";
            return false;
        }

        struct evbuffer* input = evhttp_request_get_input_buffer(req);
        if (input == nullptr) {
            errMsg = "bad request";
            return false;
        }

        const size_t post_size = evbuffer_get_length(input);
        if (post_size == 0) {
            errMsg = "empty request body";
            return false;
        }
        if (post_size > maxBytes) {
            errMsg = "payload too large";
            return false;
        }
        const unsigned char* data = evbuffer_pullup(input, post_size);
        if (data == nullptr) {
            errMsg = "bad request";
            return false;
        }
        body.assign((const char*)data, post_size);
        return true;
    }

    bool parse_json_body_limited(struct evhttp_request* req, size_t maxBytes, Json::Value& root, std::string& errMsg) {
        root = Json::Value(Json::objectValue);
        errMsg.clear();

        std::string body;
        if (!read_body_limited(req, maxBytes, body, errMsg)) {
            return false;
        }

        Json::CharReaderBuilder builder;
        builder["collectComments"] = false;
        const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
        JSONCPP_STRING errs;
        if (!reader->parse(body.data(), body.data() + body.size(), &root, &errs) || !errs.empty()) {
            errMsg = "invalid json";
            return false;
        }
        if (!root.isObject()) {
            errMsg = "json must be object";
            return false;
        }
        return true;
    }

    bool normalize_base64_inplace(std::string& value, std::string& errMsg) {
        // Normalize base64: remove whitespace.
        std::string compact;
        compact.reserve(value.size());
        for (unsigned char c : value) {
            if (!std::isspace(c)) {
                compact.push_back(static_cast<char>(c));
            }
        }
        value.swap(compact);

        // Validate base64 chars early (avoid partial decode surprises).
        auto is_b64_char = [](unsigned char c) {
            return (std::isalnum(c) != 0) || c == '+' || c == '/' || c == '=';
        };
        for (unsigned char c : value) {
            if (!is_b64_char(c)) {
                errMsg = "invalid base64";
                return false;
            }
        }
        if (value.size() < 8 || (value.size() % 4) != 0) {
            errMsg = "invalid base64 length";
            return false;
        }
        return true;
    }

    int64_t read_env_i64_clamped(const char* name, int64_t defaultValue, int64_t minValue, int64_t maxValue) {
        const char* raw = std::getenv(name);
        if (!raw || !raw[0]) {
            return defaultValue;
        }
        int64_t v = 0;
        if (!try_parse_i64(std::string(raw), v)) {
            return defaultValue;
        }
        if (v < minValue) v = minValue;
        if (v > maxValue) v = maxValue;
        return v;
    }

    bool read_png_dimensions(const unsigned char* data, size_t len, int64_t& width, int64_t& height) {
        width = 0;
        height = 0;
        static constexpr unsigned char kPngSig[8] = { 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A };
        if (!data || len < 24) {
            return false;
        }
        if (std::memcmp(data, kPngSig, 8) != 0) {
            return false;
        }
        // IHDR chunk starts at offset 8: [len(4)][type(4)] then data.
        if (!(data[12] == 'I' && data[13] == 'H' && data[14] == 'D' && data[15] == 'R')) {
            return false;
        }
        const uint32_t w = (uint32_t(data[16]) << 24) | (uint32_t(data[17]) << 16) | (uint32_t(data[18]) << 8) | uint32_t(data[19]);
        const uint32_t h = (uint32_t(data[20]) << 24) | (uint32_t(data[21]) << 16) | (uint32_t(data[22]) << 8) | uint32_t(data[23]);
        width = static_cast<int64_t>(w);
        height = static_cast<int64_t>(h);
        return width > 0 && height > 0;
    }

    bool read_jpeg_dimensions(const unsigned char* data, size_t len, int64_t& width, int64_t& height) {
        width = 0;
        height = 0;
        if (!data || len < 4) {
            return false;
        }
        if (!(data[0] == 0xFF && data[1] == 0xD8)) { // SOI
            return false;
        }

        auto is_sof = [](unsigned char marker) {
            switch (marker) {
            case 0xC0: case 0xC1: case 0xC2: case 0xC3:
            case 0xC5: case 0xC6: case 0xC7:
            case 0xC9: case 0xCA: case 0xCB:
            case 0xCD: case 0xCE: case 0xCF:
                return true;
            default:
                return false;
            }
        };

        size_t i = 2;
        while (i + 1 < len) {
            // Seek to marker 0xFF
            if (data[i] != 0xFF) {
                ++i;
                continue;
            }
            // Skip fill bytes 0xFF
            while (i < len && data[i] == 0xFF) {
                ++i;
            }
            if (i >= len) {
                return false;
            }
            const unsigned char marker = data[i++];

            // Standalone markers without a length field.
            if (marker == 0xD8 /*SOI*/ || marker == 0xD9 /*EOI*/ || marker == 0x01 /*TEM*/ || (marker >= 0xD0 && marker <= 0xD7) /*RST*/) {
                if (marker == 0xD9) {
                    return false;
                }
                continue;
            }

            if (i + 1 >= len) {
                return false;
            }
            const auto segLen = static_cast<uint16_t>(
                (static_cast<uint16_t>(data[i]) << 8) | static_cast<uint16_t>(data[i + 1]));
            i += 2;
            if (segLen < 2) {
                return false;
            }
            const size_t segDataLen = static_cast<size_t>(segLen) - 2;
            if (i + segDataLen > len) {
                return false;
            }

            if (is_sof(marker)) {
                if (segDataLen < 6) {
                    return false;
                }
                const auto h = static_cast<uint16_t>(
                    (static_cast<uint16_t>(data[i + 1]) << 8) | static_cast<uint16_t>(data[i + 2]));
                const auto w = static_cast<uint16_t>(
                    (static_cast<uint16_t>(data[i + 3]) << 8) | static_cast<uint16_t>(data[i + 4]));
                width = static_cast<int64_t>(w);
                height = static_cast<int64_t>(h);
                return width > 0 && height > 0;
            }

            i += segDataLen;
        }

        return false;
    }

    bool get_encoded_image_dimensions(const unsigned char* data, size_t len, int64_t& width, int64_t& height) {
        // Only accept common encodings we can preflight safely before imdecode().
        if (read_png_dimensions(data, len, width, height)) {
            return true;
        }
        if (read_jpeg_dimensions(data, len, width, height)) {
            return true;
        }
        return false;
    }

    bool decode_base64_image_to_mat(std::string imageBase64, cv::Mat& image, std::string& errMsg) {
        errMsg.clear();
        image = cv::Mat();
        if (imageBase64.empty()) {
            errMsg = "image_base64 is required";
            return false;
        }
        if (!normalize_base64_inplace(imageBase64, errMsg)) {
            return false;
        }

        constexpr int64_t kDefaultMaxEncodedBytes = 5LL * 1024 * 1024;
        constexpr int64_t kDefaultMaxDim = 8192;
        constexpr int64_t kDefaultMaxPixels = 20LL * 1000 * 1000; // 20MP
        const int64_t maxEncodedBytes =
            read_env_i64_clamped("BEACON_HTTP_MAX_IMAGE_BYTES", kDefaultMaxEncodedBytes, 64 * 1024, 64LL * 1024 * 1024);
        const int64_t maxDim =
            read_env_i64_clamped("BEACON_HTTP_MAX_IMAGE_DIM", kDefaultMaxDim, 256, 100000);
        const int64_t maxPixels =
            read_env_i64_clamped("BEACON_HTTP_MAX_IMAGE_PIXELS", kDefaultMaxPixels, 256LL * 256, 500LL * 1000 * 1000);

        // Reject obviously huge payloads before decode (base64 expands by 4/3).
        {
            size_t padding = 0;
            if (!imageBase64.empty() && imageBase64.back() == '=') {
                padding++;
                if (imageBase64.size() >= 2 && imageBase64[imageBase64.size() - 2] == '=') {
                    padding++;
                }
            }
            const size_t est = (imageBase64.size() / 4) * 3 - padding;
            if (est > static_cast<size_t>(maxEncodedBytes)) {
                errMsg = "image too large";
                return false;
            }
        }

        Base64 base64;
        const std::string decoded = base64.decode(imageBase64);
        if (decoded.empty()) {
            errMsg = "invalid base64 decode";
            return false;
        }
        if (decoded.size() > static_cast<size_t>(maxEncodedBytes)) {
            errMsg = "image too large";
            return false;
        }

        int64_t width = 0;
        int64_t height = 0;
        const auto* encodedPtr = reinterpret_cast<const unsigned char*>(decoded.data());
        const size_t encodedLen = decoded.size();
        if (!get_encoded_image_dimensions(encodedPtr, encodedLen, width, height)) {
            errMsg = "unsupported image format (jpeg/png only)";
            return false;
        }
        if (width <= 0 || height <= 0 || width > maxDim || height > maxDim) {
            errMsg = "image too large";
            return false;
        }
        if (width > 0 && height > 0) {
            const int64_t pixels = width * height;
            if (pixels <= 0 || pixels > maxPixels) {
                errMsg = "image too large";
                return false;
            }
        }

        if (encodedLen > static_cast<size_t>(std::numeric_limits<int>::max())) {
            errMsg = "image too large";
            return false;
        }
        std::vector<unsigned char> encoded(encodedLen);
        std::memcpy(encoded.data(), encodedPtr, encodedLen);
        cv::Mat encodedMat(1, static_cast<int>(encoded.size()), CV_8UC1, encoded.data());
        image = cv::imdecode(encodedMat, cv::IMREAD_COLOR);
        if (image.empty()) {
            errMsg = "invalid image";
            return false;
        }
	        if (image.cols <= 0 || image.rows <= 0 || image.cols > maxDim || image.rows > maxDim) {
	            image = cv::Mat();
	            errMsg = "image too large";
	            return false;
	        }
	        if (const int64_t pixels = static_cast<int64_t>(image.cols) * static_cast<int64_t>(image.rows);
	            pixels <= 0 || pixels > maxPixels) {
	            image = cv::Mat();
	            errMsg = "image too large";
	            return false;
	        }
	        return true;
	    }

    bool parse_embedding_from_json(const Json::Value& root, std::vector<float>& out, std::string& errMsg) {
        out.clear();
        errMsg.clear();

        // Prefer explicit float array.
        const Json::Value arr = root.get("embedding", Json::Value());
        if (arr.isArray()) {
            out.reserve(arr.size());
            for (const auto& v : arr) {
                if (v.isNumeric()) {
                    out.push_back(v.asFloat());
                }
                else if (v.isString()) {
                    const std::string raw = v.asString();
                    float parsed = 0.0f;
                    if (try_parse_f32(raw, parsed)) {
                        out.push_back(parsed);
                    }
                    else {
                        out.push_back(0.0f);
                    }
                }
                else {
                    out.push_back(0.0f);
                }
            }
            if (out.empty()) {
                errMsg = "embedding is empty";
                return false;
            }
            return true;
        }

        // Fallback: float32 buffer encoded as base64.
        std::string b64 = root.get("embedding_base64", "").asString();
        if (b64.empty()) {
            return false;
        }
        if (!normalize_base64_inplace(b64, errMsg)) {
            return false;
        }
        Base64 base64;
        const std::string decoded = base64.decode(b64);
        if (decoded.empty()) {
            errMsg = "invalid base64 decode";
            return false;
        }
        if ((decoded.size() % sizeof(float)) != 0) {
            errMsg = "invalid embedding bytes";
            return false;
        }
        const size_t n = decoded.size() / sizeof(float);
        if (n == 0 || n > 8192) {
            errMsg = "invalid embedding length";
            return false;
        }
        out.resize(n);
        std::memcpy(out.data(), decoded.data(), decoded.size());
        return true;
    }

    bool extract_embedding_from_image(Scheduler* scheduler, const std::string& featureAlgorithmCode, const cv::Mat& image, std::vector<float>& out, std::string& errMsg) {
        out.clear();
        errMsg.clear();
        if (scheduler == nullptr) {
            errMsg = "server not ready";
            return false;
        }
        const Config* config = scheduler->getConfig();
        const std::string resolvedFeatureCode = config
            ? config->resolveFaceFeatureAlgorithmCode(featureAlgorithmCode)
            : trim_copy(featureAlgorithmCode);
        if (resolvedFeatureCode.empty()) {
            errMsg = "featureAlgorithmCode is required";
            return false;
        }
        struct AlgorithmPin {
            Scheduler* scheduler;
            const std::string& code;
            Algorithm* algorithm = nullptr;
            AlgorithmPin(Scheduler* s, const std::string& c)
                : scheduler(s), code(c) {
                if (scheduler) {
                    algorithm = scheduler->acquireAlgorithm(code);
                }
            }
            AlgorithmPin(const AlgorithmPin&) = delete;
            AlgorithmPin& operator=(const AlgorithmPin&) = delete;
            AlgorithmPin(AlgorithmPin&&) = delete;
            AlgorithmPin& operator=(AlgorithmPin&&) = delete;
            ~AlgorithmPin() {
                if (scheduler && algorithm) {
                    scheduler->releaseAlgorithm(code);
                }
            }
        };

        AlgorithmPin pin(scheduler, resolvedFeatureCode);
        Algorithm* algo = pin.algorithm;
        if (!algo) {
            errMsg = "feature algorithm not loaded";
            return false;
        }
        std::vector<cv::Mat> images;
        images.push_back(image);
        std::vector<std::vector<float>> embeddings;
        if (!algo->extractEmbeddings(images, embeddings, errMsg)) {
            if (errMsg.empty()) {
                errMsg = "extractEmbeddings failed";
            }
            return false;
        }
        if (embeddings.empty() || embeddings[0].empty()) {
            errMsg = "empty embedding";
            return false;
        }
        out = std::move(embeddings[0]);
        return true;
    }
}


Server::Server() {
#ifdef WIN32
    WSADATA wdSockMsg;
    int s = WSAStartup(MAKEWORD(2, 2), &wdSockMsg);

    if (0 != s)
    {
        switch (s)
        {
        case WSASYSNOTREADY: printf("重启电脑，或者检查网络库");   break;
        case WSAVERNOTSUPPORTED: printf("请更新网络库");  break;
        case WSAEINPROGRESS: printf("请重新启动");  break;
        case WSAEPROCLIM:  printf("请关闭不必要的软件，以确保有足够的网络资源"); break;
        }
    }

    if (2 != HIBYTE(wdSockMsg.wVersion) || 2 != LOBYTE(wdSockMsg.wVersion))
    {
        LOGE("网络库版本错误");
        return;
    }
#endif

}
Server::~Server() {
    stop();
    LOGE("");
#ifdef WIN32
    WSACleanup();
#endif

}

void Server::stop() {
    mStopRequested.store(true);
    if (mThread.joinable()) {
        mThread.join();
    }
    mStarted.store(false);
}

namespace {
    struct ServerShutdownTimerCtx {
        std::atomic<bool>* stopRequested = nullptr;
        Scheduler* scheduler = nullptr;
        struct event_base* base = nullptr;
    };

    void server_shutdown_timer_cb(evutil_socket_t, short, void* arg) {  // NOSONAR - libevent callback signature
        auto* ctx = static_cast<ServerShutdownTimerCtx*>(arg);
        if (!ctx || !ctx->base) {
            return;
        }
        const bool stop = (ctx->stopRequested && ctx->stopRequested->load())
            || (ctx->scheduler && !ctx->scheduler->getState());
        if (stop) {
            event_base_loopbreak(ctx->base);
        }
    }
}  // namespace

void Server::run(Scheduler* scheduler) {
    beacon::otel::InitializeFromEnv();

    if (!scheduler || !scheduler->getConfig()) {
        LOGE("Server::start missing scheduler/config");
        if (scheduler) {
            scheduler->setState(false);
        }
        mStarted.store(false);
        return;
    }

    std::string token = scheduler->getConfig()->openApiToken;
	    const char* bind_host = token.empty() ? "127.0.0.1" : "0.0.0.0";
	    const int port = scheduler->getConfig()->analyzerPort;
	    LOGI("启动分析器服务：http://%s:%d", bind_host, port);
	    if (port <= 0 || port > static_cast<int>(std::numeric_limits<std::uint16_t>::max())) {
	        LOGE("invalid analyzer port: %d", port);
	        scheduler->setState(false);
	        mStarted.store(false);
	        return;
	    }

    event_config* evt_config = event_config_new();
    if (!evt_config) {
        LOGE("event_config_new failed");
        scheduler->setState(false);
        mStarted.store(false);
        return;
    }
    struct event_base* base = event_base_new_with_config(evt_config);
    if (!base) {
        LOGE("event_base_new_with_config failed");
        event_config_free(evt_config);
        scheduler->setState(false);
        mStarted.store(false);
        return;
    }
    struct evhttp* http = evhttp_new(base);
    if (!http) {
        LOGE("evhttp_new failed");
        event_base_free(base);
        event_config_free(evt_config);
        scheduler->setState(false);
        mStarted.store(false);
        return;
    }
    evhttp_set_default_content_type(http, "text/html; charset=utf-8");

    evhttp_set_timeout(http, 30);
    evhttp_set_cb(http, "/", api_cb<api_index>, scheduler);
    evhttp_set_cb(http, "/api/health", api_cb<api_health>, scheduler);
    evhttp_set_cb(http, "/api/controls", api_cb<api_controls>, scheduler);
    evhttp_set_cb(http, "/api/control", api_cb<api_control>, scheduler);
    evhttp_set_cb(http, "/api/control/add", api_cb<api_control_add>, scheduler);
    evhttp_set_cb(http, "/api/control/cancel", api_cb<api_control_cancel>, scheduler);

    evhttp_set_cb(http, "/api/algorithm/list", api_cb<api_algorithm_list>, scheduler);
    evhttp_set_cb(http, "/api/algorithm/load", api_cb<api_algorithm_load>, scheduler);
    evhttp_set_cb(http, "/api/algorithm/unload", api_cb<api_algorithm_unload>, scheduler);
    evhttp_set_cb(http, "/api/algorithm/testInfer", api_cb<api_algorithm_test_infer>, scheduler);

    evhttp_set_cb(http, "/api/face/list", api_cb<api_face_list>, scheduler);
    evhttp_set_cb(http, "/api/face/add", api_cb<api_face_add>, scheduler);
    evhttp_set_cb(http, "/api/face/delete", api_cb<api_face_delete>, scheduler);
    evhttp_set_cb(http, "/api/face/search", api_cb<api_face_search>, scheduler);
    evhttp_set_cb(http, "/api/face/enable", api_cb<api_face_enable>, scheduler);
    evhttp_set_cb(http, "/api/face/disable", api_cb<api_face_disable>, scheduler);

    evhttp_set_cb(http, "/api/license/info", api_cb<api_license_info>, scheduler);
    evhttp_set_cb(http, "/api/resource/info", api_cb<api_resource_info>, scheduler);
    evhttp_set_cb(http, "/api/resource/setmax", api_cb<api_resource_set_max>, scheduler);
    evhttp_set_cb(http, "/api/device/info", api_cb<api_device_info>, scheduler);
    evhttp_set_cb(http, "/api/scheduler/info", api_cb<api_scheduler_info>, scheduler);
    evhttp_set_cb(http, "/metrics", api_cb<api_metrics>, scheduler);
    evhttp_set_cb(http, "/api/metrics", api_cb<api_metrics>, scheduler);

	    const auto bind_port = static_cast<std::uint16_t>(port);
	    const int bind_rc = evhttp_bind_socket(http, bind_host, bind_port);
    if (bind_rc != 0) {
        LOGE("evhttp_bind_socket failed: host=%s port=%d", bind_host, port);
        evhttp_free(http);
        event_base_free(base);
        event_config_free(evt_config);
        scheduler->setState(false);
        mStarted.store(false);
        return;
    }

    ServerShutdownTimerCtx shutdownCtx;
    shutdownCtx.stopRequested = &mStopRequested;
    shutdownCtx.scheduler = scheduler;
    shutdownCtx.base = base;

    struct event* shutdownEvent = event_new(base, -1, EV_PERSIST, server_shutdown_timer_cb, &shutdownCtx);
    if (!shutdownEvent) {
        LOGE("event_new(shutdown timer) failed");
        evhttp_free(http);
        event_base_free(base);
        event_config_free(evt_config);
        scheduler->setState(false);
        mStarted.store(false);
        return;
    }
    struct timeval interval;
    interval.tv_sec = 0;
    interval.tv_usec = 200 * 1000;
    event_add(shutdownEvent, &interval);

    event_base_dispatch(base);

    event_free(shutdownEvent);
    evhttp_free(http);
    event_base_free(base);
    event_config_free(evt_config);

    scheduler->setState(false);
    mStarted.store(false);
}

void Server::start(Scheduler* scheduler) {
    if (!scheduler) {
        LOGE("Server::start scheduler is null");
        return;
    }

    // Allow restart only after a previous thread has been joined.
    if (mThread.joinable()) {
        mThread.join();
    }

    bool expected = false;
    if (!mStarted.compare_exchange_strong(expected, true)) {
        LOGE("Server::start already started");
        return;
    }
    mStopRequested.store(false);
    scheduler->setState(true);

    try {
        mThread = std::thread(&Server::run, this, scheduler);
    }
    catch (const std::system_error& e) {
        LOGE("Server::start thread create failed: %s", e.what());
        scheduler->setState(false);
        mStarted.store(false);
    }

}

static void api_index(struct evhttp_request* req, Scheduler* /*scheduler*/) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
   
    Json::Value result_urls;
    result_urls["/api"] = "this api version 1.0";
    result_urls["/api/health"] = "check health";
    result_urls["/api/controls"] = "get all control being analyzed";
    result_urls["/api/control"] = "get control being analyzed";
    result_urls["/api/control/add"] = "add control";
    result_urls["/api/control/cancel"] = "cancel control";
    result_urls["/api/algorithm/list"] = "list loaded algorithms";
    result_urls["/api/algorithm/load"] = "load algorithm model/plugin";
    result_urls["/api/algorithm/unload"] = "unload algorithm";
    result_urls["/api/algorithm/testInfer"] = "one-shot inference test (debug)";
    result_urls["/api/face/list"] = "list faces (face db)";
    result_urls["/api/face/add"] = "add/update face (face db)";
    result_urls["/api/face/delete"] = "delete face (face db)";
    result_urls["/api/face/search"] = "search nearest face (face db)";
    result_urls["/api/face/enable"] = "enable face search";
    result_urls["/api/face/disable"] = "disable face search";
    result_urls["/api/largeModelCalcu"] = "largeModelCalcu";
    result_urls["/api/license/info"] = "local license info";
    result_urls["/api/device/info"] = "inference device/providers info";
    result_urls["/api/resource/info"] = "resource info";
    result_urls["/api/resource/setmax"] = "set max controls";
    result_urls["/api/scheduler/info"] = "scheduler stats";
    result_urls["/metrics"] = "Prometheus metrics (text)";
    result_urls["/api/metrics"] = "Prometheus metrics (text)";
    
    
    Json::Value result;
    result["urls"] = result_urls;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);

}
static void api_health(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    int result_code = 0;
    std::string result_msg = "error";

    // 健康检测
    result_code = 1000;
    result_msg = "current service health";


    Json::Value result;
    result["msg"] = result_msg;
    result["code"] = result_code;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);

}
static void api_controls(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);

    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;

    Json::Value result_data;
    Json::Value result_data_item;
    int result_code = 0;
    std::string result_msg = "error";
    Json::Value result;

    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

        std::vector<Control*> controls;
        int len = scheduler->apiControls(controls);

        if (len > 0) {
            int64_t curTimestamp = getCurTimestamp();
            int64_t startTimestamp = 0;
            for (size_t i = 0; i < controls.size(); i++)
            {
                startTimestamp = controls[i]->startTimestamp;

                result_data_item["code"] = controls[i]->code.data();
                result_data_item["streamUrl"] = controls[i]->streamUrl.data();

                result_data_item["pushStream"] = controls[i]->pushStream;
                result_data_item["pushStreamUrl"] = controls[i]->pushStreamUrl.data();
                result_data_item["algorithmCode"] = controls[i]->algorithmCode.data();
                result_data_item["forceInferenceDevice"] = controls[i]->forceInferenceDevice;
                result_data_item["requestedInferenceDevice"] = controls[i]->requestedInferenceDevice;
                result_data_item["effectiveInferenceDevice"] = controls[i]->effectiveInferenceDevice;
                result_data_item["inferenceDeviceDegraded"] = controls[i]->inferenceDeviceDegraded;
                result_data_item["inferenceDeviceReason"] = controls[i]->inferenceDeviceReason;
                result_data_item["objectCode"] = controls[i]->objectCode.data();
                result_data_item["recognitionRegion"] = controls[i]->recognitionRegion.data();

                result_data_item["checkFps"] = controls[i]->checkFps;
                result_data_item["startTimestamp"] = startTimestamp;
                result_data_item["liveMilliseconds"] = curTimestamp - startTimestamp;


                result_data.append(result_data_item);
            }
            result["data"] = result_data;
            result_code = 1000;
            result_msg = "success";
        }
        else {
            result_msg = "the number of control exector is empty";
        }


    }
    else {
        result_msg = "invalid request parameter";
    }
    result["msg"] = result_msg;
    result["code"] = result_code;

    //LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());


    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);

}
static void api_control(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);

    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;

    Json::Value result_control;
    int result_code = 0;
    std::string result_msg = "error";
    

    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

	        const Control* control = nullptr;
        if (root["code"].isString()) {
            std::string code = root["code"].asCString();
            control = scheduler->apiControl(code);
        }

        if (control) {
            result_control["code"] = control->code;
            result_control["checkFps"] = control->checkFps;
            result_control["forceInferenceDevice"] = control->forceInferenceDevice;
            result_control["requestedInferenceDevice"] = control->requestedInferenceDevice;
            result_control["effectiveInferenceDevice"] = control->effectiveInferenceDevice;
            result_control["inferenceDeviceDegraded"] = control->inferenceDeviceDegraded;
            result_control["inferenceDeviceReason"] = control->inferenceDeviceReason;

            result_code = 1000;
            result_msg = "success";

        }
        else {
            result_msg = "the control does not exist";
        }
    }
    else {
        result_msg = "invalid request parameter";
    }

    Json::Value result;
    result["control"] = result_control;
    result["msg"] = result_msg;
    result["code"] = result_code;

    LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());


    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);

}
static void api_control_add(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);

    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;

    int result_code = 0;
    std::string result_msg = "error";
    Json::Value result_device(Json::objectValue);


    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

        Control control;

        control.code = root["code"].asCString();

        control.streamCode = root["streamCode"].asString();
        control.streamApp = root["streamApp"].asString();
        control.streamName = root["streamName"].asString();
        control.streamUrl = root["streamUrl"].asString();
        control.pushStream = root["pushStream"].asBool();
        control.pushStreamUrl = root["pushStreamUrl"].asString();

        control.algorithmCode = root["algorithmCode"].asString();
        if (root["forceInferenceDevice"].isBool()) {
            control.forceInferenceDevice = root["forceInferenceDevice"].asBool();
        }
        else if (root["forceInferenceDevice"].isNumeric()) {
            control.forceInferenceDevice = (root["forceInferenceDevice"].asInt() != 0);
        }
        else if (root["forceInferenceDevice"].isString()) {
            std::string v = root["forceInferenceDevice"].asString();
            std::transform(v.begin(), v.end(), v.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (v == "1" || v == "true" || v == "yes" || v == "on") {
                control.forceInferenceDevice = true;
            }
            else if (v == "0" || v == "false" || v == "no" || v == "off") {
                control.forceInferenceDevice = false;
            }
        }
	        control.api_url = root["api_url"].asString();
	        control.object_str = root["object_str"].asString();
	        control.objects_v1 = split(control.object_str, ",");
	        control.objects_v1_len = static_cast<int>(control.objects_v1.size());
	        control.objectCode = root["objectCode"].asString();
	        control.recognitionRegion = root["recognitionRegion"].asString();

        // ========== 区域绘制类型/越线检测配置 ==========
        if (root["drawType"].isString()) {
            control.drawType = root["drawType"].asString();
        }
        if (root["lineCoordinates"].isString()) {
            control.lineCoordinates = root["lineCoordinates"].asString();
        }
        if (root["lineViolationDirection"].isString()) {
            control.lineViolationDirection = root["lineViolationDirection"].asString();
        }
        if (root["enableTracking"].isBool()) {
            control.enableTracking = root["enableTracking"].asBool();
        }
        else if (root["enableTracking"].isNumeric()) {
            control.enableTracking = (root["enableTracking"].asInt() != 0);
        }
        else if (root["enableTracking"].isString()) {
            std::string v = root["enableTracking"].asString();
            std::transform(v.begin(), v.end(), v.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (v == "1" || v == "true" || v == "yes" || v == "on") {
                control.enableTracking = true;
            }
            else if (v == "0" || v == "false" || v == "no" || v == "off") {
                control.enableTracking = false;
            }
        }

        // ========== 布控级硬件编解码配额开关（v4.20.1） ==========
        control.enableHardwareDecode = parseJsonBool(root, "enableHardwareDecode", false);
        control.enableHardwareEncode = parseJsonBool(root, "enableHardwareEncode", false);
        // =============================================
        // =============================================

        if (root["classThresh"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["classThresh"].asString(), parsed)) {
                control.classThresh = parsed;
            }
        }
        else if (root["classThresh"].isNumeric()) {
            control.classThresh = root["classThresh"].asFloat();
        }
        if (root["overlapThresh"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["overlapThresh"].asString(), parsed)) {
                control.overlapThresh = parsed;
            }
        }
        else if (root["overlapThresh"].isNumeric()) {
            control.overlapThresh = root["overlapThresh"].asFloat();
        }
        if (root["alarmVideoType"].isString()) {
            control.alarmVideoType = root["alarmVideoType"].asString();
        }
        if (root["alarmImageCount"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["alarmImageCount"].asString(), parsed)) {
                control.alarmImageCount = parsed;
            }
        }
        else if (root["alarmImageCount"].isNumeric()) {
            control.alarmImageCount = root["alarmImageCount"].asInt();
        }
        if (root["alarmCoverPosition"].isString()) {
            std::string pos = root["alarmCoverPosition"].asString();
            std::transform(pos.begin(), pos.end(), pos.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (pos == "front" || pos == "middle" || pos == "back" || pos == "custom") {
                control.alarmCoverPosition = pos;
            }
            else {
                control.alarmCoverPosition = "front";
            }
        }
        if (root["alarmCoverCustomIndex"].isNumeric()) {
            control.alarmCoverCustomIndex = std::max(0, root["alarmCoverCustomIndex"].asInt());
        }
        else if (root["alarmCoverCustomIndex"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["alarmCoverCustomIndex"].asString(), parsed)) {
                control.alarmCoverCustomIndex = std::max(0, parsed);
            }
        }
        if (root["alarmImageDrawMode"].isString()) {
            control.alarmImageDrawMode = normalizeAlarmImageDrawMode(root["alarmImageDrawMode"].asString());
        }
        control.forceFrameAlarm = parseJsonBool(root, "forceFrameAlarm", false);

        // ========== 解析算法模型配置参数 ==========
        if (root["modelPrecision"].isString()) {
            control.modelPrecision = root["modelPrecision"].asString();
        }
        if (root["inputWidth"].isNumeric()) {
            control.inputWidth = root["inputWidth"].asInt();
        }
        else if (root["inputWidth"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["inputWidth"].asString(), parsed)) {
                control.inputWidth = parsed;
            }
        }
        if (root["inputHeight"].isNumeric()) {
            control.inputHeight = root["inputHeight"].asInt();
        }
        else if (root["inputHeight"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["inputHeight"].asString(), parsed)) {
                control.inputHeight = parsed;
            }
        }
        if (root["modelConcurrency"].isNumeric()) {
            control.modelConcurrency = std::max(1, root["modelConcurrency"].asInt());
        }
        else if (root["modelConcurrency"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["modelConcurrency"].asString(), parsed)) {
                control.modelConcurrency = std::max(1, parsed);
            }
        }
        if (root["nmsThresh"].isNumeric()) {
            control.nmsThresh = root["nmsThresh"].asFloat();
        }
        else if (root["nmsThresh"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["nmsThresh"].asString(), parsed)) {
                control.nmsThresh = parsed;
            }
        }
        if (root["confThresh"].isNumeric()) {
            control.confThresh = root["confThresh"].asFloat();
        }
        else if (root["confThresh"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["confThresh"].asString(), parsed)) {
                control.confThresh = parsed;
            }
        }
        // ==============================================

        // ========== 解析基础算法检测模式配置 ==========
        if (root["basicAlgoDetectMode"].isNumeric()) {
            control.basicAlgoDetectMode = root["basicAlgoDetectMode"].asInt();
        }
        else if (root["basicAlgoDetectMode"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["basicAlgoDetectMode"].asString(), parsed)) {
                control.basicAlgoDetectMode = parsed;
            }
        }
	        if (root["basicAlgoDetectInterval"].isNumeric()) {
	            control.basicAlgoDetectInterval = std::max(1, root["basicAlgoDetectInterval"].asInt());
	        }
		        else if (root["basicAlgoDetectInterval"].isString()) {
                    int parsed = 0;
                    if (try_parse_i32(root["basicAlgoDetectInterval"].asString(), parsed)) {
                        control.basicAlgoDetectInterval = std::max(1, parsed);
                    }
		        }
	        applyDecodeStrideFromJson(root, control);
	        applyPullFrequencyFromJson(root, control);
	        applyPsEffectMinFpsFromJson(root, control);
	        applyFfmpegSkipLoopFilterFromJson(root, control);
	        applyFfmpegSkipIdctFromJson(root, control);
	        // ==============================================

	        // ========== 解析推流视频质量配置 ==========
	        if (root["pushVideoCodec"].isString()) {
	            control.pushVideoCodec = root["pushVideoCodec"].asString();
        }
        if (root["pushVideoBitrate"].isNumeric()) {
            control.pushVideoBitrate = root["pushVideoBitrate"].asInt();
        }
        else if (root["pushVideoBitrate"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["pushVideoBitrate"].asString(), parsed)) {
                control.pushVideoBitrate = parsed;
            }
        }
        if (root["pushVideoFps"].isNumeric()) {
            control.pushVideoFps = root["pushVideoFps"].asInt();
        }
        else if (root["pushVideoFps"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["pushVideoFps"].asString(), parsed)) {
                control.pushVideoFps = parsed;
            }
        }
        if (root["pushVideoWidth"].isNumeric()) {
            control.pushVideoWidth = root["pushVideoWidth"].asInt();
        }
        else if (root["pushVideoWidth"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["pushVideoWidth"].asString(), parsed)) {
                control.pushVideoWidth = parsed;
            }
        }
        if (root["pushVideoHeight"].isNumeric()) {
            control.pushVideoHeight = root["pushVideoHeight"].asInt();
        }
        else if (root["pushVideoHeight"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["pushVideoHeight"].asString(), parsed)) {
                control.pushVideoHeight = parsed;
            }
        }
        if (root["pushVideoGop"].isNumeric()) {
            control.pushVideoGop = root["pushVideoGop"].asInt();
        }
        else if (root["pushVideoGop"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["pushVideoGop"].asString(), parsed)) {
                control.pushVideoGop = parsed;
            }
        }
        // ==============================================

        // ========== 解析 OSD 配置 ==========
        if (root["osdEnabled"].isBool()) {
            control.osdEnabled = root["osdEnabled"].asBool();
        }
        else if (root["osdEnabled"].isNumeric()) {
            control.osdEnabled = (root["osdEnabled"].asInt() != 0);
        }
        if (root["osdText"].isString()) {
            control.osdText = root["osdText"].asString();
        }
        if (root["osdPosition"].isString()) {
            control.osdPosition = root["osdPosition"].asString();
        }
        if (root["osdX"].isNumeric()) {
            control.osdX = root["osdX"].asInt();
        }
        else if (root["osdX"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdX"].asString(), parsed)) {
                control.osdX = parsed;
            }
        }
        if (root["osdY"].isNumeric()) {
            control.osdY = root["osdY"].asInt();
        }
        else if (root["osdY"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdY"].asString(), parsed)) {
                control.osdY = parsed;
            }
        }
        if (root["osdFontSize"].isNumeric()) {
            control.osdFontSize = root["osdFontSize"].asInt();
        }
        else if (root["osdFontSize"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdFontSize"].asString(), parsed)) {
                control.osdFontSize = parsed;
            }
        }
        if (root["osdFontColor"].isString()) {
            control.osdFontColor = root["osdFontColor"].asString();
        }
        if (root["osdBgEnabled"].isBool()) {
            control.osdBgEnabled = root["osdBgEnabled"].asBool();
        }
        else if (root["osdBgEnabled"].isNumeric()) {
            control.osdBgEnabled = (root["osdBgEnabled"].asInt() != 0);
        }

        // --- OSD 贴图参数 ---
        if (root["osdImagePath"].isString()) {
            control.osdImagePath = root["osdImagePath"].asString();
        }
        if (root["osdImageX"].isNumeric()) {
            control.osdImageX = root["osdImageX"].asInt();
        }
        else if (root["osdImageX"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdImageX"].asString(), parsed)) {
                control.osdImageX = parsed;
            }
        }
        if (root["osdImageY"].isNumeric()) {
            control.osdImageY = root["osdImageY"].asInt();
        }
        else if (root["osdImageY"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdImageY"].asString(), parsed)) {
                control.osdImageY = parsed;
            }
        }
        if (root["osdImageScale"].isNumeric()) {
            control.osdImageScale = root["osdImageScale"].asFloat();
        }
        else if (root["osdImageScale"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["osdImageScale"].asString(), parsed)) {
                control.osdImageScale = parsed;
            }
        }
        if (control.osdImageScale <= 0.0f) {
            control.osdImageScale = 1.0f;
        }
        if (root["osdImageAlpha"].isNumeric()) {
            control.osdImageAlpha = root["osdImageAlpha"].asFloat();
        }
        else if (root["osdImageAlpha"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["osdImageAlpha"].asString(), parsed)) {
                control.osdImageAlpha = parsed;
            }
        }
        if (control.osdImageAlpha < 0.0f) control.osdImageAlpha = 0.0f;
        if (control.osdImageAlpha > 1.0f) control.osdImageAlpha = 1.0f;

        // Algo/FPS overlay 坐标（画面左侧算法名与FPS）
        if (root["osdAlgoX"].isNumeric()) {
            control.osdAlgoX = root["osdAlgoX"].asInt();
        }
        else if (root["osdAlgoX"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdAlgoX"].asString(), parsed)) {
                control.osdAlgoX = parsed;
            }
        }
        if (root["osdAlgoY"].isNumeric()) {
            control.osdAlgoY = root["osdAlgoY"].asInt();
        }
        else if (root["osdAlgoY"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdAlgoY"].asString(), parsed)) {
                control.osdAlgoY = parsed;
            }
        }
        if (root["osdFpsX"].isNumeric()) {
            control.osdFpsX = root["osdFpsX"].asInt();
        }
        else if (root["osdFpsX"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdFpsX"].asString(), parsed)) {
                control.osdFpsX = parsed;
            }
        }
        if (root["osdFpsY"].isNumeric()) {
            control.osdFpsY = root["osdFpsY"].asInt();
        }
        else if (root["osdFpsY"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["osdFpsY"].asString(), parsed)) {
                control.osdFpsY = parsed;
            }
        }
        // ==============================================

        // ========== 解析算法流绘制样式（v4.627） ==========
        applyOverlayStyleFromJson(root, control);
        // ==============================================

        // ========== 解析算法流程模式配置 ==========
        if (root["usePipelineMode"].isBool()) {
            control.usePipelineMode = root["usePipelineMode"].asBool();
        }
        else if (root["usePipelineMode"].isNumeric()) {
            control.usePipelineMode = (root["usePipelineMode"].asInt() != 0);
        }
        if (root["pipelineMode"].isNumeric()) {
            control.algorithmPipelineMode = root["pipelineMode"].asInt();
        }
        else if (root["pipelineMode"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["pipelineMode"].asString(), parsed)) {
                control.algorithmPipelineMode = parsed;
            }
        }
        if (root["trackingAlgorithmCode"].isString()) {
            control.trackingAlgorithmCode = root["trackingAlgorithmCode"].asString();
        }
        if (root["classificationAlgorithmCode"].isString()) {
            control.classificationAlgorithmCode = root["classificationAlgorithmCode"].asString();
        }
        if (root["featureAlgorithmCode"].isString()) {
            control.featureAlgorithmCode = root["featureAlgorithmCode"].asString();
        }
        if (root["behaviorAlgorithmCode"].isString()) {
            control.behaviorAlgorithmCode = root["behaviorAlgorithmCode"].asString();
        }
        if (root["behaviorApiUrl"].isString()) {
            control.behaviorApiUrl = root["behaviorApiUrl"].asString();
        }
        if (root["trackingConfig"].isString()) {
            control.trackingConfig = root["trackingConfig"].asString();
        }
        if (root["classificationConfig"].isString()) {
            control.classificationConfig = root["classificationConfig"].asString();
        }
        if (root["featureConfig"].isString()) {
            control.featureConfig = root["featureConfig"].asString();
        }
        if (root["behaviorConfig"].isString()) {
            control.behaviorConfig = root["behaviorConfig"].asString();
        }
        // ==============================================

        // ========== 解析层级算法（二级检测）配置 ==========
        if (root["enableHierarchicalAlgorithm"].isBool()) {
            control.enableHierarchicalAlgorithm = root["enableHierarchicalAlgorithm"].asBool();
        }
        else if (root["enableHierarchicalAlgorithm"].isNumeric()) {
            control.enableHierarchicalAlgorithm = (root["enableHierarchicalAlgorithm"].asInt() != 0);
        }
        else if (root["enableHierarchicalAlgorithm"].isString()) {
            const std::string v = root["enableHierarchicalAlgorithm"].asString();
            if (v == "1" || v == "true" || v == "True" || v == "TRUE") {
                control.enableHierarchicalAlgorithm = true;
            }
            else if (v == "0" || v == "false" || v == "False" || v == "FALSE") {
                control.enableHierarchicalAlgorithm = false;
            }
        }

        if (root["secondaryAlgorithmCode"].isString()) {
            control.secondaryAlgorithmCode = root["secondaryAlgorithmCode"].asString();
        }
        if (root["secondaryApiUrl"].isString()) {
            control.secondaryApi_url = root["secondaryApiUrl"].asString();
        }
        else if (root["secondaryApi_url"].isString()) {
            // backward compatible (snake-case)
            control.secondaryApi_url = root["secondaryApi_url"].asString();
        }

        if (root["secondaryConfThresh"].isNumeric()) {
            control.secondaryConfThresh = root["secondaryConfThresh"].asFloat();
        }
        else if (root["secondaryConfThresh"].isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(root["secondaryConfThresh"].asString(), parsed)) {
                control.secondaryConfThresh = parsed;
            }
        }
        if (control.secondaryConfThresh <= 0.0f) {
            control.secondaryConfThresh = 0.25f;
        }
        // ==============================================

        // Client-provided, unit: seconds. Guard against bad input (non-numeric/overflow).
        if (root["minInterval"].isNumeric()) {
            control.minInterval = std::max(0, root["minInterval"].asInt()) * 1000;
        }
        else if (root["minInterval"].isString()) {
            int parsed = 0;
            if (try_parse_i32(root["minInterval"].asString(), parsed)) {
                control.minInterval = static_cast<int64_t>(std::max(0, parsed)) * 1000;
            }
        }
        //强制设置报警时间最大不能超过3分钟=180000毫秒
        if (control.minInterval > 180000) {
            control.minInterval = 180000;
        }


        if (control.validateAdd(result_msg)) {
            scheduler->apiControlAdd(&control, result_code, result_msg);
            if (result_code == 1000) {
                if (const Control* running = scheduler->apiControl(control.code)) {
                    result_device["forceInferenceDevice"] = running->forceInferenceDevice;
                    result_device["requestedInferenceDevice"] = running->requestedInferenceDevice;
                    result_device["effectiveInferenceDevice"] = running->effectiveInferenceDevice;
                    result_device["inferenceDeviceDegraded"] = running->inferenceDeviceDegraded;
                    result_device["inferenceDeviceReason"] = running->inferenceDeviceReason;
                }
            }
        }
    }
    else {
        result_msg = "invalid request parameter";
    }

    Json::Value result;
    result["msg"] = result_msg;
    result["code"] = result_code;
    if (!result_device.empty()) {
        result["device"] = result_device;
    }

    LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);


}

static void api_control_cancel(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);

    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());

    Json::Value root;
    JSONCPP_STRING errs;

    int result_code = 0;
    std::string result_msg = "error";

    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

        Control control;

        if (root["code"].isString()) {
            control.code = root["code"].asCString();
        }
        if (control.validateCancel(result_msg)) {
            scheduler->apiControlCancel(&control, result_code, result_msg);
        }

    }
    else {
        result_msg = "invalid request parameter";
    }

    Json::Value result;
    result["msg"] = result_msg;
    result["code"] = result_code;

    LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);


}

// ============== 动态模型管理 API ==============

static void api_algorithm_list(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    std::vector<std::string> algorithms = scheduler->listAlgorithms();

    Json::Value result_data;
    for (const auto& algo : algorithms) {
        result_data.append(algo);
    }

    // Backward compatible: keep `algorithms` as a string array, and also provide `items`
    // with operational details (refCount/controls/etc.) for Admin UI and industrial ops.
    Json::Value items(Json::arrayValue);
    try {
        std::scoped_lock lock(scheduler->mAlgorithmMtx);
        for (const auto& pair : scheduler->mAlgorithmMap) {
            const std::string& code = pair.first;
            const AlgorithmInfo& info = pair.second;

            Json::Value item;
            item["code"] = code;
            item["modelPath"] = info.modelPath;
            item["refCount"] = info.refCount.load();
            item["controlCount"] = (Json::UInt64)info.controlCodes.size();
            item["isBuiltin"] = info.isBuiltin;
            item["isLoaded"] = info.isLoaded;
            item["requestedDevice"] = info.requestedDevice;
            item["effectiveDevice"] = info.effectiveDevice;
            item["deviceDegraded"] = info.deviceDegraded;
            item["deviceDegradeReason"] = info.deviceDegradeReason;
            item["lastUnusedTimestampMs"] = (Json::Int64)info.lastUnusedTimestampMs;

            // Preview a few control codes for debugging (avoid huge payloads at scale).
            Json::Value preview(Json::arrayValue);
            int n = 0;
            for (const auto& c : info.controlCodes) {
                preview.append(c);
                if (++n >= 10) {
                    break;
                }
            }
            item["controlCodesPreview"] = preview;

            items.append(item);
        }
    }
    catch (const std::exception& ex) { // NOSONAR
        LOGW("api_algorithm_list: build items failed: %s", ex.what());
    }

    Json::Value result;
    result["algorithms"] = result_data;
    result["count"] = (int)algorithms.size();
    result["items"] = items;
    result["timestamp"] = (Json::Int64)getCurTimestamp();
    result["msg"] = "success";
    result["code"] = 1000;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_algorithm_load(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;

    int result_code = 0;
    std::string result_msg = "error";
    InferenceDeviceDecision loadedDeviceDecision;
    bool hasLoadedDeviceDecision = false;

	    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

	        std::string code = root["code"].asString();
	        std::string modelPath = root["modelPath"].asString();
            std::string algorithmSubtypeRaw;
            if (root["algorithmSubtype"].isString()) {
                algorithmSubtypeRaw = root["algorithmSubtype"].asString();
            }
            AlgorithmSubtype subtype = parse_algorithm_subtype(algorithmSubtypeRaw);
            std::string algorithmSubtype = normalize_algorithm_subtype(algorithmSubtypeRaw);
            if (algorithmSubtype.empty()) {
                algorithmSubtype = "detection";
            }

        // 解析类别名称数组
        std::vector<std::string> classNames;
        if (root["classNames"].isArray()) {
            for (const auto& name : root["classNames"]) {
                classNames.push_back(name.asString());
            }
        }
	        std::string device = "CPU";
	        if (root["device"].isString()) {
	            device = root["device"].asString();
	        }
	        const bool forceInferenceDevice = parseJsonBool(root, "forceInferenceDevice", false);

	        int concurrency = 0;
	        if (root["modelConcurrency"].isNumeric()) {
	            concurrency = std::max(1, root["modelConcurrency"].asInt());
	        }
		        else if (root["modelConcurrency"].isString()) {
                    int parsed = 0;
                    if (try_parse_i32(root["modelConcurrency"].asString(), parsed)) {
                        concurrency = std::max(1, parsed);
                    }
                    else {
                        concurrency = 0;
                    }
		        }

            std::string validateErr;
            if (!validate_algorithm_load_request(code, modelPath, classNames, subtype, validateErr)) {
                result_msg = validateErr;
            }
            else {
                if (concurrency <= 0) {
                    const Config* config = scheduler->getConfig();
                    concurrency = config ? std::max(1, config->modelConcurrency) : 1;
                }
                const bool ok = scheduler->loadAlgorithm(
                    code, modelPath, classNames, device, algorithmSubtype, result_msg, concurrency,
                    forceInferenceDevice);
                if (ok) {
                    result_code = 1000;
                    result_msg = "Algorithm loaded successfully";
                    hasLoadedDeviceDecision = scheduler->getAlgorithmDeviceDecision(
                        code, loadedDeviceDecision);
                }
            }
	    }
    else {
        result_msg = "invalid request parameter";
    }

    Json::Value result;
    result["msg"] = result_msg;
    result["code"] = result_code;
    if (hasLoadedDeviceDecision) {
        result["requestedDevice"] = loadedDeviceDecision.requestedDevice;
        result["effectiveDevice"] = loadedDeviceDecision.effectiveDevice;
        result["deviceDegraded"] = loadedDeviceDecision.degraded;
        result["deviceDegradeReason"] = loadedDeviceDecision.reason;
    }

    LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_algorithm_unload(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;

    int result_code = 0;
    std::string result_msg = "error";

    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

        std::string code = root["code"].asString();

        if (code.empty()) {
            result_msg = "code is required";
        }
        else {
            if (scheduler->unloadAlgorithm(code, result_msg)) {
                result_code = 1000;
                result_msg = "Algorithm unloaded successfully";
            }
        }
    }
    else {
        result_msg = "invalid request parameter";
    }

    Json::Value result;
    result["msg"] = result_msg;
    result["code"] = result_code;

    LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_algorithm_test_infer(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    // This endpoint accepts base64 images and can be much larger than typical control APIs.
    // Avoid stack buffers; use a bounded dynamic buffer.
    constexpr size_t kMaxBodyBytes = 5 * 1024 * 1024;  // 5MB

    std::string body;
    {
        struct evbuffer* input = evhttp_request_get_input_buffer(req);
        if (input == nullptr) {
            send_json(req, 400, 0, "bad request");
            return;
        }
        const size_t post_size = evbuffer_get_length(input);
        if (post_size == 0) {
            send_json(req, 400, 0, "empty request body");
            return;
        }
        if (post_size > kMaxBodyBytes) {
            send_json(req, 413, 0, "payload too large");
            return;
        }
	        const unsigned char* data = evbuffer_pullup(input, post_size);
        if (data == nullptr) {
            send_json(req, 400, 0, "bad request");
            return;
        }
        body.assign((const char*)data, post_size);
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;
    if (!reader->parse(body.data(), body.data() + body.size(), &root, &errs) || !errs.empty()) {
        send_json(req, 400, 0, "invalid json");
        return;
    }

    const std::string code = trim_copy(root.get("code", "").asString());
    std::string imageBase64 = root.get("image_base64", "").asString();
    if (code.empty()) {
        send_json(req, 400, 0, "code is required");
        return;
    }
    if (imageBase64.empty()) {
        send_json(req, 400, 0, "image_base64 is required");
        return;
    }

    {
        std::string validateErr;
        if (!validate_algorithm_test_infer_request(root, validateErr)) {
            send_json(req, 400, 0, validateErr);
            return;
        }
    }

    auto readFloat = [&](const char* key, float defaultValue) -> float {
        const Json::Value v = root.get(key, Json::Value());
        if (v.isNumeric()) {
            return v.asFloat();
        }
        if (v.isString()) {
            float parsed = 0.0f;
            if (try_parse_f32(v.asString(), parsed)) {
                return parsed;
            }
            return defaultValue;
        }
        return defaultValue;
    };

    const float confThresh = readFloat("confThresh", 0.25f);
    const float nmsThresh = readFloat("nmsThresh", 0.45f);

    cv::Mat image;
    {
        std::string imgErr;
        if (!decode_base64_image_to_mat(imageBase64, image, imgErr)) {
            send_json(req, 400, 0, imgErr.empty() ? "invalid image_base64" : imgErr);
            return;
        }
    }

    struct AlgorithmPin {
        Scheduler* scheduler;
        std::string code;
        Algorithm* algorithm = nullptr;
        AlgorithmPin(Scheduler* s, std::string c)
            : scheduler(s), code(std::move(c)) {
            if (scheduler) {
                algorithm = scheduler->acquireAlgorithm(code);
            }
        }
        AlgorithmPin(const AlgorithmPin&) = delete;
        AlgorithmPin& operator=(const AlgorithmPin&) = delete;
        AlgorithmPin(AlgorithmPin&&) = delete;
        AlgorithmPin& operator=(AlgorithmPin&&) = delete;
        ~AlgorithmPin() {
            if (scheduler && algorithm) {
                scheduler->releaseAlgorithm(code);
            }
        }
    };
    AlgorithmPin pin(scheduler, code);
    if (!pin.algorithm) {
        send_json(req, 400, 0, "algorithm not loaded");
        return;
    }
    Algorithm* algorithm = pin.algorithm;

    const int64_t t1 = getCurTime();
    std::vector<DetectObject> detects;
    const bool ok = algorithm->objectDetect(image, detects, confThresh, nmsThresh);
    const int64_t t2 = getCurTime();
    if (!ok) {
        send_json(req, 500, 0, "infer failed");
        return;
    }

    Json::Value outDetects(Json::arrayValue);
    for (const auto& d : detects) {
        outDetects.append(detectObjectToJson(d));
    }

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["latencyMs"] = (Json::Int64)std::max<int64_t>(0, t2 - t1);
    result["count"] = (int)detects.size();
    result["detects"] = outDetects;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

// ============== Face DB API ==============

static void api_face_list(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

	    const FaceDb* db = scheduler ? scheduler->getFaceDb() : nullptr;
    if (!db) {
        send_json(req, 500, 0, "face db not ready");
        return;
    }

    const auto items = db->listAllMeta();
    Json::Value outItems(Json::arrayValue);
    outItems.resize(0);
    for (const auto& e : items) {
        Json::Value item;
        item["id"] = e.id;
        item["name"] = e.name;
        item["enabled"] = e.enabled;
        item["createdAtMs"] = (Json::Int64)e.createdAtMs;
        outItems.append(item);
    }

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["count"] = (int)items.size();
    result["dim"] = db->embeddingDim();
    result["searchEnabled"] = scheduler->isFaceSearchEnabled();
    result["items"] = outItems;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_face_add(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

	    FaceDb* db = scheduler ? scheduler->getFaceDb() : nullptr;
    if (!db) {
        send_json(req, 500, 0, "face db not ready");
        return;
    }

    Json::Value root;
    std::string parseErr;
    if (!parse_json_body_limited(req, 6 * 1024 * 1024, root, parseErr)) {
        send_json(req, 400, 0, parseErr);
        return;
    }

    const std::string id = trim_copy(root.get("id", "").asString());
    if (id.empty()) {
        send_json(req, 400, 0, "id is required");
        return;
    }

    std::vector<float> embedding;
    std::string embErr;
    const bool gotEmbedding = parse_embedding_from_json(root, embedding, embErr);
    if (!gotEmbedding) {
        const std::string imageBase64 = root.get("image_base64", "").asString();
        std::string featureCode = root.get("featureAlgorithmCode", "").asString();
        if (featureCode.empty()) {
            featureCode = root.get("feature_algorithm_code", "").asString();
        }
        cv::Mat image;
        if (!decode_base64_image_to_mat(imageBase64, image, embErr)) {
            send_json(req, 400, 0, embErr.empty() ? "invalid image_base64" : embErr);
            return;
        }
        if (!extract_embedding_from_image(scheduler, featureCode, image, embedding, embErr)) {
            send_json(req, 400, 0, embErr.empty() ? "extractEmbeddings failed" : embErr);
            return;
        }
    }

    FaceItem item;
    item.id = id;
    item.name = root.get("name", "").asString();
    item.enabled = parseJsonBool(root, "enabled", true);
    item.embedding = std::move(embedding);

    std::string err;
    if (!db->upsert(item, err)) {
        send_json(req, 400, 0, err.empty() ? "upsert failed" : err);
        return;
    }
    if (!db->persistToDisk(err)) {
        send_json(req, 500, 0, err.empty() ? "persist failed" : err);
        return;
    }

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["count"] = (int)db->count();
    result["dim"] = db->embeddingDim();
    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_face_delete(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    FaceDb* db = scheduler ? scheduler->getFaceDb() : nullptr;
    if (!db) {
        send_json(req, 500, 0, "face db not ready");
        return;
    }

    Json::Value root;
    std::string parseErr;
    if (!parse_json_body_limited(req, 64 * 1024, root, parseErr)) {
        send_json(req, 400, 0, parseErr);
        return;
    }

    const std::string id = trim_copy(root.get("id", "").asString());
    if (id.empty()) {
        send_json(req, 400, 0, "id is required");
        return;
    }

    std::string err;
    if (!db->remove(id, err)) {
        send_json(req, 404, 0, err.empty() ? "not found" : err);
        return;
    }
    if (!db->persistToDisk(err)) {
        send_json(req, 500, 0, err.empty() ? "persist failed" : err);
        return;
    }

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["count"] = (int)db->count();
    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_face_search(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    if (!scheduler->isFaceSearchEnabled()) {
        send_json(req, 403, 0, "face search disabled");
        return;
    }

    const FaceDb* db = scheduler ? scheduler->getFaceDb() : nullptr;
    if (!db) {
        send_json(req, 500, 0, "face db not ready");
        return;
    }

    Json::Value root;
    std::string parseErr;
    if (!parse_json_body_limited(req, 6 * 1024 * 1024, root, parseErr)) {
        send_json(req, 400, 0, parseErr);
        return;
    }

    float minScore = 0.5f;
    if (root["minScore"].isNumeric()) {
        minScore = root["minScore"].asFloat();
    }
    else if (root["minScore"].isString()) {
        float parsed = 0.0f;
        if (try_parse_f32(root["minScore"].asString(), parsed)) {
            minScore = parsed;
        }
    }
    if (!std::isfinite(minScore)) {
        minScore = 0.5f;
    }
    if (minScore < -1.0f) minScore = -1.0f;
    if (minScore > 1.0f) minScore = 1.0f;

    std::vector<float> embedding;
    std::string embErr;
    const bool gotEmbedding = parse_embedding_from_json(root, embedding, embErr);
    if (!gotEmbedding) {
        const std::string imageBase64 = root.get("image_base64", "").asString();
        std::string featureCode = root.get("featureAlgorithmCode", "").asString();
        if (featureCode.empty()) {
            featureCode = root.get("feature_algorithm_code", "").asString();
        }
        cv::Mat image;
        if (!decode_base64_image_to_mat(imageBase64, image, embErr)) {
            send_json(req, 400, 0, embErr.empty() ? "invalid image_base64" : embErr);
            return;
        }
        if (!extract_embedding_from_image(scheduler, featureCode, image, embedding, embErr)) {
            send_json(req, 400, 0, embErr.empty() ? "extractEmbeddings failed" : embErr);
            return;
        }
    }

    FaceMatch match;
    std::string err;
    if (!db->searchNearest(embedding, match, err)) {
        send_json(req, 404, 0, err.empty() ? "not found" : err);
        return;
    }

    const bool found = match.score >= minScore;
    Json::Value result;
    result["code"] = found ? 1000 : 1001;
    result["msg"] = found ? "success" : "not found";
    result["found"] = found;
    result["minScore"] = minScore;
    result["bestScore"] = match.score;
    result["distance"] = match.distance;
    if (found) {
        Json::Value m;
        m["id"] = match.id;
        m["name"] = match.name;
        m["score"] = match.score;
        m["distance"] = match.distance;
        result["match"] = m;
    }

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_face_enable(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    scheduler->setFaceSearchEnabled(true);

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["searchEnabled"] = true;
    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_face_disable(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    scheduler->setFaceSearchEnabled(false);

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["searchEnabled"] = false;
    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_license_info(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    const LocalLicenseInfo info = scheduler ? scheduler->getLocalLicenseInfo() : LocalLicenseInfo{};

    Json::Value data;
    data["ok"] = info.ok;
    data["type"] = info.type;
    data["machine_code"] = info.machineCode;
    data["machine_code_v1"] = info.machineCodeV1;
    data["machine_code_v2"] = info.machineCodeV2;
    data["extra"] = Json::Value(Json::objectValue);

    Json::Value result;
    result["code"] = 1000;
    result["msg"] = "success";
    result["data"] = data;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

// ============== 资源监控 API ==============

static void api_resource_info(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    ResourceInfo info = scheduler->getResourceInfo();

    Json::Value result;
    result["cpuUsage"] = info.cpuUsage;
    result["memoryUsage"] = info.memoryUsage;
    result["maxControls"] = info.maxControls;
    result["maxControlsUpperBound"] = info.maxControlsUpperBound;
    result["maxPendingControls"] = info.maxPendingControls;
    result["currentControls"] = info.currentControls;
    result["detectStride"] = info.detectStride;
    result["lastCheckTime"] = (Json::Int64)info.lastCheckTime;
    result["maxHardwareDecodeChannels"] = info.maxHardwareDecodeChannels;
    result["maxHardwareEncodeChannels"] = info.maxHardwareEncodeChannels;
    result["currentDecodeChannels"] = info.currentDecodeChannels;
    result["currentEncodeChannels"] = info.currentEncodeChannels;
    result["maxPullPktQueueSize"] = info.maxPullPktQueueSize;
    result["maxPushFrameQueueSize"] = info.maxPushFrameQueueSize;
    result["pullPktQueueHighWorkers"] = info.pullPktQueueHighWorkers;
    result["pullPktQueueSevereWorkers"] = info.pullPktQueueSevereWorkers;
    result["pushFrameQueueHighWorkers"] = info.pushFrameQueueHighWorkers;
    result["pushFrameQueueSevereWorkers"] = info.pushFrameQueueSevereWorkers;
    result["droppedPullPacketsDelta"] = (Json::UInt64)info.droppedPullPacketsDelta;
    result["droppedDecodePacketsDelta"] = (Json::UInt64)info.droppedDecodePacketsDelta;
    result["droppedPushFramesDelta"] = (Json::UInt64)info.droppedPushFramesDelta;
    result["droppedAlarmFramesDelta"] = (Json::UInt64)info.droppedAlarmFramesDelta;
    result["dropWindowMs"] = (Json::Int64)info.dropWindowMs;
    result["droppedPullPacketsPerSecond"] = info.droppedPullPacketsPerSecond;
    result["droppedDecodePacketsPerSecond"] = info.droppedDecodePacketsPerSecond;
    result["droppedPushFramesPerSecond"] = info.droppedPushFramesPerSecond;
    result["droppedAlarmFramesPerSecond"] = info.droppedAlarmFramesPerSecond;
    result["msg"] = "success";
    result["code"] = 1000;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_resource_set_max(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    char buf[kRecvBufMaxSize + 1];
    if (!parse_post(req, buf)) {
        return;
    }

    Json::CharReaderBuilder builder;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    Json::Value root;
    JSONCPP_STRING errs;

    int result_code = 0;
    std::string result_msg = "error";

    if (reader->parse(buf, buf + std::strlen(buf), &root, &errs) && errs.empty()) {

        if (root["maxControls"].isInt()) {
            int maxControls = root["maxControls"].asInt();
            if (maxControls > 0 && maxControls <= 100) {
                scheduler->setMaxControls(maxControls);
                result_code = 1000;
                result_msg = "MaxControls set to " + std::to_string(maxControls);
            }
            else {
                result_msg = "maxControls must be between 1 and 100";
            }
        }
        else {
            result_msg = "maxControls (int) is required";
        }
    }
    else {
        result_msg = "invalid request parameter";
    }

    Json::Value result;
    result["msg"] = result_msg;
    result["code"] = result_code;

    LOGI("\n \t request:%s \n \t response:%s", root.toStyledString().data(), result.toStyledString().data());

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_device_info(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    Json::Value openvino_devices;
    Json::Value onnx_providers;
    std::string msg = "success";
    int code = 1000;

    try {
        ov::Core core;
        auto devices = core.get_available_devices();
        for (const auto& device : devices) {
            openvino_devices.append(device);
        }
    }
    catch (const ov::Exception& ex) {
        msg = std::string("OpenVINO device query failed: ") + ex.what();
        code = 0;
    }

    try {
        std::vector<std::string> providers = Ort::GetAvailableProviders();
        for (const auto& provider : providers) {
            onnx_providers.append(provider);
        }
    }
    catch (const Ort::Exception& ex) {
        if (code == 1000) {
            msg = std::string("ONNX Runtime provider query failed: ") + ex.what();
            code = 0;
        }
    }

    Json::Value result;
    result["code"] = code;
    result["msg"] = msg;
    result["openvinoDevices"] = openvino_devices;
    result["onnxProviders"] = onnx_providers;
    result["deviceSuffixes"] = Json::arrayValue;
    result["deviceSuffixes"].append("cpu");
    result["deviceSuffixes"].append("gpu");
    result["deviceSuffixes"].append("trt");
    result["deviceSuffixes"].append("auto");
    result["deviceSuffixes"].append("npu");

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_scheduler_info(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }
    SchedulerStatsSnapshot snapshot = scheduler->getSchedulerStatsSnapshot();

    Json::Value stats;
    stats["controlAddRequests"] = (Json::UInt64)snapshot.controlAddRequests;
    stats["controlAddSuccess"] = (Json::UInt64)snapshot.controlAddSuccess;
    stats["controlAddFailure"] = (Json::UInt64)snapshot.controlAddFailure;
    stats["controlCancelRequests"] = (Json::UInt64)snapshot.controlCancelRequests;
    stats["controlCancelSuccess"] = (Json::UInt64)snapshot.controlCancelSuccess;
    stats["controlCancelFailure"] = (Json::UInt64)snapshot.controlCancelFailure;
    stats["controlAddTotalMs"] = (Json::UInt64)snapshot.controlAddTotalMs;
    stats["controlAddMaxMs"] = (Json::UInt64)snapshot.controlAddMaxMs;
    stats["controlAddLastMs"] = (Json::UInt64)snapshot.controlAddLastMs;
    stats["controlCancelTotalMs"] = (Json::UInt64)snapshot.controlCancelTotalMs;
    stats["controlCancelMaxMs"] = (Json::UInt64)snapshot.controlCancelMaxMs;
    stats["controlCancelLastMs"] = (Json::UInt64)snapshot.controlCancelLastMs;
    stats["workerDeleteQueued"] = (Json::UInt64)snapshot.workerDeleteQueued;
    stats["workerDeleteProcessed"] = (Json::UInt64)snapshot.workerDeleteProcessed;
    stats["alarmQueued"] = (Json::UInt64)snapshot.alarmQueued;
    stats["alarmDropped"] = (Json::UInt64)snapshot.alarmDropped;
    stats["alarmProcessed"] = (Json::UInt64)snapshot.alarmProcessed;
    stats["algorithmLoadSuccess"] = (Json::UInt64)snapshot.algorithmLoadSuccess;
    stats["algorithmLoadFailure"] = (Json::UInt64)snapshot.algorithmLoadFailure;
    stats["algorithmUnloadSuccess"] = (Json::UInt64)snapshot.algorithmUnloadSuccess;
    stats["algorithmUnloadFailure"] = (Json::UInt64)snapshot.algorithmUnloadFailure;
    stats["pullReadErrors"] = (Json::UInt64)snapshot.pullReadErrors;
    stats["pullReconnectAttempts"] = (Json::UInt64)snapshot.pullReconnectAttempts;
    stats["pullReconnectSuccess"] = (Json::UInt64)snapshot.pullReconnectSuccess;
    stats["pushWriteErrors"] = (Json::UInt64)snapshot.pushWriteErrors;
    stats["pushReconnectAttempts"] = (Json::UInt64)snapshot.pushReconnectAttempts;
    stats["pushReconnectSuccess"] = (Json::UInt64)snapshot.pushReconnectSuccess;
    stats["droppedPullPackets"] = (Json::UInt64)snapshot.droppedPullPackets;
    stats["droppedDecodePackets"] = (Json::UInt64)snapshot.droppedDecodePackets;
    stats["droppedPushFrames"] = (Json::UInt64)snapshot.droppedPushFrames;
    stats["droppedAlarmFrames"] = (Json::UInt64)snapshot.droppedAlarmFrames;
    stats["lastUpdateTimestamp"] = (Json::UInt64)snapshot.lastUpdateTimestamp;
    stats["detectStride"] = snapshot.detectStride;
    stats["currentControls"] = snapshot.currentControls;
    stats["deleteQueueSize"] = (Json::UInt64)snapshot.deleteQueueSize;
    stats["alarmQueueSize"] = (Json::UInt64)snapshot.alarmQueueSize;
    {
        ResourceInfo info = scheduler->getResourceInfo();
        stats["maxPullPktQueueSize"] = info.maxPullPktQueueSize;
        stats["maxPushFrameQueueSize"] = info.maxPushFrameQueueSize;
        stats["pullPktQueueHighWorkers"] = info.pullPktQueueHighWorkers;
        stats["pullPktQueueSevereWorkers"] = info.pullPktQueueSevereWorkers;
        stats["pushFrameQueueHighWorkers"] = info.pushFrameQueueHighWorkers;
        stats["pushFrameQueueSevereWorkers"] = info.pushFrameQueueSevereWorkers;
        stats["dropWindowMs"] = (Json::Int64)info.dropWindowMs;
        stats["droppedPullPacketsDelta"] = (Json::UInt64)info.droppedPullPacketsDelta;
        stats["droppedDecodePacketsDelta"] = (Json::UInt64)info.droppedDecodePacketsDelta;
        stats["droppedPushFramesDelta"] = (Json::UInt64)info.droppedPushFramesDelta;
        stats["droppedAlarmFramesDelta"] = (Json::UInt64)info.droppedAlarmFramesDelta;
        stats["droppedPullPacketsPerSecond"] = info.droppedPullPacketsPerSecond;
        stats["droppedDecodePacketsPerSecond"] = info.droppedDecodePacketsPerSecond;
        stats["droppedPushFramesPerSecond"] = info.droppedPushFramesPerSecond;
        stats["droppedAlarmFramesPerSecond"] = info.droppedAlarmFramesPerSecond;
    }

    Json::Value result;
    result["stats"] = stats;
    result["msg"] = "success";
    result["code"] = 1000;

    struct evbuffer* buff = evbuffer_new();
    evbuffer_add_printf(buff, "%s", result.toStyledString().c_str());
    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void api_metrics(struct evhttp_request* req, Scheduler* scheduler) {
    [[maybe_unused]] auto otel_span = beacon::otel::StartServerSpan(req);
    if (!require_open_api_token(req, scheduler)) {
        return;
    }

    SchedulerStatsSnapshot snapshot = scheduler->getSchedulerStatsSnapshot();
    ResourceInfo resource = scheduler->getResourceInfo();

    struct evkeyvalq* out_headers = evhttp_request_get_output_headers(req);
    if (out_headers) {
        evhttp_add_header(out_headers, "Content-Type", "text/plain; version=0.0.4; charset=utf-8");
    }

    struct evbuffer* buff = evbuffer_new();
    if (!buff) {
        return;
    }

    auto add_u64 = [&](const char* name, uint64_t value) {
        evbuffer_add_printf(buff, "%s %llu\n", name, (unsigned long long)value);
    };
    auto add_i64 = [&](const char* name, int64_t value) {
        evbuffer_add_printf(buff, "%s %lld\n", name, (long long)value);
    };
    auto add_f64 = [&](const char* name, double value) {
        evbuffer_add_printf(buff, "%s %.6f\n", name, value);
    };

    // Control add/cancel
    add_u64("beacon_analyzer_control_add_requests_total", snapshot.controlAddRequests);
    add_u64("beacon_analyzer_control_add_success_total", snapshot.controlAddSuccess);
    add_u64("beacon_analyzer_control_add_failure_total", snapshot.controlAddFailure);
    add_u64("beacon_analyzer_control_cancel_requests_total", snapshot.controlCancelRequests);
    add_u64("beacon_analyzer_control_cancel_success_total", snapshot.controlCancelSuccess);
    add_u64("beacon_analyzer_control_cancel_failure_total", snapshot.controlCancelFailure);
    add_u64("beacon_analyzer_control_add_total_ms_total", snapshot.controlAddTotalMs);
    add_u64("beacon_analyzer_control_add_max_ms", snapshot.controlAddMaxMs);
    add_u64("beacon_analyzer_control_add_last_ms", snapshot.controlAddLastMs);
    add_u64("beacon_analyzer_control_cancel_total_ms_total", snapshot.controlCancelTotalMs);
    add_u64("beacon_analyzer_control_cancel_max_ms", snapshot.controlCancelMaxMs);
    add_u64("beacon_analyzer_control_cancel_last_ms", snapshot.controlCancelLastMs);

    // Alarm
    add_u64("beacon_analyzer_alarm_queued_total", snapshot.alarmQueued);
    add_u64("beacon_analyzer_alarm_dropped_total", snapshot.alarmDropped);
    add_u64("beacon_analyzer_alarm_processed_total", snapshot.alarmProcessed);

    // Algorithms
    add_u64("beacon_analyzer_algorithm_load_success_total", snapshot.algorithmLoadSuccess);
    add_u64("beacon_analyzer_algorithm_load_failure_total", snapshot.algorithmLoadFailure);
    add_u64("beacon_analyzer_algorithm_unload_success_total", snapshot.algorithmUnloadSuccess);
    add_u64("beacon_analyzer_algorithm_unload_failure_total", snapshot.algorithmUnloadFailure);

    // External API inference (Control.api_url)
    add_u64("beacon_analyzer_api_infer_allowed_total", snapshot.apiInferAllowed);
    add_u64("beacon_analyzer_api_infer_skipped_min_interval_total", snapshot.apiInferSkippedMinInterval);
    add_u64("beacon_analyzer_api_infer_skipped_circuit_open_total", snapshot.apiInferSkippedCircuitOpen);
    add_u64("beacon_analyzer_api_infer_success_total", snapshot.apiInferSuccess);
    add_u64("beacon_analyzer_api_infer_failure_total", snapshot.apiInferFailure);
    add_u64("beacon_analyzer_api_infer_retried_total", snapshot.apiInferRetried);
    add_u64("beacon_analyzer_api_infer_circuit_opened_total", snapshot.apiInferCircuitOpened);
    add_u64("beacon_analyzer_api_infer_latency_ms_total", snapshot.apiInferLatencyTotalMs);
    add_u64("beacon_analyzer_api_infer_latency_ms_max", snapshot.apiInferLatencyMaxMs);
    add_u64("beacon_analyzer_api_infer_latency_ms_last", snapshot.apiInferLatencyLastMs);

    // Stream robustness
    add_u64("beacon_analyzer_pull_read_errors_total", snapshot.pullReadErrors);
    add_u64("beacon_analyzer_pull_reconnect_attempts_total", snapshot.pullReconnectAttempts);
    add_u64("beacon_analyzer_pull_reconnect_success_total", snapshot.pullReconnectSuccess);
    add_u64("beacon_analyzer_push_write_errors_total", snapshot.pushWriteErrors);
    add_u64("beacon_analyzer_push_reconnect_attempts_total", snapshot.pushReconnectAttempts);
    add_u64("beacon_analyzer_push_reconnect_success_total", snapshot.pushReconnectSuccess);

    // Back-pressure drops
    add_u64("beacon_analyzer_dropped_pull_packets_total", snapshot.droppedPullPackets);
    add_u64("beacon_analyzer_dropped_decode_packets_total", snapshot.droppedDecodePackets);
    add_u64("beacon_analyzer_dropped_push_frames_total", snapshot.droppedPushFrames);
    add_u64("beacon_analyzer_dropped_alarm_frames_total", snapshot.droppedAlarmFrames);

    // Gauges
    add_i64("beacon_analyzer_detect_stride", snapshot.detectStride);
    add_i64("beacon_analyzer_current_controls", snapshot.currentControls);
    add_u64("beacon_analyzer_delete_queue_size", (uint64_t)snapshot.deleteQueueSize);
    add_u64("beacon_analyzer_alarm_queue_size", (uint64_t)snapshot.alarmQueueSize);
    add_u64("beacon_analyzer_last_update_timestamp", snapshot.lastUpdateTimestamp);

    // Pressure gauges (computed by resource monitor)
    add_i64("beacon_analyzer_pull_pkt_queue_size_max", resource.maxPullPktQueueSize);
    add_i64("beacon_analyzer_push_frame_queue_size_max", resource.maxPushFrameQueueSize);
    add_i64("beacon_analyzer_pull_pkt_queue_high_workers", resource.pullPktQueueHighWorkers);
    add_i64("beacon_analyzer_pull_pkt_queue_severe_workers", resource.pullPktQueueSevereWorkers);
    add_i64("beacon_analyzer_push_frame_queue_high_workers", resource.pushFrameQueueHighWorkers);
    add_i64("beacon_analyzer_push_frame_queue_severe_workers", resource.pushFrameQueueSevereWorkers);
    add_u64("beacon_analyzer_drop_window_ms", (uint64_t)std::max<int64_t>(0, resource.dropWindowMs));
    add_u64("beacon_analyzer_dropped_pull_packets_window", resource.droppedPullPacketsDelta);
    add_u64("beacon_analyzer_dropped_decode_packets_window", resource.droppedDecodePacketsDelta);
    add_u64("beacon_analyzer_dropped_push_frames_window", resource.droppedPushFramesDelta);
    add_u64("beacon_analyzer_dropped_alarm_frames_window", resource.droppedAlarmFramesDelta);
    add_f64("beacon_analyzer_dropped_pull_packets_per_second", resource.droppedPullPacketsPerSecond);
    add_f64("beacon_analyzer_dropped_decode_packets_per_second", resource.droppedDecodePacketsPerSecond);
    add_f64("beacon_analyzer_dropped_push_frames_per_second", resource.droppedPushFramesPerSecond);
    add_f64("beacon_analyzer_dropped_alarm_frames_per_second", resource.droppedAlarmFramesPerSecond);

    beacon::otel::SendReply(req, HTTP_OK, nullptr, buff);
    evbuffer_free(buff);
}

static void parse_get(const struct evhttp_request* req, struct evkeyvalq* params) {
    if (req == nullptr || params == nullptr) {
        return;
    }
    const char* url = request_uri(req);
    if (url == nullptr) {
        return;
    }
    std::unique_ptr<struct evhttp_uri, decltype(&evhttp_uri_free)> decoded(evhttp_uri_parse(url), &evhttp_uri_free);
    if (!decoded) {
        return;
    }
    const char* query = evhttp_uri_get_query(decoded.get());
    if (query == nullptr) {
        return;
    }
    evhttp_parse_query_str(query, params);
}
static bool parse_post(struct evhttp_request* req, char* buf) {
    if (buf) {
        buf[0] = '\0';
    }
    if (req == nullptr || buf == nullptr) {
        return false;
    }

    struct evbuffer* input = evhttp_request_get_input_buffer(req);
    if (input == nullptr) {
        send_json(req, 400, 0, "bad request");
        return false;
    }

    const size_t post_size = evbuffer_get_length(input);
    if (post_size == 0) {
        return true;
    }
    if (post_size > static_cast<size_t>(kRecvBufMaxSize)) {
        send_json(req, 413, 0, "payload too large");
        return false;
    }

    const unsigned char* data = evbuffer_pullup(input, post_size);
    if (data == nullptr) {
        send_json(req, 400, 0, "bad request");
        return false;
    }

    memcpy(buf, data, post_size);
    buf[post_size] = '\0';
    return true;
}
