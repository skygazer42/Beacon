#ifndef ANALYZER_SCHEDULER_H
#define ANALYZER_SCHEDULER_H
#include <map>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <deque>
#include <vector>
#include <thread>
#include <atomic>
#include <set>
#include <memory>
#include <cstdint>
#include <string>
#include <string_view>

#include "DetectStrideHysteresis.h"
#include "AlgorithmLoadValidation.h"
#include "LocalLicense.h"

namespace AVSAnalyzer {
	class Config;
	class Worker;
	class Algorithm;
	class FaceDb;
	struct LicenseThreadPriorityHint;
	class SharedDecodeSession;
	struct Control;
	struct AlarmImage;
	struct Alarm;

	// 算法模型信息结构 - 支持模型复用和自动删除
	struct AlgorithmInfo {
		std::unique_ptr<Algorithm> algorithm;  // Owned algorithm instance (managed, no manual delete needed).
		std::string modelPath;
		std::string decryptedDir;              // 若模型解密缓存目录（需卸载时清理）
		std::vector<std::string> classNames;
		std::atomic<int> refCount{ 0 };        // 引用计数（正在使用的布控数量）
		std::set<std::string, std::less<>> controlCodes;    // 使用该模型的布控编号集合
		bool isBuiltin = false;                // 是否为内置模型（内置模型不会被自动删除）
		bool isLoaded = false;
		std::string requestedDevice = "CPU";  // 调用方请求的推理设备
		std::string effectiveDevice = "CPU";  // 实际加载成功的推理设备
		bool deviceDegraded = false;           // 是否发生设备降级
		std::string deviceDegradeReason;       // 设备降级原因
		int64_t lastUnusedTimestampMs = 0;     // refCount=0 时记录进入空闲的时间戳（ms）；用于按 TTL 延迟卸载
	};

	struct ResourceUsageInfo {
		double cpuUsage = 0.0;          // CPU 使用率 (0-100)
		double memoryUsage = 0.0;       // 内存使用率 (0-100)
		int maxControls = 10;           // 当前生效的最大允许布控数量（会随资源自动调节）
		int maxControlsUpperBound = 20; // 布控数量上限（自动调节不会超过该值；手动设置会更新该值）
		int maxPendingControls = 2;     // 并发启动布控上限（防止批量启动时资源尖峰）
		int currentControls = 0;        // 当前布控数量
		int detectStride = 1;           // 检测步长（每 N 帧检测一次）
		int64_t lastCheckTime = 0;      // 上次检查时间
		int maxHardwareDecodeChannels = 0; // 最大硬件解码路数（0=不限制）
		int maxHardwareEncodeChannels = 0; // 最大硬件编码路数（0=不限制）
		int currentDecodeChannels = 0;     // 当前硬件解码路数
		int currentEncodeChannels = 0;     // 当前硬件编码路数
	};

	struct ResourceQueuePressureInfo {
		int maxPullPktQueueSize = 0;       // 所有布控中拉流包队列最大值
		int maxPushFrameQueueSize = 0;     // 所有布控中推流帧队列最大值
		int pullPktQueueHighWorkers = 0;   // 拉流队列高水位的布控数量
		int pullPktQueueSevereWorkers = 0; // 拉流队列严重积压的布控数量
		int pushFrameQueueHighWorkers = 0; // 推流队列高水位的布控数量
		int pushFrameQueueSevereWorkers = 0; // 推流队列严重积压的布控数量
	};

	struct ResourceDropStatsInfo {
		uint64_t droppedPullPacketsDelta = 0;   // 最近窗口内丢弃的拉流包数量
		uint64_t droppedDecodePacketsDelta = 0; // 最近窗口内丢弃的解码包数量
		uint64_t droppedPushFramesDelta = 0;    // 最近窗口内丢弃的推流帧数量
		uint64_t droppedAlarmFramesDelta = 0;   // 最近窗口内丢弃的报警帧数量
		int64_t dropWindowMs = 0;               // 最近窗口时长（ms）
		double droppedPullPacketsPerSecond = 0.0;
		double droppedDecodePacketsPerSecond = 0.0;
		double droppedPushFramesPerSecond = 0.0;
		double droppedAlarmFramesPerSecond = 0.0;
	};

	struct ResourceInfo
		: public ResourceUsageInfo,
		  public ResourceQueuePressureInfo,
		  public ResourceDropStatsInfo
	{
	};

