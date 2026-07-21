#include "DetectObjectJson.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <exception>
#include <limits>
#include <stdexcept>

#include <json/json.h>

namespace AVSAnalyzer {
namespace {

bool parse_boolish(const Json::Value& v, bool defaultValue) {
    if (v.isBool()) {
        return v.asBool();
    }
    if (v.isNumeric()) {
        return v.asInt() != 0;
    }
    if (v.isString()) {
        std::string s = v.asString();
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (s == "1" || s == "true" || s == "yes" || s == "on") {
            return true;
        }
        if (s == "0" || s == "false" || s == "no" || s == "off") {
            return false;
        }
    }
    return defaultValue;
}

int parse_intish(const Json::Value& v, int defaultValue) {
    if (v.isInt()) {
        return v.asInt();
    }
    if (v.isUInt()) {
        const auto u = v.asUInt();
        if (u > static_cast<Json::UInt>(std::numeric_limits<int>::max())) {
            return std::numeric_limits<int>::max();
        }
        return static_cast<int>(u);
    }
    if (v.isNumeric()) {
        return v.asInt();
    }
    if (v.isString()) {
        try {
            return std::stoi(v.asString());
        }
        catch (const std::invalid_argument&) {
            return defaultValue;
        }
        catch (const std::out_of_range&) {
            return defaultValue;
        }
    }
    return defaultValue;
}

float parse_floatish(const Json::Value& v, float defaultValue) {
    if (v.isNumeric()) {
        return v.asFloat();
    }
    if (v.isString()) {
        try {
            return std::stof(v.asString());
        }
        catch (const std::invalid_argument&) {
            return defaultValue;
        }
        catch (const std::out_of_range&) {
            return defaultValue;
        }
    }
    return defaultValue;
}

bool parse_keypoints(const Json::Value& keypointsVal, std::vector<DetectObject::Keypoint>& out) {
    out.clear();

    if (keypointsVal.isNull()) {
        return false;
    }

    // Allow stringified JSON for industrial integrations (best-effort).
    if (keypointsVal.isString()) {
        const std::string s = keypointsVal.asString();
        if (s.empty()) {
            return false;
        }
        Json::CharReaderBuilder builder;
        const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
        Json::Value parsed;
        JSONCPP_STRING errs;
        if (!reader->parse(s.data(), s.data() + s.size(), &parsed, &errs) || !errs.empty()) {
            return false;
        }
        return parse_keypoints(parsed, out);
    }

    if (!keypointsVal.isArray()) {
        return false;
    }

    const Json::ArrayIndex n = keypointsVal.size();
    if (n == 0) {
        return false;
    }

    const Json::Value& first = keypointsVal[0];

    // Format 1: [{x,y,confidence}, ...]
    if (first.isObject()) {
        out.reserve(static_cast<size_t>(n));
        for (Json::ArrayIndex i = 0; i < n; ++i) {
            const Json::Value& kp = keypointsVal[i];
            if (!kp.isObject()) {
                continue;
            }
            const float x = parse_floatish(kp["x"], 0.0f);
            const float y = parse_floatish(kp["y"], 0.0f);
            float c = 0.0f;
            if (kp.isMember("confidence")) {
                c = parse_floatish(kp["confidence"], 0.0f);
            }
            else if (kp.isMember("score")) {
                c = parse_floatish(kp["score"], 0.0f);
            }
            else if (kp.isMember("conf")) {
                c = parse_floatish(kp["conf"], 0.0f);
            }
            out.emplace_back(x, y, c);
        }
        return !out.empty();
    }

    // Format 2: [[x,y,c], ...] or [[x,y], ...]
    if (first.isArray()) {
        out.reserve(static_cast<size_t>(n));
        for (Json::ArrayIndex i = 0; i < n; ++i) {
            const Json::Value& kp = keypointsVal[i];
            if (!kp.isArray() || kp.size() < 2) {
                continue;
            }
            const float x = parse_floatish(kp[0], 0.0f);
            const float y = parse_floatish(kp[1], 0.0f);
            const float c = (kp.size() >= 3) ? parse_floatish(kp[2], 0.0f) : 0.0f;
            out.emplace_back(x, y, c);
        }
        return !out.empty();
    }

    // Format 3: flat [x,y,c,x,y,c,...] or [x,y,x,y,...]
    if (first.isNumeric() || first.isString()) {
        // Decide stride.
        size_t stride = 0;
        if ((n % 3) == 0) {
            stride = 3;
        }
        else if ((n % 2) == 0) {
            stride = 2;
        }
        else {
            return false;
        }

        out.reserve(static_cast<size_t>(n / static_cast<Json::ArrayIndex>(stride)));
        for (Json::ArrayIndex i = 0; i + 1 < n; i += static_cast<Json::ArrayIndex>(stride)) {
            const float x = parse_floatish(keypointsVal[i], 0.0f);
            const float y = parse_floatish(keypointsVal[i + 1], 0.0f);
            float c = 0.0f;
            if (stride == 3 && (i + 2) < n) {
                c = parse_floatish(keypointsVal[i + 2], 0.0f);
            }
            else if (stride == 2) {
                // Unknown confidence in this format.
                c = 1.0f;
            }
            out.emplace_back(x, y, c);
        }
        return !out.empty();
    }

    return false;
}

bool parse_points_2d(const Json::Value& pointsVal, std::vector<cv::Point2f>& out) {
    out.clear();

    if (pointsVal.isNull()) {
        return false;
    }

    if (pointsVal.isString()) {
        const std::string s = pointsVal.asString();
        if (s.empty()) {
            return false;
        }
        Json::CharReaderBuilder builder;
        const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
        Json::Value parsed;
        JSONCPP_STRING errs;
        if (!reader->parse(s.data(), s.data() + s.size(), &parsed, &errs) || !errs.empty()) {
            return false;
        }
        return parse_points_2d(parsed, out);
    }

    if (!pointsVal.isArray()) {
        return false;
    }

    const Json::ArrayIndex n = pointsVal.size();
    if (n == 0) {
        return false;
    }

    const Json::Value& first = pointsVal[0];

    if (first.isArray() || first.isObject()) {
        out.reserve(static_cast<size_t>(n));
        for (Json::ArrayIndex i = 0; i < n; ++i) {
            const Json::Value& p = pointsVal[i];
            if (p.isArray() && p.size() >= 2) {
                out.emplace_back(
                    parse_floatish(p[0], 0.0f),
                    parse_floatish(p[1], 0.0f));
            } else if (p.isObject()) {
                out.emplace_back(
                    parse_floatish(p.get("x", 0.0f), 0.0f),
                    parse_floatish(p.get("y", 0.0f), 0.0f));
            }
        }
        return out.size() >= 3;
    }

    if (first.isNumeric() || first.isString()) {
        if ((n % 2) != 0) {
            return false;
        }
        out.reserve(static_cast<size_t>(n / 2));
        for (Json::ArrayIndex i = 0; i + 1 < n; i += 2) {
            out.emplace_back(
                parse_floatish(pointsVal[i], 0.0f),
                parse_floatish(pointsVal[i + 1], 0.0f));
        }
        return out.size() >= 3;
    }

    return false;
}

}  // namespace

Json::Value detectObjectToJson(const DetectObject& d) {
    Json::Value item;
    item["x1"] = d.x1;
    item["y1"] = d.y1;
    item["x2"] = d.x2;
    item["y2"] = d.y2;
    item["class_id"] = d.class_id;
    item["class_score"] = d.class_score;
    item["class_name"] = d.class_name;

    if (d.hasObb) {
        // Compact format: flat [x1,y1,x2,y2,x3,y3,x4,y4] (float).
        Json::Value obb(Json::arrayValue);
        obb.resize(8);
        for (Json::ArrayIndex i = 0; i < 4; ++i) {
            obb[i * 2] = d.obb[i].x;
            obb[i * 2 + 1] = d.obb[i].y;
        }
        item["obb"] = obb;
    }

    if (d.hasSegmentation && d.segmentation.size() >= 3) {
        Json::Value polygon(Json::arrayValue);
        polygon.resize(static_cast<Json::ArrayIndex>(d.segmentation.size()));
        for (Json::ArrayIndex i = 0; i < static_cast<Json::ArrayIndex>(d.segmentation.size()); ++i) {
            Json::Value p(Json::arrayValue);
            p.append(d.segmentation[i].x);
            p.append(d.segmentation[i].y);
            polygon[i] = p;
        }
        item["polygon"] = polygon;
    }

    const bool hasPose = d.hasPose || (!d.keypoints.empty());
    if (hasPose) {
        item["hasPose"] = true;
        if (!d.keypoints.empty()) {
            Json::Value kps(Json::arrayValue);
            kps.resize(static_cast<Json::ArrayIndex>(d.keypoints.size()));
            for (Json::ArrayIndex i = 0; i < static_cast<Json::ArrayIndex>(d.keypoints.size()); ++i) {
                Json::Value kp;
                kp["x"] = d.keypoints[i].x;
                kp["y"] = d.keypoints[i].y;
                kp["confidence"] = d.keypoints[i].confidence;
                kps[i] = kp;
            }
            item["keypoints"] = kps;
        }
    }

    return item;
}

bool parseDetectObjectFromJson(const Json::Value& item, DetectObject& out, std::string* errMsg) {
    if (!item.isObject()) {
        if (errMsg) {
            *errMsg = "detect item must be a JSON object";
        }
        return false;
    }

    out = DetectObject{};

    out.x1 = parse_intish(item.get("x1", 0), 0);
    out.y1 = parse_intish(item.get("y1", 0), 0);
    out.x2 = parse_intish(item.get("x2", 0), 0);
    out.y2 = parse_intish(item.get("y2", 0), 0);

    out.class_id = parse_intish(item.get("class_id", 0), 0);
    out.class_score = parse_floatish(item.get("class_score", 0.0f), 0.0f);
    out.class_name = item.get("class_name", "").asString();

    // Pose keypoints parsing.
    std::vector<DetectObject::Keypoint> kps;
    bool gotKeypoints = false;

    if (item.isMember("keypoints")) {
        gotKeypoints = parse_keypoints(item["keypoints"], kps);
    }
    else if (item.isMember("pose") && item["pose"].isObject() && item["pose"].isMember("keypoints")) {
        gotKeypoints = parse_keypoints(item["pose"]["keypoints"], kps);
    }

    if (gotKeypoints) {
        out.hasPose = true;
        out.keypoints = std::move(kps);
    }
    else {
        out.hasPose = parse_boolish(item.get("hasPose", false), false);
        out.keypoints.clear();
    }

    // OBB parsing (best-effort).
    out.hasObb = false;
    if (item.isMember("obb")) {
        const Json::Value& v = item["obb"];
        if (v.isArray()) {
            // Format 1: flat [x1,y1,x2,y2,x3,y3,x4,y4]
            if (v.size() == 8 && (v[0].isNumeric() || v[0].isString())) {
                bool ok = true;
                for (Json::ArrayIndex i = 0; i < 4; ++i) {
                    out.obb[i].x = parse_floatish(v[i * 2], 0.0f);
                    out.obb[i].y = parse_floatish(v[i * 2 + 1], 0.0f);
                }
                out.hasObb = ok;
            }
            // Format 2: [[x,y], ...] or [{x,y}, ...]
            else if (v.size() == 4) {
                bool ok = true;
                for (Json::ArrayIndex i = 0; i < 4; ++i) {
                    const Json::Value& p = v[i];
                    if (p.isArray() && p.size() >= 2) {
                        out.obb[i].x = parse_floatish(p[0], 0.0f);
                        out.obb[i].y = parse_floatish(p[1], 0.0f);
                    } else if (p.isObject()) {
                        out.obb[i].x = parse_floatish(p.get("x", 0.0f), 0.0f);
                        out.obb[i].y = parse_floatish(p.get("y", 0.0f), 0.0f);
                    } else {
                        ok = false;
                        break;
                    }
                }
                out.hasObb = ok;
            }
        }
    }

    out.hasSegmentation = false;
    out.segmentation.clear();
    if (item.isMember("polygon")) {
        out.hasSegmentation = parse_points_2d(item["polygon"], out.segmentation);
    } else if (item.isMember("segmentation")) {
        out.hasSegmentation = parse_points_2d(item["segmentation"], out.segmentation);
    } else if (item.isMember("segment")) {
        out.hasSegmentation = parse_points_2d(item["segment"], out.segmentation);
    }
    if (!out.hasSegmentation) {
        out.segmentation.clear();
    }

    if (errMsg) {
        errMsg->clear();
    }
    return true;
}

}  // namespace AVSAnalyzer
