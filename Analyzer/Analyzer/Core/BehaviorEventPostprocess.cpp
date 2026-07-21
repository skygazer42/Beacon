#include "BehaviorEventPostprocess.h"

#include <algorithm>
#include <cctype>
#include <exception>
#include <stdexcept>
#include <string_view>
#include <json/json.h>

namespace AVSAnalyzer {

namespace {
    std::string to_lower_copy(std::string value) {
        std::transform(value.begin(), value.end(), value.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return value;
    }

    int json_get_int(const Json::Value& root, const char* key, int defaultValue) {
        if (!root.isObject() || key == nullptr) {
            return defaultValue;
        }
        const Json::Value v = root.get(key, Json::Value());
        if (v.isInt()) return v.asInt();
        if (v.isUInt()) return static_cast<int>(v.asUInt());
        if (v.isString()) {
            try {
                return std::stoi(v.asString());
            } catch (const std::invalid_argument&) {
                return defaultValue;
            } catch (const std::out_of_range&) {
                return defaultValue;
            }
        }
        return defaultValue;
    }

    std::string json_get_string(const Json::Value& root, const char* key, const std::string& defaultValue) {
        if (!root.isObject() || key == nullptr) {
            return defaultValue;
        }
        const Json::Value v = root.get(key, Json::Value());
        if (v.isString()) {
            return v.asString();
        }
        return defaultValue;
    }

    bool parse_json_object(std::string_view text, Json::Value& out) {
        out = Json::Value(Json::objectValue);
        if (text.empty()) {
            return true;
        }

        Json::CharReaderBuilder builder;
        builder["collectComments"] = false;
        std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
        JSONCPP_STRING errs;
        const char* begin = text.data();
        const char* end = text.data() + text.size();
        if (!reader->parse(begin, end, &out, &errs)) {
            return false;
        }
        return out.isObject();
    }

    int clamp_seconds(int seconds) {
        if (seconds <= 0) return 0;
        if (seconds > 3600) return 3600;
        return seconds;
    }
}

BehaviorEventPostprocessConfig parseBehaviorEventPostprocessConfig(
    const std::string& behaviorConfigJson,
    const std::string& objectCode)
{
    BehaviorEventPostprocessConfig cfg;

    const std::string objLower = to_lower_copy(objectCode);
    const bool builtinAbsence = (objLower == "absence" || objLower == "noone");
    const bool builtinUnattended = (objLower == "unattended" || objLower == "leave");

    Json::Value root;
    bool parsed = parse_json_object(behaviorConfigJson, root);
    if (!parsed) {
        // If config is invalid, fall back to safe defaults only for builtin behaviors.
        if (builtinAbsence) {
            cfg.enabled = true;
            cfg.mode = BehaviorEventPostprocessMode::Absence;
            cfg.thresholdMs = 3000;
        }
        else if (builtinUnattended) {
            cfg.enabled = true;
            cfg.mode = BehaviorEventPostprocessMode::Unattended;
            cfg.thresholdMs = 3000;
        }
        return cfg;
    }

    std::string post = to_lower_copy(json_get_string(root, "postprocess", ""));
    if (post.empty()) {
        post = to_lower_copy(json_get_string(root, "mode", ""));
    }
    if (post == "noone") {
        post = "absence";
    } else if (post == "leave") {
        post = "unattended";
    }

    if (builtinAbsence || post == "absence") {
        cfg.enabled = builtinAbsence || (post == "absence");
        cfg.mode = BehaviorEventPostprocessMode::Absence;

        int seconds = json_get_int(root, "absenceSeconds", 0);
        if (seconds <= 0) {
            seconds = json_get_int(root, "thresholdSeconds", 0);
        }
        if (seconds <= 0) {
            seconds = 3;
        }
        seconds = clamp_seconds(seconds);
        cfg.thresholdMs = static_cast<int64_t>(seconds) * 1000;
        return cfg;
    }

    if (builtinUnattended || post == "unattended") {
        cfg.enabled = builtinUnattended || (post == "unattended");
        cfg.mode = BehaviorEventPostprocessMode::Unattended;

        int seconds = json_get_int(root, "unattendedSeconds", 0);
        if (seconds <= 0) {
            seconds = json_get_int(root, "thresholdSeconds", 0);
        }
        if (seconds <= 0) {
            seconds = 3;
        }
        seconds = clamp_seconds(seconds);
        cfg.thresholdMs = static_cast<int64_t>(seconds) * 1000;
        return cfg;
    }

    return cfg;
}

BehaviorEventPostprocessor::BehaviorEventPostprocessor(const BehaviorEventPostprocessConfig& config) {
    setConfig(config);
}

void BehaviorEventPostprocessor::setConfig(const BehaviorEventPostprocessConfig& config) {
    mConfig = config;
    reset();
}

const BehaviorEventPostprocessConfig& BehaviorEventPostprocessor::config() const {
    return mConfig;
}

bool BehaviorEventPostprocessor::enabled() const {
    return mConfig.enabled && mConfig.mode != BehaviorEventPostprocessMode::None && mConfig.thresholdMs > 0;
}

void BehaviorEventPostprocessor::reset() {
    mActive = false;
    mStartMs = 0;
}

bool BehaviorEventPostprocessor::update(bool rawHappen, int64_t nowMs) {
    if (!enabled()) {
        return rawHappen;
    }
    if (!rawHappen) {
        reset();
        return false;
    }

    if (!mActive) {
        mActive = true;
        mStartMs = nowMs;
        return false;
    }

    if (nowMs < mStartMs) {
        // monotonic clock glitch; be conservative
        mStartMs = nowMs;
        return false;
    }

    return (nowMs - mStartMs) >= mConfig.thresholdMs;
}

int64_t BehaviorEventPostprocessor::activeDurationMs(int64_t nowMs) const {
    if (!mActive) {
        return 0;
    }
    if (nowMs < mStartMs) {
        return 0;
    }
    return nowMs - mStartMs;
}

void PerRegionBehaviorEventPostprocessor::setConfig(const BehaviorEventPostprocessConfig& config, size_t regionCount) {
    mConfig = config;
    mRegions.clear();
    mRegions.reserve(regionCount);
    for (size_t i = 0; i < regionCount; ++i) {
        mRegions.emplace_back(config);
    }
}

const BehaviorEventPostprocessConfig& PerRegionBehaviorEventPostprocessor::config() const {
    return mConfig;
}

bool PerRegionBehaviorEventPostprocessor::enabled() const {
    return mConfig.enabled && mConfig.mode != BehaviorEventPostprocessMode::None && mConfig.thresholdMs > 0 && !mRegions.empty();
}

size_t PerRegionBehaviorEventPostprocessor::regionCount() const {
    return mRegions.size();
}

void PerRegionBehaviorEventPostprocessor::reset() {
    for (auto& r : mRegions) {
        r.reset();
    }
}

int PerRegionBehaviorEventPostprocessor::update(const std::vector<bool>& rawHappenPerRegion, int64_t nowMs) {
    if (mRegions.empty()) {
        return -1;
    }
    if (rawHappenPerRegion.size() != mRegions.size()) {
        reset();
        return -1;
    }

    if (!enabled()) {
        for (size_t i = 0; i < rawHappenPerRegion.size(); ++i) {
            if (rawHappenPerRegion[i]) {
                return static_cast<int>(i);
            }
        }
        return -1;
    }

    for (size_t i = 0; i < rawHappenPerRegion.size(); ++i) {
        if (mRegions[i].update(rawHappenPerRegion[i], nowMs)) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

int64_t PerRegionBehaviorEventPostprocessor::activeDurationMs(size_t regionIndex, int64_t nowMs) const {
    if (regionIndex >= mRegions.size()) {
        return 0;
    }
    return mRegions[regionIndex].activeDurationMs(nowMs);
}

} // namespace AVSAnalyzer
