#include "YoloPosePostprocess.h"

#include <limits>
#include <vector>

int main() {
    std::vector<float> row(56, 0.0f);
    row[0] = 100.0f; // cx
    row[1] = 120.0f; // cy
    row[2] = 50.0f;  // w
    row[3] = 60.0f;  // h
    row[4] = 0.9f;   // score

    row[5] = 110.0f; // kp0 x
    row[6] = 130.0f; // kp0 y
    row[7] = 0.8f;   // kp0 conf

    // inject NaN/inf into later keypoints to ensure parser guards.
    row[8] = std::numeric_limits<float>::quiet_NaN();
    row[9] = std::numeric_limits<float>::infinity();
    row[10] = -std::numeric_limits<float>::infinity();

    AVSAnalyzer::YoloPoseResult obj;
    bool ok = AVSAnalyzer::parseYolov8PoseRow(row.data(), (int)row.size(), 1.0f, 1.0f, obj);
    if (!ok) {
        return 1;
    }
    if (!obj.hasPose) {
        return 2;
    }
    if (obj.keypoints[0].confidence < 0.79f || obj.keypoints[0].confidence > 0.81f) {
        return 4;
    }
    return 0;
}
