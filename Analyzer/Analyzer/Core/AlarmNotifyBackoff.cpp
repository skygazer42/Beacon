#include "AlarmNotifyBackoff.h"

#include <algorithm>

namespace AVSAnalyzer {

int64_t computeAlarmNotifyBackoffMs(int attempt) {
    if (attempt < 0) {
        attempt = 0;
    }
    // Exponential: 1s, 2s, 4s, ... (cap at 30s)
    int64_t delay = 1000;
    for (int i = 0; i < attempt; ++i) {
        if (delay >= 30000) {
            delay = 30000;
            break;
        }
        delay *= 2;
    }
    delay = std::min<int64_t>(delay, 30000);
    return delay;
}

}  // namespace AVSAnalyzer

