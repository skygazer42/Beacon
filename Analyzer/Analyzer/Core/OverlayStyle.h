#ifndef ANALYZER_OVERLAY_STYLE_H
#define ANALYZER_OVERLAY_STYLE_H

#include <json/json.h>

namespace AVSAnalyzer {

struct Control;

// Parse overlay style related keys from control-add JSON and apply to Control.
// Supported keys (camelCase, consistent with Admin):
// - osdFontThickness
// - overlayRegionColor, overlayRegionThickness
// - overlayLineColor, overlayLineThickness
// - overlayDetectColor, overlayDetectThickness, overlayDetectFontSize
void applyOverlayStyleFromJson(const Json::Value& root, Control& control);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_OVERLAY_STYLE_H

