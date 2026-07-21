#ifndef ANALYZER_API_ALGORITHM_SUPPORT_H
#define ANALYZER_API_ALGORITHM_SUPPORT_H

#include <string>

namespace AVSAnalyzer {

    // Decide whether to run the basic algorithm via external API (Control.api_url),
    // especially to keep pipeline mode from failing when no local model is loaded.
    bool shouldUseBasicApiInference(bool usePipelineMode, int pipelineMode, const std::string& apiUrl);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_API_ALGORITHM_SUPPORT_H

