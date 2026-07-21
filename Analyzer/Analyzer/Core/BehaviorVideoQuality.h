#ifndef ANALYZER_BEHAVIOR_VIDEO_QUALITY_H
#define ANALYZER_BEHAVIOR_VIDEO_QUALITY_H

#include <algorithm>
#include <cctype>
#include <cmath>
#include <string>
#include <vector>

#include <json/value.h>

#include "Algorithm.h"

namespace AVSAnalyzer {

struct VideoQualityStats {
    float meanGray = 0.0f;
    float stdGray = 0.0f;
    float meanSaturation = 0.0f;
    float edgeDensity = 0.0f;
    float channelDiffMean = 0.0f;
    float boundaryDensity = 0.0f;
};

inline std::string normalizeVideoQualityBehaviorName(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

inline bool isVideoQualityBuiltin(const std::string& behaviorName) {
    const std::string v = normalizeVideoQualityBehaviorName(behaviorName);
    return v == "occlusion" || v == "grayscreen" || v == "gray_screen" ||
           v == "corruptscreen" || v == "corrupt_screen" ||
           v == "flowerscreen" || v == "flower_screen";
}

inline std::string canonicalVideoQualityBehaviorName(const std::string& behaviorName) {
    const std::string v = normalizeVideoQualityBehaviorName(behaviorName);
    if (v == "gray_screen") {
        return "grayscreen";
    }
    if (v == "corrupt_screen" || v == "flowerscreen" || v == "flower_screen") {
        return "corruptscreen";
    }
    return v;
}

inline std::string videoQualityEventName(const std::string& behaviorName) {
    const std::string v = canonicalVideoQualityBehaviorName(behaviorName);
    if (v == "occlusion") {
        return "OCCLUSION";
    }
    if (v == "grayscreen") {
        return "GRAY_SCREEN";
    }
    if (v == "corruptscreen") {
        return "CORRUPT_SCREEN";
    }
    return "VIDEO_QUALITY";
}

inline VideoQualityStats analyzeVideoQualityFrame(const cv::Mat& image) {
    VideoQualityStats stats;
    if (image.empty()) {
        return stats;
    }

    cv::Mat bgr;
    if (image.channels() == 3) {
        bgr = image;
    } else if (image.channels() == 4) {
        cv::cvtColor(image, bgr, cv::COLOR_BGRA2BGR);
    } else {
        cv::cvtColor(image, bgr, cv::COLOR_GRAY2BGR);
    }

    cv::Mat gray;
    cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);

    cv::Scalar meanGray;
    cv::Scalar stdGray;
    cv::meanStdDev(gray, meanGray, stdGray);
    stats.meanGray = static_cast<float>(meanGray[0]);
    stats.stdGray = static_cast<float>(stdGray[0]);

    cv::Mat hsv;
    cv::cvtColor(bgr, hsv, cv::COLOR_BGR2HSV);
    cv::Scalar meanHsv = cv::mean(hsv);
    stats.meanSaturation = static_cast<float>(meanHsv[1]);

    cv::Mat edges;
    cv::Canny(gray, edges, 48.0, 128.0);
    const int total = std::max(1, gray.rows * gray.cols);
    stats.edgeDensity = static_cast<float>(cv::countNonZero(edges)) / static_cast<float>(total);

    std::vector<cv::Mat> channels;
    cv::split(bgr, channels);
    cv::Mat diffBG;
    cv::Mat diffGR;
    cv::Mat diffBR;
    cv::absdiff(channels[0], channels[1], diffBG);
    cv::absdiff(channels[1], channels[2], diffGR);
    cv::absdiff(channels[0], channels[2], diffBR);
    const cv::Scalar diffMean = (cv::mean(diffBG) + cv::mean(diffGR) + cv::mean(diffBR)) / 3.0;
    stats.channelDiffMean = static_cast<float>(diffMean[0]);

    if (gray.cols > 1 && gray.rows > 1) {
        cv::Mat rightA = gray(cv::Rect(0, 0, gray.cols - 1, gray.rows));
        cv::Mat rightB = gray(cv::Rect(1, 0, gray.cols - 1, gray.rows));
        cv::Mat downA = gray(cv::Rect(0, 0, gray.cols, gray.rows - 1));
        cv::Mat downB = gray(cv::Rect(0, 1, gray.cols, gray.rows - 1));

        cv::Mat diffX;
        cv::Mat diffY;
        cv::absdiff(rightA, rightB, diffX);
        cv::absdiff(downA, downB, diffY);

        cv::Mat strongX;
        cv::Mat strongY;
        cv::threshold(diffX, strongX, 56.0, 255.0, cv::THRESH_BINARY);
        cv::threshold(diffY, strongY, 56.0, 255.0, cv::THRESH_BINARY);
        strongX.convertTo(strongX, CV_8U);
        strongY.convertTo(strongY, CV_8U);

        const int totalPairs = std::max(1, strongX.rows * strongX.cols + strongY.rows * strongY.cols);
        const int strongPairs = cv::countNonZero(strongX) + cv::countNonZero(strongY);
        stats.boundaryDensity = static_cast<float>(strongPairs) / static_cast<float>(totalPairs);
    }

    return stats;
}

inline bool evaluateVideoQualityBehavior(
    const cv::Mat& image,
    const std::string& behaviorName,
    std::vector<DetectObject>& happenDetects,
    Json::Value& userData
) {
    happenDetects.clear();
    userData = Json::Value(Json::objectValue);

    if (image.empty()) {
        return false;
    }

    const std::string behavior = canonicalVideoQualityBehaviorName(behaviorName);
    if (!isVideoQualityBuiltin(behavior)) {
        return false;
    }

    const VideoQualityStats stats = analyzeVideoQualityFrame(image);
    userData["behavior"] = behavior;
    userData["mean_gray"] = stats.meanGray;
    userData["gray_stddev"] = stats.stdGray;
    userData["mean_saturation"] = stats.meanSaturation;
    userData["edge_density"] = stats.edgeDensity;
    userData["channel_diff_mean"] = stats.channelDiffMean;
    userData["boundary_density"] = stats.boundaryDensity;

    bool happen = false;
    if (behavior == "occlusion") {
        happen = stats.stdGray <= 12.0f && stats.meanSaturation <= 24.0f && stats.edgeDensity <= 0.015f;
    } else if (behavior == "grayscreen") {
        happen = stats.meanGray >= 20.0f && stats.meanGray <= 235.0f &&
                 stats.stdGray <= 10.0f && stats.meanSaturation <= 8.0f;
    } else if (behavior == "corruptscreen") {
        happen = stats.stdGray >= 40.0f && stats.edgeDensity >= 0.08f &&
                 stats.channelDiffMean >= 60.0f && stats.boundaryDensity >= 0.08f;
    }

    if (!happen) {
        return false;
    }

    DetectObject detect{};
    detect.x1 = 0;
    detect.y1 = 0;
    detect.x2 = image.cols;
    detect.y2 = image.rows;
    detect.class_id = 0;
    detect.class_name = behavior;
    detect.class_score = 1.0f;
    detect.happen = true;
    happenDetects.push_back(detect);

    userData["event"] = videoQualityEventName(behavior);
    userData["count"] = 1;
    return true;
}

}  // namespace AVSAnalyzer

#endif  // ANALYZER_BEHAVIOR_VIDEO_QUALITY_H
