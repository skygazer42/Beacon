#ifndef ANALYZER_BYTE_TRACK_H
#define ANALYZER_BYTE_TRACK_H

#include <vector>
#include <map>
#include <deque>
#include <memory>
#include <opencv2/opencv.hpp>
#include "Algorithm.h"
#include "AlgorithmPipeline.h"
#include "Tracker.h"

namespace AVSAnalyzer {

    // ========== 卡尔曼滤波器（用于目标状态预测）==========
    class KalmanBoxTracker {
    public:
        explicit KalmanBoxTracker(const cv::Rect& bbox);

        // 预测下一帧位置
        cv::Rect predict();

        // 更新状态（使用观测值）
        void update(const cv::Rect& bbox);

        // 获取当前状态
        cv::Rect getState() const;

        // 获取预测的下一帧位置
        cv::Rect getPrediction() const { return mPredictedBox; }

    private:
        cv::KalmanFilter mKF;
        cv::Rect mPredictedBox;
        int mTimeSinceUpdate = 0;
        int mAge = 0;
    };

    // ========== ByteTrack 追踪对象 ==========
	    struct STrack {
        int trackId = -1;
        cv::Rect bbox;
        float score;
        int frameId;
        int trackletLen = 0;    // 追踪持续长度
        int startFrame;
        bool isActivated = false; // 是否已激活

	        std::unique_ptr<KalmanBoxTracker> kalmanFilter;
	        cv::Rect prediction;    // 预测位置

        // 追踪状态
        enum class State {
            New = 0,            // 新追踪
            Tracked = 1,        // 正在追踪
            Lost = 2,           // 丢失
            Removed = 3         // 已移除
        };
	        State state = State::New;

	        STrack(const cv::Rect& bbox, float score, int currentFrameId);
	        ~STrack() = default;

            STrack(const STrack&) = delete;
            STrack& operator=(const STrack&) = delete;
            STrack(STrack&&) noexcept = default;
            STrack& operator=(STrack&&) noexcept = default;

        void activate(int currentFrameId, int newId);
        void reActivate(const STrack& newTrack, int currentFrameId, int newId = -1);
        void update(const STrack& newTrack, int currentFrameId);
        void markLost();
        void markRemoved();

        cv::Rect tlwh() const { return bbox; }
        cv::Rect tlbr() const {
            return cv::Rect(bbox.x, bbox.y, bbox.x + bbox.width, bbox.y + bbox.height);
        }

        static cv::Rect tlbrToTlwh(const cv::Rect& tlbr) {
            return cv::Rect(tlbr.x, tlbr.y, tlbr.width - tlbr.x, tlbr.height - tlbr.y);
        }
    };

    // ========== ByteTrack 追踪器 ==========
		    class ByteTracker {
		    public:
		        explicit ByteTracker(
		            int frameRate = 30,
		            int trackBuffer = 30,           // 追踪缓冲帧数
		            float trackThresh = 0.5f,       // 高分检测阈值
		            float highThresh = 0.6f,        // 高分阈值（第一次关联）
		            float matchThresh = 0.8f        // IOU匹配阈值
		        );

		        ~ByteTracker();

		        ByteTracker(const ByteTracker&) = delete;
		        ByteTracker& operator=(const ByteTracker&) = delete;
		        ByteTracker(ByteTracker&& other) noexcept;
		        ByteTracker& operator=(ByteTracker&& other) noexcept;

	        // 更新追踪（ByteTrack核心算法）
	        std::vector<STrack*> update(const std::vector<DetectObject>& detections, int frameId);

        // 清空追踪器
        void clear();

        // 获取追踪数量
        size_t getTrackCount() const;

        // 计算IOU（公开：用于将追踪结果回写到检测对象中）
        static float iou(const cv::Rect& a, const cv::Rect& b);

    private:
        // 计算IOU矩阵
        static std::vector<std::vector<float>> iouDistance(
            const std::vector<STrack*>& aTracks,
            const std::vector<STrack*>& bTracks
        );

        // 基于代价升序的贪心一对一分配
        static void linearAssignment(
            const std::vector<std::vector<float>>& costMatrix,
            float thresh,
            std::vector<std::vector<int>>& matches,
            std::vector<int>& unmatched_a,
            std::vector<int>& unmatched_b
        );

        // 移除重复追踪
        void removeDuplicateStracks(
            std::vector<STrack*>& aTracks,
            std::vector<STrack*>& bTracks,
            std::vector<STrack*>& result
        );

        // 合并追踪列表
        void jointStracks(
            std::vector<STrack*>& aTracks,
            const std::vector<STrack*>& bTracks,
            std::vector<STrack*>& result
        );

        // 从追踪列表中减去另一个列表
        void subStracks(
            std::vector<STrack*>& aTracks,
            const std::vector<STrack*>& bTracks
        );

    private:
        int mFrameId = 0;
        int mFrameRate;
        int mTrackBuffer;
        float mTrackThresh;
        float mHighThresh;
        float mMatchThresh;
        int mMaxTimeLost;
        int mNextId = 1;

	        std::vector<std::unique_ptr<STrack>> mTrackedStracks;   // 正在追踪的目标
	        std::vector<std::unique_ptr<STrack>> mLostStracks;      // 丢失的目标
	        std::vector<std::unique_ptr<STrack>> mRemovedStracks;   // 已移除的目标
	    };

    // ========== ByteTrack 追踪节点 ==========
    class ByteTrackNode : public PipelineNode {
    public:
        explicit ByteTrackNode(
            const std::string& name,
            int frameRate = 30,
            int trackBuffer = 30,
            float trackThresh = 0.5f,
            float highThresh = 0.6f,
            float matchThresh = 0.8f
        ) : mName(name),
            mTracker(frameRate, trackBuffer, trackThresh, highThresh, matchThresh) {}

        bool process(PipelineContext& context) override;

        PipelineNodeType getType() const override {
            return PipelineNodeType::Tracker;
        }

        std::string getName() const override {
            return mName;
        }

        // 获取追踪器
        ByteTracker& getTracker() {
            return mTracker;
        }

    private:
        std::string mName;
        ByteTracker mTracker;
        int mFrameId = 0;
    };

    // ========== 贪心一对一分配 ==========
    class GreedyAssignment {
    public:
        // 按代价从低到高选择不冲突的行列配对
        static std::vector<int> Solve(const std::vector<std::vector<float>>& costMatrix);
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_BYTE_TRACK_H