	struct SchedulerStatsControlSnapshot {
		uint64_t controlAddRequests = 0;
		uint64_t controlAddSuccess = 0;
		uint64_t controlAddFailure = 0;
		uint64_t controlCancelRequests = 0;
		uint64_t controlCancelSuccess = 0;
		uint64_t controlCancelFailure = 0;
		uint64_t controlAddTotalMs = 0;
		uint64_t controlAddMaxMs = 0;
		uint64_t controlAddLastMs = 0;
		uint64_t controlCancelTotalMs = 0;
		uint64_t controlCancelMaxMs = 0;
		uint64_t controlCancelLastMs = 0;
	};

	struct SchedulerStatsEventSnapshot {
		uint64_t workerDeleteQueued = 0;
		uint64_t workerDeleteProcessed = 0;
		uint64_t alarmQueued = 0;
		uint64_t alarmDropped = 0;
		uint64_t alarmProcessed = 0;
		uint64_t algorithmLoadSuccess = 0;
		uint64_t algorithmLoadFailure = 0;
		uint64_t algorithmUnloadSuccess = 0;
		uint64_t algorithmUnloadFailure = 0;
	};

	struct SchedulerStatsIoSnapshot {
		uint64_t pullReadErrors = 0;
		uint64_t pullReconnectAttempts = 0;
		uint64_t pullReconnectSuccess = 0;
		uint64_t pushWriteErrors = 0;
		uint64_t pushReconnectAttempts = 0;
		uint64_t pushReconnectSuccess = 0;
	};

	struct SchedulerStatsDropNotifySnapshot {
		uint64_t droppedPullPackets = 0;
		uint64_t droppedDecodePackets = 0;
		uint64_t droppedPushFrames = 0;
		uint64_t droppedAlarmFrames = 0;
		uint64_t alarmNotifyQueued = 0;
		uint64_t alarmNotifySent = 0;
		uint64_t alarmNotifyFailed = 0;
		uint64_t alarmNotifyRetried = 0;
	};

	struct SchedulerStatsApiInferSnapshot {
		uint64_t apiInferAllowed = 0;
		uint64_t apiInferSkippedMinInterval = 0;
		uint64_t apiInferSkippedCircuitOpen = 0;
		uint64_t apiInferSuccess = 0;
		uint64_t apiInferFailure = 0;
		uint64_t apiInferRetried = 0;
		uint64_t apiInferCircuitOpened = 0;
		uint64_t apiInferLatencyTotalMs = 0;
		uint64_t apiInferLatencyMaxMs = 0;
		uint64_t apiInferLatencyLastMs = 0;
	};

	struct SchedulerStatsRuntimeSnapshot {
		uint64_t lastUpdateTimestamp = 0;
		int detectStride = 1;
		int currentControls = 0;
		size_t deleteQueueSize = 0;
		size_t alarmQueueSize = 0;
	};

	struct SchedulerStatsSnapshot
		: public SchedulerStatsControlSnapshot,
		  public SchedulerStatsEventSnapshot,
		  public SchedulerStatsIoSnapshot,
		  public SchedulerStatsDropNotifySnapshot,
		  public SchedulerStatsApiInferSnapshot,
		  public SchedulerStatsRuntimeSnapshot
	{
	};

	struct SchedulerStatsControlCounters {
		std::atomic<uint64_t> controlAddRequests{ 0 };
		std::atomic<uint64_t> controlAddSuccess{ 0 };
		std::atomic<uint64_t> controlAddFailure{ 0 };
		std::atomic<uint64_t> controlCancelRequests{ 0 };
		std::atomic<uint64_t> controlCancelSuccess{ 0 };
		std::atomic<uint64_t> controlCancelFailure{ 0 };
		std::atomic<uint64_t> controlAddTotalMs{ 0 };
		std::atomic<uint64_t> controlAddMaxMs{ 0 };
		std::atomic<uint64_t> controlAddLastMs{ 0 };
		std::atomic<uint64_t> controlCancelTotalMs{ 0 };
		std::atomic<uint64_t> controlCancelMaxMs{ 0 };
		std::atomic<uint64_t> controlCancelLastMs{ 0 };
	};

