#include "PipelineModeAdvanced.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <json/json.h>
#include <memory>

#include "DetectObjectGeometry.h"
#include "FaceDb.h"
#include "RecognitionRegions.h"
#include "Utils/CalcuIOU.h"

namespace {

std::string to_lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool parse_json_object(const std::string& text, Json::Value& out, std::string& err) {
    out = Json::Value(Json::objectValue);
    err.clear();
    if (text.empty()) {
        return true;
    }

    Json::CharReaderBuilder builder;
    builder["collectComments"] = false;
    std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
    const char* begin = text.data();
    const char* end = text.data() + text.size();
    if (!reader->parse(begin, end, &out, &err)) {
        return false;
    }
    if (!out.isObject()) {
        err = "config must be a JSON object";
        return false;
    }
    return true;
}

bool json_get_bool(const Json::Value& root, const char* key, bool default_value) {
    if (!root.isObject() || key == nullptr) {
        return default_value;
    }
    const Json::Value v = root.get(key, Json::Value());
    if (v.isBool()) return v.asBool();
    if (v.isInt()) return v.asInt() != 0;
    if (v.isUInt()) return v.asUInt() != 0;
    if (v.isString()) {
        const std::string s = to_lower_copy(v.asString());
        if (s == "1" || s == "true" || s == "yes" || s == "on") return true;
        if (s == "0" || s == "false" || s == "no" || s == "off") return false;
    }
    return default_value;
}

float json_get_float(const Json::Value& root, const char* key, float default_value) {
    if (!root.isObject() || key == nullptr) {
        return default_value;
    }
    const Json::Value v = root.get(key, Json::Value());
    if (v.isDouble()) return static_cast<float>(v.asDouble());
    if (v.isInt()) return static_cast<float>(v.asInt());
    if (v.isUInt()) return static_cast<float>(v.asUInt());
    if (v.isString()) {
        try {
            return std::stof(v.asString());
        } catch (...) {
            return default_value;
        }
    }
    return default_value;
}

std::string json_get_string_lower(const Json::Value& root, const char* key, const std::string& default_value) {
    if (!root.isObject() || key == nullptr) {
        return default_value;
    }
    const Json::Value v = root.get(key, Json::Value());
    if (v.isString()) {
        return to_lower_copy(v.asString());
    }
    return default_value;
}

double calcRecognitionCoverageRatio(const AVSAnalyzer::Control* control, const std::vector<double>& object_d) {
    if (!control) {
        return 0.0;
    }
    if (!control->recognitionRegions_d.empty()) {
        return AVSAnalyzer::calcMaxCoverageRatio(control->recognitionRegions_d, object_d);
    }
    if (!control->recognitionRegion_d.empty()) {
        return AVSAnalyzer::CalcuPolygonIOU(control->recognitionRegion_d, object_d);
    }
    // No region configured => treat as full-image pass (industrial-safe default).
    return 1.0;
}

bool inRecognitionRegion(const AVSAnalyzer::Control* control, const AVSAnalyzer::DetectObject& detect) {
    const std::vector<double> object_d = AVSAnalyzer::detectObjectToPolygonPixels(detect);
    const double ratio = calcRecognitionCoverageRatio(control, object_d);
    return ratio >= 0.5;
}

float compute_embedding_norm(const std::vector<float>& v) {
    double sum = 0.0;
    for (float x : v) {
        if (!std::isfinite(x)) {
            continue;
        }
        sum += static_cast<double>(x) * static_cast<double>(x);
    }
    return static_cast<float>(std::sqrt(sum));
}

struct FaceStrangerConfig {
    bool enabled = false;
    float minScore = 0.5f;
    bool alarmWhenDbEmpty = false;
};

FaceStrangerConfig parseFaceStrangerConfig(const std::string& behaviorConfigJson) {
    FaceStrangerConfig cfg{};

    Json::Value root;
    std::string err;
    if (!parse_json_object(behaviorConfigJson, root, err)) {
        return cfg;
    }

    if (json_get_string_lower(root, "builtinBehavior", "") != "stranger") {
        return cfg;
    }

    cfg.enabled = true;
    const Json::Value stranger = (root.isObject() && root.isMember("stranger") && root["stranger"].isObject())
        ? root["stranger"]
        : root;

    cfg.minScore = json_get_float(
        stranger,
        "minScore",
        json_get_float(
            stranger,
            "faceMatchMinScore",
            json_get_float(stranger, "strangerMinScore", cfg.minScore)));
    if (!std::isfinite(cfg.minScore)) {
        cfg.minScore = 0.5f;
    }
    cfg.minScore = std::max(0.0f, std::min(1.0f, cfg.minScore));
    cfg.alarmWhenDbEmpty = json_get_bool(stranger, "alarmWhenDbEmpty", false);
    return cfg;
}

int applyFaceStrangerBehavior(
    const AVSAnalyzer::Control* control,
    const FaceStrangerConfig& cfg,
    const AVSAnalyzer::FaceDb* faceDb,
    const std::vector<std::vector<float>>& embeddings,
    std::vector<AVSAnalyzer::DetectObject>& detects,
    Json::Value* userData) {
    if (userData) {
        *userData = Json::Value(Json::objectValue);
    }
    if (!control || !cfg.enabled) {
        return 0;
    }

    Json::Value matches(Json::arrayValue);
    int strangerCount = 0;

    for (size_t i = 0; i < detects.size(); ++i) {
        auto& d = detects[i];
        d.happen = false;

        if (d.class_name.empty() || d.class_name != control->objectCode) {
            continue;
        }
        d.attributes["face_candidate"] = 1.0f;

        if (i >= embeddings.size() || embeddings[i].empty()) {
            d.attributes["face_found"] = 0.0f;
            d.attributes["face_stranger"] = 0.0f;
            continue;
        }

        AVSAnalyzer::FaceMatch match;
        std::string err;
        const bool searchOk = (faceDb != nullptr) && faceDb->searchNearest(embeddings[i], match, err);
        const bool dbEmpty = (err == "empty database" || err == "no enabled face");
        const bool found = searchOk && match.score >= cfg.minScore;
        const bool isStranger = searchOk ? !found : (cfg.alarmWhenDbEmpty && dbEmpty);

        d.attributes["face_found"] = found ? 1.0f : 0.0f;
        d.attributes["face_stranger"] = isStranger ? 1.0f : 0.0f;
        if (searchOk) {
            d.attributes["face_best_score"] = match.score;
            d.attributes["face_match_distance"] = match.distance;
        }
        if (isStranger) {
            d.happen = true;
            ++strangerCount;
        }

        if (!searchOk && !isStranger) {
            continue;
        }

        Json::Value item(Json::objectValue);
        item["x1"] = d.x1;
        item["y1"] = d.y1;
        item["x2"] = d.x2;
        item["y2"] = d.y2;
        item["found"] = found;
        if (searchOk) {
            item["bestScore"] = match.score;
            item["distance"] = match.distance;
            item["matchedId"] = match.id;
            item["matchedName"] = match.name;
        }
        if (!err.empty()) {
            item["reason"] = err;
        }
        matches.append(item);
    }

    if (strangerCount > 0 && userData) {
        (*userData)["behavior"] = "stranger";
        (*userData)["event"] = "STRANGER";
        (*userData)["count"] = strangerCount;
        (*userData)["minScore"] = cfg.minScore;
        (*userData)["matches"] = matches;
    }

    return strangerCount;
}

}  // namespace

