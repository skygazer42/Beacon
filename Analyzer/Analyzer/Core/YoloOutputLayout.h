#ifndef ANALYZER_YOLO_OUTPUT_LAYOUT_H
#define ANALYZER_YOLO_OUTPUT_LAYOUT_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace AVSAnalyzer {

struct YoloOutputLayout {
    int rows = 0;       // number of candidate boxes
    int dim = 0;        // per-row dimension (4+classes or 5+classes; pose etc)
    bool rowsFirst = false; // true: raw is rows x dim; false: raw is dim x rows (need transpose)
};

// Validate the model IO after a detection output has been selected.
// A one-class YOLOv8/YOLO11 head has dim=5: four box values plus one class score.
bool isValidYoloDetectionModelIo(
    size_t inputCount,
    size_t outputCount,
    int outputDim,
    int outputRows
);

// Best-effort parse of YOLO output tensor shape into a 2D matrix view.
//
// Supports common export layouts:
// - 3D: [1, dim, rows] (dim first)
// - 3D: [1, rows, dim] (rows first)
// - 4D: [1, 1, rows, dim] / [1, rows, dim, 1]
// - 4D: [1, anchors, rows, dim] / [1, dim, anchors, rows]
//
// `classCount` is used to disambiguate `dim` (4+classes or 5+classes). Pass 0 when unknown.
bool parseYoloOutputLayout(
    const std::vector<int64_t>& shape,
    int classCount,
    YoloOutputLayout& out,
    std::string& errMsg
);

// Multi-output models (e.g. seg) can expose multiple output tensors. This helper tries to pick the
// most likely "detection head" output and returns its parsed 2D layout.
bool selectYoloDetectionOutput(
    const std::vector<std::vector<int64_t>>& outputShapes,
    int classCount,
    size_t& selectedIndex,
    YoloOutputLayout& selectedLayout,
    std::string& errMsg
);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_YOLO_OUTPUT_LAYOUT_H
