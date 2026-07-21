#ifndef ANALYZER_RECOGNITION_REGIONS_H
#define ANALYZER_RECOGNITION_REGIONS_H

#include <string>
#include <vector>

namespace AVSAnalyzer {

// Parse recognitionRegion string (normalized coordinates) into pixel-space polygons.
//
// Input format (backward compatible):
// - Single region:  "x1,y1,x2,y2,x3,y3,..."
// - Multi regions:  "region1;region2;region3"
// Where each region is a polygon with >= 3 points (>= 6 numbers), normalized in [0,1].
//
// Output:
// - outRegionsPixels: vector of regions, each region as [x1,y1,x2,y2,...] in pixel coords.
// - errMsg: empty when ok, otherwise best-effort reason.
bool parseRecognitionRegionsPixels(
    const std::string& normalizedRegions,
    int videoWidth,
    int videoHeight,
    std::vector<std::vector<double>>& outRegionsPixels,
    std::string& errMsg);

// Calculate max "coverage ratio" among regions:
//   ratio = intersect_area(region, object) / area(object)
// Returns 0 when no region/object is valid.
double calcMaxCoverageRatio(
    const std::vector<std::vector<double>>& regionPixels,
    const std::vector<double>& objectPixels);

} // namespace AVSAnalyzer

#endif // ANALYZER_RECOGNITION_REGIONS_H

