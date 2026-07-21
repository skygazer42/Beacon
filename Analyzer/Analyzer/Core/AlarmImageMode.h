#ifndef ANALYZER_ALARM_IMAGE_MODE_H
#define ANALYZER_ALARM_IMAGE_MODE_H

#include <algorithm>
#include <cctype>
#include <string>

namespace AVSAnalyzer {

struct AlarmImageModeSpec {
    std::string mode = "boxed";
    int mainImageDrawType = 1;  // 1=boxed, 0=clean
    bool captureRawSnapshot = false;
    bool saveMainImageFromRawSnapshot = false;
    bool saveCleanExtraImage = false;
    bool preferCleanVariantForLabelme = false;
    bool drawAlarmOverlay = true;
};

inline std::string normalizeAlarmImageDrawMode(std::string mode) {
    mode.erase(mode.begin(), std::find_if(mode.begin(), mode.end(), [](unsigned char ch) {
        return std::isspace(ch) == 0;
    }));
    mode.erase(std::find_if(mode.rbegin(), mode.rend(), [](unsigned char ch) {
        return std::isspace(ch) == 0;
    }).base(), mode.end());
    std::transform(mode.begin(), mode.end(), mode.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    if (mode != "clean" && mode != "both" && mode != "boxed") {
        mode = "boxed";
    }
    return mode;
}

inline AlarmImageModeSpec makeAlarmImageModeSpec(const std::string& modeValue) {
    AlarmImageModeSpec spec;
    spec.mode = normalizeAlarmImageDrawMode(modeValue);
    if (spec.mode == "clean") {
        spec.mainImageDrawType = 0;
        spec.captureRawSnapshot = true;
        spec.saveMainImageFromRawSnapshot = true;
        spec.saveCleanExtraImage = false;
        spec.preferCleanVariantForLabelme = true;
        spec.drawAlarmOverlay = false;
    } else if (spec.mode == "both") {
        spec.mainImageDrawType = 1;
        spec.captureRawSnapshot = true;
        spec.saveMainImageFromRawSnapshot = false;
        spec.saveCleanExtraImage = true;
        spec.preferCleanVariantForLabelme = true;
        spec.drawAlarmOverlay = true;
    }
    return spec;
}

}  // namespace AVSAnalyzer

#endif  // ANALYZER_ALARM_IMAGE_MODE_H
