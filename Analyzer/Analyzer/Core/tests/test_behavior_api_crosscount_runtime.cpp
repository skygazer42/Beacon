#include <string>
#include <vector>

#include <json/json.h>
#include <opencv2/opencv.hpp>

#define private public
#include "Analyzer.h"
#undef private

#include "ByteTrack.h"
#include "Control.h"
#include "DetectObjectJson.h"
#include "LineCrossing.h"
#include "ReidTracker.h"
#include "Scheduler.h"
#include "Tracker.h"
#include "Utils/Request.h"

namespace AVSAnalyzer {

static std::string gStubBehaviorApiResponse;
static std::vector<LineCrossingEvent> gStubLineCrossingEvents;

Algorithm* Scheduler::getAlgorithm(const std::string& /*code*/) {
    return nullptr;
}

Config* Scheduler::getConfig() {
    return nullptr;
}

void Scheduler::statsIncApiInferSkippedMinInterval(uint64_t /*count*/) {}
void Scheduler::statsIncApiInferSkippedCircuitOpen(uint64_t /*count*/) {}
void Scheduler::statsIncApiInferAllowed(uint64_t /*count*/) {}
void Scheduler::statsIncApiInferRetried(uint64_t /*count*/) {}
void Scheduler::statsObserveApiInferLatencyMs(uint64_t /*latencyMs*/) {}
void Scheduler::statsIncApiInferSuccess(uint64_t /*count*/) {}
void Scheduler::statsIncApiInferFailure(uint64_t /*count*/) {}
void Scheduler::statsIncApiInferCircuitOpened(uint64_t /*count*/) {}

Request::Request() {}
Request::~Request() {}
bool Request::get(const char* /*url*/, std::string& /*response*/) { return false; }
bool Request::post(const char* /*url*/, const char* /*data*/, std::string& /*response*/) { return false; }
bool Request::post(const char* /*url*/, std::string_view /*data*/, std::string& response) {
    response = gStubBehaviorApiResponse;
    return true;
}
bool Request::post(const char* url, std::string_view data, std::string& response, std::string_view /*token*/) {
    return post(url, data, response);
}
bool Request::post(const char* url,
                   std::string_view data,
                   std::string& response,
                   std::string_view /*token*/,
                   int /*connectTimeoutSeconds*/,
                   int /*timeoutSeconds*/) {
    return post(url, data, response);
}

ByteTracker::ByteTracker(int /*frameRate*/, int /*trackBuffer*/, float /*trackThresh*/, float /*highThresh*/, float /*matchThresh*/) {}
ByteTracker::~ByteTracker() {}

ReidTracker::ReidTracker(const ReidTrackerConfig& /*cfg*/) {}
ReidTracker::~ReidTracker() {}

std::vector<TrackedObject> SimpleTracker::update(const std::vector<DetectObject>& /*detections*/, int64_t /*timestamp*/) {
    return {};
}

Line Line::fromString(const std::string& /*str*/, int /*imageWidth*/, int /*imageHeight*/) {
    return Line(cv::Point(0, 0), cv::Point(100, 100), "line");
}

std::vector<LineCrossingEvent> LineCrossingDetector::detectCrossing(const std::vector<TrackedObject>& /*tracks*/,
                                                                    int64_t /*timestamp*/) {
    return gStubLineCrossingEvents;
}

}  // namespace AVSAnalyzer

