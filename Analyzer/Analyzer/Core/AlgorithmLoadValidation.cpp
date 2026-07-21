#include "AlgorithmLoadValidation.h"

namespace AVSAnalyzer {
    namespace {
        std::string to_lower_copy(std::string value) {
            std::transform(value.begin(), value.end(), value.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            return value;
        }

        bool ends_with(std::string_view value, std::string_view suffix) {
            if (value.size() < suffix.size()) {
                return false;
            }
            return value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
        }

        std::string trim_copy(std::string value) {
            auto notSpace = [](unsigned char c) { return !std::isspace(c); };
            value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
            value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
            return value;
        }

        std::string device_base(std::string_view device) {
            const size_t colon = device.find(':');
            return std::string(device.substr(0, colon));
        }
    }

    std::string normalize_inference_device(std::string_view value) {
        std::string normalized = trim_copy(std::string(value));
        if (normalized.empty()) {
            return "CPU";
        }
        std::transform(normalized.begin(), normalized.end(), normalized.begin(),
            [](unsigned char c) { return static_cast<char>(std::toupper(c)); });

        const size_t colon = normalized.find(':');
        std::string base = normalized.substr(0, colon);
        const std::string suffix = colon == std::string::npos ? "" : normalized.substr(colon);
        if (base == "GPU") {
            base = "CUDA";
        }
        else if (base == "TRT") {
            base = "TENSORRT";
        }
        return base + suffix;
    }

    InferenceDeviceDecision make_inference_device_decision(
        std::string_view requestedDevice,
        std::string_view effectiveDevice,
        std::string_view fallbackReason
    ) {
        InferenceDeviceDecision decision;
        decision.requestedDevice = normalize_inference_device(requestedDevice);
        decision.effectiveDevice = normalize_inference_device(effectiveDevice);
        decision.degraded = device_base(decision.requestedDevice) != "AUTO"
            && decision.requestedDevice != decision.effectiveDevice;
        if (decision.degraded) {
            decision.reason = fallbackReason.empty()
                ? "requested inference device was not available"
                : std::string(fallbackReason);
        }
        return decision;
    }

    bool inference_device_decision_allowed(
        const InferenceDeviceDecision& decision,
        bool forceInferenceDevice,
        std::string& errMsg
    ) {
        if (forceInferenceDevice && decision.degraded) {
            errMsg = "forced inference device unavailable: requested=" + decision.requestedDevice
                + " effective=" + decision.effectiveDevice
                + " reason=" + decision.reason;
            return false;
        }
        errMsg.clear();
        return true;
    }

    std::string normalize_algorithm_subtype(std::string_view value) {
        if (std::string lower = to_lower_copy(std::string(value));
            lower == "detection" || lower == "classification" || lower == "tracking" || lower == "behavior" || lower == "ocr") {
            return lower;
        }
        return "";
    }

    AlgorithmSubtype parse_algorithm_subtype(std::string_view value) {
        std::string s = normalize_algorithm_subtype(value);
        if (s.empty()) {
            if (value.empty()) {
                return AlgorithmSubtype::Detection;
            }
            return AlgorithmSubtype::Unknown;
        }
        if (s == "detection") return AlgorithmSubtype::Detection;
        if (s == "classification") return AlgorithmSubtype::Classification;
        if (s == "tracking") return AlgorithmSubtype::Tracking;
        if (s == "behavior") return AlgorithmSubtype::Behavior;
        if (s == "ocr") return AlgorithmSubtype::Ocr;
        return AlgorithmSubtype::Unknown;
    }

    bool is_plugin_model_path(std::string_view modelPath) {
        std::string lower = to_lower_copy(std::string(modelPath));
        return ends_with(lower, ".dll") || ends_with(lower, ".so") || ends_with(lower, ".dylib");
    }

    bool is_class_names_required(std::string_view modelPath, AlgorithmSubtype subtype) {
        if (is_plugin_model_path(modelPath)) {
            return false;
        }
        if (subtype == AlgorithmSubtype::Tracking) {
            return false;
        }
        return true;
    }

    bool validate_algorithm_load_request(
        std::string_view code,
        std::string_view modelPath,
        const std::vector<std::string>& classNames,
        AlgorithmSubtype subtype,
        std::string& errMsg
    ) {
        if (code.empty() || modelPath.empty()) {
            errMsg = "code and modelPath are required";
            return false;
        }

        if (subtype == AlgorithmSubtype::Unknown) {
            errMsg = "invalid algorithmSubtype";
            return false;
        }

        if (is_class_names_required(modelPath, subtype) && classNames.empty()) {
            errMsg = "classNames array is required";
            return false;
        }

        errMsg = "ok";
        return true;
    }

} // namespace AVSAnalyzer
