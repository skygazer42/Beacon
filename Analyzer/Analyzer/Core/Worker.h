#ifndef ANALYZER_WORKER_H
#define ANALYZER_WORKER_H
#include <thread>
#include <queue>
#include <mutex>
#include <memory>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <vector>
#include <string>
#include <cstdint>

#include "LicenseThreadPriority.h"

namespace AVSAnalyzer {
	class Scheduler;
	class AvPushStream;
	class Analyzer;
	class SharedDecodeSession;
	class DecodedFrameQueue;
	struct Control;
	struct Frame;
	class FramePool;

	struct WorkerOwnedResources {
		std::unique_ptr<Control> mControl;
		Scheduler* mScheduler = nullptr;
		std::unique_ptr<AvPushStream> mPushStream;
		std::unique_ptr<Analyzer> mAnalyzer;
		std::shared_ptr<FramePool> mVideoFramePool;
	};

	struct WorkerExecutionState {
		std::atomic<bool> mState{ false };
		std::atomic<int> mSourceInputQueueSize{ 0 };
		std::vector<std::thread> mThreads;
	};

	struct WorkerAlarmConfigState {
		int mAlarmPrefixFrames = 30;
		int mAlarmTotalFrames = 60; // legacy: used as fallback for image interval when fps is unknown
		size_t mAlarmVideoQueueMaxFrames = 90;
		bool mAlarmNeedFrames = true;
		int64_t mLastAlarmTimestamp = 0; // monotonic ms (cooldown)
		int64_t mAlarmMergeWindowMs = 10 * 1000;
		int64_t mAlarmSegmentMaxMs = 60 * 1000;
		int64_t mAlarmMinSegmentMs = 0; // derived from config (prefer alarmVideoSeconds)
	};

	struct WorkerSharedDecodeState {
		std::string mSharedDecodeKey{};
		SharedDecodeSession* mSharedDecodeSession = nullptr;
		bool mSharedDecodeSubscribed = false;
		std::unique_ptr<DecodedFrameQueue> mDecodedFrameQ;
		bool mHasEncodeChannel = false;  // 是否占用了硬件编码通道
	};

	struct WorkerLicensePriorityState {
		std::atomic<int> mLicenseThreadPriorityEnabled{ 0 };
		std::atomic<int> mLicenseThreadPriorityStreamRank{ 0 };
		std::atomic<int> mLicenseThreadPriorityFirstNActiveStreams{ 0 };
		std::atomic<int> mLicenseThreadPriorityNiceValue{ 0 };
		std::atomic<uint64_t> mLicenseThreadPriorityGeneration{ 1 };
	};

	struct WorkerAlarmQueueState {
		std::deque<Frame*> mAlarmVideoFrameQ;
		std::mutex mAlarmVideoFrameQ_mtx;
		std::condition_variable mAlarmVideoFrameQ_cv;
	};

	struct WorkerAlarmSessionTimingState {
		bool recordVideo = false;
		int totalFramesMin = 0; // used for image interval only
		int imageCount = 0;
		int imageSaved = 0;
		int imageInterval = 0;
		int regionIndex = -1;         // 0-based recognition region index (best-effort)
		int64_t happenTimestampMs = 0; // epoch ms (best-effort)
		int width = 0;
		int height = 0;
		int fps = 0;
		int64_t segmentStartMs = 0; // monotonic ms
		int64_t segmentEndMs = 0;   // monotonic ms
		int64_t lastTriggerMs = 0;  // monotonic ms
		int64_t basePtsMs = 0;      // first frame timestamp in this segment (for PTS)
		int64_t lastPtsMs = -1;     // ensure monotonic PTS (ms)
		uint64_t enqueueSeq = 0;    // used for adaptive sampling
	};

	struct WorkerAlarmSessionPathState {
		std::string videoType;
		std::string relativeDir;
		std::string baseDirAbs;
		std::string videoPathRel;
		std::string videoPathAbs;
		std::string imagePathRel;
		std::string imagePathAbs;
		std::string cleanImagePathRel;
		std::string cleanImagePathAbs;
	};

	struct WorkerAlarmSessionRenderState {
		std::string coverPosition{ "front" };
		std::string alarmImageDrawMode{ "boxed" };
		int mainImageDrawType = 1;
		std::string triggerUserDataJson;
		std::string triggerDetectsJson;
		int coverCustomIndex = 0;
		bool coverWritten = false;
		bool stop = false;
		size_t maxQueueSize = 10;
	};

	struct WorkerAlarmSessionQueueState {
		std::deque<Frame*> frameQueue;
		std::mutex queueMtx;
		std::condition_variable queueCv;
		std::unique_ptr<std::thread> encodeThread;
	};

	class Worker
		: public WorkerOwnedResources,
		  private WorkerExecutionState,
		  private WorkerAlarmConfigState,
		  private WorkerSharedDecodeState,
		  private WorkerLicensePriorityState,
		  private WorkerAlarmQueueState
	{
	public:
		explicit Worker(Scheduler* scheduler, Control* control);
		~Worker();
		static void decodeVideoThread(Worker* arg);// （线程）解码视频帧和实时分析视频帧
		void handleDecodeVideo();
		static void generateAlarmThread(Worker* arg);//（线程）实时准备报警视频帧
		void handleGenerateAlarm();
		bool start(std::string& msg);
		bool enqueueDecodedFrame(
			const unsigned char* buf,
			int size,
			int width,
			int height,
			int fps,
			int sourceQueueSize,
			int64_t timestampMs);

		bool getState();
		void requestStop(); // stop threads without touching Scheduler bookkeeping
		void remove();
		void updateLicenseThreadPriorityHint(bool enabled, int streamRank, int firstNActiveStreams, int niceValue);
		void maybeRefreshCurrentThreadPriority(uint64_t& lastSeenGeneration, const char* threadName);
		int getAlarmVideoFrameQSize();            // 报警帧队列大小（监控/限流）
		size_t getAlarmVideoQueueMaxFrames();     // 报警帧队列上限（用于解释队列压力）
		int getSourceInputQueueSize() const;
	private:
		struct AlarmSession
			: public WorkerAlarmSessionTimingState,
			  public WorkerAlarmSessionPathState,
			  public WorkerAlarmSessionRenderState,
			  public WorkerAlarmSessionQueueState
		{
		};
		std::unique_ptr<AlarmSession> mAlarmSession;

		void addAlarmVideoFrameQ(Frame* frame);
		bool getAlarmVideoFrame(Frame*& frame);
		void clearAlarmVideoFrameQ();
		bool ensureLocalAlgorithmLoaded(const std::string& code, const char* label, std::string& msg) const;
		bool notifyFrameAlarm(Frame* triggerFrame);
		bool startAlarmSession(Frame* triggerFrame);
		void enqueueAlarmFrame(AlarmSession* session, Frame* frame);
		void stopAlarmSession(AlarmSession* session);
		void handleAlarmEncode(AlarmSession* session);
		void releaseFrame(Frame* frame);
		void releaseDecodedFrame(Frame* frame);
		bool ensureDecodedFrameGeometry(const Frame* frame);
		LicenseThreadPriorityHint getLicenseThreadPriorityHint() const;

	};
}
#endif //ANALYZER_WORKER_H
