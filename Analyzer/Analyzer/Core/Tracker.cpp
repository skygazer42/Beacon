#include "Tracker.h"
#include "Utils/Log.h"
#include <algorithm>

namespace AVSAnalyzer {

    float SimpleTracker::computeIOU(const DetectObject& a, const DetectObject& b) {
        int x1 = std::max(a.x1, b.x1);
        int y1 = std::max(a.y1, b.y1);
        int x2 = std::min(a.x2, b.x2);
        int y2 = std::min(a.y2, b.y2);

        if (x2 < x1 || y2 < y1) {
            return 0.0f;
        }

        auto intersectionArea = static_cast<float>((x2 - x1) * (y2 - y1));
        auto areaA = static_cast<float>((a.x2 - a.x1) * (a.y2 - a.y1));
        auto areaB = static_cast<float>((b.x2 - b.x1) * (b.y2 - b.y1));
        float unionArea = areaA + areaB - intersectionArea;

        if (unionArea <= 0.0f) {
            return 0.0f;
        }

        return intersectionArea / unionArea;
    }

    cv::Point SimpleTracker::getCenter(const DetectObject& det) {
        return cv::Point((det.x1 + det.x2) / 2, (det.y1 + det.y2) / 2);
    }

    std::vector<TrackedObject> SimpleTracker::update(const std::vector<DetectObject>& detections,
                                                      int64_t timestamp) {
        // 1. 计算匹配矩阵（IOU）
        std::vector<std::vector<float>> iouMatrix;
        std::vector<int> trackIds;

        for (const auto& pair : mTracks) {
            trackIds.push_back(pair.first);
            std::vector<float> row;
            for (const auto& det : detections) {
                float iou = computeIOU(pair.second.detection, det);
                row.push_back(iou);
            }
            iouMatrix.push_back(row);
        }

        // 2. 匹配追踪与检测（简单贪心匹配）
        std::vector<bool> trackMatched(trackIds.size(), false);
        std::vector<bool> detMatched(detections.size(), false);

        // 按 IOU 降序匹配
        for (size_t iter = 0; iter < trackIds.size() * detections.size(); ++iter) {
            float maxIOU = mIouThreshold;
            int maxTrackIdx = -1;
            int maxDetIdx = -1;

            for (size_t ti = 0; ti < trackIds.size(); ++ti) {
                if (trackMatched[ti]) continue;
                for (size_t di = 0; di < detections.size(); ++di) {
                    if (detMatched[di]) continue;
                    if (iouMatrix[ti][di] > maxIOU) {
                        maxIOU = iouMatrix[ti][di];
                        maxTrackIdx = static_cast<int>(ti);
                        maxDetIdx = static_cast<int>(di);
                    }
                }
            }

            if (maxTrackIdx == -1) break;

            // 匹配成功
            trackMatched[maxTrackIdx] = true;
            detMatched[maxDetIdx] = true;

            int trackId = trackIds[maxTrackIdx];
            auto& track = mTracks[trackId];
            track.detection = detections[maxDetIdx];
            track.age++;
            track.lostFrames = 0;
            track.lastSeen = timestamp;

            cv::Point center = getCenter(detections[maxDetIdx]);
            track.trajectory.push_back(center);
            if (track.trajectory.size() > static_cast<size_t>(mMaxTrajectoryLength)) {
                track.trajectory.pop_front();
            }
        }

        // 3. 处理未匹配的追踪（增加丢失计数）
        std::vector<int> toRemove;
        for (size_t ti = 0; ti < trackIds.size(); ++ti) {
            if (!trackMatched[ti]) {
                int trackId = trackIds[ti];
                auto& track = mTracks[trackId];
                track.lostFrames++;
                if (track.lostFrames > mMaxLostFrames) {
                    toRemove.push_back(trackId);
                }
            }
        }

        // 移除丢失太久的追踪
        for (int id : toRemove) {
            mTracks.erase(id);
        }

        // 4. 创建新追踪（未匹配的检测）
        for (size_t di = 0; di < detections.size(); ++di) {
            if (!detMatched[di]) {
                TrackedObject newTrack;
                newTrack.trackId = mNextId++;
                newTrack.detection = detections[di];
                newTrack.age = 1;
                newTrack.lostFrames = 0;
                newTrack.firstSeen = timestamp;
                newTrack.lastSeen = timestamp;
                cv::Point center = getCenter(detections[di]);
                newTrack.trajectory.push_back(center);

                mTracks[newTrack.trackId] = newTrack;
            }
        }

        // 5. 返回所有活跃追踪
        std::vector<TrackedObject> result;
        for (const auto& pair : mTracks) {
            result.push_back(pair.second);
        }

        return result;
    }

    bool TrackerNode::process(PipelineContext& context) {
        if (context.detections.empty()) {
            // 没有检测结果，但仍需更新追踪器（处理丢失）
            mTracker.update(context.detections, context.timestamp);
            return true;
        }

        // 更新追踪器
        std::vector<TrackedObject> tracks = mTracker.update(context.detections, context.timestamp);

        LOGI("TrackerNode: %zu detections -> %zu tracks", context.detections.size(), tracks.size());

        // 将追踪ID添加到检测对象的属性中
        // 注意：这里假设检测结果和追踪结果的顺序对应
        // 更健壮的方法是根据 IOU 重新匹配
        for (size_t i = 0; i < context.detections.size() && i < tracks.size(); ++i) {
            // 找到对应的追踪（通过 IOU）
            float maxIOU = 0.0f;
            int bestTrackIdx = -1;
            for (size_t ti = 0; ti < tracks.size(); ++ti) {
                float iou = mTracker.computeIOU(context.detections[i], tracks[ti].detection);
                if (iou > maxIOU) {
                    maxIOU = iou;
                    bestTrackIdx = static_cast<int>(ti);
                }
            }

            if (bestTrackIdx >= 0 && maxIOU > 0.3f) {
                context.detections[i].attributes["track_id"] = static_cast<float>(tracks[bestTrackIdx].trackId);
                context.detections[i].attributes["track_age"] = static_cast<float>(tracks[bestTrackIdx].age);
            }
        }

        return true;
    }

} // namespace AVSAnalyzer
