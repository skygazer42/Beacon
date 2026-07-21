#ifndef ANALYZER_DETECT_SCHEDULE_H
#define ANALYZER_DETECT_SCHEDULE_H

#include <cstdint>

namespace AVSAnalyzer {

struct DetectScheduleState {
    int64_t lastDetectTimestampMs = 0;
};

// Decide whether to run "basic algorithm detection" for current frame.
//
// mode:
// - 0: free competition (use dynamicStride)
// - 1: fixed interval frames (interval = frames)
// - 2: fixed interval seconds (interval = seconds)
//
// NOTE: nowTimestampMs should be monotonic milliseconds (e.g. getCurTime()).
bool shouldRunBasicDetection(
    int mode,
    int interval,
    int64_t frameCount,
    int dynamicStride,
    int64_t nowTimestampMs,
    DetectScheduleState& state
);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_DETECT_SCHEDULE_H

