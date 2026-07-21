#include "EngineModelSupport.h"

#include <algorithm>
#include <cctype>

namespace AVSAnalyzer {
namespace {

bool endsWith(const std::string& value, const std::string& suffix) {
    if (value.size() < suffix.size()) {
        return false;
    }
    return value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

std::string toLowerCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

}  // namespace

bool isTensorrtEngineModelFile(const std::string& modelPath) {
    if (modelPath.empty()) {
        return false;
    }
    const std::string lower = toLowerCopy(modelPath);
    return endsWith(lower, ".engine") || endsWith(lower, ".plan");
}

}  // namespace AVSAnalyzer

