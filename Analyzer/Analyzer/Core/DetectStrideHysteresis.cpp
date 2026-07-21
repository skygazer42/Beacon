#include "DetectStrideHysteresis.h"

namespace AVSAnalyzer {

DetectStrideHysteresis::DetectStrideHysteresis(int initialStride, int64_t relaxAfterMs)
    : mCurrentStride(clampStride(initialStride)),
      mRelaxAfterMs(relaxAfterMs >= 0 ? relaxAfterMs : 0) {}

int DetectStrideHysteresis::clampStride(int value) const {
    // Scheduler currently uses [1..5] for detectStride. Keep the clamp small to
    // avoid accidental extreme values causing "no detection" for too long.
    if (value < 1) {
        return 1;
    }
    if (value > 5) {
        return 5;
    }
    return value;
}

int DetectStrideHysteresis::update(int desiredStride, int64_t nowMs) {
    if (nowMs < 0) {
        nowMs = 0;
    }

    const int desired = clampStride(desiredStride);

    // Tighten immediately.
    if (desired > mCurrentStride) {
        mCurrentStride = desired;
        mStableSinceMs = -1;
        return mCurrentStride;
    }

    // No relaxation needed.
    if (desired == mCurrentStride) {
        mStableSinceMs = -1;
        return mCurrentStride;
    }

    // desired < current: candidate relax after stable window.
    if (mRelaxAfterMs <= 0) {
        mCurrentStride = desired;
        mStableSinceMs = -1;
        return mCurrentStride;
    }

    if (mStableSinceMs < 0) {
        mStableSinceMs = nowMs;
        return mCurrentStride;
    }

    if (nowMs - mStableSinceMs >= mRelaxAfterMs) {
        mCurrentStride -= 1;
        if (mCurrentStride < desired) {
            mCurrentStride = desired;
        }
        // Require another full stable window for the next relaxation step.
        mStableSinceMs = nowMs;
    }

    return mCurrentStride;
}

int DetectStrideHysteresis::current() const {
    return mCurrentStride;
}

void DetectStrideHysteresis::reset(int stride) {
    mCurrentStride = clampStride(stride);
    mStableSinceMs = -1;
}

}  // namespace AVSAnalyzer
