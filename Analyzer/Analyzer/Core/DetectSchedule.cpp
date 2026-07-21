#include "DetectSchedule.h"

#include <algorithm>

namespace AVSAnalyzer {

bool shouldRunBasicDetection(
    int mode,
    int interval,
    int64_t frameCount,
    int dynamicStride,
    int64_t nowTimestampMs,
    DetectScheduleState& state
) {
    if (dynamicStride < 1) {
        dynamicStride = 1;
    }

    if (mode == 1) {
        // Fixed interval frames.
        const int everyFrames = std::max(1, interval);
        return (frameCount % everyFrames) == 0;
    }

	    if (mode == 2) {
	        // Fixed interval time (seconds).
	        const int64_t intervalSeconds = std::max<int64_t>(1, interval);
	        if (const int64_t intervalMs = intervalSeconds * 1000;
	            state.lastDetectTimestampMs <= 0 || (nowTimestampMs - state.lastDetectTimestampMs) >= intervalMs) {
	            state.lastDetectTimestampMs = nowTimestampMs;
	            return true;
	        }
	        return false;
	    }

    // mode == 0 (default): free competition, use dynamic stride.
    return (dynamicStride <= 1) || (frameCount % dynamicStride) == 0;
}

}  // namespace AVSAnalyzer
