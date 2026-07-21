#include "TargetSizeFilter.h"

#include <algorithm>
#include <cctype>
#include <exception>
#include <stdexcept>
#include <string_view>

#include <json/json.h>

namespace AVSAnalyzer {
namespace {

bool parse_json_object(std::string_view text, Json::Value& out) {
    out = Json::Value();
    if (text.empty()) {
        return false;
    }
    Json::CharReaderBuilder builder;
    std::string errs;
    const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    if (!reader) {
        return false;
    }
    const char* b = text.data();
    const char* e = b + text.size();
    if (!reader->parse(b, e, &out, &errs)) {
        return false;
    }
    if (!errs.empty()) {
        return false;
    }
    return out.isObject();
}

int get_int(const Json::Value& obj, const char* key, int fallback) {
    if (!key || !obj.isObject()) {
        return fallback;
    }
    const Json::Value v = obj[key];
    if (v.isInt()) {
        return v.asInt();
    }
    if (v.isUInt()) {
        return static_cast<int>(v.asUInt());
    }
    if (v.isString()) {
        try {
            return std::stoi(v.asString());
        } catch (const std::invalid_argument&) {
            return fallback;
        } catch (const std::out_of_range&) {
            return fallback;
        }
    }
    if (v.isDouble()) {
        return static_cast<int>(v.asDouble());
    }
    return fallback;
}

float get_float(const Json::Value& obj, const char* key, float fallback) {
    if (!key || !obj.isObject()) {
        return fallback;
    }
    const Json::Value v = obj[key];
    if (v.isNumeric()) {
        return v.asFloat();
    }
    if (v.isString()) {
        try {
            return std::stof(v.asString());
        } catch (const std::invalid_argument&) {
            return fallback;
        } catch (const std::out_of_range&) {
            return fallback;
        }
    }
    return fallback;
}

float clamp01(float v) {
    if (v < 0.0f) return 0.0f;
    if (v > 1.0f) return 1.0f;
    return v;
}

template <typename ValueType, typename LimitType>
bool passes_min_threshold(ValueType value, LimitType minValue) {
    return minValue <= static_cast<LimitType>(0) || value >= static_cast<ValueType>(minValue);
}

template <typename ValueType, typename LimitType>
bool passes_max_threshold(ValueType value, LimitType maxValue) {
    return maxValue <= static_cast<LimitType>(0) || value <= static_cast<ValueType>(maxValue);
}

}  // namespace

TargetSizeFilterConfig parseTargetSizeFilterConfig(const std::string& behaviorConfigJson) {
    TargetSizeFilterConfig cfg{};

    Json::Value root;
    if (!parse_json_object(behaviorConfigJson, root)) {
        return cfg;
    }

    cfg.minWidth = std::max(0, get_int(root, "minTargetWidth", get_int(root, "minWidth", 0)));
    cfg.minHeight = std::max(0, get_int(root, "minTargetHeight", get_int(root, "minHeight", 0)));
    cfg.maxWidth = std::max(0, get_int(root, "maxTargetWidth", get_int(root, "maxWidth", 0)));
    cfg.maxHeight = std::max(0, get_int(root, "maxTargetHeight", get_int(root, "maxHeight", 0)));

    cfg.minArea = std::max(0, get_int(root, "minTargetArea", get_int(root, "minArea", 0)));
    cfg.maxArea = std::max(0, get_int(root, "maxTargetArea", get_int(root, "maxArea", 0)));

    cfg.minAreaRatio = clamp01(get_float(root, "minTargetAreaRatio", get_float(root, "minAreaRatio", 0.0f)));
    cfg.maxAreaRatio = clamp01(get_float(root, "maxTargetAreaRatio", get_float(root, "maxAreaRatio", 0.0f)));

    // Enabled when any threshold is set (non-zero).
    cfg.enabled = (cfg.minWidth > 0) || (cfg.minHeight > 0) || (cfg.maxWidth > 0) || (cfg.maxHeight > 0) ||
                  (cfg.minArea > 0) || (cfg.maxArea > 0) || (cfg.minAreaRatio > 0.0f) || (cfg.maxAreaRatio > 0.0f);

    return cfg;
}

bool passTargetAreaRatioFilter(const TargetSizeFilterConfig& cfg, long long bboxArea, int imageW, int imageH) {
    if (imageW <= 0 || imageH <= 0) {
        return true;
    }

    const double imageArea = static_cast<double>(imageW) * static_cast<double>(imageH);
    if (imageArea <= 0.0) {
        return true;
    }

    const auto ratio = static_cast<float>(static_cast<double>(bboxArea) / imageArea);
    return passes_min_threshold(ratio, cfg.minAreaRatio) && passes_max_threshold(ratio, cfg.maxAreaRatio);
}

bool passTargetSizeFilter(const TargetSizeFilterConfig& cfg, int bboxW, int bboxH, int imageW, int imageH) {
    if (!cfg.enabled) {
        return true;
    }
    if (bboxW <= 0 || bboxH <= 0) {
        return false;
    }

    const long long area = static_cast<long long>(bboxW) * static_cast<long long>(bboxH);
    return passes_min_threshold(bboxW, cfg.minWidth) &&
           passes_min_threshold(bboxH, cfg.minHeight) &&
           passes_max_threshold(bboxW, cfg.maxWidth) &&
           passes_max_threshold(bboxH, cfg.maxHeight) &&
           passes_min_threshold(area, cfg.minArea) &&
           passes_max_threshold(area, cfg.maxArea) &&
           passTargetAreaRatioFilter(cfg, area, imageW, imageH);
}

}  // namespace AVSAnalyzer
