#pragma once

#include "Control.h"

#include <algorithm>
#include <exception>
#include <stdexcept>
#include <string>

#include <json/json.h>

namespace AVSAnalyzer {

namespace control_perf_params {
inline int clampFps(int v) {
    if (v < 0) return 0;
    if (v > 60) return 60;
    return v;
}
}  // namespace control_perf_params

inline void applyPullFrequencyFromJson(const Json::Value& root, Control& control) {
    int v = control_perf_params::clampFps(control.pullFrequency);

    try {
        const Json::Value& j = root.isMember("pullFrequency") ? root["pullFrequency"] : root["pull_frequency"];
        if (j.isNumeric()) {
            v = j.asInt();
        } else if (j.isString()) {
            v = std::stoi(j.asString());
        }
    } catch (const std::invalid_argument&) {
        v = control_perf_params::clampFps(control.pullFrequency);
    } catch (const std::out_of_range&) {
        v = control_perf_params::clampFps(control.pullFrequency);
    }

    control.pullFrequency = control_perf_params::clampFps(v);
}

inline void applyPsEffectMinFpsFromJson(const Json::Value& root, Control& control) {
    int v = control_perf_params::clampFps(control.psEffectMinFps);

    try {
        const Json::Value& j = root.isMember("psEffectMinFps") ? root["psEffectMinFps"] : root["ps_effect_min_fps"];
        if (j.isNumeric()) {
            v = j.asInt();
        } else if (j.isString()) {
            v = std::stoi(j.asString());
        }
    } catch (const std::invalid_argument&) {
        v = control_perf_params::clampFps(control.psEffectMinFps);
    } catch (const std::out_of_range&) {
        v = control_perf_params::clampFps(control.psEffectMinFps);
    }

    control.psEffectMinFps = control_perf_params::clampFps(v);
}

}  // namespace AVSAnalyzer
