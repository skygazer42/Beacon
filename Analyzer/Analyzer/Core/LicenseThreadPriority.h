#ifndef ANALYZER_LICENSE_THREAD_PRIORITY_H
#define ANALYZER_LICENSE_THREAD_PRIORITY_H

#include <json/json.h>

#include <string>

namespace AVSAnalyzer {

struct LicenseThreadPriorityHint {
    bool enabled = false;
    int streamRank = 0;
    int firstNActiveStreams = 0;
    int niceValue = 0;
};

int clampThreadNiceValue(int value);
LicenseThreadPriorityHint parseLicenseThreadPriorityHint(const Json::Value& raw);
bool isThreadPriorityBoostActive(const LicenseThreadPriorityHint& hint);
int targetThreadNiceValue(const LicenseThreadPriorityHint& hint);
bool applyCurrentThreadPriorityBestEffort(const LicenseThreadPriorityHint& hint, std::string* errMsg = nullptr);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_LICENSE_THREAD_PRIORITY_H
