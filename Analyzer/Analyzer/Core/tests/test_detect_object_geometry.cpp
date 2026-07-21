#include "DetectObjectGeometry.h"

#include <cassert>
#include <cmath>
#include <vector>

using namespace AVSAnalyzer;

namespace {

static bool nearly(double a, double b, double eps = 1e-6) {
    return std::fabs(a - b) <= eps;
}

}  // namespace

int main() {
    DetectObject seg{};
    seg.x1 = 10;
    seg.y1 = 20;
    seg.x2 = 40;
    seg.y2 = 60;
    seg.hasSegmentation = true;
    seg.segmentation.emplace_back(10.0f, 20.0f);
    seg.segmentation.emplace_back(40.0f, 20.0f);
    seg.segmentation.emplace_back(35.0f, 60.0f);
    seg.segmentation.emplace_back(12.0f, 55.0f);

    std::vector<double> poly = detectObjectToPolygonPixels(seg);
    assert(poly.size() == 8);
    assert(nearly(poly[0], 10.0));
    assert(nearly(poly[1], 20.0));
    assert(nearly(poly[4], 35.0));
    assert(nearly(poly[5], 60.0));

    DetectObject obb{};
    obb.x1 = 0;
    obb.y1 = 0;
    obb.x2 = 10;
    obb.y2 = 20;
    obb.hasObb = true;
    obb.obb[0] = cv::Point2f(1.0f, 2.0f);
    obb.obb[1] = cv::Point2f(3.0f, 4.0f);
    obb.obb[2] = cv::Point2f(5.0f, 6.0f);
    obb.obb[3] = cv::Point2f(7.0f, 8.0f);
    poly = detectObjectToPolygonPixels(obb);
    assert(poly.size() == 8);
    assert(nearly(poly[6], 7.0));
    assert(nearly(poly[7], 8.0));

    DetectObject box{};
    box.x1 = 1;
    box.y1 = 2;
    box.x2 = 11;
    box.y2 = 12;
    poly = detectObjectToPolygonPixels(box);
    assert(poly.size() == 8);
    assert(nearly(poly[0], 1.0));
    assert(nearly(poly[1], 2.0));
    assert(nearly(poly[6], 1.0));
    assert(nearly(poly[7], 12.0));

    return 0;
}
