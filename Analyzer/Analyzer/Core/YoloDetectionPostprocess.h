#ifndef ANALYZER_YOLO_DETECTION_POSTPROCESS_H
#define ANALYZER_YOLO_DETECTION_POSTPROCESS_H

#include "Algorithm.h"

#include <string>
#include <vector>

namespace AVSAnalyzer {

struct YoloDetectionFormat {
    int outputDim = 0;
    bool hasObjectness = false;
    bool hasAngle = false;
    bool index4ObjOrAngleAmbiguous = false;
    bool index4ObjOrAngleDecided = false;
    bool index4UseObjectness = true;
    int classOffset = 4;
};

struct YoloDetectionDecodeOptions {
    const std::vector<std::string>* classNames = nullptr;
    float scoreThreshold = 0.25f;
    float nmsThreshold = 0.5f;
    float xFactor = 1.0f;
    float yFactor = 1.0f;
};

struct YoloDetectionDecodeOutput {
    YoloDetectionFormat* format = nullptr;
    std::vector<DetectObject>* detects = nullptr;
    std::string* errMsg = nullptr;
};

YoloDetectionFormat inferYoloDetectionFormat(
    int outputDim,
    int classCount,
    const std::string& modelPathHint
);

void resolveAmbiguousYoloDetectionFormat(
    const cv::Mat& detOutput,
    YoloDetectionFormat& format
);

bool decodeYoloDetections(
    const cv::Mat& detOutput,
    const YoloDetectionDecodeOptions& options,
    YoloDetectionDecodeOutput& output
);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_YOLO_DETECTION_POSTPROCESS_H
