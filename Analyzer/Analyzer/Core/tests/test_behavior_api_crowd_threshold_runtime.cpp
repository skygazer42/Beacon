#include <algorithm>
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
    return {};
}

std::vector<LineCrossingEvent> LineCrossingDetector::detectCrossing(const std::vector<TrackedObject>& /*tracks*/,
                                                                    int64_t /*timestamp*/) {
    return {};
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

AVSAnalyzer::Control makeCrowdControl(const std::string& behaviorConfigJson) {
    AVSAnalyzer::Control control;
    control.usePipelineMode = true;
    control.algorithmPipelineMode = 5;
    control.behaviorAlgorithmCode = "crowd";
    control.behaviorApiUrl = "http://example.com/behavior";
    control.behaviorConfig = behaviorConfigJson;
    control.objectCode = "person";
    control.recognitionRegion = "0,0,1,0,1,1,0,1";
    control.videoWidth = 100;
    control.videoHeight = 100;
    control.videoFps = 25;
    control.parseRecognitionRegion();
    return control;
}

int runCrowdCase(AVSAnalyzer::Analyzer& analyzer,
                 int64_t frameCount,
                 const std::vector<AVSAnalyzer::DetectObject>& detects,
                 bool expectedHappen,
                 size_t expectedDetectCount,
                 int errBase) {
    cv::Mat image(100, 100, CV_8UC3, cv::Scalar(0, 0, 0));
    std::vector<AVSAnalyzer::DetectObject> out;
    bool happen = !expectedHappen;
    float happenScore = -1.0f;

    setBehaviorApiDetects(detects);
    if (!analyzer.executePipelineMode5(frameCount, image, out, happen, happenScore)) {
        return errBase;
    }
    if (happen != expectedHappen) {
        return errBase + 1;
    }
    if (out.size() != expectedDetectCount) {
        return errBase + 2;
    }
    if (expectedHappen) {
        if (happenScore <= 0.0f) {
            return errBase + 3;
        }
    } else if (happenScore != 0.0f) {
        return errBase + 4;
    }
    return 0;
}

}  // namespace

int main() {
    const auto onePerson = std::vector<AVSAnalyzer::DetectObject>{
        makeDetect(10, 10, 40, 40, "person", 0.95f),
    };
    const auto twoPeople = std::vector<AVSAnalyzer::DetectObject>{
        makeDetect(10, 10, 40, 40, "person", 0.95f),
        makeDetect(50, 10, 80, 40, "person", 0.93f),
    };

    AVSAnalyzer::Control geControl = makeCrowdControl(
        "{\"apiType\":\"v2\",\"builtinBehavior\":\"crowd\",\"minCount\":2}");
    AVSAnalyzer::Analyzer geAnalyzer(nullptr, &geControl);

    int rc = runCrowdCase(geAnalyzer, 1, twoPeople, true, 2, 10);
    if (rc != 0) {
        return rc;
    }
    rc = runCrowdCase(geAnalyzer, 2, onePerson, false, 1, 20);
    if (rc != 0) {
        return rc;
    }

    AVSAnalyzer::Control leControl = makeCrowdControl(
        "{\"apiType\":\"v2\",\"builtinBehavior\":\"crowd\",\"countOp\":\"le\",\"maxCount\":0}");
    AVSAnalyzer::Analyzer leAnalyzer(nullptr, &leControl);

    rc = runCrowdCase(leAnalyzer, 3, {}, true, 0, 30);
    if (rc != 0) {
        return rc;
    }
    rc = runCrowdCase(leAnalyzer, 4, onePerson, false, 1, 40);
    if (rc != 0) {
        return rc;
    }

    return 0;
}
