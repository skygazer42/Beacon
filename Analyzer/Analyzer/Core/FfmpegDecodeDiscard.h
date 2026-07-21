#ifndef ANALYZER_FFMPEG_DECODE_DISCARD_H
#define ANALYZER_FFMPEG_DECODE_DISCARD_H

#include "Control.h"
#include "Utils/JsonBool.h"

#include <json/value.h>

namespace AVSAnalyzer {

inline void applyFfmpegSkipLoopFilterFromJson(const Json::Value& root, Control& control) {
    // Accept both camelCase and snake_case keys for industrial integrations.
    const bool v =
        parseJsonBool(root, "ffmpegSkipLoopFilter", false) ||
        parseJsonBool(root, "skipLoopFilter", false) ||
        parseJsonBool(root, "skip_loop_filter", false) ||
        parseJsonBool(root, "ffmpeg_skip_loop_filter", false);
    control.ffmpegSkipLoopFilter = v;
}

inline void applyFfmpegSkipIdctFromJson(const Json::Value& root, Control& control) {
    const bool v =
        parseJsonBool(root, "ffmpegSkipIdct", false) ||
        parseJsonBool(root, "skipIdct", false) ||
        parseJsonBool(root, "skip_idct", false) ||
        parseJsonBool(root, "ffmpeg_skip_idct", false);
    control.ffmpegSkipIdct = v;
}

}  // namespace AVSAnalyzer

#endif  // ANALYZER_FFMPEG_DECODE_DISCARD_H

