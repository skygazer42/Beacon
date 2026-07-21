#include "ControlAlgorithmCodes.h"

#include <algorithm>
#include <cctype>

#include "ApiAlgorithmSupport.h"
#include "Control.h"

namespace AVSAnalyzer {

namespace {

std::string to_lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

}  // namespace

std::vector<std::string> collectLocalAlgorithmCodes(const Control* control) {
    std::vector<std::string> codes;
    if (!control) {
        return codes;
    }

    auto pushUnique = [&](const std::string& code) {
        if (code.empty()) {
            return;
        }
        if (std::find(codes.begin(), codes.end(), code) != codes.end()) {
            return;
        }
        codes.push_back(code);
    };

    const bool useBasicApiInference =
        shouldUseBasicApiInference(control->usePipelineMode, control->algorithmPipelineMode, control->api_url);
    const bool isPipelineMode5 = control->usePipelineMode && control->algorithmPipelineMode == 5;

    // Primary algorithm (detection / base algorithm)
    if (!useBasicApiInference && !isPipelineMode5 &&
        !control->algorithmCode.empty() &&
        control->algorithmCode != "wensou" && control->algorithmCode != "api") {
        pushUnique(!control->algorithmInstanceKey.empty() ? control->algorithmInstanceKey : control->algorithmCode);
    }

    // Hierarchical secondary algorithm (local-only)
    if (control->enableHierarchicalAlgorithm &&
        !control->secondaryAlgorithmCode.empty() &&
        control->secondaryApi_url.empty() &&
        control->secondaryAlgorithmCode != "wensou" && control->secondaryAlgorithmCode != "api") {
        pushUnique(control->secondaryAlgorithmCode);
    }

    if (control->usePipelineMode) {
        const int mode = control->algorithmPipelineMode;

        // Mode 2: tracking algorithm (exclude builtin bytetrack)
        if (mode == 2) {
            const std::string trackingLower = to_lower_copy(control->trackingAlgorithmCode);
            if (!trackingLower.empty() && trackingLower != "bytetrack") {
                pushUnique(control->trackingAlgorithmCode);
            }
        }

        // Modes with classification stage.
        if ((mode == 3 || mode == 4 || mode == 6 || mode == 7) && !control->classificationAlgorithmCode.empty()) {
            pushUnique(control->classificationAlgorithmCode);
        }

        // Modes with feature (embedding) stage.
        if ((mode == 7 || mode == 9) && !control->featureAlgorithmCode.empty()) {
            pushUnique(control->featureAlgorithmCode);
        }

        // Optional behavior algorithm (plugin/local) - currently used by modes 1-4 only.
        if (mode >= 1 && mode <= 4 && !control->behaviorAlgorithmCode.empty()) {
            pushUnique(control->behaviorAlgorithmCode);
        }
    }

    return codes;
}

}  // namespace AVSAnalyzer
