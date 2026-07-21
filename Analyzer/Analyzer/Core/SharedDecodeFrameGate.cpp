#include "SharedDecodeFrameGate.h"

#include <algorithm>

namespace AVSAnalyzer {

bool SharedDecodeFrameGate::shouldProcessFrame(const SharedDecodeFrameGateConfig& config, int64_t timestampMs) {
    int effectiveFps = std::max(0, config.pullFrequency);
    if (config.pushStream) {
        effectiveFps = std::max(effectiveFps, std::max(0, config.psEffectMinFps));
    }
	    effectiveFps = std::min(effectiveFps, 60);

	    if (effectiveFps > 0) {
	        if (const int64_t intervalMs = std::max<int64_t>(1, 1000 / std::max(1, effectiveFps));
	            mLastProcessTimestampMs > 0 && timestampMs > 0 &&
	            (timestampMs - mLastProcessTimestampMs) < intervalMs) {
	            return false;
	        }
	        mLastProcessTimestampMs = timestampMs;
	        return true;
	    }

    mFrameCount++;
    const int stride = std::max(1, config.decodeStride);
    return (mFrameCount % stride) == 0;
}

}  // namespace AVSAnalyzer
