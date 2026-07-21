#ifndef ANALYZER_SHARED_DECODE_KEY_H
#define ANALYZER_SHARED_DECODE_KEY_H

#include <string>

namespace AVSAnalyzer {

struct DecodeReuseKey {
    std::string value{};
};

DecodeReuseKey makeDecodeReuseKey(
    const std::string& streamUrl,
    bool ffmpegSkipLoopFilter,
    bool ffmpegSkipIdct);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_SHARED_DECODE_KEY_H
