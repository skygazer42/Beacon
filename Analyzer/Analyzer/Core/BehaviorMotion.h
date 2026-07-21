#ifndef ANALYZER_BEHAVIOR_MOTION_H
#define ANALYZER_BEHAVIOR_MOTION_H

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include <json/value.h>

#include "AlgorithmPipeline.h"
#include "Tracker.h"

namespace AVSAnalyzer {

inline float computeTrackMotionDisplacement(const TrackedObject& track) {
    if (track.trajectory.size() < 2) {
        return 0.0f;
    }
    const cv::Point& first = track.trajectory.front();
    const cv::Point& last = track.trajectory.back();
    const auto dx = static_cast<float>(last.x - first.x);
    const auto dy = static_cast<float>(last.y - first.y);
    return std::sqrt(dx * dx + dy * dy);
}

inline bool evaluateMotionBehavior(
    const std::vector<TrackedObject>& tracks,
    float minDisplacement,
    const std::string& eventName,
    std::vector<DetectObject>& happenDetects,
    Json::Value& userData) {
    happenDetects.clear();
    userData = Json::Value(Json::objectValue);

    if (minDisplacement < 0.0f) {
        minDisplacement = 0.0f;
    }

    int bestTrackId = 0;
    float bestDisplacement = 0.0f;
    Json::Value internalTargets(Json::arrayValue);

    for (const auto& track : tracks) {
        if (track.trackId <= 0) {
            continue;
        }
        const float displacement = computeTrackMotionDisplacement(track);
        if (displacement < minDisplacement) {
            continue;
        }

        DetectObject d = track.detection;
        d.happen = true;
        d.attributes["track_id"] = static_cast<float>(track.trackId);
        d.attributes["motion_displacement"] = displacement;
        happenDetects.push_back(d);

        Json::Value item(Json::objectValue);
        item["track_id"] = track.trackId;
        item["motion_displacement"] = displacement;
        internalTargets.append(item);

        if (displacement >= bestDisplacement) {
            bestDisplacement = displacement;
            bestTrackId = track.trackId;
        }
    }

    if (happenDetects.empty()) {
        return false;
    }

    userData["behavior"] = "motion";
    userData["event"] = eventName.empty() ? "MOTION" : eventName;
    userData["track_id"] = bestTrackId;
    userData["motion_count"] = static_cast<int>(happenDetects.size());
    userData["motion_displacement"] = bestDisplacement;
    userData["internal_targets"] = internalTargets;
    return true;
}

}  // namespace AVSAnalyzer

#endif  // ANALYZER_BEHAVIOR_MOTION_H
