#include "AlgorithmPipeline.h"
#include "Utils/Log.h"
#include <algorithm>

namespace AVSAnalyzer {

    bool ClassifierNode::process(PipelineContext& context) {
        if (!mAlgorithm || context.detections.empty()) {
            return true;  // 空检测结果不是错误
        }

        LOGI("ClassifierNode processing %zu detections", context.detections.size());

        for (auto& detect : context.detections) {
            // 提取检测区域
            int x1 = std::max(0, detect.x1);
            int y1 = std::max(0, detect.y1);
            int x2 = std::min(context.image.cols, detect.x2);
            int y2 = std::min(context.image.rows, detect.y2);

            if (x2 <= x1 || y2 <= y1) {
                LOGE("Invalid bbox: (%d,%d,%d,%d)", x1, y1, x2, y2);
                continue;
            }

            // 裁剪 ROI
            cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
            cv::Mat roiImage = context.image(roi);

            // 对 ROI 进行分类
            std::vector<DetectObject> classResults;
            if (mAlgorithm->objectDetect(roiImage, classResults, mConfThresh, 0.5f)) {
                // 将分类结果存储为子对象
                for (auto& result : classResults) {
                    // 转换坐标到原图坐标系
                    result.x1 += x1;
                    result.y1 += y1;
                    result.x2 += x1;
                    result.y2 += y1;
                }
                detect.subObjects = classResults;
                detect.subAlgorithmCode = mName;

                // 如果有分类结果，取最高置信度的作为主分类
                if (!classResults.empty()) {
                    auto maxIt = std::max_element(classResults.begin(), classResults.end(),
                        [](const DetectObject& a, const DetectObject& b) {
                            return a.class_score < b.class_score;
                        });
                    detect.attributes["secondary_class"] = static_cast<float>(maxIt->class_id);
                    detect.attributes["secondary_score"] = maxIt->class_score;
                }
            }
        }

        return true;
    }

} // namespace AVSAnalyzer
