#include "OverlayStyle.h"

#include "Control.h"

#include <algorithm>
#include <cctype>
#include <string>

namespace AVSAnalyzer {

namespace {

int clampInt(int value, int minV, int maxV, int defaultV) {
    if (value < minV || value > maxV) {
        return defaultV;
    }
    return value;
}

bool parseIntFromJson(const Json::Value& v, int& out) {
    if (v.isInt()) {
        out = v.asInt();
        return true;
    }
    if (v.isUInt()) {
        out = static_cast<int>(v.asUInt());
        return true;
    }
    if (v.isDouble()) {
        out = static_cast<int>(v.asDouble());
        return true;
    }
    if (v.isString()) {
        try {
            out = std::stoi(v.asString());
            return true;
        }
        catch (...) {
            return false;
        }
    }
    return false;
}

}  // namespace

void applyOverlayStyleFromJson(const Json::Value& root, Control& control) {
    // OSD font thickness
    {
        int v = control.osdFontThickness;
        if (root.isMember("osdFontThickness") && parseIntFromJson(root["osdFontThickness"], v)) {
            control.osdFontThickness = clampInt(v, 1, 16, control.osdFontThickness);
        }
    }

    // Region overlay
    if (root.isMember("overlayRegionColor") && root["overlayRegionColor"].isString()) {
        control.overlayRegionColor = root["overlayRegionColor"].asString();
    }
    {
        int v = control.overlayRegionThickness;
        if (root.isMember("overlayRegionThickness") && parseIntFromJson(root["overlayRegionThickness"], v)) {
            control.overlayRegionThickness = clampInt(v, 1, 32, control.overlayRegionThickness);
        }
    }

    // Line overlay
    if (root.isMember("overlayLineColor") && root["overlayLineColor"].isString()) {
        control.overlayLineColor = root["overlayLineColor"].asString();
    }
    {
        int v = control.overlayLineThickness;
        if (root.isMember("overlayLineThickness") && parseIntFromJson(root["overlayLineThickness"], v)) {
            control.overlayLineThickness = clampInt(v, 1, 32, control.overlayLineThickness);
        }
    }

    // Detect overlay
    if (root.isMember("overlayDetectColor") && root["overlayDetectColor"].isString()) {
        control.overlayDetectColor = root["overlayDetectColor"].asString();
    }
    {
        int v = control.overlayDetectThickness;
        if (root.isMember("overlayDetectThickness") && parseIntFromJson(root["overlayDetectThickness"], v)) {
            control.overlayDetectThickness = clampInt(v, 1, 16, control.overlayDetectThickness);
        }
    }
    {
        int v = control.overlayDetectFontSize;
        if (root.isMember("overlayDetectFontSize") && parseIntFromJson(root["overlayDetectFontSize"], v)) {
            control.overlayDetectFontSize = clampInt(v, 6, 256, control.overlayDetectFontSize);
        }
    }
}

}  // namespace AVSAnalyzer

