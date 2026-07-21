#include "BehaviorAnalysis.h"
#include "Utils/Log.h"
#include <cmath>
#include <algorithm>

namespace AVSAnalyzer {

    // ========== LoiteringNode Implementation ==========

    bool LoiteringNode::isInRegion(const DetectObject& obj, const std::vector<cv::Point>& region) {
        if (region.empty()) return false;

        // 使用目标中心点判断
        cv::Point center((obj.x1 + obj.x2) / 2, (obj.y1 + obj.y2) / 2);
        double result = cv::pointPolygonTest(region, center, false);
        return result >= 0;  // >=0 表示在多边形内部或边界上
    }

    float LoiteringNode::computeIOU(const cv::Rect& box, const std::vector<cv::Point>& region) {
        if (region.empty()) return 0.0f;

        // 计算边界框与多边形的交集面积
        cv::Rect boundingRect = cv::boundingRect(region);
        cv::Rect intersection = box & boundingRect;

        if (intersection.area() == 0) {
            return 0.0f;
        }

        // 简化：使用边界矩形的IOU作为近似
        auto intersectionArea = static_cast<float>(intersection.area());
        auto boxArea = static_cast<float>(box.area());
        auto regionArea = static_cast<float>(boundingRect.area());
        float unionArea = boxArea + regionArea - intersectionArea;

        return (unionArea > 0) ? (intersectionArea / unionArea) : 0.0f;
    }

    bool LoiteringNode::process(PipelineContext& context) {
        if (!mTrackerNode || mRegions.empty()) {
            return true;
        }

        const auto& tracks = mTrackerNode->getTracker().getTracks();

        // 遍历所有追踪目标
        for (const auto& pair : tracks) {
            int trackId = pair.first;
            const auto& track = pair.second;

            // 检查是否在任一区域内
            bool inAnyRegion = false;
            for (const auto& region : mRegions) {
                if (isInRegion(track.detection, region)) {
                    inAnyRegion = true;
                    break;
                }
            }

            if (inAnyRegion) {
                // 在区域内，增加停留帧数
                mLoiteringFrames[trackId]++;

                // 检查是否超过阈值
                if (mLoiteringFrames[trackId] >= mDurationThreshold) {
                    // 标记为停留事件
                    context.globalAttrs["loitering_detected"] = 1.0f;
                    context.globalAttrs["loitering_track_id"] = static_cast<float>(trackId);
                    context.globalAttrs["loitering_duration"] = static_cast<float>(mLoiteringFrames[trackId]);

                    LOGI("Loitering detected: track=%d, duration=%d frames",
                         trackId, mLoiteringFrames[trackId]);
                }
            } else {
                // 不在区域内，重置计数
                mLoiteringFrames[trackId] = 0;
            }
        }

        // 清理已消失的追踪
        std::vector<int> toRemove;
        for (const auto& pair : mLoiteringFrames) {
            if (tracks.find(pair.first) == tracks.end()) {
                toRemove.push_back(pair.first);
            }
        }
        for (int id : toRemove) {
            mLoiteringFrames.erase(id);
        }

        return true;
    }

    // ========== IntrusionNode Implementation ==========

    bool IntrusionNode::isInRegion(const DetectObject& obj, const std::vector<cv::Point>& region) {
        if (region.empty()) return false;

        cv::Point center((obj.x1 + obj.x2) / 2, (obj.y1 + obj.y2) / 2);
        double result = cv::pointPolygonTest(region, center, false);
        return result >= 0;
    }

    bool IntrusionNode::process(PipelineContext& context) {
        if (!mTrackerNode || mForbiddenRegions.empty()) {
            return true;
        }

        const auto& tracks = mTrackerNode->getTracker().getTracks();
        mIntruders.clear();

        int intrusionCount = 0;
        for (const auto& pair : tracks) {
            int trackId = pair.first;
            const auto& track = pair.second;

            // 检查是否在禁止区域内
            for (const auto& region : mForbiddenRegions) {
                if (isInRegion(track.detection, region)) {
                    mIntruders.insert(trackId);
                    intrusionCount++;

                    LOGI("Intrusion detected: track=%d in forbidden region", trackId);
                    break;
                }
            }
        }

        if (intrusionCount > 0) {
            context.globalAttrs["intrusion_count"] = static_cast<float>(intrusionCount);
            context.globalAttrs["intrusion_detected"] = 1.0f;
        }

        return true;
    }