	struct SchedulerStatsEventCounters {
		std::atomic<uint64_t> workerDeleteQueued{ 0 };
		std::atomic<uint64_t> workerDeleteProcessed{ 0 };
		std::atomic<uint64_t> alarmQueued{ 0 };
		std::atomic<uint64_t> alarmDropped{ 0 };
		std::atomic<uint64_t> alarmProcessed{ 0 };
		std::atomic<uint64_t> algorithmLoadSuccess{ 0 };
		std::atomic<uint64_t> algorithmLoadFailure{ 0 };
		std::atomic<uint64_t> algorithmUnloadSuccess{ 0 };
		std::atomic<uint64_t> algorithmUnloadFailure{ 0 };
	};

	struct SchedulerStatsIoCounters {
		std::atomic<uint64_t> pullReadErrors{ 0 };
		std::atomic<uint64_t> pullReconnectAttempts{ 0 };
		std::atomic<uint64_t> pullReconnectSuccess{ 0 };
		std::atomic<uint64_t> pushWriteErrors{ 0 };
		std::atomic<uint64_t> pushReconnectAttempts{ 0 };
		std::atomic<uint64_t> pushReconnectSuccess{ 0 };
	};

	struct SchedulerStatsDropNotifyCounters {
		std::atomic<uint64_t> droppedPullPackets{ 0 };
		std::atomic<uint64_t> droppedDecodePackets{ 0 };
		std::atomic<uint64_t> droppedPushFrames{ 0 };
		std::atomic<uint64_t> droppedAlarmFrames{ 0 };
		std::atomic<uint64_t> alarmNotifyQueued{ 0 };
		std::atomic<uint64_t> alarmNotifySent{ 0 };
		std::atomic<uint64_t> alarmNotifyFailed{ 0 };
		std::atomic<uint64_t> alarmNotifyRetried{ 0 };
	};

	struct SchedulerStatsApiInferCounters {
		std::atomic<uint64_t> apiInferAllowed{ 0 };
		std::atomic<uint64_t> apiInferSkippedMinInterval{ 0 };
		std::atomic<uint64_t> apiInferSkippedCircuitOpen{ 0 };
		std::atomic<uint64_t> apiInferSuccess{ 0 };
		std::atomic<uint64_t> apiInferFailure{ 0 };
		std::atomic<uint64_t> apiInferRetried{ 0 };
		std::atomic<uint64_t> apiInferCircuitOpened{ 0 };
		std::atomic<uint64_t> apiInferLatencyTotalMs{ 0 };
		std::atomic<uint64_t> apiInferLatencyMaxMs{ 0 };
		std::atomic<uint64_t> apiInferLatencyLastMs{ 0 };
	};

	struct SchedulerStatsRuntimeCounters {
		std::atomic<uint64_t> lastUpdateTimestamp{ 0 };
	};

	struct SchedulerStats
		: public SchedulerStatsControlCounters,
		  public SchedulerStatsEventCounters,
		  public SchedulerStatsIoCounters,
		  public SchedulerStatsDropNotifyCounters,
		  public SchedulerStatsApiInferCounters,
		  public SchedulerStatsRuntimeCounters
	{
	};

	struct SharedDecodeSessionEntry {
		std::unique_ptr<SharedDecodeSession> session;
		int refs = 0;
	};

	struct SchedulerCoreState {
		Config* mConfig = nullptr;
		std::atomic<bool> mState{ false };
		std::unique_ptr<FaceDb> mFaceDb;
		std::atomic<bool> mFaceSearchEnabled{ true };
	};

	struct SchedulerAlgorithmRegistryState {
		std::mutex mAlgorithmMtx;
		std::map<std::string, AlgorithmInfo, std::less<>> mAlgorithmMap;  // 动态算法存储
	};

	struct SchedulerResourceState {
		ResourceInfo mResourceInfo;
		std::mutex mResourceMtx;
		std::mutex mResourceUpdateMtx; // serialize updateResourceInfo() to avoid data races
		uint64_t mLastDroppedPullPackets = 0;
		uint64_t mLastDroppedDecodePackets = 0;
		uint64_t mLastDroppedPushFrames = 0;
		uint64_t mLastDroppedAlarmFrames = 0;
		int64_t mLastDropCalcTimestamp = 0;
		std::unique_ptr<std::thread> mResourceMonitorThread;
	};

	struct SchedulerAdmissionState {
		std::atomic<int> mPendingControls{ 0 };
		std::mutex mAdmissionMtx;
		std::atomic<int> mMaxPendingControls{ 2 };
		std::atomic<int> mDetectStride{ 1 };
		DetectStrideHysteresis mDetectStrideHysteresis;
		std::atomic<int> mCurrentDecodeChannels{ 0 };  // 当前硬件解码通道数
		std::atomic<int> mCurrentEncodeChannels{ 0 };  // 当前硬件编码通道数
		std::mutex mDecodeChannelMtx;                  // 解码通道互斥锁
		std::mutex mEncodeChannelMtx;                  // 编码通道互斥锁
	};

