#include "BehaviorApiPayload.h"

#include <cstdint>
#include <cstdio>

namespace AVSAnalyzer {

namespace {

void appendJsonEscaped(std::string& out, std::string_view value) {
    out.push_back('"');
    for (char ch : value) {
        switch (ch) {
        case '"':
            out.append("\\\"");
            break;
        case '\\':
            out.append("\\\\");
            break;
        case '\b':
            out.append("\\b");
            break;
        case '\f':
            out.append("\\f");
            break;
        case '\n':
            out.append("\\n");
            break;
        case '\r':
            out.append("\\r");
            break;
        case '\t':
            out.append("\\t");
            break;
        default: {
            const unsigned char u = static_cast<unsigned char>(ch);
            if (u < 0x20) {
                char buf[7];
                std::snprintf(buf, sizeof(buf), "\\u%04x", (unsigned int)u);
                out.append(buf);
            } else {
                out.push_back(ch);
            }
        } break;
        }
    }
    out.push_back('"');
}

void appendJsonKey(std::string& out, std::string_view key) {
    appendJsonEscaped(out, key);
    out.push_back(':');
}

void appendJsonKeyValueString(std::string& out, std::string_view key, std::string_view value) {
    appendJsonKey(out, key);
    appendJsonEscaped(out, value);
}

void appendJsonKeyValueInt(std::string& out, std::string_view key, int value) {
    appendJsonKey(out, key);
    out.append(std::to_string(value));
}

void appendJsonKeyValueInt64(std::string& out, std::string_view key, int64_t value) {
    appendJsonKey(out, key);
    out.append(std::to_string(static_cast<long long>(value)));
}

void appendJsonKeyValueBool(std::string& out, std::string_view key, bool value) {
    appendJsonKey(out, key);
    out.append(value ? "true" : "false");
}

}  // namespace

Json::Value buildBehaviorApiPayloadV2(const BehaviorApiPayloadInput& in) {
    Json::Value param;

    param["image_base64"] = std::string(in.imageBase64);
    param["nodeCode"] = in.stream.nodeCode;
    param["controlCode"] = in.stream.controlCode;
    param["streamCode"] = in.stream.streamCode;
    param["streamApp"] = in.stream.streamApp;
    param["streamName"] = in.stream.streamName;
    param["pipelineMode"] = in.stream.pipelineMode;

    // Backward compatibility:
    param["behaviorAlgorithmCode"] = in.behavior.algorithmCode;

    // Protocol v2 alignment:
    param["flowCode"] = in.behavior.algorithmCode;
    param["algorithmCode"] = in.behavior.algorithmCode;

    param["behaviorConfig"] = in.behavior.config;
    param["recognitionRegion"] = in.behavior.recognitionRegion;
    param["detectClassNames"] = in.behavior.detectClassNames;

    Json::Value videoInfo;
    videoInfo["width"] = in.video.width;
    videoInfo["height"] = in.video.height;
    videoInfo["fps"] = in.video.fps;
    param["videoInfo"] = videoInfo;

    Json::Value osdConfig;
    osdConfig["enabled"] = in.osd.enabled;
    osdConfig["text"] = in.osd.text;
    osdConfig["position"] = in.osd.position;
    osdConfig["x"] = in.osd.x;
    osdConfig["y"] = in.osd.y;
    osdConfig["fontSize"] = in.osd.fontSize;
    osdConfig["fontColor"] = in.osd.fontColor;
    osdConfig["bgEnabled"] = in.osd.bgEnabled;
    param["osdConfig"] = osdConfig;

    Json::Value extensions;
    extensions["frameId"] = static_cast<Json::Int64>(in.extensions.frameId);
    extensions["timestamp"] = static_cast<Json::Int64>(in.extensions.timestampMs);
    extensions["drawType"] = in.extensions.drawType;
    param["extensions"] = extensions;

    return param;
}

std::string buildBehaviorApiPayloadV2JsonString(const BehaviorApiPayloadInput& in) {
    // Performance note:
    // - Avoid constructing Json::Value with a huge base64 blob (multiple copies).
    // - Build the JSON string directly with proper escaping for small fields.
    std::string out;
    out.reserve(in.imageBase64.size() + 1024);

    out.push_back('{');

    appendJsonKeyValueString(out, "image_base64", in.imageBase64);
    out.push_back(',');
    appendJsonKeyValueString(out, "nodeCode", in.stream.nodeCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "controlCode", in.stream.controlCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "streamCode", in.stream.streamCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "streamApp", in.stream.streamApp);
    out.push_back(',');
    appendJsonKeyValueString(out, "streamName", in.stream.streamName);
    out.push_back(',');
    appendJsonKeyValueInt(out, "pipelineMode", in.stream.pipelineMode);
    out.push_back(',');

    // Backward compatibility:
    appendJsonKeyValueString(out, "behaviorAlgorithmCode", in.behavior.algorithmCode);
    out.push_back(',');

    // Protocol v2 alignment:
    appendJsonKeyValueString(out, "flowCode", in.behavior.algorithmCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "algorithmCode", in.behavior.algorithmCode);
    out.push_back(',');

    appendJsonKeyValueString(out, "behaviorConfig", in.behavior.config);
    out.push_back(',');
    appendJsonKeyValueString(out, "recognitionRegion", in.behavior.recognitionRegion);
    out.push_back(',');
    appendJsonKeyValueString(out, "detectClassNames", in.behavior.detectClassNames);
    out.push_back(',');

    appendJsonKey(out, "videoInfo");
    out.push_back('{');
    appendJsonKeyValueInt(out, "width", in.video.width);
    out.push_back(',');
    appendJsonKeyValueInt(out, "height", in.video.height);
    out.push_back(',');
    appendJsonKeyValueInt(out, "fps", in.video.fps);
    out.push_back('}');
    out.push_back(',');

    appendJsonKey(out, "osdConfig");
    out.push_back('{');
    appendJsonKeyValueBool(out, "enabled", in.osd.enabled);
    out.push_back(',');
    appendJsonKeyValueString(out, "text", in.osd.text);
    out.push_back(',');
    appendJsonKeyValueString(out, "position", in.osd.position);
    out.push_back(',');
    appendJsonKeyValueInt(out, "x", in.osd.x);
    out.push_back(',');
    appendJsonKeyValueInt(out, "y", in.osd.y);
    out.push_back(',');
    appendJsonKeyValueInt(out, "fontSize", in.osd.fontSize);
    out.push_back(',');
    appendJsonKeyValueString(out, "fontColor", in.osd.fontColor);
    out.push_back(',');
    appendJsonKeyValueBool(out, "bgEnabled", in.osd.bgEnabled);
    out.push_back('}');
    out.push_back(',');

    appendJsonKey(out, "extensions");
    out.push_back('{');
    appendJsonKeyValueInt64(out, "frameId", in.extensions.frameId);
    out.push_back(',');
    appendJsonKeyValueInt64(out, "timestamp", in.extensions.timestampMs);
    out.push_back(',');
    appendJsonKeyValueString(out, "drawType", in.extensions.drawType);
    out.push_back('}');

    out.push_back('}');
    return out;
}

Json::Value buildBehaviorApiPayloadV3(const BehaviorApiPayloadInput& in) {
    Json::Value param = buildBehaviorApiPayloadV2(in);

    param["roi_image_base64"] = std::string(in.roi.imageBase64);
    Json::Value roiRect;
    roiRect["x1"] = in.roi.x1;
    roiRect["y1"] = in.roi.y1;
    roiRect["x2"] = in.roi.x2;
    roiRect["y2"] = in.roi.y2;
    param["roiRect"] = roiRect;

    return param;
}

std::string buildBehaviorApiPayloadV3JsonString(const BehaviorApiPayloadInput& in) {
    // Performance note: same as v2; avoid Json::Value copies for huge base64.
    std::string out;
    out.reserve(in.imageBase64.size() + in.roi.imageBase64.size() + 1280);

    out.push_back('{');

    appendJsonKeyValueString(out, "image_base64", in.imageBase64);
    out.push_back(',');
    appendJsonKeyValueString(out, "roi_image_base64", in.roi.imageBase64);
    out.push_back(',');

    appendJsonKey(out, "roiRect");
    out.push_back('{');
    appendJsonKeyValueInt(out, "x1", in.roi.x1);
    out.push_back(',');
    appendJsonKeyValueInt(out, "y1", in.roi.y1);
    out.push_back(',');
    appendJsonKeyValueInt(out, "x2", in.roi.x2);
    out.push_back(',');
    appendJsonKeyValueInt(out, "y2", in.roi.y2);
    out.push_back('}');
    out.push_back(',');

    appendJsonKeyValueString(out, "nodeCode", in.stream.nodeCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "controlCode", in.stream.controlCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "streamCode", in.stream.streamCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "streamApp", in.stream.streamApp);
    out.push_back(',');
    appendJsonKeyValueString(out, "streamName", in.stream.streamName);
    out.push_back(',');
    appendJsonKeyValueInt(out, "pipelineMode", in.stream.pipelineMode);
    out.push_back(',');

    // Backward compatibility:
    appendJsonKeyValueString(out, "behaviorAlgorithmCode", in.behavior.algorithmCode);
    out.push_back(',');

    // Protocol v2 alignment:
    appendJsonKeyValueString(out, "flowCode", in.behavior.algorithmCode);
    out.push_back(',');
    appendJsonKeyValueString(out, "algorithmCode", in.behavior.algorithmCode);
    out.push_back(',');

    appendJsonKeyValueString(out, "behaviorConfig", in.behavior.config);
    out.push_back(',');
    appendJsonKeyValueString(out, "recognitionRegion", in.behavior.recognitionRegion);
    out.push_back(',');
    appendJsonKeyValueString(out, "detectClassNames", in.behavior.detectClassNames);
    out.push_back(',');

    appendJsonKey(out, "videoInfo");
    out.push_back('{');
    appendJsonKeyValueInt(out, "width", in.video.width);
    out.push_back(',');
    appendJsonKeyValueInt(out, "height", in.video.height);
    out.push_back(',');
    appendJsonKeyValueInt(out, "fps", in.video.fps);
    out.push_back('}');
    out.push_back(',');

    appendJsonKey(out, "osdConfig");
    out.push_back('{');
    appendJsonKeyValueBool(out, "enabled", in.osd.enabled);
    out.push_back(',');
    appendJsonKeyValueString(out, "text", in.osd.text);
    out.push_back(',');
    appendJsonKeyValueString(out, "position", in.osd.position);
    out.push_back(',');
    appendJsonKeyValueInt(out, "x", in.osd.x);
    out.push_back(',');
    appendJsonKeyValueInt(out, "y", in.osd.y);
    out.push_back(',');
    appendJsonKeyValueInt(out, "fontSize", in.osd.fontSize);
    out.push_back(',');
    appendJsonKeyValueString(out, "fontColor", in.osd.fontColor);
    out.push_back(',');
    appendJsonKeyValueBool(out, "bgEnabled", in.osd.bgEnabled);
    out.push_back('}');
    out.push_back(',');

    appendJsonKey(out, "extensions");
    out.push_back('{');
    appendJsonKeyValueInt64(out, "frameId", in.extensions.frameId);
    out.push_back(',');
    appendJsonKeyValueInt64(out, "timestamp", in.extensions.timestampMs);
    out.push_back(',');
    appendJsonKeyValueString(out, "drawType", in.extensions.drawType);
    out.push_back('}');

    out.push_back('}');
    return out;
}

}  // namespace AVSAnalyzer
