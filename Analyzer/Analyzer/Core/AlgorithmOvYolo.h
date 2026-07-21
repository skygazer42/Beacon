#ifndef ANALYZER_ALGORITHMOVYOLO_H
#define ANALYZER_ALGORITHMOVYOLO_H

#include <string>
#include <vector>
#include <deque>
#include <mutex>
#include <queue>
#include <atomic>
#include <cstddef>
#include <memory>
#include <openvino/openvino.hpp> //openvino header file
#include "Algorithm.h"
#include "YoloDetectionPostprocess.h"
#include "YoloSegmentationPostprocess.h"

namespace AVSAnalyzer {
	class Config;

	class AlgorithmOvYolo : public Algorithm
	{
	public:
		AlgorithmOvYolo(const Config* config, const std::string& modelPath, const std::vector<std::string>& classNames, const std::string& device,
		                int concurrency = 1, int requestedInputWidth = 0, int requestedInputHeight = 0);
		~AlgorithmOvYolo() override;
		bool objectDetect(cv::Mat& image, std::vector<DetectObject>& detects,
			float scoreThreshold, float nmsThreshold) override;
	private:
		std::vector<std::string> mClassNames;
		std::string mDevice;
		std::atomic<size_t> mRR{ 0 };
		std::unique_ptr<ov::Core> core;
		ov::CompiledModel compiled_model;
		std::vector<ov::InferRequest>  mRequests;
		std::deque<std::mutex> mReqMtx;
		std::mutex mDetectFormatMtx;
		int mInputWidth = 640;
		int mInputHeight = 640;
		size_t mSelectedOutputIndex = 0;
		bool mIsClassifier = false;
		int mClassifierClassCount = 0;
		YoloDetectionFormat mDetectFormat{};
		bool mHasSegmentation = false;
		size_t mProtoOutputIndex = 0;
		YoloSegmentationPrototypeLayout mProtoLayout{};
	};
}
#endif //ANALYZER_ALGORITHMOVYOLO_H
