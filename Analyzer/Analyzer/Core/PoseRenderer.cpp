#include "PoseRenderer.h"
#include "Utils/Log.h"

namespace AVSAnalyzer {

    PoseRenderer::PoseRenderer() {
        // 定义 COCO 格式的骨架连接（17个关键点）
        // 颜色方案：头部（红色），躯干（绿色），左臂（蓝色），右臂（黄色），左腿（青色），右腿（洋红色）

        // 头部连接（红色系）
        mSkeletonConnections.push_back(SkeletonConnection(0, 1, cv::Scalar(0, 0, 255)));    // nose-left_eye
        mSkeletonConnections.push_back(SkeletonConnection(0, 2, cv::Scalar(0, 0, 255)));    // nose-right_eye
        mSkeletonConnections.push_back(SkeletonConnection(1, 3, cv::Scalar(0, 0, 255)));    // left_eye-left_ear
        mSkeletonConnections.push_back(SkeletonConnection(2, 4, cv::Scalar(0, 0, 255)));    // right_eye-right_ear

        // 躯干连接（绿色系）
        mSkeletonConnections.push_back(SkeletonConnection(5, 6, cv::Scalar(0, 255, 0)));    // left_shoulder-right_shoulder
        mSkeletonConnections.push_back(SkeletonConnection(5, 11, cv::Scalar(0, 255, 0)));   // left_shoulder-left_hip
        mSkeletonConnections.push_back(SkeletonConnection(6, 12, cv::Scalar(0, 255, 0)));   // right_shoulder-right_hip
        mSkeletonConnections.push_back(SkeletonConnection(11, 12, cv::Scalar(0, 255, 0)));  // left_hip-right_hip

        // 左臂连接（蓝色系）
        mSkeletonConnections.push_back(SkeletonConnection(5, 7, cv::Scalar(255, 0, 0)));    // left_shoulder-left_elbow
        mSkeletonConnections.push_back(SkeletonConnection(7, 9, cv::Scalar(255, 0, 0)));    // left_elbow-left_wrist

        // 右臂连接（黄色系）
        mSkeletonConnections.push_back(SkeletonConnection(6, 8, cv::Scalar(0, 255, 255)));  // right_shoulder-right_elbow
        mSkeletonConnections.push_back(SkeletonConnection(8, 10, cv::Scalar(0, 255, 255))); // right_elbow-right_wrist

        // 左腿连接（青色系）
        mSkeletonConnections.push_back(SkeletonConnection(11, 13, cv::Scalar(255, 255, 0))); // left_hip-left_knee
        mSkeletonConnections.push_back(SkeletonConnection(13, 15, cv::Scalar(255, 255, 0))); // left_knee-left_ankle

        // 右腿连接（洋红色系）
        mSkeletonConnections.push_back(SkeletonConnection(12, 14, cv::Scalar(255, 0, 255))); // right_hip-right_knee
        mSkeletonConnections.push_back(SkeletonConnection(14, 16, cv::Scalar(255, 0, 255))); // right_knee-right_ankle
    }

    void PoseRenderer::drawKeypoint(cv::Mat& image, const DetectObject::Keypoint& kp,
                                    const cv::Scalar& color, int radius) {
        if (kp.confidence <= 0.0f) {
            return;  // 跳过低置信度关键点
        }

        cv::Point center(static_cast<int>(kp.x), static_cast<int>(kp.y));

        // 检查点是否在图像范围内
        if (center.x < 0 || center.x >= image.cols || center.y < 0 || center.y >= image.rows) {
            return;
        }

        // 绘制关键点圆圈
        cv::circle(image, center, radius, color, -1);  // 填充圆

        // 如果置信度较低，绘制半透明效果（可选）
        if (kp.confidence < 0.5f) {
            cv::circle(image, center, radius + 1, cv::Scalar(255, 255, 255), 1);  // 外圈标记低置信度
        }
    }

