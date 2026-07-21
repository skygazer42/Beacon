#include "ApiAlgorithmSupport.h"

#include <cctype>

namespace AVSAnalyzer {

    namespace {
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
    }

    bool shouldUseBasicApiInference(bool usePipelineMode, int pipelineMode, const std::string& apiUrl) {
        if (trim_copy(apiUrl).empty()) {
            return false;
        }

        if (!usePipelineMode) {
            return true;
        }

        // Pipeline mode 5 uses behaviorApiUrl; basic api_url should not override it.
        if (pipelineMode == 5) {
            return false;
        }

        return true;
    }

}  // namespace AVSAnalyzer

