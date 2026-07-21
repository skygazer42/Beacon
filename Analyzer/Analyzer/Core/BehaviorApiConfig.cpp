#include "BehaviorApiConfig.h"

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

std::string trim_copy(const std::string& s) {
    size_t b = 0;
    while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) b++;
    size_t e = s.size();
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) e--;
    return s.substr(b, e - b);
}

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

int json_get_int(const Json::Value& obj, const char* key, int fallback) {
    if (!obj.isObject() || !key) {
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

float json_get_float(const Json::Value& obj, const char* key, float fallback) {
    if (!obj.isObject() || !key) {
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

bool json_get_bool(const Json::Value& obj, const char* key, bool fallback) {
    if (!obj.isObject() || !key) {
        return fallback;
    }
    const Json::Value v = obj[key];
    if (v.isBool()) {
        return v.asBool();
    }
    if (v.isInt()) {
        return v.asInt() != 0;
    }
    if (v.isUInt()) {
        return v.asUInt() != 0;
    }
    if (v.isDouble()) {
        return v.asDouble() != 0.0;
    }
    if (v.isString()) {
        const std::string raw = to_lower_copy(trim_copy(v.asString()));
        if (raw == "1" || raw == "true" || raw == "yes" || raw == "y" || raw == "on") {
            return true;
        }
        if (raw == "0" || raw == "false" || raw == "no" || raw == "n" || raw == "off") {
            return false;
        }
    }
    return fallback;
}

std::string json_get_string(const Json::Value& obj, const char* key, const std::string& fallback) {
    if (!obj.isObject() || !key) {
        return fallback;
    }
    const Json::Value v = obj[key];
    if (v.isString()) {
        return v.asString();
    }
    return fallback;
}

float clamp01(float v) {
    if (v < 0.0f) return 0.0f;
    if (v > 1.0f) return 1.0f;
    return v;
}

int normalized_api_version(const Json::Value& root, int fallback) {
    int apiVersion = json_get_int(root, "apiVersion", fallback);
    const std::string apiType = to_lower_copy(json_get_string(root, "apiType", ""));
    if (apiType.find("v3") != std::string::npos) {
        return 3;
    }
    if (apiType.find("v2") != std::string::npos) {
        return 2;
    }
    if (apiVersion < 1 || apiVersion > 3) {
        return 1;
    }
    return apiVersion;
}

std::string resolve_builtin_behavior_name(
    const Json::Value& root,
    const std::string& behaviorAlgorithmCode,
    int apiVersion)
{
    std::string builtinBehavior = to_lower_copy(json_get_string(root, "builtinBehavior", ""));
    if (builtinBehavior.empty()) {
        builtinBehavior = to_lower_copy(json_get_string(root, "builtin_behavior", ""));
    }
    if (builtinBehavior.empty()) {
        builtinBehavior = to_lower_copy(json_get_string(root, "builtin", ""));
    }
    if (builtinBehavior.empty() && apiVersion >= 2) {
        builtinBehavior = to_lower_copy(behaviorAlgorithmCode);
    }
    return builtinBehavior;
}

CountTriggerOp parse_count_trigger_op(const Json::Value& root, CountTriggerOp fallback) {
    std::string op = to_lower_copy(trim_copy(json_get_string(root, "countOp", "")));
    if (op.empty()) {
        op = to_lower_copy(trim_copy(json_get_string(root, "crowdOp", "")));
    }
    if (op == "le" || op == "<=") {
        return CountTriggerOp::LE;
    }
    if (op == "ge" || op == ">=") {
        return CountTriggerOp::GE;
    }
    return fallback;
}

void apply_crowd_config(const Json::Value& root, BehaviorApiConfig& cfg) {
    cfg.crowdMinCount = std::max(1, json_get_int(root, "crowdMinCount", cfg.crowdMinCount));
    cfg.crowdMinCount = std::max(1, json_get_int(root, "minCount", cfg.crowdMinCount));
    cfg.crowdTriggerOp = parse_count_trigger_op(root, cfg.crowdTriggerOp);
    if (cfg.crowdTriggerOp != CountTriggerOp::LE) {
        return;
    }

    cfg.crowdMaxCount = json_get_int(root, "crowdMaxCount", cfg.crowdMinCount);
    cfg.crowdMaxCount = json_get_int(root, "maxCount", cfg.crowdMaxCount);
}

std::string resolve_motion_event_name(const Json::Value& root) {
    std::string motionEventName = trim_copy(json_get_string(root, "motionEventName", ""));
    if (motionEventName.empty()) {
        motionEventName = trim_copy(json_get_string(root, "eventName", ""));
    }
    if (motionEventName.empty()) {
        motionEventName = trim_copy(json_get_string(root, "event_name", ""));
    }
    if (motionEventName.empty()) {
        motionEventName = trim_copy(json_get_string(root, "customEventName", ""));
    }
    if (motionEventName.empty()) {
        motionEventName = "MOTION";
    }
    return motionEventName;
}

void apply_motion_config(const Json::Value& root, BehaviorApiConfig& cfg) {
    cfg.loiteringSeconds = json_get_int(root, "loiteringSeconds", cfg.loiteringSeconds);
    cfg.loiteringSeconds = json_get_int(root, "thresholdSeconds", cfg.loiteringSeconds);
    if (cfg.loiteringSeconds < 1) cfg.loiteringSeconds = 1;
    if (cfg.loiteringSeconds > 3600) cfg.loiteringSeconds = 3600;

    cfg.motionMinDisplacement = json_get_int(root, "motionMinDisplacement", cfg.motionMinDisplacement);
    cfg.motionMinDisplacement = json_get_int(root, "minDisplacement", cfg.motionMinDisplacement);
    cfg.motionMinDisplacement = json_get_int(root, "displacementThreshold", cfg.motionMinDisplacement);
    if (cfg.motionMinDisplacement < 1) cfg.motionMinDisplacement = 1;
    if (cfg.motionMinDisplacement > 100000) cfg.motionMinDisplacement = 100000;

    cfg.motionEventName = resolve_motion_event_name(root);
}

}  // namespace

BuiltinBehaviorType parseBuiltinBehaviorType(const std::string& value, BuiltinBehaviorType fallback) {
    const std::string v = to_lower_copy(trim_copy(value));
    if (v.empty()) {
        return fallback;
    }

    if (v == "intrusion" || v == "area") {
        return BuiltinBehaviorType::Intrusion;
    }
    if (v == "super") {
        return BuiltinBehaviorType::Super;
    }
    if (v == "motion") {
        return BuiltinBehaviorType::Motion;
    }
    if (v == "occlusion" || v == "cover" || v == "occluded") {
        return BuiltinBehaviorType::Occlusion;
    }
    if (v == "grayscreen" || v == "gray_screen" || v == "gray") {
        return BuiltinBehaviorType::GrayScreen;
    }
    if (v == "corruptscreen" || v == "corrupt_screen" || v == "flowerscreen" || v == "flower_screen" || v == "flower") {
        return BuiltinBehaviorType::CorruptScreen;
    }
    if (v == "crowd") {
        return BuiltinBehaviorType::Crowd;
    }
    if (v == "crossing" || v == "cross") {
        return BuiltinBehaviorType::Crossing;
    }
    if (v == "crosscount" || v == "cross_count" || v == "cross-count") {
        return BuiltinBehaviorType::CrossCount;
    }
    if (v == "loitering" || v == "stay") {
        return BuiltinBehaviorType::Loitering;
    }
    if (v == "absence" || v == "noone") {
        return BuiltinBehaviorType::Absence;
    }
    if (v == "unattended" || v == "leave") {
        return BuiltinBehaviorType::Unattended;
    }

    return fallback;
}

std::string builtinBehaviorTypeToString(BuiltinBehaviorType t) {
    switch (t) {
    case BuiltinBehaviorType::Intrusion:
        return "intrusion";
    case BuiltinBehaviorType::Super:
        return "super";
    case BuiltinBehaviorType::Motion:
        return "motion";
    case BuiltinBehaviorType::Occlusion:
        return "occlusion";
    case BuiltinBehaviorType::GrayScreen:
        return "grayscreen";
    case BuiltinBehaviorType::CorruptScreen:
        return "corruptscreen";
    case BuiltinBehaviorType::Crowd:
        return "crowd";
    case BuiltinBehaviorType::Crossing:
        return "crossing";
    case BuiltinBehaviorType::CrossCount:
        return "crosscount";
    case BuiltinBehaviorType::Loitering:
        return "loitering";
    case BuiltinBehaviorType::Absence:
        return "absence";
    case BuiltinBehaviorType::Unattended:
        return "unattended";
    default:
        return "intrusion";
    }
}

std::vector<std::string> parseBehaviorTargetsLowerCsv(const std::string& objectCodeCsv) {
    std::vector<std::string> targetsLower;
    std::string currentToken;
    for (char ch : objectCodeCsv) {
        if (ch == ',') {
            if (const auto token = to_lower_copy(trim_copy(currentToken)); !token.empty()) {
                targetsLower.push_back(token);
            }
            currentToken.clear();
            continue;
        }

        currentToken.push_back(ch);
    }

    if (const auto tailToken = to_lower_copy(trim_copy(currentToken)); !tailToken.empty()) {
        targetsLower.push_back(tailToken);
    }
    return targetsLower;
}

BehaviorApiConfig parseBehaviorApiConfig(
    const std::string& behaviorConfigJson,
    const std::string& behaviorAlgorithmCode,
    const std::string& objectCodeCsv
) {
    BehaviorApiConfig cfg{};
    cfg.targetsLower = parseBehaviorTargetsLowerCsv(objectCodeCsv);

    Json::Value root;
    if (!parse_json_object(behaviorConfigJson, root)) {
        // v2 fallback: allow behaviorAlgorithmCode to select built-in rule
        cfg.builtinBehavior = parseBuiltinBehaviorType(behaviorAlgorithmCode, BuiltinBehaviorType::Intrusion);
        return cfg;
    }

    cfg.apiVersion = normalized_api_version(root, cfg.apiVersion);
    cfg.builtinBehavior = parseBuiltinBehaviorType(
        resolve_builtin_behavior_name(root, behaviorAlgorithmCode, cfg.apiVersion),
        BuiltinBehaviorType::Intrusion);

    cfg.regionIouThresh = clamp01(json_get_float(root, "regionIouThresh", cfg.regionIouThresh));
    cfg.regionIouThresh = clamp01(json_get_float(root, "regionIou", cfg.regionIouThresh));

    // SUPER: bbox center-point selection (ratio in [0,1]).
    cfg.centerPointX = clamp01(json_get_float(root, "centerPointX", cfg.centerPointX));
    cfg.centerPointX = clamp01(json_get_float(root, "centerX", cfg.centerPointX));
    cfg.centerPointX = clamp01(json_get_float(root, "center_x", cfg.centerPointX));
    cfg.centerPointX = clamp01(json_get_float(root, "center_point_x", cfg.centerPointX));

    cfg.centerPointY = clamp01(json_get_float(root, "centerPointY", cfg.centerPointY));
    cfg.centerPointY = clamp01(json_get_float(root, "centerY", cfg.centerPointY));
    cfg.centerPointY = clamp01(json_get_float(root, "center_y", cfg.centerPointY));
    cfg.centerPointY = clamp01(json_get_float(root, "center_point_y", cfg.centerPointY));

    cfg.debug = json_get_bool(root, "debug", cfg.debug);
    cfg.debug = json_get_bool(root, "enableDebug", cfg.debug);
    cfg.debug = json_get_bool(root, "logDebug", cfg.debug);

    apply_crowd_config(root, cfg);
    apply_motion_config(root, cfg);

    return cfg;
}

const BehaviorApiConfig& BehaviorApiConfigCache::get(
    const std::string& behaviorConfigJson,
    const std::string& behaviorAlgorithmCode,
    const std::string& objectCodeCsv
) {
    if (!mHasValue ||
        behaviorConfigJson != mLastBehaviorConfigJson ||
        behaviorAlgorithmCode != mLastBehaviorAlgorithmCode ||
        objectCodeCsv != mLastObjectCodeCsv) {
        mCached = parseBehaviorApiConfig(behaviorConfigJson, behaviorAlgorithmCode, objectCodeCsv);
        mLastBehaviorConfigJson = behaviorConfigJson;
        mLastBehaviorAlgorithmCode = behaviorAlgorithmCode;
        mLastObjectCodeCsv = objectCodeCsv;
        mHasValue = true;
        mParseCount += 1;
    }
    return mCached;
}

}  // namespace AVSAnalyzer
