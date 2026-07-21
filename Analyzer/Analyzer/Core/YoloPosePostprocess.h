#ifndef ANALYZER_YOLOPOSEPOSTPROCESS_H
#define ANALYZER_YOLOPOSEPOSTPROCESS_H

#include <array>

namespace AVSAnalyzer {

struct YoloPoseKeypoint {
    float x = 0.0f;
    float y = 0.0f;
    float confidence = 0.0f;
};

struct YoloPoseResult {
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;
    float score = 0.0f;
    int class_id = 0;
    bool hasPose = false;
    std::array<YoloPoseKeypoint, 17> keypoints{};
};

bool isYolov8PoseDim(int dim);

bool parseYolov8PoseRow(const float* row, int dim, float x_factor, float y_factor, YoloPoseResult& out);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_YOLOPOSEPOSTPROCESS_H
