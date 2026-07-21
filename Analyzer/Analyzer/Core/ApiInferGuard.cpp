#include "ApiInferGuard.h"

#include <algorithm>

namespace AVSAnalyzer {

bool ApiInferGuard::tryAcquire(int64_t nowMonoMs, std::string* reason) {
    if (reason) {
        reason->clear();
    }

    if (nowMonoMs <= 0) {
        // Caller should provide monotonic ms; if not, still allow but avoid negative math.
        nowMonoMs = 0;
    }

    if (mCfg.circuitBreakerFails > 0 && mCfg.circuitBreakerOpenSeconds > 0 &&
        mState.circuitOpenUntilMs > 0 && nowMonoMs < mState.circuitOpenUntilMs) {
        if (reason) {
            *reason = "circuit_open";
        }
        return false;
    }

    if (mCfg.minIntervalMs > 0 && mState.lastAcquireMs > 0) {
        const int64_t delta = nowMonoMs - mState.lastAcquireMs;
        if (delta >= 0 && delta < mCfg.minIntervalMs) {
            if (reason) {
                *reason = "min_interval";
            }
            return false;
        }
    }

    mState.lastAcquireMs = nowMonoMs;
    return true;
}

void ApiInferGuard::recordResult(bool ok, int64_t nowMonoMs, bool* circuitOpened) {
    if (circuitOpened) {
        *circuitOpened = false;
    }

    if (ok) {
        mState.consecutiveFailures = 0;
        mState.circuitOpenUntilMs = 0;
        return;
    }

    if (mCfg.circuitBreakerFails <= 0) {
        return;
    }

    mState.consecutiveFailures++;
    mState.consecutiveFailures = std::max(0, mState.consecutiveFailures);

    if (mCfg.circuitBreakerOpenSeconds <= 0) {
        return;
    }

    if (mState.consecutiveFailures >= mCfg.circuitBreakerFails) {
        const int64_t openMs = static_cast<int64_t>(mCfg.circuitBreakerOpenSeconds) * 1000;
        if (openMs > 0) {
            mState.circuitOpenUntilMs = std::max<int64_t>(mState.circuitOpenUntilMs, nowMonoMs + openMs);
            if (circuitOpened) {
                *circuitOpened = true;
            }
        }
    }
}

}  // namespace AVSAnalyzer
