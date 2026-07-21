#ifndef ANALYZER_ALGORITHM_LOAD_VALIDATION_H
#define ANALYZER_ALGORITHM_LOAD_VALIDATION_H

#include <algorithm>
#include <cctype>
#include <string>
#include <string_view>
#include <vector>

namespace AVSAnalyzer {

    enum class AlgorithmSubtype {
        Detection,
        Classification,
        Tracking,
        Behavior,
        Ocr,
        Unknown,
    };

    std::string normalize_algorithm_subtype(std::string_view value);
    AlgorithmSubtype parse_algorithm_subtype(std::string_view value);

    bool is_plugin_model_path(std::string_view modelPath);
    bool is_class_names_required(std::string_view modelPath, AlgorithmSubtype subtype);

    struct InferenceDeviceDecision {
        std::string requestedDevice{"CPU"};
        std::string effectiveDevice{"CPU"};
        bool degraded = false;
        std::string reason{};
    };

    std::string normalize_inference_device(std::string_view value);
    InferenceDeviceDecision make_inference_device_decision(
        std::string_view requestedDevice,
        std::string_view effectiveDevice,
        std::string_view fallbackReason
    );
    bool inference_device_decision_allowed(
        const InferenceDeviceDecision& decision,
        bool forceInferenceDevice,
        std::string& errMsg
    );

    // Validate minimal params for /api/algorithm/load. Keep this helper side-effect free for unit testing.
    bool validate_algorithm_load_request(
        std::string_view code,
        std::string_view modelPath,
        const std::vector<std::string>& classNames,
        AlgorithmSubtype subtype,
        std::string& errMsg
    );

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHM_LOAD_VALIDATION_H
