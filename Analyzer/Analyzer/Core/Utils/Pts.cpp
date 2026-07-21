#include "Pts.h"

#include <algorithm>

namespace AVSAnalyzer {

int64_t normalizePtsMs(int64_t timestampMs, int64_t& baseTimestampMs, int64_t& lastPtsMs) {
    if (timestampMs <= 0) {
        timestampMs = 0;
    }

    if (baseTimestampMs <= 0) {
        baseTimestampMs = timestampMs;
        lastPtsMs = 0;
        return 0;
    }

    int64_t pts = timestampMs - baseTimestampMs;
    if (pts < 0) {
        pts = 0;
    }

    if (lastPtsMs >= 0 && pts <= lastPtsMs) {
        pts = lastPtsMs + 1;
    }
    lastPtsMs = pts;
    return pts;
}

int64_t normalizePtsMsWithMinStep(int64_t timestampMs,
                                 int64_t& baseTimestampMs,
                                 int64_t& lastPtsMs,
                                 int64_t minStepMs) {
    if (minStepMs <= 0) {
        minStepMs = 1;
    }

    const int64_t prevLastPtsMs = lastPtsMs;
    int64_t pts = normalizePtsMs(timestampMs, baseTimestampMs, lastPtsMs);

    if (prevLastPtsMs >= 0) {
        const int64_t minPts = prevLastPtsMs + minStepMs;
        if (pts < minPts) {
            pts = minPts;
            lastPtsMs = pts;
        }
    }

    return pts;
}

}  // namespace AVSAnalyzer
