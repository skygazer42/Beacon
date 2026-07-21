#ifndef ANALYZER_YOLO_SEGMENTATION_POSTPROCESS_H
#define ANALYZER_YOLO_SEGMENTATION_POSTPROCESS_H

#include "YoloDetectionPostprocess.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace AVSAnalyzer {

struct YoloSegmentationPrototypeLayout {
    int channels = 0;
    int height = 0;
    int width = 0;
    bool channelsFirst = true;
};

bool parseYoloSegmentationPrototypeLayout(
    const std::vector<int64_t>& shape,
    int coeffDim,
    YoloSegmentationPrototypeLayout& out,
    std::string& errMsg
);

bool selectYoloSegmentationPrototypeOutput(
    const std::vector<std::vector<int64_t>>& outputShapes,
    size_t detectionIndex,
    int coeffDim,
    size_t& selectedIndex,
    YoloSegmentationPrototypeLayout& selectedLayout,
    std::string& errMsg
);

struct YoloSegmentationDecodeOptions {
    const std::vector<std::string>* classNames = nullptr;
    float scoreThreshold = 0.25f;
    float nmsThreshold = 0.5f;
    float xFactor = 1.0f;
    float yFactor = 1.0f;
    int imageWidth = 0;
    int imageHeight = 0;
};

bool decodeYoloSegmentationDetections(
    const cv::Mat& detOutput,
    const float* protoData,
    const YoloSegmentationPrototypeLayout& protoLayout,
    const YoloSegmentationDecodeOptions& options,
    YoloDetectionDecodeOutput& output
);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_YOLO_SEGMENTATION_POSTPROCESS_H
