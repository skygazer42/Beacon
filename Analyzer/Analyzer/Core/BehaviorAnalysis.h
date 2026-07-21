#ifndef ANALYZER_BEHAVIOR_ANALYSIS_H
#define ANALYZER_BEHAVIOR_ANALYSIS_H

#include <vector>
#include <map>
#include <string>
#include <opencv2/opencv.hpp>
#include "Tracker.h"
#include "AlgorithmPipeline.h"

namespace AVSAnalyzer {

    // ========== 行为分析类型 ==========
    enum class BehaviorType {
        LineCrossing,       // 越线检测
        Loitering,          // 停留/徘徊检测
        IntrusionDetection, // 区域入侵检测
        FallDetection,      // 跌倒检测（基于姿态）
        Counting,           // 计数（进出统计）
        CrowdDensity,       // 密度检测
        SpeedEstimation,    // 速度估计
        DirectionChange     // 方向突变检测
    };

    // ========== 停留检测节点 ==========
    // 检测目标在指定区域内停留超过阈值时间
    class LoiteringNode : public BehaviorNode {
    public:
        LoiteringNode(const std::string& name, TrackerNode* trackerNode,
                     int durationThreshold = 30,  // 停留帧数阈值（约1秒@30fps）
                     float minIOU = 0.5f)          // 判断在区域内的IOU阈值
            : BehaviorNode(name), mTrackerNode(trackerNode),
              mDurationThreshold(durationThreshold) {
            (void)minIOU;
        }

        bool process(PipelineContext& context) override;

        // 设置检测区域（多边形）
        void setRegions(const std::vector<std::vector<cv::Point>>& regions) {
            mRegions = regions;
        }

        // 获取停留事件
        const std::map<int, int>& getLoiteringTracks() const {
            return mLoiteringFrames;  // trackId -> 停留帧数
        }

    private:
        bool isInRegion(const DetectObject& obj, const std::vector<cv::Point>& region);
        float computeIOU(const cv::Rect& box, const std::vector<cv::Point>& region);

        TrackerNode* mTrackerNode;
        int mDurationThreshold;
        std::vector<std::vector<cv::Point>> mRegions;
        std::map<int, int> mLoiteringFrames;  // trackId -> 已停留帧数
    };

    // ========== 区域入侵检测节点 ==========
    // 检测目标进入禁止区域
    class IntrusionNode : public BehaviorNode {
    public:
        IntrusionNode(const std::string& name, TrackerNode* trackerNode,
                     float minIOU = 0.1f)  // 触发入侵的最小IOU阈值
            : BehaviorNode(name), mTrackerNode(trackerNode) {
            (void)minIOU;
        }

        bool process(PipelineContext& context) override;

        // 设置禁止区域
        void setForbiddenRegions(const std::vector<std::vector<cv::Point>>& regions) {
            mForbiddenRegions = regions;
        }

        // 获取入侵目标
        const std::set<int>& getIntruders() const {
            return mIntruders;
        }

    private:
        bool isInRegion(const DetectObject& obj, const std::vector<cv::Point>& region);

        TrackerNode* mTrackerNode;
        std::vector<std::vector<cv::Point>> mForbiddenRegions;
        std::set<int> mIntruders;  // 当前入侵的trackId集合
    };

    // ========== 跌倒检测节点 ==========
    // 基于姿态关键点检测跌倒行为
    class FallDetectionNode : public BehaviorNode {
    public:
        explicit FallDetectionNode(const std::string& name,
                         float aspectRatioThreshold = 1.5f,   // 宽高比阈值（横向>竖向）
                         float hipKneeAngleThreshold = 120.0f) // 髋-膝角度阈值
            : BehaviorNode(name),
              mAspectRatioThreshold(aspectRatioThreshold),
              mHipKneeAngleThreshold(hipKneeAngleThreshold) {}

        bool process(PipelineContext& context) override;

        // 获取跌倒目标索引
        const std::vector<int>& getFallenIndices() const {
            return mFallenIndices;
        }

    private:
        bool detectFall(const DetectObject& obj);
        float computeAngle(const cv::Point2f& p1, const cv::Point2f& p2, const cv::Point2f& p3);

        float mAspectRatioThreshold;
        float mHipKneeAngleThreshold;
        std::vector<int> mFallenIndices;
    };

    // ========== 计数节点 ==========
    // 统计通过计数线的目标数量
    class CountingNode : public BehaviorNode {
    public:
        struct CountingLine {
            cv::Point p1;
            cv::Point p2;
            std::string name;
            int inCount = 0;   // 进入计数
            int outCount = 0;  // 离开计数

            CountingLine() = default;
            CountingLine(const cv::Point& start, const cv::Point& end, const std::string& n)
                : p1(start), p2(end), name(n) {}
        };

        CountingNode(const std::string& name, TrackerNode* trackerNode)
            : BehaviorNode(name), mTrackerNode(trackerNode) {}

        bool process(PipelineContext& context) override;

        // 设置计数线
        void setCountingLines(const std::vector<CountingLine>& lines) {
            mCountingLines = lines;
        }

        // 获取统计结果
        const std::vector<CountingLine>& getCounts() const {
            return mCountingLines;
        }