    void PoseRenderer::drawSkeleton(cv::Mat& image,
                                    const std::vector<DetectObject::Keypoint>& keypoints,
                                    float threshold) {
        if (keypoints.size() < 17) {
            LOGW("Invalid keypoint count: %zu (expected 17 for COCO format)", keypoints.size());
            return;
        }

        // 绘制骨架连接
        for (const auto& connection : mSkeletonConnections) {
            if (connection.point1 < 0 || connection.point2 < 0 ||
                static_cast<size_t>(connection.point1) >= keypoints.size() ||
                static_cast<size_t>(connection.point2) >= keypoints.size()) {
                continue;
            }

            const auto& kp1 = keypoints[connection.point1];
            const auto& kp2 = keypoints[connection.point2];

            // 只有两个关键点的置信度都足够高时才绘制连接
            if (kp1.confidence < threshold || kp2.confidence < threshold) {
                continue;
            }

            cv::Point pt1(static_cast<int>(kp1.x), static_cast<int>(kp1.y));
            cv::Point pt2(static_cast<int>(kp2.x), static_cast<int>(kp2.y));

            // 检查点是否在图像范围内
            if (pt1.x < 0 || pt1.x >= image.cols || pt1.y < 0 || pt1.y >= image.rows ||
                pt2.x < 0 || pt2.x >= image.cols || pt2.y < 0 || pt2.y >= image.rows) {
                continue;
            }

            // 绘制骨架线条
            cv::line(image, pt1, pt2, connection.color, 2, cv::LINE_AA);
        }
    }

    void PoseRenderer::renderPose(cv::Mat& image, const DetectObject& detect,
                                  float keypointThreshold, int radius, int thickness) {
        if (!detect.hasPose || detect.keypoints.empty()) {
            return;
        }

        // 1. 绘制边界框
        if (mDrawBoundingBox) {
            cv::Scalar boxColor(0, 255, 0);  // 绿色边界框
            cv::rectangle(image, cv::Point(detect.x1, detect.y1),
                         cv::Point(detect.x2, detect.y2), boxColor, thickness);

            // 绘制类别和置信度标签
            if (!detect.class_name.empty()) {
                std::string label = detect.class_name + " " +
                                   std::to_string(static_cast<int>(detect.class_score * 100)) + "%";
                int baseline = 0;
                cv::Size labelSize = cv::getTextSize(label, cv::FONT_HERSHEY_SIMPLEX, 0.5, 1, &baseline);
                cv::rectangle(image, cv::Point(detect.x1, detect.y1 - labelSize.height - 5),
                             cv::Point(detect.x1 + labelSize.width, detect.y1), boxColor, -1);
                cv::putText(image, label, cv::Point(detect.x1, detect.y1 - 3),
                           cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(0, 0, 0), 1);
            }
        }

        // 2. 绘制骨架连接
        if (mDrawSkeleton) {
            drawSkeleton(image, detect.keypoints, keypointThreshold);
        }

        // 3. 绘制关键点
        if (mDrawKeypoints) {
            // 为不同身体部位使用不同颜色
            std::vector<cv::Scalar> keypointColors = {
                cv::Scalar(255, 0, 0),    // 0: nose (红)
                cv::Scalar(255, 0, 0),    // 1: left_eye (红)
                cv::Scalar(255, 0, 0),    // 2: right_eye (红)
                cv::Scalar(255, 0, 0),    // 3: left_ear (红)
                cv::Scalar(255, 0, 0),    // 4: right_ear (红)
                cv::Scalar(0, 255, 0),    // 5: left_shoulder (绿)
                cv::Scalar(0, 255, 0),    // 6: right_shoulder (绿)
                cv::Scalar(0, 0, 255),    // 7: left_elbow (蓝)
                cv::Scalar(0, 255, 255),  // 8: right_elbow (黄)
                cv::Scalar(0, 0, 255),    // 9: left_wrist (蓝)
                cv::Scalar(0, 255, 255),  // 10: right_wrist (黄)
                cv::Scalar(255, 255, 0),  // 11: left_hip (青)
                cv::Scalar(255, 0, 255),  // 12: right_hip (洋红)
                cv::Scalar(255, 255, 0),  // 13: left_knee (青)
                cv::Scalar(255, 0, 255),  // 14: right_knee (洋红)
                cv::Scalar(255, 255, 0),  // 15: left_ankle (青)
                cv::Scalar(255, 0, 255)   // 16: right_ankle (洋红)
            };

            for (size_t i = 0; i < detect.keypoints.size() && i < keypointColors.size(); ++i) {
                if (detect.keypoints[i].confidence >= keypointThreshold) {
                    drawKeypoint(image, detect.keypoints[i], keypointColors[i], radius);
                }
            }
        }
    }

    void PoseRenderer::renderPoses(cv::Mat& image, const std::vector<DetectObject>& detects,
                                   float keypointThreshold, int radius, int thickness) {
        for (const auto& detect : detects) {
            renderPose(image, detect, keypointThreshold, radius, thickness);
        }
    }

} // namespace AVSAnalyzer
