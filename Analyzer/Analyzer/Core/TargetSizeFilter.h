#ifndef ANALYZER_TARGET_SIZE_FILTER_H
#define ANALYZER_TARGET_SIZE_FILTER_H

#include <string>

namespace AVSAnalyzer {

struct TargetSizeFilterConfig {
    bool enabled = false;

    int minWidth = 0;
    int minHeight = 0;
    int maxWidth = 0;
    int maxHeight = 0;

    int minArea = 0;
    int maxArea = 0;

    float minAreaRatio = 0.0f;  // (bbox area) / (image area)
    float maxAreaRatio = 0.0f;
};

// Parse size filter config from behaviorConfig JSON (best-effort).
// Supported keys (all optional):
// - minTargetWidth/minWidth, minTargetHeight/minHeight
// - maxTargetWidth/maxWidth, maxTargetHeight/maxHeight
// - minTargetArea/minArea, maxTargetArea/maxArea
// - minTargetAreaRatio/minAreaRatio, maxTargetAreaRatio/maxAreaRatio
TargetSizeFilterConfig parseTargetSizeFilterConfig(const std::string& behaviorConfigJson);

// Side-effect free helper for unit testing the area-ratio gate independently.
bool passTargetAreaRatioFilter(const TargetSizeFilterConfig& cfg, long long bboxArea, int imageW, int imageH);

// Apply filter to a bbox (w/h in pixels). Returns true when the bbox is allowed.
bool passTargetSizeFilter(const TargetSizeFilterConfig& cfg, int bboxW, int bboxH, int imageW, int imageH);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_TARGET_SIZE_FILTER_H
