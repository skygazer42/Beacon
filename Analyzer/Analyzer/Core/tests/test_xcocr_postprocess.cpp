#include "AlgorithmXcOcr.h"

#include <cassert>
#include <memory>

namespace AVSAnalyzer {
namespace {

class DummyCharDetector final : public Algorithm {
public:
    DummyCharDetector() : Algorithm(/*config=*/nullptr) { setCreateState(true); }
    ~DummyCharDetector() override = default;

    void setDetections(std::vector<DetectObject> dets) {
        mDets = std::move(dets);
    }

    bool objectDetect(cv::Mat& /*image*/,
                      std::vector<DetectObject>& detects,
                      float /*scoreThreshold*/,
                      float /*nmsThreshold*/) override {
        detects = mDets;
        return true;
    }

private:
    std::vector<DetectObject> mDets;
};

DetectObject make_char(int x1, int y1, int x2, int y2, const std::string& text, float score = 0.9f) {
    DetectObject d{};
    d.x1 = x1;
    d.y1 = y1;
    d.x2 = x2;
    d.y2 = y2;
    d.class_name = text;
    d.class_id = 0;
    d.class_score = score;
    return d;
}

}  // namespace
}  // namespace AVSAnalyzer

int main() {
    using namespace AVSAnalyzer;

    // Case 1: single line, x-order should be applied.
    auto inner = std::make_unique<DummyCharDetector>();
    inner->setDetections({
        make_char(30, 10, 40, 30, "1"),
        make_char(10, 12, 20, 32, "A"),
        make_char(50, 11, 60, 31, "B"),
    });

    AlgorithmXcOcr ocr(/*config=*/nullptr, /*inner=*/std::move(inner));

    cv::Mat dummy(64, 64, CV_8UC3);
    std::vector<DetectObject> out;
    assert(ocr.objectDetect(dummy, out, 0.0f, 0.0f) == true);
    assert(out.size() == 1);
    assert(out[0].class_name == "A1B");
    assert(out[0].x1 == 10);
    assert(out[0].y1 == 10);
    assert(out[0].x2 == 60);
    assert(out[0].y2 == 32);
    assert(out[0].subObjects.size() == 3);

    // Case 2: two lines should produce two outputs (best-effort grouping by y).
    auto inner2 = std::make_unique<DummyCharDetector>();
    inner2->setDetections({
        make_char(10, 10, 20, 30, "A"),
        make_char(22, 10, 32, 30, "B"),
        make_char(10, 60, 20, 80, "1"),
        make_char(22, 60, 32, 80, "2"),
    });
    AlgorithmXcOcr ocr2(/*config=*/nullptr, /*inner=*/std::move(inner2));
    out.clear();
    assert(ocr2.objectDetect(dummy, out, 0.0f, 0.0f) == true);
    assert(out.size() == 2);
    assert(out[0].class_name == "AB");
    assert(out[1].class_name == "12");

    return 0;
}
