#include "YoloDetectionPostprocess.h"
#include "YoloSegmentationPostprocess.h"

#include <cassert>
#include <cmath>
#include <string>
#include <vector>

using namespace AVSAnalyzer;

namespace {

static bool nearly(float a, float b, float eps = 1e-4f) {
    return std::fabs(a - b) <= eps;
}

}  // namespace

int main() {
    {
        YoloSegmentationPrototypeLayout layout;
        std::string err;
        const bool ok = parseYoloSegmentationPrototypeLayout({1, 32, 160, 160}, 32, layout, err);
        assert(ok);
        assert(err.empty());
        assert(layout.channels == 32);
        assert(layout.height == 160);
        assert(layout.width == 160);
        assert(layout.channelsFirst == true);
    }

    {
        size_t idx = 0;
        YoloSegmentationPrototypeLayout layout;
        std::string err;
        const bool ok = selectYoloSegmentationPrototypeOutput(
            {{1, 7, 1}, {1, 2, 4, 4}},
            /*detectionIndex=*/0,
            /*coeffDim=*/2,
            idx,
            layout,
            err);
        assert(ok);
        assert(err.empty());
        assert(idx == 1);
        assert(layout.channels == 2);
        assert(layout.height == 4);
        assert(layout.width == 4);
    }

    cv::Mat detOutput(1, 7, CV_32F);
    detOutput.at<float>(0, 0) = 2.0f;   // cx
    detOutput.at<float>(0, 1) = 2.0f;   // cy
    detOutput.at<float>(0, 2) = 2.0f;   // w
    detOutput.at<float>(0, 3) = 2.0f;   // h
    detOutput.at<float>(0, 4) = 0.95f;  // class 0 score
    detOutput.at<float>(0, 5) = 1.0f;   // mask coeff ch0
    detOutput.at<float>(0, 6) = 0.0f;   // mask coeff ch1

    std::vector<float> proto(2 * 4 * 4, -10.0f);
    for (int y = 1; y <= 2; ++y) {
        for (int x = 1; x <= 2; ++x) {
            proto[0 * 16 + y * 4 + x] = 10.0f;
        }
    }

    YoloSegmentationPrototypeLayout protoLayout;
    protoLayout.channels = 2;
    protoLayout.height = 4;
    protoLayout.width = 4;
    protoLayout.channelsFirst = true;

    std::vector<std::string> classNames = {"person"};
    YoloDetectionFormat format = inferYoloDetectionFormat(detOutput.cols, static_cast<int>(classNames.size()), "synthetic-seg.onnx");
	    format.outputDim = detOutput.cols;

	    std::vector<DetectObject> detects;
	    std::string err;
	    YoloSegmentationDecodeOptions options;
	    options.classNames = &classNames;
	    options.scoreThreshold = 0.25f;
	    options.nmsThreshold = 0.5f;
	    options.xFactor = 1.0f;
	    options.yFactor = 1.0f;
	    options.imageWidth = 4;
	    options.imageHeight = 4;
	    YoloDetectionDecodeOutput output;
	    output.format = &format;
	    output.detects = &detects;
	    output.errMsg = &err;
	    const bool ok = decodeYoloSegmentationDetections(detOutput, proto.data(), protoLayout, options, output);
    assert(ok);
    assert(err.empty());
    assert(detects.size() == 1);
    assert(detects[0].class_name == "person");
    assert(nearly(detects[0].class_score, 0.95f));
    assert(detects[0].x1 == 1);
    assert(detects[0].y1 == 1);
    assert(detects[0].x2 == 3);
    assert(detects[0].y2 == 3);
    assert(detects[0].hasSegmentation == true);
    assert(detects[0].segmentation.size() >= 4);

    float minX = 1e9f;
    float minY = 1e9f;
    float maxX = -1e9f;
    float maxY = -1e9f;
    for (const auto& p : detects[0].segmentation) {
        minX = std::min(minX, p.x);
        minY = std::min(minY, p.y);
        maxX = std::max(maxX, p.x);
        maxY = std::max(maxY, p.y);
    }
    assert(minX >= 0.5f && minX <= 1.5f);
    assert(minY >= 0.5f && minY <= 1.5f);
    assert(maxX >= 1.5f && maxX <= 3.5f);
    assert(maxY >= 1.5f && maxY <= 3.5f);

    return 0;
}
