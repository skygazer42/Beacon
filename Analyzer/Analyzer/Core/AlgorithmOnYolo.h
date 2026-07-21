#ifndef ANALYZER_ALGORITHMONYOLO_H
#define ANALYZER_ALGORITHMONYOLO_H

#include <string>
#include <vector>
#include <deque>
#include <mutex>
#include <queue>
#include <array>
#include <atomic>
#include <memory>
#include "Algorithm.h"
#include "YoloSegmentationPostprocess.h"
#include <onnxruntime_cxx_api.h>

namespace AVSAnalyzer {
	class Config;

	struct OnnxRuntimeEngineModelState {
		std::vector<std::string> mClassNames;
		std::string mModelPath;
		int mRequestedInputWidth = 0;
		int mRequestedInputHeight = 0;
		std::string mRequestedDevice = "CPU";
		int mRequestedDeviceId = 0;
	};

	struct OnnxRuntimeEngineSessionState {
		Ort::Env mEnv{ nullptr };
		Ort::SessionOptions mSessionOptions{ nullptr };
		Ort::Session mSession{ nullptr };
		bool mReady = false;
		std::vector<std::string> mInputNames;
		std::vector<std::string> mOutputNames;
		int mInputWidth = 0;
		int mInputHeight = 0;
		size_t mInputTensorSize = 0;
		std::array<int64_t, 4> mInputShapeInfo{ 0, 0, 0, 0 };
	};

	struct OnnxRuntimeEngineOutputState {
		int mOutputDim = 0;
		int mOutputRow = 0;
		bool mOutputRowsFirst = false;     // true: output is [rows, dim], false: output is [dim, rows]
		size_t mSelectedOutputIndex = 0;   // multi-output models: which output tensor is used as detection output
		bool mHasObjectness = false;       // true for YOLOv5-like outputs (x,y,w,h,obj,classes...)
		int mClassOffset = 4;              // 4 for YOLOv8, 5 for YOLOv5 (skip obj)
		bool mHasAngle = false;            // true for OBB outputs (x,y,w,h,angle,...)
	};

	struct OnnxRuntimeEngineSegmentationState {
		bool mHasSegmentation = false;     // true for YOLO seg outputs with prototype tensor
		bool mIndex4ObjOrAngleAmbiguous = false;
		bool mIndex4ObjOrAngleDecided = false;
		bool mIndex4UseObjectness = true;  // when ambiguous and decided: true=obj, false=angle
		size_t mProtoOutputIndex = 0;
		YoloSegmentationPrototypeLayout mProtoLayout{};
	};

	struct OnnxRuntimeEngineProviderState {
		std::string mSelectedProvider = "CPU";
		std::string mTensorRTInitError{};
		std::string mCudaInitError{};
	};

		class OnnxRuntimeEngine
			: private OnnxRuntimeEngineModelState,
			  private OnnxRuntimeEngineSessionState,
			  private OnnxRuntimeEngineOutputState,
			  private OnnxRuntimeEngineSegmentationState,
			  private OnnxRuntimeEngineProviderState
		{
		public:
			explicit OnnxRuntimeEngine(const Config* config, const std::string& modelPath, const std::vector<std::string>& classNames, const std::string& device,
			                           int requestedInputWidth = 0, int requestedInputHeight = 0);
			~OnnxRuntimeEngine();
			bool runInference(const cv::Mat& image, std::vector<DetectObject>& detects,
				float scoreThreshold, float nmsThreshold);
		bool isReady() const;
		std::string getSelectedProvider() const { return mSelectedProvider; } // CPU/CUDA/TENSORRT
		std::string getRequestedDevice() const { return mRequestedDevice; }   // normalized type (CPU/CUDA/TENSORRT/AUTO/...)
		int getRequestedDeviceId() const { return mRequestedDeviceId; }
		std::string getTensorRTInitError() const { return mTensorRTInitError; }
		std::string getCudaInitError() const { return mCudaInitError; }
		std::string getPreprocessReport() const;

	private:
		bool initModelIO();
	};
	class AlgorithmOnYolo : public Algorithm
	{
	public:
		AlgorithmOnYolo(const Config* config, const std::string& modelPath, const std::vector<std::string>& classNames, const std::string& device,
		                int concurrency = 1, int requestedInputWidth = 0, int requestedInputHeight = 0);
		~AlgorithmOnYolo() override;
		bool objectDetect(cv::Mat& image, std::vector<DetectObject>& detects,
						  float scoreThreshold, float nmsThreshold) override;
		std::string getSelectedProvider() const;
		std::string getProviderInitReport() const;
	private:
		std::vector<std::string> mClassNames;
		std::string mDevice;
		std::vector<std::unique_ptr<OnnxRuntimeEngine>> mEngines;
		std::deque<std::mutex> mEngineMtx;
		std::atomic<size_t> mRR{ 0 };
	};
}
#endif //ANALYZER_ALGORITHMONYOLO_H