    // ========== FallDetectionNode Implementation ==========

    float FallDetectionNode::computeAngle(const cv::Point2f& p1, const cv::Point2f& p2,
                                          const cv::Point2f& p3) {
        // 计算p1-p2-p3的角度
        cv::Point2f v1 = p1 - p2;
        cv::Point2f v2 = p3 - p2;

        float dot = v1.x * v2.x + v1.y * v2.y;
        float len1 = std::sqrt(v1.x * v1.x + v1.y * v1.y);
        float len2 = std::sqrt(v2.x * v2.x + v2.y * v2.y);

        if (len1 == 0 || len2 == 0) return 0.0f;

        float cosAngle = dot / (len1 * len2);
        cosAngle = std::max(-1.0f, std::min(1.0f, cosAngle));

        return std::acos(cosAngle) * 180.0f / static_cast<float>(M_PI);
    }

    bool FallDetectionNode::detectFall(const DetectObject& obj) {
	        // 方法1：基于边界框宽高比
	        int width = obj.x2 - obj.x1;
	        int height = obj.y2 - obj.y1;
	        if (height == 0) return false;

	        if (const float aspectRatio = static_cast<float>(width) / static_cast<float>(height);
	            aspectRatio > mAspectRatioThreshold) {
	            return true;  // 横向躺倒
	        }

        // 方法2：基于姿态关键点（如果有）
        if (obj.hasPose && obj.keypoints.size() >= 17) {
            // COCO关键点：11=left_hip, 12=right_hip, 13=left_knee, 15=left_ankle
            const auto& leftHip = obj.keypoints[11];
            const auto& rightHip = obj.keypoints[12];
            const auto& leftKnee = obj.keypoints[13];
            const auto& leftAnkle = obj.keypoints[15];

	            // 检查髋部是否接近地面（y坐标接近边界框底部）
	            float hipY = (leftHip.y + rightHip.y) / 2.0f;
	            if (const auto boxBottom = static_cast<float>(obj.y2);
	                (boxBottom - hipY) < static_cast<float>(height) * 0.3f) {  // 髋部在底部30%范围内
		                return true;
		            }

            // 检查髋-膝-踝角度
            if (leftHip.confidence > 0.5f && leftKnee.confidence > 0.5f && leftAnkle.confidence > 0.5f) {
                cv::Point2f hip(leftHip.x, leftHip.y);
                cv::Point2f knee(leftKnee.x, leftKnee.y);
                cv::Point2f ankle(leftAnkle.x, leftAnkle.y);

                float angle = computeAngle(hip, knee, ankle);
                if (angle > mHipKneeAngleThreshold) {  // 腿部伸直（跌倒状态）
                    return true;
                }
            }
        }

        return false;
    }

    bool FallDetectionNode::process(PipelineContext& context) {
        mFallenIndices.clear();

        for (size_t i = 0; i < context.detections.size(); ++i) {
            if (detectFall(context.detections[i])) {
                mFallenIndices.push_back(static_cast<int>(i));
                context.detections[i].happen = true;  // 标记为事件发生

                LOGI("Fall detected: object index=%zu", i);
            }
        }

        if (!mFallenIndices.empty()) {
            context.globalAttrs["fall_count"] = static_cast<float>(mFallenIndices.size());
            context.globalAttrs["fall_detected"] = 1.0f;
        }

        return true;
    }

    // ========== CountingNode Implementation ==========

    int CountingNode::crossProduct(const cv::Point& o, const cv::Point& a, const cv::Point& b) {
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    }