namespace {

AVSAnalyzer::DetectObject makeDetect(int x1, int y1, int x2, int y2, const std::string& className, float score) {
    AVSAnalyzer::DetectObject detect;
    detect.x1 = x1;
    detect.y1 = y1;
    detect.x2 = x2;
    detect.y2 = y2;
    detect.class_name = className;
    detect.class_score = score;
    return detect;
}

AVSAnalyzer::LineCrossingEvent makeEvent(int trackId, const AVSAnalyzer::DetectObject& detect) {
    AVSAnalyzer::LineCrossingEvent event;
    event.trackId = trackId;
    event.object = detect;
    event.timestamp = 123;
    return event;
}

std::string buildBehaviorApiResponse(const std::vector<AVSAnalyzer::DetectObject>& detects) {
    Json::Value root(Json::objectValue);
    root["code"] = 1000;
    root["msg"] = "ok";

    Json::Value result(Json::objectValue);
    Json::Value detectsJson(Json::arrayValue);
    for (const auto& detect : detects) {
        Json::Value item(Json::objectValue);
        item["x1"] = detect.x1;
        item["y1"] = detect.y1;
        item["x2"] = detect.x2;
        item["y2"] = detect.y2;
        item["class_name"] = detect.class_name;
        item["class_score"] = detect.class_score;
        detectsJson.append(item);
    }
    result["detects"] = detectsJson;
    root["result"] = result;

    Json::StreamWriterBuilder builder;
    builder["indentation"] = "";
    return Json::writeString(builder, root);
}

void setBehaviorApiDetects(const std::vector<AVSAnalyzer::DetectObject>& detects) {
    AVSAnalyzer::gStubBehaviorApiResponse = buildBehaviorApiResponse(detects);
}

AVSAnalyzer::Control makeCrossCountControl() {
    AVSAnalyzer::Control control;
    control.usePipelineMode = true;
    control.algorithmPipelineMode = 5;
    control.behaviorAlgorithmCode = "crosscount";
    control.behaviorApiUrl = "http://example.com/behavior";
    control.behaviorConfig = "{\"apiType\":\"v2\",\"builtinBehavior\":\"crosscount\"}";
    control.objectCode = "person";
    control.recognitionRegion = "0,0,1,0,1,1,0,1";
    control.lineCoordinates = "0,0,1,1";
    control.videoWidth = 100;
    control.videoHeight = 100;
    control.videoFps = 25;
    control.parseRecognitionRegion();
    return control;
}

int runCrossCountCase(AVSAnalyzer::Analyzer& analyzer) {
    cv::Mat image(100, 100, CV_8UC3, cv::Scalar(0, 0, 0));
    std::vector<AVSAnalyzer::DetectObject> out;
    bool happen = false;
    float happenScore = -1.0f;

    const auto detect = makeDetect(10, 10, 40, 40, "person", 0.95f);
    setBehaviorApiDetects({detect});
    AVSAnalyzer::gStubLineCrossingEvents = {
        makeEvent(101, detect),
        makeEvent(101, detect),
    };

    if (!analyzer.executePipelineMode5(1, image, out, happen, happenScore)) {
        return 10;
    }
    if (!happen) {
        return 11;
    }
    if (happenScore <= 0.0f) {
        return 12;
    }
    if (out.size() != 1) {
        return 13;
    }
    if (static_cast<int>(out[0].attributes["track_id"]) != 101) {
        return 14;
    }

    Json::CharReaderBuilder readerBuilder;
    Json::Value userData(Json::objectValue);
    std::string errs;
    const std::string userDataJson = analyzer.getLastUserDataJson();
    std::unique_ptr<Json::CharReader> reader(readerBuilder.newCharReader());
    if (!reader->parse(userDataJson.data(), userDataJson.data() + userDataJson.size(), &userData, &errs)) {
        return 15;
    }
    if (userData["event"].asString() != "CROSSCOUNT") {
        return 16;
    }
    if (userData["behavior"].asString() != "crosscount") {
        return 17;
    }
    if (userData["cross_count"].asInt() != 1) {
        return 18;
    }
    if (!userData["internal_targets"].isArray() || userData["internal_targets"].size() != 1) {
        return 19;
    }
    if (userData["internal_targets"][0]["track_id"].asInt() != 101) {
        return 20;
    }

    return 0;
}

}  // namespace

int main() {
    AVSAnalyzer::Control control = makeCrossCountControl();
    AVSAnalyzer::Analyzer analyzer(nullptr, &control);
    return runCrossCountCase(analyzer);
}