	struct SchedulerStatsState {
		SchedulerStats mStats;
	};

	struct SchedulerWorkerState {
		std::map<std::string, Worker*, std::less<>> mWorkerMap; // <control.code,Worker*>
		std::mutex mWorkerMapMtx;
		std::map<std::string, SharedDecodeSessionEntry, std::less<>> mSharedDecodeSessionMap;
		std::mutex mSharedDecodeSessionMtx;
		std::queue<Worker*> mTobeDeletedWorkerQ;
		std::mutex mTobeDeletedWorkerQ_mtx;
		std::condition_variable mTobeDeletedWorkerQ_cv;
		std::unique_ptr<std::thread> mDeleteWorkerThread;
	};

	struct SchedulerAlarmState {
		std::unique_ptr<std::thread> mLoopAlarmThread;
		std::queue<Alarm*> mAlarmQ;
		std::mutex mAlarmQ_mtx;
		std::condition_variable mAlarmQ_cv;
		size_t mAlarmQMaxSize = 5;
	};

	struct AlarmNotifyTask {
		std::string url;
		std::string data;
		std::string token;
		int attempt = 0;
		int64_t nextAttemptMs = 0;
	};

	struct SchedulerAlarmNotifyState {
		std::mutex mAlarmNotifyMtx;
		std::condition_variable mAlarmNotifyCv;
		std::deque<AlarmNotifyTask> mAlarmNotifyQ;
		std::unique_ptr<std::thread> mAlarmNotifyThread;
	};

