#ifndef ANALYZER_ANALYZER_H
#define ANALYZER_ANALYZER_H

#include <string>
#include <vector>
#include <memory>
#include <unordered_map>
#include <opencv2/opencv.hpp>
#include <iostream>
#include <filesystem>
#include <json/json.h>

#include "ApiInferGuard.h"
#include "BehaviorApiConfig.h"
#include "BehaviorEventPostprocess.h"
#include "TargetSizeFilter.h"
namespace AVSAnalyzer {
	struct Control;
	class Config;
	class Scheduler;
	class Algorithm;
	class ByteTracker;
	class ReidTracker;
	class SimpleTracker;
	class LineCrossingDetector;
	struct DetectObject;

	struct AnalyzerAlgorithmState {
		Algorithm* primary = nullptr;
		std::string primaryCode{};
		Algorithm* secondary = nullptr;
		std::string secondaryCode{};
		Algorithm* tracking = nullptr;
		Algorithm* classification = nullptr;
		Algorithm* behavior = nullptr;
		Algorithm* feature = nullptr;
	};

	struct AnalyzerTrackingState {
		std::unique_ptr<ByteTracker> byteTracker;
		int byteTrackFrameId = 0;
		std::unique_ptr<ReidTracker> reidTracker;
		int reidFrameId = 0;
		int reidEmbedEveryNFrames = 1;
		int reidMaxRoiPerFrame = 0;
		bool reidEmbedTargetOnly = false;
		bool debugDrawTrackId = false;
		float trackAssignIouThresh = 0.3f;
		std::unique_ptr<SimpleTracker> behaviorApiV2Tracker;
		std::unique_ptr<LineCrossingDetector> behaviorApiV2LineCrossing;
		bool behaviorApiV2LineInited = false;
		std::unordered_map<int, int> behaviorApiV2LoiteringFrames;
		BehaviorApiConfigCache behaviorApiConfigCache{};
	};

	struct AnalyzerApiState {
		std::vector<uchar> jpegBuffer;
		std::string imageBase64;
		std::string roiImageBase64;
		std::vector<int> jpegParams;
		Json::StreamWriterBuilder jsonWriter;
		ApiInferGuard inferGuard;
		int inferConnectTimeoutSeconds = 2;
		int inferTimeoutSeconds = 5;
		int inferRetryMax = 0;
	};

	struct AnalyzerPostprocessState {
		BehaviorEventPostprocessor behaviorEventPostprocess;
		PerRegionBehaviorEventPostprocessor perRegionBehaviorEventPostprocess;
		bool usePerRegionBehaviorEventPostprocess = false;
		int lastRegionIndex = -1;
		TargetSizeFilterConfig targetSizeFilterConfig{};
		BuiltinBehaviorType lastMode5BuiltinBehavior = BuiltinBehaviorType::Intrusion;
		int lastMode5ApiVersion = 1;
		Json::Value lastUserData = Json::Value(Json::objectValue);
	};

	class Analyzer
	{
	public:
		explicit Analyzer(Scheduler* scheduler, Control* control);
		~Analyzer();
		bool handleVideoFrame(int64_t frameCount, cv::Mat &image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		int getLastRegionIndex() const { return mPostprocessState.lastRegionIndex; } // 0-based, -1 when unknown/not applicable
		// Optional per-frame user_data for alarms/UI (JSON object string). Empty when not available.
		std::string getLastUserDataJson() const;
	private:
		bool postImage2Server(int64_t frameCount, const cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);

		// ========== 层级算法支持 ==========
		// 对检测结果进行二级处理
		bool processSecondaryAlgorithm(const cv::Mat& image, std::vector<DetectObject>& detects);
		// ====================================

		Scheduler* mScheduler;
		Control*   mControl;
		AnalyzerAlgorithmState mAlgorithms;
		AnalyzerTrackingState mTrackingState;

		// 流程模式执行方法
		bool executePipelineMode1(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode2(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode3(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode4(int64_t /*frameCount*/, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode5(int64_t frameCount, const cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode6(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode7(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode8(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		bool executePipelineMode9(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore);
		// ======================================

		AnalyzerApiState mApiState;
		AnalyzerPostprocessState mPostprocessState;

	};
}
#endif //ANALYZER_ANALYZER_H
