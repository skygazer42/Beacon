#include "YoloPosePostprocess.h"

#include <algorithm>
#include <cmath>

namespace AVSAnalyzer {
namespace {

constexpr int kYolov8PoseKeypoints = 17;
constexpr int kYolov8PoseDim = 4 + 1 + kYolov8PoseKeypoints * 3; // cx,cy,w,h,score + 17*(x,y,conf)

float clamp01(float value) {
    if (!std::isfinite(value)) {
        return 0.0f;
    }
    return std::max(0.0f, std::min(1.0f, value));
}

}  // namespace

bool isYolov8PoseDim(int dim) {
    return dim == kYolov8PoseDim;
}

bool parseYolov8PoseRow(const float* row, int dim, float x_factor, float y_factor, YoloPoseResult& out) {
    if (!row) {
        return false;
    }
    if (dim < kYolov8PoseDim) {
        return false;
    }
    if (!std::isfinite(x_factor) || x_factor <= 0.0f) {
        x_factor = 1.0f;
    }
    if (!std::isfinite(y_factor) || y_factor <= 0.0f) {
        y_factor = 1.0f;
    }

    const float cx = row[0];
    const float cy = row[1];
    const float ow = row[2];
    const float oh = row[3];
    if (!std::isfinite(cx) || !std::isfinite(cy) || !std::isfinite(ow) || !std::isfinite(oh)) {
        return false;
    }
    if (ow <= 0.0f || oh <= 0.0f) {
        return false;
    }

    float score = row[4];
    if (!std::isfinite(score)) {
        score = 0.0f;
    }

    const float x1 = (cx - 0.5f * ow) * x_factor;
    const float y1 = (cy - 0.5f * oh) * y_factor;
    const float x2 = (cx + 0.5f * ow) * x_factor;
    const float y2 = (cy + 0.5f * oh) * y_factor;

    out.x1 = static_cast<int>(x1);
    out.y1 = static_cast<int>(y1);
    out.x2 = static_cast<int>(x2);
    out.y2 = static_cast<int>(y2);
    out.score = clamp01(score);
    out.class_id = 0;
    out.hasPose = true;

    const int base = 5;
    for (int i = 0; i < kYolov8PoseKeypoints; ++i) {
        const int idx = base + i * 3;
        float x = row[idx];
        float y = row[idx + 1];
        float c = row[idx + 2];

        if (!std::isfinite(x) || !std::isfinite(y)) {
            x = 0.0f;
            y = 0.0f;
        }
        x *= x_factor;
        y *= y_factor;
        c = clamp01(c);

        out.keypoints[static_cast<size_t>(i)] = YoloPoseKeypoint{ x, y, c };
    }

    return true;
}

}  // namespace AVSAnalyzer
