#ifndef ANALYZER_UTILS_PTS_H
#define ANALYZER_UTILS_PTS_H

#include <cstdint>

namespace AVSAnalyzer {

// Normalize a monotonic timestamp into a strictly monotonic PTS (ms).
// - First call anchors baseTimestampMs and returns 0.
// - Older / equal timestamps still return lastPtsMs+1.
// - Returns PTS in milliseconds relative to baseTimestampMs.
int64_t normalizePtsMs(int64_t timestampMs, int64_t& baseTimestampMs, int64_t& lastPtsMs);

// Like normalizePtsMs(), but enforces a minimum step between consecutive PTS values.
// This is useful for push/encode pipelines where timestamp jitter (or repeated timestamps)
// can lead to perceived frame reversal / timeline stutter on some players.
int64_t normalizePtsMsWithMinStep(int64_t timestampMs,
                                 int64_t& baseTimestampMs,
                                 int64_t& lastPtsMs,
                                 int64_t minStepMs);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_UTILS_PTS_H
