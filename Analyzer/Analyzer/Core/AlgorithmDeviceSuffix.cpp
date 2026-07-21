#include "AlgorithmDeviceSuffix.h"

#include <algorithm>
#include <cctype>

namespace AVSAnalyzer {
    namespace {
        bool endsWith(std::string_view value, std::string_view suffix) {
            if (value.size() < suffix.size()) {
                return false;
            }
            return value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
        }

        bool parseSuffixWithOptionalNumericId(
            std::string_view lower,
            std::string_view suffix,
            std::string_view deviceBase,
            std::string_view original,
            std::string& outBase,
            std::string& outDevice
        ) {
            // Accept: <base><suffix> or <base><suffix><digits>
            // Example: "on_yolov8n_80_gpu" or "on_yolov8n_80_gpu1"
            if (lower.size() < suffix.size()) {
                return false;
            }

            const size_t suffixPos = lower.rfind(suffix);
            if (suffixPos == std::string::npos) {
                return false;
            }
            if (suffixPos + suffix.size() > lower.size()) {
                return false;
            }

            const size_t idPos = suffixPos + suffix.size();
            if (idPos == lower.size()) {
                outBase.assign(original.data(), suffixPos);
                outDevice.assign(deviceBase.data(), deviceBase.size());
                return true;
            }

            for (size_t i = idPos; i < lower.size(); ++i) {
                if (!std::isdigit(static_cast<unsigned char>(lower[i]))) {
                    return false;
                }
            }

            outBase.assign(original.data(), suffixPos);
            outDevice.assign(deviceBase.data(), deviceBase.size());
            outDevice.push_back(':');
            outDevice.append(original.data() + idPos, original.size() - idPos);
            return true;
        }
    }

    void parseAlgorithmDeviceSuffix(std::string_view code, std::string& baseCode, std::string& device) {
        baseCode.assign(code.data(), code.size());
        device = "CPU";

        if (code.empty()) {
            return;
        }

        std::string lower(code.data(), code.size());
        std::transform(lower.begin(), lower.end(), lower.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

        // NOTE: Order matters: handle *_gpu[<id>] / *_trt[<id>] first.
        if (parseSuffixWithOptionalNumericId(lower, "_gpu", "GPU", code, baseCode, device)) {
            return;
        }
        if (parseSuffixWithOptionalNumericId(lower, "_trt", "TRT", code, baseCode, device)) {
            return;
        }

        if (endsWith(lower, "_cpu")) {
            baseCode = code.substr(0, code.size() - 4);
            device = "CPU";
            return;
        }
        if (endsWith(lower, "_auto")) {
            baseCode = code.substr(0, code.size() - 5);
            device = "AUTO";
            return;
        }
        if (endsWith(lower, "_npu")) {
            baseCode = code.substr(0, code.size() - 4);
            device = "NPU";
            return;
        }
    }

}  // namespace AVSAnalyzer
