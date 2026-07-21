#ifndef ANALYZER_POSE_RENDERER_H
#define ANALYZER_POSE_RENDERER_H

#include <opencv2/opencv.hpp>
#include <vector>
#include "Algorithm.h"

namespace AVSAnalyzer {

    // COCO 人体关键点索引（17个关键点）
    enum class CocoKeypoint {
        Nose = 0,
        LeftEye = 1,
        RightEye = 2,
        LeftEar = 3,
        RightEar = 4,
        LeftShoulder = 5,
        RightShoulder = 6,
        LeftElbow = 7,
        RightElbow = 8,
        LeftWrist = 9,
        RightWrist = 10,
        LeftHip = 11,
        RightHip = 12,
        LeftKnee = 13,
        RightKnee = 14,
        LeftAnkle = 15,
        RightAnkle = 16
    };

    // 骨架连接定义（COCO格式）
    struct SkeletonConnection {
        int point1;
        int point2;
        cv::Scalar color;

        SkeletonConnection(int p1, int p2, const cv::Scalar& c)
            : point1(p1), point2(p2), color(c) {}
    };

    class PoseRenderer {
    public:
        PoseRenderer();

        // 渲染单个检测对象的姿态
        void renderPose(cv::Mat& image, const DetectObject& detect,
                       float keypointThreshold = 0.3f,
                       int radius = 3,
                       int thickness = 2);

        // 渲染多个检测对象的姿态
        void renderPoses(cv::Mat& image, const std::vector<DetectObject>& detects,
                        float keypointThreshold = 0.3f,
                        int radius = 3,
                        int thickness = 2);

        // 设置是否绘制骨架连接
        void setDrawSkeleton(bool enable) { mDrawSkeleton = enable; }

        // 设置是否绘制关键点
        void setDrawKeypoints(bool enable) { mDrawKeypoints = enable; }

        // 设置是否绘制边界框
        void setDrawBoundingBox(bool enable) { mDrawBoundingBox = enable; }

    private:
        void drawKeypoint(cv::Mat& image, const DetectObject::Keypoint& kp,
                         const cv::Scalar& color, int radius);

        void drawSkeleton(cv::Mat& image, const std::vector<DetectObject::Keypoint>& keypoints,
                         float threshold);

        bool mDrawSkeleton = true;
        bool mDrawKeypoints = true;
        bool mDrawBoundingBox = true;

        // COCO 骨架连接定义
        std::vector<SkeletonConnection> mSkeletonConnections;
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_POSE_RENDERER_H
