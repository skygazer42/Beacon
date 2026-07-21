#include "Request.h"
#include <curl/curl.h>
#include "Log.h"
#include <mutex>
#include <cstring>

namespace AVSAnalyzer {
    inline size_t onWrite(char* buffer, size_t size, size_t nmemb, void* stream);
    bool isSuccessfulHttpResponse(bool requestCompleted, bool hasHttpStatus, long httpStatusCode);

    namespace {
        bool isHttp2xx(long code) {
            return code >= 200 && code < 300;
        }

        void configureSecureTls(CURL* curl) { // NOSONAR - libcurl exposes CURL as an opaque handle typedef
            if (curl == nullptr) {
                return;
            }
            long sslVersion = CURL_SSLVERSION_TLSv1_2;
#ifdef CURL_SSLVERSION_MAX_TLSv1_3
            sslVersion |= CURL_SSLVERSION_MAX_TLSv1_3;
#endif
            curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
            curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
            curl_easy_setopt(curl, CURLOPT_SSLVERSION, sslVersion); // NOSONAR - enforce TLS >= 1.2 and allow negotiation up to 1.3 when available
        }

        void ensureCurlGlobalInit() {
            static std::once_flag curlInitOnce;
            std::call_once(curlInitOnce, []() {
#ifdef _WIN32
                curl_global_init(CURL_GLOBAL_WIN32);
#else
                curl_global_init(CURL_GLOBAL_DEFAULT);
#endif
            });
        }

        bool postImpl(
            const char* url,
            const char* data,
            size_t dataSize,
            std::string& response,
            std::string_view token,
            int connectTimeoutSeconds,
            int timeoutSeconds);

        bool postImpl(const char* url, const char* data, size_t dataSize, std::string& response) {
            return postImpl(url, data, dataSize, response, std::string_view{}, 30, 30);
        }

        bool postImpl(const char* url, const char* data, size_t dataSize, std::string& response, std::string_view token) {
            return postImpl(url, data, dataSize, response, token, 30, 30);
        }

        bool postImpl(
            const char* url,
            const char* data,
            size_t dataSize,
            std::string& response,
            std::string_view token,
            int connectTimeoutSeconds,
            int timeoutSeconds) {
            ensureCurlGlobalInit();

            if (!url || !url[0]) {
                LOGE("Request::post url is empty");
                return false;
            }
            if (!data) {
                data = "";
                dataSize = 0;
            }

            CURL* curl = curl_easy_init();
            if (!curl) {
                LOGE("curl_easy_init error: url=%s", url);
                return false;
            }

            struct curl_slist* headers = nullptr;
            headers = curl_slist_append(headers, "User-Agent: Analyzer;");
            headers = curl_slist_append(headers, "Content-Type:application/json;");
            if (!token.empty()) {
                std::string tokenHeader;
                tokenHeader.reserve(16 + token.size()); // "X-Beacon-Token: " is 16 bytes.
                tokenHeader.append("X-Beacon-Token: ");
                tokenHeader.append(token.data(), token.size());
                headers = curl_slist_append(headers, tokenHeader.c_str());
            }
            headers = curl_slist_append(headers, "expect: ;"); // avoid 100-continue delay
            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

            curl_easy_setopt(curl, CURLOPT_HEADER, 0);
            curl_easy_setopt(curl, CURLOPT_URL, url);
            curl_easy_setopt(curl, CURLOPT_POST, 1);
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, data);
            curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(dataSize));

            configureSecureTls(curl);

            curl_easy_setopt(curl, CURLOPT_VERBOSE, 0);
            curl_easy_setopt(curl, CURLOPT_READFUNCTION, static_cast<curl_read_callback>(nullptr));
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, onWrite);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
            curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1);
            if (connectTimeoutSeconds <= 0) connectTimeoutSeconds = 30;
            if (timeoutSeconds <= 0) timeoutSeconds = 30;
            curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, connectTimeoutSeconds);
            curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeoutSeconds);

            CURLcode code = curl_easy_perform(curl);
            bool ok = true;
            if (code != CURLE_OK) {
                LOGE("curl_easy_strerror: url=%s, %s", url, curl_easy_strerror(code));
                ok = false;
            }
            else {
                long httpCode = 0;
                if (curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &httpCode) == CURLE_OK &&
                    !isHttp2xx(httpCode)) {
                    LOGE("HTTP status not OK: url=%s status=%ld", url, httpCode);
                    ok = false;
                }
            }

            curl_slist_free_all(headers);
            curl_easy_cleanup(curl);
            return ok;
        }
    } // namespace

    bool isSuccessfulHttpResponse(bool requestCompleted, bool hasHttpStatus, long httpStatusCode) {
        return requestCompleted && (!hasHttpStatus || isHttp2xx(httpStatusCode));
    }

    inline size_t onWrite(char* buffer, size_t size, size_t nmemb, void* stream) {  // NOSONAR - libcurl callback signature

        auto* str = static_cast<std::string*>(stream);
        if (str == nullptr || buffer == nullptr)
        {
            return 0;
        }

        str->append(buffer, size * nmemb);
        return size * nmemb;
    }
    Request::Request() = default;

    Request::~Request() = default;

    bool Request::get(const char* url, std::string& response) {
        ensureCurlGlobalInit();
        if (!url || !url[0]) {
            LOGE("Request::get url is empty");
            return false;
        }

        CURL* curl = curl_easy_init();
        if (!curl) {
            LOGE("curl_easy_init error");
            return false;
        }

        curl_easy_setopt(curl, CURLOPT_URL, url);
        configureSecureTls(curl);

        curl_easy_setopt(curl, CURLOPT_VERBOSE, 0);//0 or 1 当等于1时，会显示详细的调试信息,
        curl_easy_setopt(curl, CURLOPT_READFUNCTION, static_cast<curl_read_callback>(nullptr));
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, onWrite);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
        curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1);

        curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10);

        const CURLcode code = curl_easy_perform(curl);
        const bool requestCompleted = code == CURLE_OK;
        long httpCode = 0;
        const bool hasHttpStatus = requestCompleted &&
            (curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &httpCode) == CURLE_OK);
        const bool result = isSuccessfulHttpResponse(requestCompleted, hasHttpStatus, httpCode);

        if (!requestCompleted) {
            LOGE("curl_easy_strerror: %s", curl_easy_strerror(code));
        }
        else if (hasHttpStatus && !isHttp2xx(httpCode)) {
            LOGE("HTTP status not OK: url=%s status=%ld", url ? url : "", httpCode);
        }

        curl_easy_cleanup(curl);
        return result;
    }
    bool Request::post(const char* url, const char* data, std::string& response) {
        size_t dataSize = data ? std::strlen(data) : 0;
        return postImpl(url, data, dataSize, response);
    }

    bool Request::post(const char* url, std::string_view data, std::string& response) {
        return postImpl(url, data.data(), data.size(), response);
    }

    bool Request::post(const char* url, std::string_view data, std::string& response, std::string_view token) {
        return postImpl(url, data.data(), data.size(), response, token);
    }

    bool Request::post(const char* url, std::string_view data, std::string& response, std::string_view token,
                       int connectTimeoutSeconds, int timeoutSeconds) {
        return postImpl(url, data.data(), data.size(), response, token, connectTimeoutSeconds, timeoutSeconds);
    }
}
