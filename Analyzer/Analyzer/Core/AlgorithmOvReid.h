#ifndef ANALYZER_ALGORITHM_OV_REID_H
#define ANALYZER_ALGORITHM_OV_REID_H

#include "Algorithm.h"

#include <atomic>
#include <deque>
#include <memory>
#include <mutex>
#include <openvino/openvino.hpp>

namespace AVSAnalyzer {
    class Config;

	    class AlgorithmOvReid : public Algorithm {
	    public:
	        AlgorithmOvReid(
	            const Config* config,
	            const std::string& modelPath,
	            const std::string& device,
	            int concurrency = 1,
	            int requestedInputWidth = 0,
            int requestedInputHeight = 0
        );
        ~AlgorithmOvReid() override;

        bool objectDetect(cv::Mat& image, std::vector<DetectObject>& detects, float scoreThreshold, float nmsThreshold) override;

        bool extractEmbeddings(
            const std::vector<cv::Mat>& images,
            std::vector<std::vector<float>>& embeddings,
            std::string& errMsg
        ) override;

        int embeddingDim() const override { return mEmbeddingDim; }
        AlgorithmType getType() const override { return AlgorithmType::Recognizer; }

    private:
        std::string mDevice;
        int mInputWidth = 0;
        int mInputHeight = 0;
        int mEmbeddingDim = 0;
        int64_t mInputBatchDim = -1; // 1=static batch, -1=unknown/dynamic

        std::unique_ptr<ov::Core> core;
        ov::CompiledModel compiled_model;
        std::vector<ov::InferRequest> mRequests;
        std::deque<std::mutex> mReqMtx;
        std::atomic<size_t> mRR{ 0 };
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHM_OV_REID_H
