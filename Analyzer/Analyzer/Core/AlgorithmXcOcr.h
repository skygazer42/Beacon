#ifndef ANALYZER_ALGORITHM_XC_OCR_H
#define ANALYZER_ALGORITHM_XC_OCR_H

#include "Algorithm.h"

#include <memory>

namespace AVSAnalyzer {

// XcOCR framework (best-effort):
// - Treat the underlying model as a "character detector" that outputs one DetectObject per character.
// - Post-process detections into one or multiple "text line" objects (e.g., license plate string).
//
// This design is engine-agnostic: the inner Algorithm can be OpenVINO/ONNXRuntime/plugin/.rknn/.om.
class AlgorithmXcOcr final : public Algorithm {
public:
    AlgorithmXcOcr(Config* config, std::unique_ptr<Algorithm> inner);
    ~AlgorithmXcOcr() override = default;

    bool objectDetect(cv::Mat& image,
                      std::vector<DetectObject>& detects,
                      float scoreThreshold,
                      float nmsThreshold) override;

private:
    std::unique_ptr<Algorithm> mInner;
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_ALGORITHM_XC_OCR_H