    private:
        bool isLeftOfLine(const cv::Point& point, const cv::Point& p1, const cv::Point& p2);
        int crossProduct(const cv::Point& o, const cv::Point& a, const cv::Point& b);

        TrackerNode* mTrackerNode;
        std::vector<CountingLine> mCountingLines;
        std::map<int, std::map<std::string, bool>> mLastSide;  // trackId -> lineName -> isLeft
    };

    // ========== 速度估计节点 ==========
    // 估计目标移动速度并检测超速
    class SpeedEstimationNode : public BehaviorNode {
    public:
        SpeedEstimationNode(const std::string& name, TrackerNode* trackerNode,
                           float pixelsPerMeter = 10.0f,  // 像素到米的转换比例
                           float fps = 25.0f,              // 视频帧率
                           float speedThreshold = 5.0f)    // 超速阈值（米/秒）
            : BehaviorNode(name), mTrackerNode(trackerNode),
              mPixelsPerMeter(pixelsPerMeter), mFPS(fps),
              mSpeedThreshold(speedThreshold) {}

        bool process(PipelineContext& context) override;

        // 获取速度估计结果
        const std::map<int, float>& getSpeeds() const {
            return mSpeeds;  // trackId -> 速度（米/秒）
        }

        // 获取超速目标
        const std::set<int>& getSpeeders() const {
            return mSpeeders;
        }

    private:
        TrackerNode* mTrackerNode;
        float mPixelsPerMeter;
        float mFPS;
        float mSpeedThreshold;
        std::map<int, float> mSpeeds;
        std::set<int> mSpeeders;
    };

    // ========== 算法管道构建器扩展 ==========
    class ExtendedPipelineBuilder {
    public:
        ExtendedPipelineBuilder() = default;

        // 添加检测节点
        ExtendedPipelineBuilder& addDetector(Algorithm* algo, const std::string& name,
                                            float confThresh, float nmsThresh) {
            mPipeline->addNode(std::make_unique<DetectorNode>(algo, name, confThresh, nmsThresh));
            return *this;
        }

        // 添加追踪节点
        ExtendedPipelineBuilder& addTracker(const std::string& name, float iouThreshold = 0.3f,
                                           int maxLost = 30, int maxTrajectory = 50) {
            auto node = std::make_unique<TrackerNode>(name, iouThreshold, maxLost, maxTrajectory);
            mLastTracker = node.get();  // 保存最后一个追踪节点，供行为节点使用
            mPipeline->addNode(std::move(node));
            return *this;
        }

        // 添加分类节点
        ExtendedPipelineBuilder& addClassifier(Algorithm* algo, const std::string& name,
                                              float confThresh) {
            mPipeline->addNode(std::make_unique<ClassifierNode>(algo, name, confThresh));
            return *this;
        }

        // 添加停留检测节点
        ExtendedPipelineBuilder& addLoitering(const std::string& name, int durationThreshold = 30,
                                             float minIOU = 0.5f) {
            if (!mLastTracker) {
                LOGE("Cannot add LoiteringNode without a TrackerNode first");
                return *this;
            }
            mPipeline->addNode(std::make_unique<LoiteringNode>(name, mLastTracker, durationThreshold, minIOU));
            return *this;
        }

        // 添加入侵检测节点
        ExtendedPipelineBuilder& addIntrusion(const std::string& name, float minIOU = 0.1f) {
            if (!mLastTracker) {
                LOGE("Cannot add IntrusionNode without a TrackerNode first");
                return *this;
            }
            mPipeline->addNode(std::make_unique<IntrusionNode>(name, mLastTracker, minIOU));
            return *this;
        }

        // 添加跌倒检测节点
        ExtendedPipelineBuilder& addFallDetection(const std::string& name,
                                                  float aspectRatioThreshold = 1.5f,
                                                  float hipKneeAngleThreshold = 120.0f) {
            mPipeline->addNode(std::make_unique<FallDetectionNode>(name, aspectRatioThreshold, hipKneeAngleThreshold));
            return *this;
        }

        // 添加计数节点
        ExtendedPipelineBuilder& addCounting(const std::string& name) {
            if (!mLastTracker) {
                LOGE("Cannot add CountingNode without a TrackerNode first");
                return *this;
            }
            mPipeline->addNode(std::make_unique<CountingNode>(name, mLastTracker));
            return *this;
        }

        // 添加速度估计节点
        ExtendedPipelineBuilder& addSpeedEstimation(const std::string& name,
                                                    float pixelsPerMeter = 10.0f,
                                                    float fps = 25.0f,
                                                    float speedThreshold = 5.0f) {
            if (!mLastTracker) {
                LOGE("Cannot add SpeedEstimationNode without a TrackerNode first");
                return *this;
            }
            mPipeline->addNode(std::make_unique<SpeedEstimationNode>(name, mLastTracker, pixelsPerMeter, fps, speedThreshold));
            return *this;
        }

        // 构建管道
        std::unique_ptr<AlgorithmPipeline> build() {
            return std::move(mPipeline);
        }

    private:
        std::unique_ptr<AlgorithmPipeline> mPipeline = std::make_unique<AlgorithmPipeline>();
        TrackerNode* mLastTracker = nullptr;
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_BEHAVIOR_ANALYSIS_H