	class Scheduler
		: public SchedulerAlgorithmRegistryState,
		  private SchedulerCoreState,
		  private SchedulerResourceState,
		  private SchedulerAdmissionState,
		  private SchedulerStatsState,
		  private SchedulerWorkerState,
		  private SchedulerAlarmState,
		  private SchedulerAlarmNotifyState
	{
	public:
		friend class Worker;

		explicit Scheduler(Config* config);
		~Scheduler();

		Config* getConfig();

		bool initAlgorithm();

		bool loadAlgorithm(const std::string& code, const std::string& modelPath,
		                   const std::vector<std::string>& classNames, const std::string& device, std::string& errMsg);
		bool loadAlgorithm(const std::string& code, const std::string& modelPath,
		                   const std::vector<std::string>& classNames, const std::string& device, std::string& errMsg, int concurrency);
		bool loadAlgorithm(const std::string& code, const std::string& modelPath,
		                   const std::vector<std::string>& classNames, const std::string& device,
		                   const std::string& algorithmSubtype, std::string& errMsg);
		bool loadAlgorithm(const std::string& code, const std::string& modelPath,
		                   const std::vector<std::string>& classNames, const std::string& device,
		                   const std::string& algorithmSubtype, std::string& errMsg, int concurrency);
		bool loadAlgorithm(const std::string& code, const std::string& modelPath,
		                   const std::vector<std::string>& classNames, const std::string& device,
		                   const std::string& algorithmSubtype, std::string& errMsg, int concurrency,
		                   bool forceInferenceDevice);
		bool unloadAlgorithm(const std::string& code, std::string& errMsg);
		Algorithm* getAlgorithm(const std::string& code);     // 获取算法实例（不改变引用计数）
		Algorithm* acquireAlgorithm(const std::string& code); // 获取算法实例（增加引用计数；用于 API/临时使用，防止卸载竞态）
		void releaseAlgorithm(const std::string& code);       // 释放算法引用（减少引用计数；与 acquireAlgorithm 配对）
		std::vector<std::string> listAlgorithms();            // 列出所有已加载的算法
		bool getAlgorithmDeviceDecision(std::string_view code, InferenceDeviceDecision& decision);
		bool ensureAlgorithmLoaded(const std::string& code, std::string& errMsg); // 根据预设映射按需加载
		bool ensureAlgorithmLoaded(const std::string& code, int concurrency, std::string& errMsg); // 指定并发实例数（仅首次加载生效）
		bool ensureAlgorithmLoaded(const std::string& code, int concurrency, bool forceInferenceDevice,
		                           std::string& errMsg);

		void bindControlToAlgorithm(const std::string& algorithmCode, const std::string& controlCode);
		void unbindControlFromAlgorithm(const std::string& algorithmCode, const std::string& controlCode);
		void tryAutoUnloadAlgorithm(const std::string& algorithmCode);  // 尝试自动卸载无引用的模型

		void updateResourceInfo();                 // 更新资源使用信息
		bool canAddControl(std::string& errMsg);   // 检查是否可以添加新布控
		ResourceInfo getResourceInfo();            // 获取当前资源信息
		void setMaxControls(int maxControls);      // 手动设置最大布控数
		int getDetectStride();                     // 获取当前检测步长
		SchedulerStatsSnapshot getSchedulerStatsSnapshot(); // 获取调度统计
		void statsIncPullReadErrors(uint64_t count = 1);
		void statsIncPullReconnectAttempts(uint64_t count = 1);
		void statsIncPullReconnectSuccess(uint64_t count = 1);
		void statsIncPushWriteErrors(uint64_t count = 1);
		void statsIncPushReconnectAttempts(uint64_t count = 1);
		void statsIncPushReconnectSuccess(uint64_t count = 1);
		void statsIncDroppedPullPackets(uint64_t count = 1);
		void statsIncDroppedDecodePackets(uint64_t count = 1);
		void statsIncDroppedPushFrames(uint64_t count = 1);
		void statsIncDroppedAlarmFrames(uint64_t count = 1);

		void statsIncApiInferAllowed(uint64_t count = 1);
		void statsIncApiInferSkippedMinInterval(uint64_t count = 1);
		void statsIncApiInferSkippedCircuitOpen(uint64_t count = 1);
		void statsIncApiInferSuccess(uint64_t count = 1);
		void statsIncApiInferFailure(uint64_t count = 1);
		void statsIncApiInferRetried(uint64_t count = 1);
		void statsIncApiInferCircuitOpened(uint64_t count = 1);
		void statsObserveApiInferLatencyMs(uint64_t latencyMs);

		void enqueueAlarmNotify(std::string_view url, std::string_view data, std::string_view token);

		FaceDb* getFaceDb();
		bool isFaceSearchEnabled() const;
		void setFaceSearchEnabled(bool enabled);

		bool reserveDecodeChannel(std::string& errMsg); // 预留硬件解码通道
		void releaseDecodeChannel();                    // 释放硬件解码通道
		bool reserveEncodeChannel(std::string& errMsg); // 预留硬件编码通道
		void releaseEncodeChannel();                    // 释放硬件编码通道

		void loop();

		void setState(bool state);
		bool getState();

		void addAlarm(Alarm* alarm);

		int apiControls(std::vector<Control*>& controls);
		Control* apiControl(std::string_view code);
		LocalLicenseInfo getLocalLicenseInfo() const;
		void apiControlAdd(Control* control, int& result_code, std::string& result_msg);
		void apiControlCancel(const Control* control, int& result_code, std::string& result_msg);

		bool acquireControlLease(Control* control, std::string& errMsg);
		void releaseControlLease(const std::string& leaseId);

	private:
		void cleanupExpiredAlgorithms(); // 清理超过 TTL 的空闲算法模型（非内置）
		static void resourceMonitorThread(Scheduler* arg);
		void handleResourceMonitor();

		static void alarmNotifyThread(Scheduler* arg);
		void handleAlarmNotify();

		void handleLicenseLeaseRenew();
		bool renewLeaseId(const std::string& leaseId, int ttlSeconds, LicenseThreadPriorityHint* outHint, std::string& errMsg);
		std::string getNodeId();
		bool reserveControlSlot(std::string& errMsg);
		void releaseControlSlot();

		bool acquireSharedDecodeSession(Control* control, SharedDecodeSession*& session, std::string& key, std::string& errMsg);
		void releaseSharedDecodeSession(const std::string& key, Worker* worker);
		int getWorkerSize();
		bool isAdd(const Control* control);
		bool addWorker(const Control* control, Worker* worker);
		bool removeWorker(const Control* control, bool releaseLease = false); // 加入到待实际删除队列
		Worker* getWorker(const Control* control);

		void handleDeleteWorker();
		static void deleteWorkerThread(Scheduler* arg);

		static void loopAlarmThread(Scheduler* arg);
		void handleLoopAlarm();
		bool getAlarm(Alarm*& alarm, int& alarmQSize);
		void clearAlarmQueue();
	};
}
#endif //ANALYZER_SCHEDULER_H
