#include "DetectObjectGeometry.h"

namespace AVSAnalyzer {

std::vector<double> detectObjectToPolygonPixels(const DetectObject& detect) {
    std::vector<double> out;

    if (detect.hasSegmentation && detect.segmentation.size() >= 3) {
        out.reserve(detect.segmentation.size() * 2);
        for (const auto& p : detect.segmentation) {
            out.push_back(static_cast<double>(p.x));
            out.push_back(static_cast<double>(p.y));
        }
        return out;
    }

    if (detect.hasObb) {
        out.reserve(8);
        for (const auto& p : detect.obb) {
            out.push_back(static_cast<double>(p.x));
            out.push_back(static_cast<double>(p.y));
        }
        return out;
    }

    out.reserve(8);
    out.push_back(static_cast<double>(detect.x1));
    out.push_back(static_cast<double>(detect.y1));
    out.push_back(static_cast<double>(detect.x2));
    out.push_back(static_cast<double>(detect.y1));
    out.push_back(static_cast<double>(detect.x2));
    out.push_back(static_cast<double>(detect.y2));
    out.push_back(static_cast<double>(detect.x1));
    out.push_back(static_cast<double>(detect.y2));
    return out;
}

}  // namespace AVSAnalyzer
