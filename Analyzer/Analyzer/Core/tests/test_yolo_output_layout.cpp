#include "YoloOutputLayout.h"

#include <cstdint>
#include <string>
#include <vector>

static int assert_layout(
    const std::vector<int64_t>& shape,
    int class_count,
    int expected_rows,
    int expected_dim,
    bool expected_rows_first
) {
    AVSAnalyzer::YoloOutputLayout layout;
    std::string err;
    if (!AVSAnalyzer::parseYoloOutputLayout(shape, class_count, layout, err)) {
        return 1;
    }
    if (layout.rows != expected_rows) {
        return 2;
    }
    if (layout.dim != expected_dim) {
        return 3;
    }
    if (layout.rowsFirst != expected_rows_first) {
        return 4;
    }
    return 0;
}

int main() {
    // A one-class YOLOv8/YOLO11 detection head is [cx, cy, w, h, class], so dim=5 is valid.
    if (!AVSAnalyzer::isValidYoloDetectionModelIo(/*inputCount=*/1, /*outputCount=*/1, /*outputDim=*/5, /*outputRows=*/8400)) {
        return 1;
    }

    // Typical YOLOv8 export: [1, 84, 8400] (dim first)
    if (int rc = assert_layout({1, 84, 8400}, 80, 8400, 84, false)) return 10 + rc;
    // Typical YOLOv8 export: [1, 8400, 84] (rows first)
    if (int rc = assert_layout({1, 8400, 84}, 80, 8400, 84, true)) return 20 + rc;

    // 4D exports that include redundant singleton dims.
    if (int rc = assert_layout({1, 1, 8400, 84}, 80, 8400, 84, true)) return 30 + rc;
    if (int rc = assert_layout({1, 84, 1, 8400}, 80, 8400, 84, false)) return 40 + rc;

    // Anchors/grid split: [1, 3, 8400, 85] => rows=25200, dim=85 (rows first)
    if (int rc = assert_layout({1, 3, 8400, 85}, 80, 25200, 85, true)) return 50 + rc;
    // Anchors/grid split but dim first: [1, 85, 3, 8400] => rows=25200, dim=85 (dim first)
    if (int rc = assert_layout({1, 85, 3, 8400}, 80, 25200, 85, false)) return 60 + rc;

    // Pose-like dim should still be recognized by heuristics when class list is unknown.
    if (int rc = assert_layout({1, 56, 8400}, 0, 8400, 56, false)) return 70 + rc;
    if (int rc = assert_layout({1, 1, 8400, 56}, 0, 8400, 56, true)) return 80 + rc;

    return 0;
}
