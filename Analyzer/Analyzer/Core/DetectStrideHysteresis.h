#ifndef ANALYZER_DETECT_STRIDE_HYSTERESIS_H
#define ANALYZER_DETECT_STRIDE_HYSTERESIS_H

#include <cstdint>

namespace AVSAnalyzer {

// Hysteresis controller for detectStride:
// - Tighten (increase stride) immediately when the system is under pressure.
// - Relax (decrease stride) slowly only after a stable window.
class DetectStrideHysteresis {
public:
    explicit DetectStrideHysteresis(int initialStride = 1, int64_t relaxAfterMs = 30000);

    // Update with desired stride and current monotonic time (ms).
    // Returns the effective stride after applying hysteresis.
    int update(int desiredStride, int64_t nowMs);

    int current() const;

    void reset(int stride = 1);

private:
    int clampStride(int value) const;

    int mCurrentStride = 1;
    int64_t mRelaxAfterMs = 30000;
    int64_t mStableSinceMs = -1;
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_DETECT_STRIDE_HYSTERESIS_H
