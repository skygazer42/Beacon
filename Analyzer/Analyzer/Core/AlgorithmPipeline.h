#ifndef ANALYZER_ALGORITHM_PIPELINE_H
#define ANALYZER_ALGORITHM_PIPELINE_H

#include <string>
#include <vector>
#include <memory>
#include <map>
#include <functional>
#include "Algorithm.h"
#include "Utils/Log.h"

namespace AVSAnalyzer {

    // 算法管道节点类型
    enum class PipelineNodeType {
        Detector,       // 检测器：输入图像，输出检测框
        Tracker,        // 追踪器：输入检测框，输出带追踪ID的目标
        Classifier,     // 分类器：输入ROI，输出分类标签
        Recognizer,     // 识别器：输入ROI，输出特征/ID
        Behavior,       // 行为分析：输入追踪序列，输出行为标签
        Attribute,      // 属性分析：输入ROI，输出属性值
        LineCrossing    // 越线检测：输入追踪轨迹，输出越线事件
    };

    // 算法管道上下文：在管道节点间传递数据
    struct PipelineContext {
        cv::Mat image;                              // 当前帧图像
        std::vector<DetectObject> detections;       // 检测结果
        std::map<std::string, float, std::less<>> globalAttrs;   // 全局属性
        int64_t frameId = 0;                        // 帧ID
        int64_t timestamp = 0;                      // 时间戳（ms）

        // 清空检测结果
        void clearDetections() {
            detections.clear();
        }
    };

    // 算法管道节点基类
    class PipelineNode {
    public:
        virtual ~PipelineNode() = default;

        // 处理上下文（核心方法）
        virtual bool process(PipelineContext& context) = 0;

        // 获取节点类型
        virtual PipelineNodeType getType() const = 0;

        // 获取节点名称
        virtual std::string getName() const = 0;

        // 是否准备就绪
        virtual bool isReady() const { return true; }
    };

    // 检测节点：包装检测算法
    class DetectorNode : public PipelineNode {
    public:
        DetectorNode(Algorithm* algorithm, const std::string& name,
                     float confThresh, float nmsThresh)
            : mAlgorithm(algorithm), mName(name),
              mConfThresh(confThresh), mNmsThresh(nmsThresh) {}

        bool process(PipelineContext& context) override {
            if (!mAlgorithm) return false;
            context.clearDetections();
            return mAlgorithm->objectDetect(context.image, context.detections,
                                           mConfThresh, mNmsThresh);
        }

        PipelineNodeType getType() const override {
            return PipelineNodeType::Detector;
        }

        std::string getName() const override {
            return mName;
        }

        bool isReady() const override {
            return mAlgorithm != nullptr && mAlgorithm->createState();
        }

    private:
        Algorithm* mAlgorithm;
        std::string mName;
        float mConfThresh;
        float mNmsThresh;
    };

    // 分类节点：对每个检测区域进行分类
    class ClassifierNode : public PipelineNode {
    public:
        ClassifierNode(Algorithm* algorithm, const std::string& name,
                      float confThresh)
            : mAlgorithm(algorithm), mName(name), mConfThresh(confThresh) {}

        bool process(PipelineContext& context) override;

        PipelineNodeType getType() const override {
            return PipelineNodeType::Classifier;
        }

        std::string getName() const override {
            return mName;
        }

        bool isReady() const override {
            return mAlgorithm != nullptr && mAlgorithm->createState();
        }

    private:
        Algorithm* mAlgorithm;
        std::string mName;
        float mConfThresh;
    };

    // 算法管道：串联多个算法节点
    class AlgorithmPipeline {
    public:
        AlgorithmPipeline() = default;
        ~AlgorithmPipeline() = default;

        // 添加节点
        void addNode(std::unique_ptr<PipelineNode> node) {
            mNodes.push_back(std::move(node));
        }

        // 执行管道
        bool execute(PipelineContext& context) const {
            for (const auto& node : mNodes) {
                if (!node->isReady()) {
                    LOGE("Pipeline node not ready: %s", node->getName().c_str());
                    return false;
                }
                if (!node->process(context)) {
                    LOGE("Pipeline node failed: %s", node->getName().c_str());
                    return false;
                }
            }
            return true;
        }

        // 获取节点数量
        size_t getNodeCount() const {
            return mNodes.size();
        }

        // 清空管道
        void clear() {
            mNodes.clear();
        }

    private:
        std::vector<std::unique_ptr<PipelineNode>> mNodes;
    };

    // 算法管道构建器：简化管道创建
    class PipelineBuilder {
    public:
        PipelineBuilder() = default;

        // 添加检测节点
        PipelineBuilder& addDetector(Algorithm* algo, const std::string& name,
                                     float confThresh, float nmsThresh) {
            mPipeline->addNode(std::make_unique<DetectorNode>(algo, name, confThresh, nmsThresh));
            return *this;
        }

        // 添加分类节点
        PipelineBuilder& addClassifier(Algorithm* algo, const std::string& name,
                                       float confThresh) {
            mPipeline->addNode(std::make_unique<ClassifierNode>(algo, name, confThresh));
            return *this;
        }

        // 构建管道
        std::unique_ptr<AlgorithmPipeline> build() {
            return std::move(mPipeline);
        }

    private:
        std::unique_ptr<AlgorithmPipeline> mPipeline = std::make_unique<AlgorithmPipeline>();
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHM_PIPELINE_H