namespace AVSAnalyzer {

PipelineDetectConfig parsePipelineDetectConfig(const std::string& behaviorConfigJson) {
    PipelineDetectConfig cfg{};

    Json::Value root;
    std::string err;
    if (!parse_json_object(behaviorConfigJson, root, err)) {
        return cfg;
    }

    Json::Value pipeline = root;
    if (root.isObject() && root.isMember("pipeline") && root["pipeline"].isObject()) {
        pipeline = root["pipeline"];
    }

    cfg.detect1Enabled = json_get_bool(pipeline, "detect1Enabled", cfg.detect1Enabled);
    cfg.detect2Enabled = json_get_bool(pipeline, "detect2Enabled", cfg.detect2Enabled);

    cfg.detectLogic = json_get_string_lower(pipeline, "detectLogic", cfg.detectLogic);
    if (cfg.detectLogic != "and" && cfg.detectLogic != "or") {
        cfg.detectLogic = "and";
    }

    cfg.detect2Input = json_get_string_lower(pipeline, "detect2Input", cfg.detect2Input);
    if (cfg.detect2Input == "crop") {
        cfg.detect2Input = "roi";
    }
    if (cfg.detect2Input == "full_image" || cfg.detect2Input == "image") {
        cfg.detect2Input = "full";
    }
    if (cfg.detect2Input != "roi" && cfg.detect2Input != "full") {
        cfg.detect2Input = "roi";
    }

    return cfg;
}

void fillPipelineClassNameFromControl(const Control* control, DetectObject& detect) {
    if (!control) {
        return;
    }
    if (!detect.class_name.empty()) {
        return;
    }
    const int id = detect.class_id;
    if (id >= 0 && id < control->objects_v1_len) {
        detect.class_name = control->objects_v1[id];
    }
}

void applyPipelineClassificationResult(const Control* control, const DetectObject& classResult, DetectObject& detect) {
    detect.class_id = classResult.class_id;
    detect.class_name = classResult.class_name;
    detect.class_score = classResult.class_score;
    fillPipelineClassNameFromControl(control, detect);
}

bool pipelineDetectMatchesObjectCode(const Control* control, DetectObject& detect) {
    if (!control) {
        return false;
    }
    fillPipelineClassNameFromControl(control, detect);
    return !detect.class_name.empty() && detect.class_name == control->objectCode;
}

bool runPipelineMode6(
    const Control* control,
    Algorithm* classifier,
    Algorithm* detector,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore) {
    happenDetects.clear();
    happen = false;
    happenScore = 0.0f;

    if (!control) {
        return false;
    }
    if (!detector) {
        return false;
    }

    // Step 1: classification gate (best-effort)
    if (classifier) {
        std::vector<DetectObject> classResults;
        if (classifier->objectDetect(image, classResults, control->confThresh, control->nmsThresh)) {
            bool classMatched = false;
            for (const auto& c : classResults) {
                if (!c.class_name.empty() && c.class_name == control->objectCode) {
                    classMatched = true;
                    break;
                }
            }
            if (!classMatched) {
                return true;  // gate closed => no alarm
            }
        }
    }

    // Step 2: detection
    std::vector<DetectObject> detResults;
    if (!detector->objectDetect(image, detResults, control->confThresh, control->nmsThresh)) {
        return false;
    }
    for (auto& d : detResults) {
        fillPipelineClassNameFromControl(control, d);
    }

    // Step 3: behavior (region match + target filter)
    int matchCount = 0;
    for (auto d : detResults) {
        if (!inRecognitionRegion(control, d)) {
            continue;
        }
        if (!d.class_name.empty() && d.class_name == control->objectCode) {
            d.happen = true;
            ++matchCount;
        }
        happenDetects.push_back(std::move(d));
    }

    if (matchCount > 0) {
        happen = true;
        happenScore = 1.0f;
    }
    return true;
}

bool runPipelineMode7(
    const Control* control,
    Algorithm* detector,
    Algorithm* classifier,
    Algorithm* featureAlgorithm,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore,
    const FaceDb* faceDb,
    Json::Value* userData) {
    happenDetects.clear();
    happen = false;
    happenScore = 0.0f;
    if (userData) {
        *userData = Json::Value(Json::objectValue);
    }

    if (!control) {
        return false;
    }
    if (!detector) {
        return false;
    }

    const FaceStrangerConfig strangerCfg = parseFaceStrangerConfig(control->behaviorConfig);

    // Step 1: detection
    std::vector<DetectObject> detResults;
    if (!detector->objectDetect(image, detResults, control->confThresh, control->nmsThresh)) {
        return false;
    }
    for (auto& d : detResults) {
        fillPipelineClassNameFromControl(control, d);
    }

    // Step 2: classification on ROI (best-effort)
    if (classifier) {
        for (auto& d : detResults) {
            const int x1 = std::max(0, d.x1);
            const int y1 = std::max(0, d.y1);
            const int x2 = std::min(image.cols, d.x2);
            const int y2 = std::min(image.rows, d.y2);
            if (x2 <= x1 || y2 <= y1) {
                continue;
            }

            cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
            cv::Mat roiImage = image(roi);

            std::vector<DetectObject> classResults;
            if (!classifier->objectDetect(roiImage, classResults, control->confThresh, control->nmsThresh)) {
                continue;
            }
            if (!classResults.empty()) {
                d.class_name = classResults[0].class_name;
                d.class_score = classResults[0].class_score;
            }
        }
    }

    // Step 3: behavior gate (region match + target filter)
    int matchCount = 0;
    std::vector<DetectObject> regionMatched;
    regionMatched.reserve(detResults.size());
    for (auto d : detResults) {
        if (!inRecognitionRegion(control, d)) {
            continue;
        }
        if (!strangerCfg.enabled && !d.class_name.empty() && d.class_name == control->objectCode) {
            d.happen = true;
            ++matchCount;
        }
        regionMatched.push_back(std::move(d));
    }

    // Step 4: feature step (best-effort)
    std::vector<std::vector<float>> embeddings;
    if (featureAlgorithm && !regionMatched.empty()) {
        std::vector<cv::Mat> rois;
        rois.reserve(regionMatched.size());
        std::vector<cv::Rect> rects;
        rects.reserve(regionMatched.size());

        for (const auto& d : regionMatched) {
            const int x1 = std::max(0, d.x1);
            const int y1 = std::max(0, d.y1);
            const int x2 = std::min(image.cols, d.x2);
            const int y2 = std::min(image.rows, d.y2);
            if (x2 <= x1 || y2 <= y1) {
                rects.emplace_back();
                rois.emplace_back();
                continue;
            }
            cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
            rects.push_back(roi);
            rois.push_back(image(roi));
        }

        std::string errMsg;
        if (featureAlgorithm->extractEmbeddings(rois, embeddings, errMsg) && embeddings.size() == rois.size()) {
            const int dim = featureAlgorithm->embeddingDim();
            for (size_t i = 0; i < regionMatched.size(); ++i) {
                const float norm = compute_embedding_norm(embeddings[i]);
                regionMatched[i].attributes["feature_dim"] = static_cast<float>(dim);
                regionMatched[i].attributes["feature_norm"] = norm;
            }
        }
    }

    if (strangerCfg.enabled) {
        matchCount = applyFaceStrangerBehavior(control, strangerCfg, faceDb, embeddings, regionMatched, userData);
    }

    happenDetects = std::move(regionMatched);
    if (matchCount > 0) {
        happen = true;
        happenScore = 1.0f;
    }
    return true;
}

bool runPipelineMode8(
    const Control* control,
    Algorithm* detector1,
    Algorithm* detector2,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore) {
    happenDetects.clear();
    happen = false;
    happenScore = 0.0f;

    if (!control) {
        return false;
    }

    const PipelineDetectConfig cfg = parsePipelineDetectConfig(control->behaviorConfig);
    const bool useDetect1 = cfg.detect1Enabled;
    const bool useDetect2 = cfg.detect2Enabled && detector2 != nullptr;
    const bool detect2Full = (cfg.detect2Input == "full");

    std::vector<DetectObject> det1Results;
    if (useDetect1) {
        if (!detector1) {
            return false;
        }
        if (!detector1->objectDetect(image, det1Results, control->confThresh, control->nmsThresh)) {
            return false;
        }
        for (auto& d : det1Results) {
            fillPipelineClassNameFromControl(control, d);
        }
    }

    int match1 = 0;
    std::vector<DetectObject> regionMatched1;
    if (useDetect1) {
        for (auto d : det1Results) {
            if (!inRecognitionRegion(control, d)) {
                continue;
            }
            if (!d.class_name.empty() && d.class_name == control->objectCode) {
                d.happen = true;
                ++match1;
            }
            regionMatched1.push_back(std::move(d));
        }
    }

    int match2 = 0;
    std::vector<DetectObject> regionMatched2Full;
    if (useDetect2) {
        if (detect2Full) {
            std::vector<DetectObject> det2Results;
            const float thresh = (control->secondaryConfThresh > 0.0f) ? control->secondaryConfThresh : control->confThresh;
            if (!detector2->objectDetect(image, det2Results, thresh, control->nmsThresh)) {
                return false;
            }

            for (auto d : det2Results) {
                if (!inRecognitionRegion(control, d)) {
                    continue;
                }
                if (!d.class_name.empty() && d.class_name == control->objectCode) {
                    d.happen = true;
                    ++match2;
                }
                regionMatched2Full.push_back(std::move(d));
            }
        } else {
            // detect2 on ROI from detect1 results.
            const float thresh = (control->secondaryConfThresh > 0.0f) ? control->secondaryConfThresh : control->confThresh;
            for (auto& d1 : regionMatched1) {
                const int x1 = std::max(0, d1.x1);
                const int y1 = std::max(0, d1.y1);
                const int x2 = std::min(image.cols, d1.x2);
                const int y2 = std::min(image.rows, d1.y2);
                if (x2 <= x1 || y2 <= y1) {
                    continue;
                }
                cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
                cv::Mat roiImage = image(roi);

                std::vector<DetectObject> sub;
                if (!detector2->objectDetect(roiImage, sub, thresh, control->nmsThresh)) {
                    return false;
                }

                for (auto& s : sub) {
                    s.x1 += x1;
                    s.y1 += y1;
                    s.x2 += x1;
                    s.y2 += y1;
                    if (!inRecognitionRegion(control, s)) {
                        continue;
                    }
                    if (!s.class_name.empty() && s.class_name == control->objectCode) {
                        s.happen = true;
                        ++match2;
                    }
                    d1.subObjects.push_back(s);
                }
            }
        }
    }

    if (useDetect1 && !useDetect2) {
        happen = match1 > 0;
    }
    else if (!useDetect1 && useDetect2) {
        happen = match2 > 0;
    }
    else if (useDetect1 && useDetect2) {
        if (cfg.detectLogic == "or") {
            happen = (match1 > 0) || (match2 > 0);
        }
        else {
            happen = (match1 > 0) && (match2 > 0);
        }
    }

    if (useDetect1) {
        happenDetects.insert(happenDetects.end(), regionMatched1.begin(), regionMatched1.end());
    }
    if (!useDetect1 && useDetect2 && detect2Full) {
        happenDetects.insert(happenDetects.end(), regionMatched2Full.begin(), regionMatched2Full.end());
    }
    if (useDetect1 && useDetect2 && detect2Full && cfg.detectLogic == "or") {
        happenDetects.insert(happenDetects.end(), regionMatched2Full.begin(), regionMatched2Full.end());
    }

    if (happen) {
        happenScore = 1.0f;
    }

    return true;
}

bool runPipelineMode9(
    const Control* control,
    Algorithm* detector1,
    Algorithm* featureAlgorithm,
    Algorithm* detector2,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore,
    const FaceDb* faceDb,
    Json::Value* userData) {
    happenDetects.clear();
    happen = false;
    happenScore = 0.0f;
    if (userData) {
        *userData = Json::Value(Json::objectValue);
    }

    if (!control) {
        return false;
    }

    const PipelineDetectConfig cfg = parsePipelineDetectConfig(control->behaviorConfig);
    const FaceStrangerConfig strangerCfg = parseFaceStrangerConfig(control->behaviorConfig);
    const bool useDetect1 = cfg.detect1Enabled;
    const bool useDetect2 = cfg.detect2Enabled && detector2 != nullptr;
    const bool detect2Full = (cfg.detect2Input == "full");

    std::vector<DetectObject> det1Results;
    if (useDetect1) {
        if (!detector1) {
            return false;
        }
        if (!detector1->objectDetect(image, det1Results, control->confThresh, control->nmsThresh)) {
            return false;
        }
        for (auto& d : det1Results) {
            fillPipelineClassNameFromControl(control, d);
        }
    }

    int match1 = 0;
    std::vector<DetectObject> regionMatched1;
    if (useDetect1) {
        for (auto d : det1Results) {
            if (!inRecognitionRegion(control, d)) {
                continue;
            }
            if (!strangerCfg.enabled && !d.class_name.empty() && d.class_name == control->objectCode) {
                d.happen = true;
                ++match1;
            }
            regionMatched1.push_back(std::move(d));
        }
    }

    // Feature step: best-effort; never fails the pipeline.
    std::vector<std::vector<float>> embeddings;
    if (featureAlgorithm && !regionMatched1.empty()) {
        std::vector<cv::Mat> rois;
        rois.reserve(regionMatched1.size());
        std::vector<cv::Rect> rects;
        rects.reserve(regionMatched1.size());

        for (const auto& d1 : regionMatched1) {
            const int x1 = std::max(0, d1.x1);
            const int y1 = std::max(0, d1.y1);
            const int x2 = std::min(image.cols, d1.x2);
            const int y2 = std::min(image.rows, d1.y2);
            if (x2 <= x1 || y2 <= y1) {
                rects.emplace_back();
                rois.emplace_back();
                continue;
            }
            cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
            rects.push_back(roi);
            rois.push_back(image(roi));
        }

        std::string errMsg;
        if (featureAlgorithm->extractEmbeddings(rois, embeddings, errMsg) && embeddings.size() == rois.size()) {
            const int dim = featureAlgorithm->embeddingDim();
            for (size_t i = 0; i < regionMatched1.size(); ++i) {
                const float norm = compute_embedding_norm(embeddings[i]);
                regionMatched1[i].attributes["feature_dim"] = static_cast<float>(dim);
                regionMatched1[i].attributes["feature_norm"] = norm;
            }
        }
    }

    Json::Value strangerUserData(Json::objectValue);
    if (strangerCfg.enabled) {
        match1 = applyFaceStrangerBehavior(control, strangerCfg, faceDb, embeddings, regionMatched1, &strangerUserData);
    }

    int match2 = 0;
    std::vector<DetectObject> regionMatched2Full;
    if (useDetect2) {
        const float thresh = (control->secondaryConfThresh > 0.0f) ? control->secondaryConfThresh : control->confThresh;
        if (detect2Full) {
            std::vector<DetectObject> det2Results;
            if (!detector2->objectDetect(image, det2Results, thresh, control->nmsThresh)) {
                return false;
            }

            for (auto d : det2Results) {
                if (!inRecognitionRegion(control, d)) {
                    continue;
                }
                if (!d.class_name.empty() && d.class_name == control->objectCode) {
                    d.happen = true;
                    ++match2;
                }
                regionMatched2Full.push_back(std::move(d));
            }
        } else {
            for (auto& d1 : regionMatched1) {
                const int x1 = std::max(0, d1.x1);
                const int y1 = std::max(0, d1.y1);
                const int x2 = std::min(image.cols, d1.x2);
                const int y2 = std::min(image.rows, d1.y2);
                if (x2 <= x1 || y2 <= y1) {
                    continue;
                }
                cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
                cv::Mat roiImage = image(roi);

                std::vector<DetectObject> sub;
                if (!detector2->objectDetect(roiImage, sub, thresh, control->nmsThresh)) {
                    return false;
                }

                for (auto& s : sub) {
                    s.x1 += x1;
                    s.y1 += y1;
                    s.x2 += x1;
                    s.y2 += y1;
                    if (!inRecognitionRegion(control, s)) {
                        continue;
                    }
                    if (!s.class_name.empty() && s.class_name == control->objectCode) {
                        s.happen = true;
                        ++match2;
                    }
                    d1.subObjects.push_back(s);
                }
            }
        }
    }

    if (useDetect1 && !useDetect2) {
        happen = match1 > 0;
    }
    else if (!useDetect1 && useDetect2) {
        happen = strangerCfg.enabled ? false : (match2 > 0);
    }
    else if (useDetect1 && useDetect2) {
        if (strangerCfg.enabled) {
            if (cfg.detectLogic == "and") {
                happen = (match1 > 0) && (match2 > 0);
            }
            else {
                // Stranger alarm remains face-match-driven; detect2 only acts as an optional confirmer.
                happen = (match1 > 0);
            }
        }
        else if (cfg.detectLogic == "or") {
            happen = (match1 > 0) || (match2 > 0);
        }
        else {
            happen = (match1 > 0) && (match2 > 0);
        }
    }

    if (strangerCfg.enabled && !happen) {
        for (auto& d : regionMatched1) {
            d.happen = false;
        }
    }

    if (useDetect1) {
        happenDetects.insert(happenDetects.end(), regionMatched1.begin(), regionMatched1.end());
    }
    if (!strangerCfg.enabled && !useDetect1 && useDetect2 && detect2Full) {
        happenDetects.insert(happenDetects.end(), regionMatched2Full.begin(), regionMatched2Full.end());
    }
    if (!strangerCfg.enabled && useDetect1 && useDetect2 && detect2Full && cfg.detectLogic == "or") {
        happenDetects.insert(happenDetects.end(), regionMatched2Full.begin(), regionMatched2Full.end());
    }

    if (happen) {
        happenScore = 1.0f;
        if (strangerCfg.enabled && userData) {
            *userData = strangerUserData;
        }
    }

    return true;
}

}  // namespace AVSAnalyzer
