#ifndef ANALYZER_ALGORITHM_ON_REID_H
#define ANALYZER_ALGORITHM_ON_REID_H

#include "Algorithm.h"
#include <atomic>
#include <deque>
#include <memory>
#include <mutex>
#include <onnxruntime_cxx_api.h>

namespace AVSAnalyzer {
    class Config;

	    class OnnxRuntimeReidEngine {
	    public:
	        explicit OnnxRuntimeReidEngine(
	            const Config* config,
	            const std::string& modelPath,
	            const std::string& device,
	            int requestedInputWidth = 0,
	            int requestedInputHeight = 0
        );
        ~OnnxRuntimeReidEngine();

        bool isReady() const { return mReady; }
        int embeddingDim() const { return mEmbeddingDim; }

        bool extractEmbeddings(
            const std::vector<cv::Mat>& images,
            std::vector<std::vector<float>>& embeddings,
            std::string& errMsg
        );

    private:
        bool initModelIO(std::string& errMsg);

        std::string mModelPath;
        std::string mDevice;

        Ort::Env mEnv{ nullptr };
        Ort::SessionOptions mSessionOptions{ nullptr };
        Ort::Session mSession{ nullptr };
        bool mReady = false;

        std::vector<std::string> mInputNames;
        std::vector<std::string> mOutputNames;

        int mRequestedInputWidth = 0;
        int mRequestedInputHeight = 0;
        int64_t mInputBatchDim = -1; // model-declared batch dim (1, -1=dynamic, ...)
        int mInputWidth = 0;
        int mInputHeight = 0;
        int mEmbeddingDim = 0;
    };

    class AlgorithmOnReid : public Algorithm {
	    public:
	        AlgorithmOnReid(
	            const Config* config,
	            const std::string& modelPath,
	            const std::string& device,
	            int concurrency = 1,
	            int requestedInputWidth = 0,
            int requestedInputHeight = 0
        );
        ~AlgorithmOnReid() override;

        bool objectDetect(cv::Mat& image, std::vector<DetectObject>& detects, float scoreThreshold, float nmsThreshold) override;

        bool extractEmbeddings(
            const std::vector<cv::Mat>& images,
            std::vector<std::vector<float>>& embeddings,
            std::string& errMsg
        ) override;

        int embeddingDim() const override;

        AlgorithmType getType() const override { return AlgorithmType::Recognizer; }

    private:
        std::string mDevice;
        std::vector<std::unique_ptr<OnnxRuntimeReidEngine>> mEngines;
        std::deque<std::mutex> mEngineMtx;
        std::atomic<size_t> mRR{ 0 };
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHM_ON_REID_H
