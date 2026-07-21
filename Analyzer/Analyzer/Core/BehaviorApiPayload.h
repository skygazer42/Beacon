#ifndef ANALYZER_BEHAVIORAPIPAYLOAD_H
#define ANALYZER_BEHAVIORAPIPAYLOAD_H

#include <string>
#include <string_view>

#include <json/json.h>

namespace AVSAnalyzer {

struct BehaviorApiPayloadRoi {
    std::string_view imageBase64{};
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;
};

struct BehaviorApiPayloadStreamInfo {
    std::string nodeCode{};
    std::string controlCode{};
    std::string streamCode{};
    std::string streamApp{};
    std::string streamName{};
    int pipelineMode = 5;
};

struct BehaviorApiPayloadBehaviorInfo {
    std::string algorithmCode{};
    std::string config{};
    std::string recognitionRegion{};
    std::string detectClassNames{};
};

struct BehaviorApiPayloadVideoInfo {
    int width = 0;
    int height = 0;
    int fps = 0;
};

struct BehaviorApiPayloadOsdConfig {
    bool enabled = false;
    std::string text{};
    std::string position{"top-left"};
    int x = 10;
    int y = 30;
    int fontSize = 24;
    std::string fontColor{"255,255,255"};
    bool bgEnabled = true;
};

struct BehaviorApiPayloadExtensions {
    std::string drawType{"polygon"};
    int64_t frameId = 0;
    int64_t timestampMs = 0;
};

struct BehaviorApiPayloadInput {
    std::string_view imageBase64{};
    BehaviorApiPayloadRoi roi{};
    BehaviorApiPayloadStreamInfo stream{};
    BehaviorApiPayloadBehaviorInfo behavior{};
    BehaviorApiPayloadVideoInfo video{};
    BehaviorApiPayloadOsdConfig osd{};
    BehaviorApiPayloadExtensions extensions{};
};

Json::Value buildBehaviorApiPayloadV2(const BehaviorApiPayloadInput& in);
std::string buildBehaviorApiPayloadV2JsonString(const BehaviorApiPayloadInput& in);

Json::Value buildBehaviorApiPayloadV3(const BehaviorApiPayloadInput& in);
std::string buildBehaviorApiPayloadV3JsonString(const BehaviorApiPayloadInput& in);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_BEHAVIORAPIPAYLOAD_H