    bool CountingNode::isLeftOfLine(const cv::Point& point, const cv::Point& p1, const cv::Point& p2) {
        int cp = crossProduct(p1, p2, point);
        return cp > 0;
    }

    bool CountingNode::process(PipelineContext& context) {
        if (!mTrackerNode || mCountingLines.empty()) {
            return true;
        }

        const auto& tracks = mTrackerNode->getTracker().getTracks();

        for (const auto& pair : tracks) {
            int trackId = pair.first;
            const auto& track = pair.second;

            if (track.trajectory.size() < 2) continue;

            cv::Point currentPos = track.trajectory.back();

            // 检查每条计数线
            for (auto& line : mCountingLines) {
	                bool currLeft = isLeftOfLine(currentPos, line.p1, line.p2);

	                // 检查是否有历史位置记录
	                auto& trackLineHistory = mLastSide[trackId];
	                if (auto it = trackLineHistory.find(line.name); it != trackLineHistory.end()) {
	                    bool prevLeft = it->second;

	                    // 检测越线（左右侧变化）
	                    if (prevLeft != currLeft) {
	                        if (prevLeft && !currLeft) {
                            line.outCount++;  // 从左到右：离开
                            LOGI("Counting: track=%d crossed line '%s' (OUT), total out=%d",
                                 trackId, line.name.c_str(), line.outCount);
                        } else {
                            line.inCount++;   // 从右到左：进入
                            LOGI("Counting: track=%d crossed line '%s' (IN), total in=%d",
                                 trackId, line.name.c_str(), line.inCount);
                        }
                    }
                }

                // 更新当前侧
                trackLineHistory[line.name] = currLeft;
            }
        }

        // 将计数结果添加到上下文
        int totalIn = 0;
        int totalOut = 0;
        for (const auto& line : mCountingLines) {
            totalIn += line.inCount;
            totalOut += line.outCount;
        }

        context.globalAttrs["counting_in"] = static_cast<float>(totalIn);
        context.globalAttrs["counting_out"] = static_cast<float>(totalOut);
        context.globalAttrs["counting_net"] = static_cast<float>(totalIn - totalOut);

        return true;
    }

    // ========== SpeedEstimationNode Implementation ==========

    bool SpeedEstimationNode::process(PipelineContext& context) {
        if (!mTrackerNode) {
            return true;
        }

        const auto& tracks = mTrackerNode->getTracker().getTracks();
        mSpeeds.clear();
        mSpeeders.clear();

        for (const auto& pair : tracks) {
            int trackId = pair.first;
            const auto& track = pair.second;

            if (track.trajectory.size() < 2) continue;

            // 计算最近两帧之间的位移
            cv::Point p1 = track.trajectory[track.trajectory.size() - 2];
            cv::Point p2 = track.trajectory.back();

            const auto dx = static_cast<float>(p2.x - p1.x);
            const auto dy = static_cast<float>(p2.y - p1.y);
            float distance_pixels = std::sqrt(dx * dx + dy * dy);

            // 转换为实际距离（米）
            float distance_meters = distance_pixels / mPixelsPerMeter;

            // 计算速度（米/秒）
            float speed = distance_meters * mFPS;  // 一帧的位移 * 帧率 = 速度

            mSpeeds[trackId] = speed;

            // 检查是否超速
            if (speed > mSpeedThreshold) {
                mSpeeders.insert(trackId);
                LOGI("Speeding detected: track=%d, speed=%.2f m/s", trackId, speed);
            }
        }

        if (!mSpeeders.empty()) {
            context.globalAttrs["speeding_count"] = static_cast<float>(mSpeeders.size());
            context.globalAttrs["speeding_detected"] = 1.0f;

            // 记录最高速度
            float maxSpeed = 0.0f;
            for (const auto& pair : mSpeeds) {
                maxSpeed = std::max(maxSpeed, pair.second);
            }
            context.globalAttrs["max_speed"] = maxSpeed;
        }

        return true;
    }

} // namespace AVSAnalyzer
