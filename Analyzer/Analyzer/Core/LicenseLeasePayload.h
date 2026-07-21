#ifndef ANALYZER_LICENSE_LEASE_PAYLOAD_H
#define ANALYZER_LICENSE_LEASE_PAYLOAD_H

#include <json/json.h>

#include <cctype>
#include <string>

namespace AVSAnalyzer {

struct LicenseLeaseAcquireInput {
    std::string nodeId{};
    std::string controlCode{};
    std::string streamCode{};
    std::string algorithmCode{};
    int ttlSeconds = 120;
};

inline std::string trimLicenseLeaseField(const std::string& value) {
    size_t start = 0;
    while (start < value.size() && std::isspace(static_cast<unsigned char>(value[start]))) {
        ++start;
    }
    size_t end = value.size();
    while (end > start && std::isspace(static_cast<unsigned char>(value[end - 1]))) {
        --end;
    }
    return value.substr(start, end - start);
}

inline std::string normalizeLicenseLeaseStreamCode(const std::string& streamCode, const std::string& controlCode) {
    if (const std::string stream = trimLicenseLeaseField(streamCode); !stream.empty()) {
        return stream;
    }
    return trimLicenseLeaseField(controlCode);
}

inline Json::Value buildLicenseLeaseAcquirePayload(const LicenseLeaseAcquireInput& input) {
    Json::Value body;
    body["node_id"] = input.nodeId;
    body["control_code"] = input.controlCode;
    body["stream_code"] = normalizeLicenseLeaseStreamCode(input.streamCode, input.controlCode);
    body["algorithm_code"] = input.algorithmCode;
    body["ttl_seconds"] = input.ttlSeconds;
    return body;
}

}  // namespace AVSAnalyzer

#endif  // ANALYZER_LICENSE_LEASE_PAYLOAD_H
