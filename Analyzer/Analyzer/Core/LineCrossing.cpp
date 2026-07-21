#include "LineCrossing.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include <cmath>
#include <exception>
#include <stdexcept>

namespace AVSAnalyzer {

	    Line Line::fromString(const std::string& str, int imageWidth, int imageHeight) {
	        if (const std::vector<std::string> parts = split(str, ","); parts.size() >= 4) {
	            try {
	                float x1 = std::stof(parts[0]);
	                float y1 = std::stof(parts[1]);
	                float x2 = std::stof(parts[2]);
                float y2 = std::stof(parts[3]);

                // 将归一化坐标转换为像素坐标
                const auto w = static_cast<float>(imageWidth);
                const auto h = static_cast<float>(imageHeight);
                cv::Point p1(static_cast<int>(x1 * w),
                            static_cast<int>(y1 * h));
                cv::Point p2(static_cast<int>(x2 * w),
                            static_cast<int>(y2 * h));

                std::string name = (parts.size() > 4) ? parts[4] : "line";
                return Line(p1, p2, name);
            }
            catch (const std::invalid_argument&) {
                LOGE("Failed to parse line from string: %s", str.c_str());
            }
            catch (const std::out_of_range&) {
                LOGE("Failed to parse line from string: %s", str.c_str());
            }
        }
        return Line();
    }

    int LineCrossingDetector::crossProduct(const cv::Point& o, const cv::Point& a, const cv::Point& b) {
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    }

    bool LineCrossingDetector::isLeftOfLine(const cv::Point& point, const Line& line) {
        int cp = crossProduct(line.p1, line.p2, point);
        return cp > 0;  // 左侧为正
    }

    bool LineCrossingDetector::linesIntersect(const cv::Point& p1, const cv::Point& p2,
                                               const cv::Point& p3, const cv::Point& p4,
                                               cv::Point& intersection) {
        int d = (p1.x - p2.x) * (p3.y - p4.y) - (p1.y - p2.y) * (p3.x - p4.x);
        if (d == 0) {
            return false;  // 平行或重合
        }

        int pre = (p1.x * p2.y - p1.y * p2.x);
        int post = (p3.x * p4.y - p3.y * p4.x);

        int x = (pre * (p3.x - p4.x) - (p1.x - p2.x) * post) / d;
        int y = (pre * (p3.y - p4.y) - (p1.y - p2.y) * post) / d;

        // 检查交点是否在两条线段上
        if (x < std::min(p1.x, p2.x) || x > std::max(p1.x, p2.x) ||
            x < std::min(p3.x, p4.x) || x > std::max(p3.x, p4.x) ||
            y < std::min(p1.y, p2.y) || y > std::max(p1.y, p2.y) ||
            y < std::min(p3.y, p4.y) || y > std::max(p3.y, p4.y)) {
            return false;
        }

        intersection = cv::Point(x, y);
        return true;
    }

    std::vector<LineCrossingEvent> LineCrossingDetector::detectCrossing(
        const std::vector<TrackedObject>& tracks, int64_t timestamp) {

        std::vector<LineCrossingEvent> events;

        for (const auto& track : tracks) {
            if (track.trajectory.size() < 2) {
                continue;  // 需要至少2个点才能判断越线
            }

            int trackId = track.trackId;
            cv::Point currentPos = track.trajectory.back();
            cv::Point prevPos = (track.trajectory.size() >= 2) ?
                               track.trajectory[track.trajectory.size() - 2] :
                               currentPos;

            // 检查每条线
            for (const auto& line : mLines) {
                bool prevLeft = isLeftOfLine(prevPos, line);
                bool currLeft = isLeftOfLine(currentPos, line);

                // 判断是否越线（左右侧发生变化）
                if (prevLeft != currLeft) {
                    // 检查是否已经记录过该目标越过该线
                    if (mCrossingHistory[line.name].count(trackId) > 0) {
                        continue;  // 已经越过，避免重复触发
                    }

                    cv::Point crossPoint;
                    if (linesIntersect(prevPos, currentPos, line.p1, line.p2, crossPoint)) {
                        LineCrossingEvent event;
                        event.trackId = trackId;
                        event.lineName = line.name;
                        event.crossPoint = crossPoint;
                        event.timestamp = timestamp;
                        event.object = track.detection;

                        // 判断方向
                        if (prevLeft && !currLeft) {
                            event.direction = CrossDirection::Forward;  // 从左到右
                        } else {
                            event.direction = CrossDirection::Backward;  // 从右到左
	                        }

	                        // 判断是否违规
	                        if (auto it = mViolationDirections.find(line.name); it != mViolationDirections.end()) {
	                            event.isViolation = (event.direction == it->second);
	                        } else {
	                            event.isViolation = false;  // 默认不违规
	                        }

                        events.push_back(event);
                        mCrossingHistory[line.name].insert(trackId);

                        LOGI("Line crossing detected: track=%d, line=%s, direction=%d, violation=%d",
                             trackId, line.name.c_str(), static_cast<int>(event.direction),
                             event.isViolation);
                    }
                }
            }

            // 更新位置记录
            mLastPositions[trackId] = currentPos;
        }

        return events;
    }

    bool LineCrossingNode::process(PipelineContext& context) {
        if (!mTrackerNode) {
            return false;
        }

        // 获取追踪器的追踪结果
        const auto& tracks = mTrackerNode->getTracker().getTracks();
        std::vector<TrackedObject> trackList;
        for (const auto& pair : tracks) {
            trackList.push_back(pair.second);
        }

        // 检测越线事件
        mEvents = mDetector.detectCrossing(trackList, context.timestamp);

        // 将越线事件信息添加到上下文中
        if (!mEvents.empty()) {
            context.globalAttrs["line_crossing_count"] = static_cast<float>(mEvents.size());

            // 统计违规事件
            int violationCount = 0;
            for (const auto& event : mEvents) {
                if (event.isViolation) {
                    violationCount++;
                }
            }
            context.globalAttrs["line_violation_count"] = static_cast<float>(violationCount);

            LOGI("LineCrossingNode: %zu crossing events, %d violations",
                 mEvents.size(), violationCount);
        }

        return true;
    }

} // namespace AVSAnalyzer
