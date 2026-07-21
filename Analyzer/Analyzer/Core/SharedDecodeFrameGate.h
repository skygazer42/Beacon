#ifndef ANALYZER_SHARED_DECODE_FRAME_GATE_H
#define ANALYZER_SHARED_DECODE_FRAME_GATE_H

#include <cstdint>

namespace AVSAnalyzer {

struct SharedDecodeFrameGateConfig {
    int pullFrequency = 0;
    int psEffectMinFps = 0;
    bool pushStream = false;
    int decodeStride = 1;
};

class SharedDecodeFrameGate {
public:
    bool shouldProcessFrame(const SharedDecodeFrameGateConfig& config, int64_t timestampMs);

private:
    int64_t mLastProcessTimestampMs = 0;
    int64_t mFrameCount = 0;
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_SHARED_DECODE_FRAME_GATE_H
