#ifndef ANALYZER_PIPELINE_MODE_ADVANCED_H
#define ANALYZER_PIPELINE_MODE_ADVANCED_H

#include <string>
#include <vector>

#include <opencv2/opencv.hpp>

#include "Algorithm.h"
#include "Control.h"

namespace Json {
class Value;
}

namespace AVSAnalyzer {

class FaceDb;

struct PipelineDetectConfig {
    bool detect1Enabled = true;
    bool detect2Enabled = true;
    std::string detectLogic = "and";   // and/or
    std::string detect2Input = "roi";  // roi/full
};

PipelineDetectConfig parsePipelineDetectConfig(const std::string& behaviorConfigJson);

// Shared helpers for classification-oriented pipeline modes.
// They normalize classifier outputs against Control::objects_v1 so pipeline modes 3/4/6/7
// can handle label-name outputs and class_id-only outputs consistently.
void fillPipelineClassNameFromControl(const Control* control, DetectObject& detect);
void applyPipelineClassificationResult(const Control* control, const DetectObject& classResult, DetectObject& detect);
bool pipelineDetectMatchesObjectCode(const Control* control, DetectObject& detect);

// Pipeline mode 6: classification -> detect -> behavior
// - classification is used as a frame gate (industrial-friendly background/scene filter).
// - if classification does not match, the pipeline returns success with happen=false.
bool runPipelineMode6(
    const Control* control,
    Algorithm* classifier,
    Algorithm* detector,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore);

// Pipeline mode 7: detect -> classification -> feature -> behavior
// - classification is applied on each detection ROI (similar to mode 3).
// - feature step is best-effort: if featureAlgorithm supports embeddings, attach metadata to DetectObject::attributes.
bool runPipelineMode7(
    const Control* control,
    Algorithm* detector,
    Algorithm* classifier,
    Algorithm* featureAlgorithm,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore,
    const FaceDb* faceDb = nullptr,
    Json::Value* userData = nullptr);

// Pipeline mode 8: detect -> detect -> behavior
// Notes:
// - detector2 is optional (nullptr => treat as disabled).
// - We keep output compatible with existing DetectObject: when detect2Input=roi,
//   sub-detections are attached to detect1 objects via DetectObject::subObjects.
bool runPipelineMode8(
    const Control* control,
    Algorithm* detector1,
    Algorithm* detector2,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore);

// Pipeline mode 9: detect -> feature -> detect -> behavior
// - featureAlgorithm is optional; when present, embeddings are computed for ROI and
//   stored as best-effort numeric attributes (norm/dim) in DetectObject::attributes.
bool runPipelineMode9(
    const Control* control,
    Algorithm* detector1,
    Algorithm* featureAlgorithm,
    Algorithm* detector2,
    cv::Mat& image,
    std::vector<DetectObject>& happenDetects,
    bool& happen,
    float& happenScore,
    const FaceDb* faceDb = nullptr,
    Json::Value* userData = nullptr);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_PIPELINE_MODE_ADVANCED_H
