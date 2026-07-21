#include "AlarmQueuePolicy.h"

#include <algorithm>
#include <cctype>

namespace AVSAnalyzer {
    namespace {
        std::string toLower(std::string value) {
            std::transform(value.begin(), value.end(), value.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            return value;
        }
    }

    size_t pickAlarmVideoQueueMaxFrames(const std::string& alarmVideoType, int alarmImageCount, int alarmPrefixFrames) {
        int prefix = alarmPrefixFrames;
        if (prefix < 1) {
            prefix = 1;
        }

        const std::string typeLower = toLower(std::string(alarmVideoType));
        const bool recordVideo = (typeLower != "none");
        if (recordVideo) {
            return static_cast<size_t>(prefix);
        }

        int images = alarmImageCount;
        if (images < 0) {
            images = 0;
        }

        // Image-only alarm:
        // - For 0~1 image, we only need a tiny queue (trigger frame).
        // - For >1 images, allow a small buffer but cap by alarmPrefixFrames to avoid large memory on weak machines.
        if (images <= 1) {
            return static_cast<size_t>(std::min(prefix, 2));
        }

        int desired = images * 2 + 1;
        if (desired < 3) {
            desired = 3;
        }
        if (desired > prefix) {
            desired = prefix;
        }
        if (desired < 1) {
            desired = 1;
        }
        return static_cast<size_t>(desired);
    }
}

