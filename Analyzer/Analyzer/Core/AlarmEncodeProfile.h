#ifndef ANALYZER_ALARM_ENCODE_PROFILE_H
#define ANALYZER_ALARM_ENCODE_PROFILE_H

#include <string>

namespace AVSAnalyzer {

    struct AlarmEncodeSettings {
        int bit_rate = 0;
        int rc_min_rate = 0;
        int rc_max_rate = 0;
        int rc_buffer_size = 0;
        int thread_count = 0;
        int max_b_frames = 0;
        int rc_lookahead = -1;  // -1 = use encoder default
        std::string preset{};
        std::string tune{};     // empty = do not set
        std::string crf{};
    };

    AlarmEncodeSettings pickAlarmEncodeSettings(std::string profile, int width, int height);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_ALARM_ENCODE_PROFILE_H
