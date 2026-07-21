#ifndef ANALYZER_TRACKER_H
#define ANALYZER_TRACKER_H

#include <vector>
#include <map>
#include <deque>
#include <opencv2/opencv.hpp>
#include "Algorithm.h"
#include "AlgorithmPipeline.h"

namespace AVSAnalyzer {

    // 追踪目标
    struct TrackedObject {
        int trackId = -1;                   // 追踪ID
        DetectObject detection;             // 当前检测结果
        std::deque<cv::Point> trajectory;   // 轨迹点（中心点历史）
        int age = 0;                        // 存活帧数
        int lostFrames = 0;                 // 丢失帧数
        int64_t firstSeen = 0;              // 首次出现时间戳
        int64_t lastSeen = 0;               // 最后出现时间戳
        cv::Mat feature;                    // 外观特征（可选）

        TrackedObject() = default;

        // `TrackedObject` is frequently moved around (e.g. vectors / maps).
        // Make the move operations explicitly `noexcept` to allow standard
        // containers to optimize reallocation paths.
        TrackedObject(const TrackedObject&) = default;
        TrackedObject& operator=(const TrackedObject&) = default;
        TrackedObject(TrackedObject&&) noexcept = default;
        TrackedObject& operator=(TrackedObject&&) noexcept = default;
    };

	    // 简单的 IOU-based 追踪器
	    class SimpleTracker {
	    public:
	        explicit SimpleTracker(float iouThreshold = 0.3f, int maxLost = 30, int maxTrajectory = 50)
	            : mIouThreshold(iouThreshold), mMaxLostFrames(maxLost),
	              mMaxTrajectoryLength(maxTrajectory) {}

        // 更新追踪（输入当前帧检测结果）
        std::vector<TrackedObject> update(const std::vector<DetectObject>& detections,
                                          int64_t timestamp);

        // 获取当前追踪目标
        const std::map<int, TrackedObject>& getTracks() const {
            return mTracks;
        }

        // 清空追踪器
        void clear() {
            mTracks.clear();
            mNextId = 1;
        }

        // 获取追踪数量
	        size_t getTrackCount() const {
	            return mTracks.size();
	        }

	        float computeIOU(const DetectObject& a, const DetectObject& b);

	    private:
	        cv::Point getCenter(const DetectObject& det);

        std::map<int, TrackedObject> mTracks;  // trackId -> TrackedObject
        int mNextId = 1;
        float mIouThreshold;
        int mMaxLostFrames;
        int mMaxTrajectoryLength;
    };

	    // 追踪节点：包装追踪器
	    class TrackerNode : public PipelineNode {
	    public:
	        explicit TrackerNode(const std::string& name, float iouThreshold = 0.3f,
	                   int maxLost = 30, int maxTrajectory = 50)
	            : mName(name), mTracker(iouThreshold, maxLost, maxTrajectory) {}

        bool process(PipelineContext& context) override;

        PipelineNodeType getType() const override {
            return PipelineNodeType::Tracker;
        }

        std::string getName() const override {
            return mName;
        }

        // 获取追踪器
        SimpleTracker& getTracker() {
            return mTracker;
        }

    private:
        std::string mName;
        SimpleTracker mTracker;
    };

	    // 行为分析节点基类
	    class BehaviorNode : public PipelineNode {
	    public:
	        explicit BehaviorNode(const std::string& name) : mName(name) {}

        PipelineNodeType getType() const override {
            return PipelineNodeType::Behavior;
        }

        std::string getName() const override {
            return mName;
        }

    private:
        std::string mName;
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_TRACKER_H
