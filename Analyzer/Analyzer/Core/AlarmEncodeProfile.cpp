#include "AlarmEncodeProfile.h"

#include <algorithm>
#include <cctype>

namespace AVSAnalyzer {

    namespace {
        std::string trim(std::string value) {
            auto is_ws = [](unsigned char c) { return std::isspace(c) != 0; };
            while (!value.empty() && is_ws(static_cast<unsigned char>(value.front()))) {
                value.erase(value.begin());
            }
            while (!value.empty() && is_ws(static_cast<unsigned char>(value.back()))) {
                value.pop_back();
            }
            return value;
        }

        std::string toLower(std::string value) {
            std::transform(value.begin(), value.end(), value.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            return value;
        }
    }

    AlarmEncodeSettings pickAlarmEncodeSettings(std::string profile, int width, int height) {
        AlarmEncodeSettings s;

        profile = toLower(trim(profile));
        if (profile.empty()) {
            profile = "balanced";
        }

        const int pixels = width * height;
        int baseBitrate = 8000000;
        if (pixels <= 640 * 480) {
            baseBitrate = 3000000;
        }
        else if (pixels <= 1280 * 720) {
            baseBitrate = 5000000;
        }
        else if (pixels <= 1920 * 1080) {
            baseBitrate = 8000000;
        }
        else {
            baseBitrate = 15000000;
        }

        double scale = 1.0;
        const char* preset = "medium";
        const char* tune = "";
        const char* crf = "20";
        int threads = 4;
        int max_b_frames = 2;
        int rc_lookahead = 10;

        if (profile == "high_quality") {
            scale = 1.5;
            preset = "slow";
            tune = "film";
            crf = "18";
            threads = 4;
            max_b_frames = 3;
            rc_lookahead = 20;
        }
        else if (profile == "low_cpu") {
            scale = 0.6;
            preset = "ultrafast";
            tune = "zerolatency";
            crf = "30";
            threads = 1;
            max_b_frames = 0;
            rc_lookahead = 0;
        }
        else if (profile != "balanced") {
            profile = "balanced";
        }

        auto bit_rate = static_cast<int>(static_cast<double>(baseBitrate) * scale);
        if (bit_rate < 300000) {
            bit_rate = 300000;
        }

        s.bit_rate = bit_rate;
        s.rc_min_rate = bit_rate * 7 / 10;
        s.rc_max_rate = bit_rate * 15 / 10;
        s.rc_buffer_size = bit_rate * 2;
        s.thread_count = threads;
        s.max_b_frames = max_b_frames;
        s.rc_lookahead = rc_lookahead;
        s.preset = preset;
        s.tune = tune;
        s.crf = crf;
        return s;
    }

}  // namespace AVSAnalyzer
