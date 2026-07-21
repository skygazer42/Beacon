#pragma once

#include <vector>

#include "Algorithm.h"

namespace AVSAnalyzer {

// Preferred polygon order:
// 1. segmentation contour
// 2. OBB corners
// 3. bbox rectangle
std::vector<double> detectObjectToPolygonPixels(const DetectObject& detect);

}  // namespace AVSAnalyzer
