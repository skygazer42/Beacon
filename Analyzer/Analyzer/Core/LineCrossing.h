#ifndef ANALYZER_LINE_CROSSING_H
#define ANALYZER_LINE_CROSSING_H

#include <vector>
#include <map>
#include <functional>
#include <string>
#include <opencv2/opencv.hpp>
#include "Tracker.h"
#include "AlgorithmPipeline.h"

namespace AVSAnalyzer {

    // 线段定义
    struct Line {
        cv::Point p1;  // 起点
        cv::Point p2;  // 终点
        std::string name;  // 线段名称

        Line() = default;
        Line(const cv::Point& start, const cv::Point& end, const std::string& n = "")
            : p1(start), p2(end), name(n) {}

        // 从字符串解析 "x1,y1,x2,y2"
        static Line fromString(const std::string& str, int imageWidth, int imageHeight);
    };

    // 越线方向
    enum class CrossDirection {
        None = 0,       // 未越线
        Forward = 1,    // 正向越线（p1->p2 左侧到右侧）
        Backward = 2,   // 反向越线（p1->p2 右侧到左侧）
        Unknown = 3     // 方向不明
    };

    // 越线事件
    struct LineCrossingEvent {
        int trackId = -1;               // 追踪ID
        std::string lineName;           // 越线的线段名称
        CrossDirection direction = CrossDirection::None; // 越线方向
        cv::Point crossPoint;           // 越线点（轨迹与线段的交点）
        int64_t timestamp = 0;          // 越线时间戳
        DetectObject object{};          // 越线目标
        bool isViolation = false;       // 是否为违规（如逆行）

        LineCrossingEvent() = default;
    };

    // 越线检测器
    class LineCrossingDetector {
    public:
        LineCrossingDetector() = default;

        // 设置检测线（支持多条线）
        void setLines(const std::vector<Line>& lines) {
            mLines = lines;
        }

        // 添加检测线
        void addLine(const Line& line) {
            mLines.push_back(line);
        }

        // 设置违规方向（如果设置，则只有该方向才算违规）
        // 例如：设置 Forward 为违规，则只有正向越线才触发违规事件
        void setViolationDirection(const std::string& lineName, CrossDirection dir) {
            mViolationDirections[lineName] = dir;
        }

        // 检测越线事件
        std::vector<LineCrossingEvent> detectCrossing(const std::vector<TrackedObject>& tracks,
                                                       int64_t timestamp);

        // 清空历史记录
        void clear() {
            mLastPositions.clear();
            mCrossingHistory.clear();
        }

    private:
        // 判断点是否在线段的左侧（使用叉积）
        bool isLeftOfLine(const cv::Point& point, const Line& line);

        // 判断线段是否相交
        bool linesIntersect(const cv::Point& p1, const cv::Point& p2,
                           const cv::Point& p3, const cv::Point& p4,
                           cv::Point& intersection);

        // 计算叉积
        int crossProduct(const cv::Point& o, const cv::Point& a, const cv::Point& b);

        std::vector<Line> mLines;
        std::map<int, cv::Point> mLastPositions;  // trackId -> 上一帧位置
        std::map<std::string, CrossDirection, std::less<>> mViolationDirections;  // lineName -> 违规方向
        std::map<std::string, std::set<int>, std::less<>> mCrossingHistory;  // lineName -> 已越线的trackId集合
    };

    // 越线检测节点
    class LineCrossingNode : public PipelineNode {
    public:
        LineCrossingNode(const std::string& name, const std::vector<Line>& lines,
                        TrackerNode* trackerNode)
            : mName(name), mTrackerNode(trackerNode) {
            mDetector.setLines(lines);
        }

        bool process(PipelineContext& context) override;

        PipelineNodeType getType() const override {
            return PipelineNodeType::LineCrossing;
        }

        std::string getName() const override {
            return mName;
        }

        // 设置违规方向
        void setViolationDirection(const std::string& lineName, CrossDirection dir) {
            mDetector.setViolationDirection(lineName, dir);
        }

        // 获取越线事件
        const std::vector<LineCrossingEvent>& getEvents() const {
            return mEvents;
        }

    private:
        std::string mName;
        TrackerNode* mTrackerNode;  // 需要追踪器提供轨迹信息
        LineCrossingDetector mDetector;
        std::vector<LineCrossingEvent> mEvents;  // 最近的越线事件
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_LINE_CROSSING_H
