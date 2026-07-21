#include "Scheduler.h"
#include "Config.h"
#include "Control.h"
#include "Worker.h"
#include "AvPullStream.h"
#include "AvPushStream.h"
#include "SharedDecodeKey.h"
#include "SharedDecodeSession.h"
#include "Algorithm.h"
#include "AlgorithmOnYolo.h"
#include "AlgorithmOnReid.h"
#include "AlgorithmOvYolo.h"
#include "AlgorithmOvReid.h"
#include "AlgorithmBuiltinCatalog.h"
#include "AlgorithmPlugin.h"
#include "AlgorithmXcOcr.h"
#include "AlgorithmInstanceKey.h"
#include "ControlAlgorithmCodes.h"
#include "ModelEncryption.h"
#include "GenerateAlarmVideo.h"
#include "LinuxMemoryUsage.h"
#include "ProcStatCpu.h"
#include "ApiAlgorithmSupport.h"
#include "AlarmNotifyBackoff.h"
#include "AlgorithmDeviceSuffix.h"
#include "EngineModelSupport.h"
#include "FaceDb.h"
#include "LicenseLeasePayload.h"
#include "LicenseThreadPriority.h"
#include "LicenseLeaseRenewPolicy.h"
#include "LocalLicense.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include "Utils/Request.h"
#include <algorithm>
#include <fstream>
#include <filesystem>
#include <string>
#include <cstring>
#include <cctype>
#include <memory>
#include <json/json.h>

#include <tuple>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#pragma comment(lib, "psapi.lib")
#elif defined(__linux__)
#include <sys/sysinfo.h>
#include <unistd.h>
#else
#include <unistd.h>
#endif

namespace AVSAnalyzer {

    namespace {
        std::string toUpper(std::string value) {
            std::transform(value.begin(), value.end(), value.begin(),
                [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
            return value;
        }

        bool endsWith(std::string_view value, std::string_view suffix) {
            if (value.size() < suffix.size()) {
                return false;
            }
            return value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
        }

        bool parseAlgorithmDevice(const std::string& code, std::string& baseCode, std::string& device) {
            parseAlgorithmDeviceSuffix(code, baseCode, device);
            return true;
        }

        bool isOpenVinoDeviceAvailable(const std::string& device, std::string& errMsg) {
            std::string target = toUpper(device.empty() ? "CPU" : device);
            if (target == "CPU") {
                return true;
            }

            try {
                ov::Core core;
                auto devices = core.get_available_devices();
                for (const auto& d : devices) {
                    std::string dUpper = toUpper(d);
                    if (dUpper == target || (dUpper.rfind(target + ".", 0) == 0)) {
                        return true;
                    }
                }
            }
            catch (const ov::Exception& ex) {
                errMsg = std::string("OpenVINO device query failed: ") + ex.what();
                return false;
            }

            errMsg = "OpenVINO device not available: " + target;
            return false;
        }

	        bool isOnnxDeviceAvailable(const std::string& device, std::string& errMsg) {
	            std::string target = toUpper(device.empty() ? "CPU" : device);
	            std::string base = target;
	            size_t colonPos = base.find(':');
	            if (colonPos != std::string::npos) {
	                base = base.substr(0, colonPos);
	            }
	            if (base == "CPU" || base == "AUTO") {
	                return true;
	            }

	            if (base == "GPU") {
	                base = "CUDA";
	            }
	            if (base == "TRT") {
	                base = "TENSORRT";
	            }

	            if (base == "CUDA") {
	                try {
	                    std::vector<std::string> providers = Ort::GetAvailableProviders();
	                    for (const auto& p : providers) {
	                        if (p == "CUDAExecutionProvider") {
	                            return true;
	                        }
	                    }
	                }
	                catch (const Ort::Exception& ex) {
	                    errMsg = std::string("ONNX Runtime provider query failed: ") + ex.what();
	                    return false;
	                }
	                errMsg = "CUDAExecutionProvider not available";
	                return false;
	            }

	            if (base == "TENSORRT") {
	                try {
	                    std::vector<std::string> providers = Ort::GetAvailableProviders();
	                    for (const auto& p : providers) {
	                        if (p == "TensorrtExecutionProvider") {
	                            return true;
	                        }
	                    }
	                }
	                catch (const Ort::Exception& ex) {
	                    errMsg = std::string("ONNX Runtime provider query failed: ") + ex.what();
	                    return false;
	                }
	                errMsg = "TensorrtExecutionProvider not available";
	                return false;
	            }

	            errMsg = "Unsupported ONNX Runtime device: " + target;
	            return false;
	        }

        void appendPreflightWarn(std::string& preflightWarn, std::string_view item) {
            if (item.empty()) {
                return;
            }
            if (!preflightWarn.empty()) {
                preflightWarn.append("; ");
            }
            preflightWarn.append(item.data(), item.size());
        }

        bool engineFromBaseCode(const std::string& baseCode, BuiltinAlgorithmEngine& outEngine) {
            if (const auto* meta = find_builtin_algorithm_meta(baseCode)) {
                outEngine = meta->engine;
                return true;
            }
            std::string lower = baseCode;
            std::transform(lower.begin(), lower.end(), lower.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (lower.rfind("on_", 0) == 0) {
                outEngine = BuiltinAlgorithmEngine::Onnx;
                return true;
            }
            if (lower.rfind("ov_", 0) == 0) {
                outEngine = BuiltinAlgorithmEngine::OpenVino;
                return true;
            }
            return false;
        }

        bool preflightAndRewriteAlgoCode(
            const Control* control,
            std::string& algoCode,
            const char* label,
            std::string& result_msg,
            std::string& preflightWarn) {
            if (!control || algoCode.empty()) {
                return true;
            }

            const std::string original = algoCode;
            std::string baseCode;
            std::string device;
            parseAlgorithmDevice(algoCode, baseCode, device);

            BuiltinAlgorithmEngine engine;
            if (!engineFromBaseCode(baseCode, engine)) {
                return true;
            }

            std::string baseDevice = toUpper(device.empty() ? "CPU" : device);
            size_t colonPos = baseDevice.find(':');
            if (colonPos != std::string::npos) {
                baseDevice = baseDevice.substr(0, colonPos);
            }

            const bool force = control->forceInferenceDevice;
            std::string err;

            if (engine == BuiltinAlgorithmEngine::Onnx) {
                if (baseDevice == "GPU") {
                    baseDevice = "CUDA";
                }
                if (baseDevice == "TRT") {
                    baseDevice = "TENSORRT";
                }
                if (baseDevice == "CPU" || baseDevice == "AUTO") {
                    return true;
                }

                if (baseDevice == "TENSORRT") {
                    if (isOnnxDeviceAvailable("TENSORRT", err)) {
                        return true;
                    }
                    if (force) {
                        result_msg = std::string(label ? label : "algorithm") + " device not supported: " + original + " (" + err + ")";
                        return false;
                    }
                    std::string cudaErr;
                    if (isOnnxDeviceAvailable("CUDA", cudaErr)) {
                        appendPreflightWarn(preflightWarn,
                            "degrade " + original + " => CUDA (" + err + ")");
                        return true;
                    }
                    appendPreflightWarn(preflightWarn,
                        "degrade " + original + " => CPU (" + err + "; " + cudaErr + ")");
                    return true;
                }

                if (baseDevice == "CUDA") {
                    if (isOnnxDeviceAvailable("CUDA", err)) {
                        return true;
                    }
                    if (force) {
                        result_msg = std::string(label ? label : "algorithm") + " device not supported: " + original + " (" + err + ")";
                        return false;
                    }
                    appendPreflightWarn(preflightWarn,
                        "degrade " + original + " => CPU (" + err + ")");
                    return true;
                }

                if (isOnnxDeviceAvailable(baseDevice, err)) {
                    return true;
                }
                if (force) {
                    result_msg = std::string(label ? label : "algorithm") + " device not supported: " + original + " (" + err + ")";
                    return false;
                }
                appendPreflightWarn(preflightWarn,
                    "degrade " + original + " => CPU (" + err + ")");
                return true;
            }

            if (engine == BuiltinAlgorithmEngine::OpenVino) {
                if (baseDevice == "CPU" || baseDevice == "AUTO") {
                    return true;
                }
                if (isOpenVinoDeviceAvailable(baseDevice, err)) {
                    return true;
                }
                if (force) {
                    result_msg = std::string(label ? label : "algorithm") + " device not supported: " + original + " (" + err + ")";
                    return false;
                }
                appendPreflightWarn(preflightWarn,
                    "degrade " + original + " => CPU (" + err + ")");
                return true;
            }

            return true;
        }
    }

    Scheduler::Scheduler(Config* config)
        : SchedulerCoreState{ config, false, nullptr, true }
    {
        LOGI("");
        if (mConfig) {
            int maxSize = mConfig->alarmQueueMaxSize;
            if (maxSize < 1) {
                maxSize = 1;
            }
            mAlarmQMaxSize = static_cast<size_t>(maxSize);

            // 初始化硬件解码/编码资源限制
            mResourceInfo.maxHardwareDecodeChannels = mConfig->maxHardwareDecodeChannels;
            mResourceInfo.maxHardwareEncodeChannels = mConfig->maxHardwareEncodeChannels;

            // 初始化布控上限与并发启动上限（工业部署常需要显式控制）
            int upper = std::max(1, mConfig->maxControls);
            mResourceInfo.maxControlsUpperBound = upper;
            mResourceInfo.maxControls = upper;
            int pendingUpper = std::max(1, mConfig->maxPendingControls);
            mMaxPendingControls.store(pendingUpper);
            mResourceInfo.maxPendingControls = pendingUpper;

            // ========== Face DB (人脸特征库) ==========
            try {
                const std::filesystem::path base = mConfig->modelDir.empty()
                    ? std::filesystem::path("models")
                    : std::filesystem::path(mConfig->modelDir);
                const std::filesystem::path faceDbPath = base / "face" / "face_db_v1.bin";
                mFaceDb = std::make_unique<FaceDb>(faceDbPath.string());
                std::string faceErr;
                if (!mFaceDb->loadFromDisk(faceErr)) {
                    LOGW("FaceDb load failed: path=%s err=%s", faceDbPath.string().c_str(), faceErr.c_str());
                }
                else {
                    LOGI("FaceDb loaded: path=%s count=%zu dim=%d",
                         faceDbPath.string().c_str(),
                         mFaceDb->count(),
                         mFaceDb->embeddingDim());
                }
            }
            catch (const std::exception& ex) { // NOSONAR
                LOGW("FaceDb init failed: %s", ex.what());
            }
            // ========================================
        }

    }

	    Scheduler::~Scheduler()
	    {
	        LOGI("");

        mState.store(false);  // 停止所有线程

        mAlarmQ_cv.notify_all();
        mTobeDeletedWorkerQ_cv.notify_all();
        mAlarmNotifyCv.notify_all();
	        clearAlarmQueue();

	        if (mLoopAlarmThread) {
	            if (mLoopAlarmThread->joinable()) {
	                mLoopAlarmThread->join();
	            }
	            mLoopAlarmThread.reset();
	        }
	        if (mAlarmNotifyThread) {
	            if (mAlarmNotifyThread->joinable()) {
	                mAlarmNotifyThread->join();
	            }
	            mAlarmNotifyThread.reset();
	        }

	        // 清理资源监控线程
	        if (mResourceMonitorThread) {
	            if (mResourceMonitorThread->joinable()) {
	                mResourceMonitorThread->join();
	            }
	            mResourceMonitorThread.reset();
	        }
	        if (mDeleteWorkerThread) {
	            if (mDeleteWorkerThread->joinable()) {
	                mDeleteWorkerThread->join();
	            }
	            mDeleteWorkerThread.reset();
	        }

	        // 清理动态加载的算法
	        std::scoped_lock lock(mAlgorithmMtx);
	        for (auto& pair : mAlgorithmMap) {
	            pair.second.algorithm.reset();
	            if (!pair.second.decryptedDir.empty()) {
	                try {
	                    std::filesystem::remove_all(pair.second.decryptedDir);
	                }
	                catch (const std::filesystem::filesystem_error&) {}
	            }
	        }
	        mAlgorithmMap.clear();
	    }

    Config* Scheduler::getConfig() {
        return mConfig;
    }

    FaceDb* Scheduler::getFaceDb() {
        return mFaceDb.get();
    }

    bool Scheduler::isFaceSearchEnabled() const {
        return mFaceSearchEnabled.load();
    }

    void Scheduler::setFaceSearchEnabled(bool enabled) {
        mFaceSearchEnabled.store(enabled);
    }
    bool Scheduler::initAlgorithm() {
        // 以前在启动时预加载模型；现在改为懒加载，按需实例化
        LOGI("initAlgorithm() skipped preload, models will be loaded on demand");
        return true;
    }
	    void Scheduler::loop() {

	        mLoopAlarmThread = std::make_unique<std::thread>(Scheduler::loopAlarmThread, this);

	        // 启动资源监控线程
	        mResourceMonitorThread = std::make_unique<std::thread>(Scheduler::resourceMonitorThread, this);

	        // 启动删除队列线程
	        mDeleteWorkerThread = std::make_unique<std::thread>(Scheduler::deleteWorkerThread, this);

	        // 启动报警通知线程（Analyzer -> Admin /alarm/openAdd）
	        mAlarmNotifyThread = std::make_unique<std::thread>(Scheduler::alarmNotifyThread, this);

        LOGI("Start Success (with resource monitor)");
        while (mState.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

    }

    int Scheduler::apiControls(std::vector<Control*>& controls) {
        int len = 0;

	        std::scoped_lock lock(mWorkerMapMtx);
	        for (auto f = mWorkerMap.begin(); f != mWorkerMap.end(); ++f) {
	            ++len;
	            controls.push_back(f->second->mControl.get());

	        }

        return len;
    }
    Control* Scheduler::apiControl(std::string_view code) {
        Control* control = nullptr;
		        std::scoped_lock lock(mWorkerMapMtx);
		        for (auto f = mWorkerMap.begin(); f != mWorkerMap.end(); ++f) {
		            if (std::string_view(f->first) == code) {
		                control = f->second->mControl.get();
		            }

	        }

        return control;
    }

    LocalLicenseInfo Scheduler::getLocalLicenseInfo() const {
        return LocalLicense(mConfig).check();
    }


	    void Scheduler::apiControlAdd(Control* control, int& result_code, std::string& result_msg) {
	        int64_t startMs = getCurTime();
	        mStats.controlAddRequests++;
	        auto recordResult = [&](bool success) {
	            uint64_t elapsed = 0;
	            if (const int64_t endMs = getCurTime(); endMs >= startMs) {
	                elapsed = static_cast<uint64_t>(endMs - startMs);
	            }
	            mStats.controlAddTotalMs += elapsed;
	            mStats.controlAddLastMs = elapsed;
	            uint64_t prevMax = mStats.controlAddMaxMs.load();
            while (elapsed > prevMax && !mStats.controlAddMaxMs.compare_exchange_weak(prevMax, elapsed)) {}
            if (success) {
                mStats.controlAddSuccess++;
            }
            else {
                mStats.controlAddFailure++;
            }
            mStats.lastUpdateTimestamp = getCurTimestamp();
        };

        if (shouldUseLocalLicense(mConfig)) {
            const LocalLicenseInfo info = getLocalLicenseInfo();
            if (!info.ok) {
                result_msg = "license_invalid";
                result_code = 0;
                recordResult(false);
                return;
            }
        }

        struct SlotGuard {
            Scheduler* scheduler;
            bool active = true;
            explicit SlotGuard(Scheduler* s) : scheduler(s) {}
            SlotGuard(const SlotGuard&) = delete;
            SlotGuard& operator=(const SlotGuard&) = delete;
            SlotGuard(SlotGuard&&) = delete;
            SlotGuard& operator=(SlotGuard&&) = delete;
            void release() {
                if (active) {
                    scheduler->releaseControlSlot();
                    active = false;
                }
            }
            ~SlotGuard() {
                if (active) {
                    scheduler->releaseControlSlot();
                }
            }
        };

        // ========== 推理设备预检（工业降级/可选强制） ==========
        std::string preflightWarn;

        if (control) {
            const bool useBasicApiInference =
                shouldUseBasicApiInference(control->usePipelineMode, control->algorithmPipelineMode, control->api_url);
            // Base detection algorithm (local model only)
            if (const bool isPipelineMode5 = control->usePipelineMode && control->algorithmPipelineMode == 5;
                !useBasicApiInference && !isPipelineMode5 &&
                !control->algorithmCode.empty() &&
                control->algorithmCode != "wensou" && control->algorithmCode != "api" &&
                !preflightAndRewriteAlgoCode(control, control->algorithmCode, "basic", result_msg, preflightWarn)) {
                result_code = 0;
                recordResult(false);
                return;
            }

            // Hierarchical secondary algorithm (local model only)
            if (control->enableHierarchicalAlgorithm &&
                !control->secondaryAlgorithmCode.empty() &&
                control->secondaryApi_url.empty() &&
                control->secondaryAlgorithmCode != "wensou" && control->secondaryAlgorithmCode != "api" &&
                !preflightAndRewriteAlgoCode(control, control->secondaryAlgorithmCode, "secondary", result_msg, preflightWarn)) {
                result_code = 0;
                recordResult(false);
                return;
            }

            // Pipeline mode local algorithms
            if (control->usePipelineMode) {
                int mode = control->algorithmPipelineMode;
                if (mode == 2) {
                    std::string trackingLower = control->trackingAlgorithmCode;
                    std::transform(trackingLower.begin(), trackingLower.end(), trackingLower.begin(),
                        [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
	                if (!trackingLower.empty() && trackingLower != "bytetrack" &&
	                    !preflightAndRewriteAlgoCode(control, control->trackingAlgorithmCode, "tracking", result_msg, preflightWarn)) {
	                    result_code = 0;
	                    recordResult(false);
	                    return;
	                    }
	                }
	                if ((mode == 3 || mode == 4) && !control->classificationAlgorithmCode.empty() &&
	                    !preflightAndRewriteAlgoCode(control, control->classificationAlgorithmCode, "classification", result_msg, preflightWarn)) {
	                    result_code = 0;
	                    recordResult(false);
	                    return;
	                }
	                if (mode >= 1 && mode <= 4 && !control->behaviorAlgorithmCode.empty() &&
	                    !preflightAndRewriteAlgoCode(control, control->behaviorAlgorithmCode, "behavior", result_msg, preflightWarn)) {
	                    result_code = 0;
	                    recordResult(false);
	                    return;
	                }
	            }
	        }
        // ==============================================================

        // 首先检查资源是否允许添加新布控（含并发保护）
        if (!reserveControlSlot(result_msg)) {
            result_code = 0;
            recordResult(false);
            return;
        }
        SlotGuard slotGuard(this);

        if (isAdd(control)) {
            result_msg = "the control is running";
            result_code = 1000;
            recordResult(true);
            return;
        }

        else {
	            if (std::string leaseErr; !acquireControlLease(control, leaseErr)) {
	                result_msg = leaseErr.empty() ? "license_invalid" : leaseErr;
	                result_code = 0;
	                recordResult(false);
                return;
            }

            // ========== Per-control model params (precision/inputWxH) -> instance reuse key ==========
            try {
                const bool useBasicApiInference =
                    shouldUseBasicApiInference(control->usePipelineMode, control->algorithmPipelineMode, control->api_url);
                const bool isPipelineMode5 = control->usePipelineMode && control->algorithmPipelineMode == 5;

                if (!useBasicApiInference && !isPipelineMode5 &&
                    !control->algorithmCode.empty() &&
                    control->algorithmCode != "wensou" && control->algorithmCode != "api") {
                    ModelConfig cfg = normalizeModelConfig(control->modelPrecision, control->inputWidth, control->inputHeight);
                    control->algorithmInstanceKey = buildAlgorithmInstanceKey(control->algorithmCode, cfg);
                }
                else {
                    control->algorithmInstanceKey.clear();
                }
            }
            catch (const std::exception&) { // NOSONAR
                control->algorithmInstanceKey.clear();
            }
            // =============================================================================

	            std::vector<std::string> localAlgoCodes;
	            std::unique_ptr<Worker> worker;
	            try {
	                worker = std::make_unique<Worker>(this, control);
	                localAlgoCodes = collectLocalAlgorithmCodes(control);

		                if (worker->start(result_msg)) {
		                    if (addWorker(control, worker.get())) {
		                        // 绑定布控到算法（模型复用）：覆盖流程/二级算法等多算法场景
		                        for (const auto& code : localAlgoCodes) {
		                            bindControlToAlgorithm(code, control->code);
		                        }

	                        result_msg = "add success";
	                        if (!preflightWarn.empty()) {
	                            result_msg += " (" + preflightWarn + ")";
	                        }
	                        result_code = 1000;
	                        slotGuard.release();
	                        (void)worker.release(); // ownership transferred to Scheduler (mWorkerMap + delete queue)
	                        recordResult(true);
	                        return;
	                    }

		                    if (control && !control->licenseLeaseId.empty()) {
		                        releaseControlLease(control->licenseLeaseId);
		                    }
		                    worker.reset();
		                    for (const auto& code : localAlgoCodes) {
		                        tryAutoUnloadAlgorithm(code);
		                    }
		                    result_msg = "add error";
		                    result_code = 0;
		                    recordResult(false);
		                    return;
		                }

		                if (control && !control->licenseLeaseId.empty()) {
		                    releaseControlLease(control->licenseLeaseId);
		                }
		                worker.reset();
		                for (const auto& code : localAlgoCodes) {
		                    tryAutoUnloadAlgorithm(code);
		                }
		                result_code = 0;
		                recordResult(false);
		                return;
		            }
		            catch (const std::exception& ex) { // NOSONAR
	                if (control && !control->licenseLeaseId.empty()) {
	                    releaseControlLease(control->licenseLeaseId);
	                }
		                worker.reset();
		                for (const auto& code : localAlgoCodes) {
		                    tryAutoUnloadAlgorithm(code);
		                }
		                result_msg = std::string("control add exception: ") + ex.what();
		                result_code = 0;
		                recordResult(false);
		                return;
		            }
	            catch (...) { // NOSONAR
	                if (control && !control->licenseLeaseId.empty()) {
	                    releaseControlLease(control->licenseLeaseId);
	                }
		                worker.reset();
		                for (const auto& code : localAlgoCodes) {
		                    tryAutoUnloadAlgorithm(code);
		                }
		                result_msg = "control add exception: unknown";
		                result_code = 0;
		                recordResult(false);
		                return;
		            }
		        }

    }
	    void Scheduler::apiControlCancel(const Control* control, int& result_code, std::string& result_msg) {
	        int64_t startMs = getCurTime();
	        mStats.controlCancelRequests++;
	        auto recordResult = [&](bool success) {
	            uint64_t elapsed = 0;
	            if (const int64_t endMs = getCurTime(); endMs >= startMs) {
	                elapsed = static_cast<uint64_t>(endMs - startMs);
	            }
	            mStats.controlCancelTotalMs += elapsed;
	            mStats.controlCancelLastMs = elapsed;
	            uint64_t prevMax = mStats.controlCancelMaxMs.load();
            while (elapsed > prevMax && !mStats.controlCancelMaxMs.compare_exchange_weak(prevMax, elapsed)) {}
            if (success) {
                mStats.controlCancelSuccess++;
            }
            else {
                mStats.controlCancelFailure++;
            }
            mStats.lastUpdateTimestamp = getCurTimestamp();
        };

	        Worker* worker = getWorker(control);

	        if (worker) {
	            if (worker->getState()) {
	                result_msg = "control is running, ";
	            }
	            else {
	                result_msg = "control is not running, ";
	            }

	            removeWorker(control, true);

	            result_msg += "cancel success";
	            result_code = 1000;
	            recordResult(true);
	            return;
	        }
	        else {
	            result_msg = "there is no such control";
	            result_code = 0;
	            recordResult(false);
	            return;
	        }

    }
    void Scheduler::setState(bool state) {
        mState.store(state);
    }
    bool Scheduler::getState() {
        return mState.load();
    }

    bool Scheduler::acquireSharedDecodeSession(
        Control* control,
        SharedDecodeSession*& session,
        std::string& key,
        std::string& errMsg) {
        session = nullptr;
        key.clear();
        if (!control) {
            errMsg = "control is null";
            return false;
        }

        key = makeDecodeReuseKey(
            control->streamUrl,
            control->ffmpegSkipLoopFilter,
            control->ffmpegSkipIdct).value;
        if (key.empty()) {
            errMsg = "streamUrl is empty";
            return false;
        }

        std::scoped_lock lock(mSharedDecodeSessionMtx);
        SharedDecodeSessionEntry& entry = mSharedDecodeSessionMap[key];
        if (!entry.session) {
            auto created = std::make_unique<SharedDecodeSession>(this, key, *control);
            if (!created->start(errMsg)) {
                if (entry.refs <= 0) {
                    mSharedDecodeSessionMap.erase(key);
                }
                return false;
            }
            entry.session = std::move(created);
        }

        entry.refs++;
        session = entry.session.get();
        return true;
    }

    void Scheduler::releaseSharedDecodeSession(const std::string& key, Worker* worker) {
        if (key.empty()) {
            return;
        }

        std::unique_ptr<SharedDecodeSession> doomed;
        {
            std::scoped_lock lock(mSharedDecodeSessionMtx);
            auto it = mSharedDecodeSessionMap.find(key);
            if (it == mSharedDecodeSessionMap.end()) {
                return;
            }

            if (it->second.session && worker) {
                it->second.session->unsubscribe(worker);
            }
            if (it->second.refs > 0) {
                it->second.refs--;
            }
            if (it->second.refs <= 0) {
                doomed = std::move(it->second.session);
                mSharedDecodeSessionMap.erase(it);
            }
        }
    }

    int Scheduler::getWorkerSize() {
        std::scoped_lock lock(mWorkerMapMtx);
        return static_cast<int>(mWorkerMap.size());
    }
    bool Scheduler::isAdd(const Control* control) {
        if (!control) {
            return false;
        }
        std::scoped_lock lock(mWorkerMapMtx);
        return mWorkerMap.find(control->code) != mWorkerMap.end();
    }
	    bool Scheduler::addWorker(const Control* control, Worker* worker) {
	        if (!control || !worker) {
	            return false;
	        }
	        std::scoped_lock lock(mWorkerMapMtx);
	        if (mWorkerMap.find(control->code) != mWorkerMap.end()) {
	            return false;
	        }
	        mWorkerMap.try_emplace(control->code, worker);
	        return true;
	    }
    bool Scheduler::removeWorker(const Control* control, bool releaseLease) {
        bool result = false;
        Worker* worker = nullptr;

        if (!control) {
            return false;
        }

	        {
	            std::scoped_lock lock(mWorkerMapMtx);
	            if (auto f = mWorkerMap.find(control->code); f != mWorkerMap.end()) {
	                worker = f->second;
	                mWorkerMap.erase(f);
	                result = true;
	            }
	        }

        if (worker) {
            std::string leaseId;
            if (releaseLease) {
                try {
                    if (worker->mControl) {
                        leaseId = worker->mControl->licenseLeaseId;
                        worker->mControl->licenseLeaseId.clear();
                    }
                }
                catch (const std::exception&) {} // NOSONAR
            }

            try {
                worker->requestStop();
            }
            catch (const std::exception&) {} // NOSONAR

            if (releaseLease && !leaseId.empty()) {
                releaseControlLease(leaseId);
            }
            {
                std::scoped_lock lck(mTobeDeletedWorkerQ_mtx);
                mTobeDeletedWorkerQ.push(worker);
            }
            mStats.workerDeleteQueued++;
            mTobeDeletedWorkerQ_cv.notify_one();
        }
        return result;
    }
	    Worker* Scheduler::getWorker(const Control* control) {
	        Worker* worker = nullptr;

	        std::scoped_lock lock(mWorkerMapMtx);
	        if (auto f = mWorkerMap.find(control->code); f != mWorkerMap.end()) {
	            worker = f->second;
	        }
	        return worker;
	    }

    void Scheduler::handleDeleteWorker() {

        std::vector<Worker*> pending;
        {
            std::unique_lock lck(mTobeDeletedWorkerQ_mtx);
            mTobeDeletedWorkerQ_cv.wait(lck, [this]() {
                return !mState.load() || !mTobeDeletedWorkerQ.empty();
            });

            if (!mState.load() && mTobeDeletedWorkerQ.empty()) {
                return;
            }

            while (!mTobeDeletedWorkerQ.empty()) {
                pending.push_back(mTobeDeletedWorkerQ.front());
                mTobeDeletedWorkerQ.pop();
            }
        }

	        for (auto* worker : pending) {
	            if (!worker) {
	                continue;
	            }

	            LOGI("code=%s,streamUrl=%s", worker->mControl->code.data(), worker->mControl->streamUrl.data());

	            // Best-effort: release license lease (exception path, etc.). cancel path clears leaseId before enqueue.
	            try {
	                if (worker->mControl && !worker->mControl->licenseLeaseId.empty()) {
	                    releaseControlLease(worker->mControl->licenseLeaseId);
	                    worker->mControl->licenseLeaseId.clear();
	                }
	            }
		            catch (const std::exception&) {} // NOSONAR

	            // IMPORTANT: only unbind/unload after the Worker is fully destroyed.
	            // The decode thread may still call into Algorithm while shutting down; unloading before join may UAF.
	            std::string controlCode;
		            std::vector<std::string> algorithmCodes;
		            try {
		                controlCode = worker->mControl ? worker->mControl->code : "";
		                algorithmCodes = collectLocalAlgorithmCodes(worker->mControl.get());
		            }
			            catch (const std::exception&) {} // NOSONAR

                std::unique_ptr<Worker> owned(worker);
                worker = nullptr;
                owned.reset();
                mStats.workerDeleteProcessed++;

                if (!controlCode.empty()) {
                    for (const auto& algorithmCode : algorithmCodes) {
                        unbindControlFromAlgorithm(algorithmCode, controlCode);
                        tryAutoUnloadAlgorithm(algorithmCode);
                    }
                }
        }

    }

    void Scheduler::deleteWorkerThread(Scheduler* arg) {
        auto* scheduler = arg;
        while (scheduler->getState()) {
            scheduler->handleDeleteWorker();
        }
        scheduler->handleDeleteWorker();
    }
    void Scheduler::handleLoopAlarm() {
        int alarmQSize = 0;

        while (mState.load()) {
            Alarm* alarm = nullptr;
            if (!getAlarm(alarm, alarmQSize)) {
                continue;
            }

            GenerateAlarmVideo gen(mConfig, alarm);
            gen.genAlarmVideo();

            std::unique_ptr<Alarm> owned(alarm);
            alarm = nullptr;
            mStats.alarmProcessed++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
        }
    }
    void Scheduler::loopAlarmThread(Scheduler* arg) {
        auto* scheduler = arg;
        scheduler->handleLoopAlarm();
    }
    void Scheduler::addAlarm(Alarm* alarm) {
        if (!alarm) {
            return;
        }

	        std::scoped_lock lock(mAlarmQ_mtx);
	        if (mAlarmQ.size() >= mAlarmQMaxSize) {
	            Alarm* dropped = mAlarmQ.front();
	            mAlarmQ.pop();
	            std::unique_ptr<Alarm> owned(dropped);
	            dropped = nullptr;
	            mStats.alarmDropped++;
	        }

        mAlarmQ.push(alarm);
        mStats.alarmQueued++;
        mStats.lastUpdateTimestamp = getCurTimestamp();
        mAlarmQ_cv.notify_one();
    }

    bool Scheduler::getAlarm(Alarm*& alarm, int& alarmQSize) {
        std::unique_lock lock(mAlarmQ_mtx);
        mAlarmQ_cv.wait(lock, [this]() { return !mState.load() || !mAlarmQ.empty(); });

        if (!mState.load() && mAlarmQ.empty()) {
            alarmQSize = 0;
            return false;
        }

        alarm = mAlarmQ.front();
        mAlarmQ.pop();
        alarmQSize = static_cast<int>(mAlarmQ.size());
        return true;
    }
    void Scheduler::clearAlarmQueue() {
	        std::scoped_lock lock(mAlarmQ_mtx);
	        while (!mAlarmQ.empty()) {
	            Alarm* alarm = mAlarmQ.front();
	            mAlarmQ.pop();
	            std::unique_ptr<Alarm> owned(alarm);
	        }
	    }

    // ============== 动态模型管理实现 ==============

    bool Scheduler::loadAlgorithm(const std::string& code, const std::string& modelPath,
                                   const std::vector<std::string>& classNames, const std::string& device, std::string& errMsg) {
        return loadAlgorithm(code, modelPath, classNames, device, "detection", errMsg);
    }

    bool Scheduler::loadAlgorithm(const std::string& code, const std::string& modelPath,
                                   const std::vector<std::string>& classNames, const std::string& device, std::string& errMsg, int concurrency) {
        return loadAlgorithm(code, modelPath, classNames, device, "detection", errMsg, concurrency);
    }

    bool Scheduler::loadAlgorithm(const std::string& code, const std::string& modelPath,
                                   const std::vector<std::string>& classNames, const std::string& device,
                                   const std::string& algorithmSubtype, std::string& errMsg) {
        int defaultConcurrency = 1;
        if (mConfig) {
            defaultConcurrency = std::max(1, mConfig->modelConcurrency);
        }
        return loadAlgorithm(code, modelPath, classNames, device, algorithmSubtype, errMsg, defaultConcurrency);
    }

    bool Scheduler::loadAlgorithm(const std::string& code, const std::string& modelPath,
                                   const std::vector<std::string>& classNames, const std::string& device,
                                   const std::string& algorithmSubtype, std::string& errMsg, int concurrency) {
        return loadAlgorithm(
            code, modelPath, classNames, device, algorithmSubtype, errMsg, concurrency, false);
    }

    bool Scheduler::loadAlgorithm(const std::string& code, const std::string& modelPath,
                                   const std::vector<std::string>& classNames, const std::string& device,
                                   const std::string& algorithmSubtype, std::string& errMsg, int concurrency,
                                   bool forceInferenceDevice) {
        std::scoped_lock lock(mAlgorithmMtx);

        // Support per-control instance key: <algorithmCode>__<PRECISION>__<W>x<H>
        std::string algoCodeForInit = code;
        ModelConfig modelCfg = normalizeModelConfig("FP32", 640, 640);
        (void)parseAlgorithmInstanceKey(code, algoCodeForInit, modelCfg);

        // 检查是否已存在
        if (mAlgorithmMap.find(code) != mAlgorithmMap.end()) {
            errMsg = "Algorithm '" + code + "' already loaded";
            mStats.algorithmLoadFailure++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
            return false;
        }

        ModelEncryptionConfig encCfg;
        if (mConfig) {
            encCfg.enabled = mConfig->modelEncrypt;
            encCfg.key = mConfig->modelEncryptKey;
            encCfg.suffix = mConfig->modelEncryptSuffix;
            encCfg.decryptDir = mConfig->modelDecryptDir;
        }

        std::string loadPath = modelPath;
        std::string decryptedDir;
        std::string decryptErr;
        if (!resolveAndMaybeDecryptModel(encCfg, code, modelPath, loadPath, decryptedDir, decryptErr)) {
            errMsg = decryptErr;
            mStats.algorithmLoadFailure++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
            return false;
        }

        auto cleanupDecryptedDirOnFailure = [&](const std::string& dir) {
            if (dir.empty()) {
                return;
            }
            try {
                std::filesystem::remove_all(dir);
            }
            catch (const std::filesystem::filesystem_error&) {}
        };
        auto failLoad = [&](std::string message) {
            errMsg = std::move(message);
            cleanupDecryptedDirOnFailure(decryptedDir);
            mStats.algorithmLoadFailure++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
            return false;
        };

	    std::unique_ptr<Algorithm> algorithm;
	    const std::string requestedDevice = normalize_inference_device(device);
	    std::string effectiveDevice = requestedDevice;
	    std::string fallbackReason;
        if (concurrency < 1) {
            concurrency = 1;
        }

        std::string lowerPath = loadPath;
        std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

        std::string subtypeLower = algorithmSubtype;
        std::transform(subtypeLower.begin(), subtypeLower.end(), subtypeLower.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (subtypeLower.empty()) {
            subtypeLower = "detection";
        }

	        auto defaultCompatLibPath = [this]() {
	            std::filesystem::path base = mConfig && !mConfig->modelDir.empty()
	                                         ? std::filesystem::path(mConfig->modelDir)
	                                         : std::filesystem::current_path();
            base /= "compat";
#ifdef _WIN32
            base /= "libbeacon_compat.dll";
#elif __APPLE__
            base /= "libbeacon_compat.dylib";
#else
            base /= "libbeacon_compat.so";
#endif
	            return base.string();
	        };

	        auto resolveCompatLib = [this, &defaultCompatLibPath]() {
	            if (mConfig && !mConfig->modelDir.empty()) {
	                // allow config override
	                std::string cfg = mConfig->compatLibPath;
                if (!cfg.empty()) {
                    return cfg;
                }
            }
            return defaultCompatLibPath();
	        };

	    // 根据模型文件类型选择推理引擎。允许降级时记录完整决策；强制设备时不尝试其他设备。
	    auto wrapIfOcr = [this, &subtypeLower](std::unique_ptr<Algorithm> inner) -> std::unique_ptr<Algorithm> {
	        if (!inner) {
	            return nullptr;
	        }
	        if (subtypeLower == "ocr") {
	            return std::make_unique<AlgorithmXcOcr>(mConfig, std::move(inner));
	        }
	        return inner;
	    };

        const bool isOnnxModel = endsWith(lowerPath, ".onnx");
        const bool isOpenVinoModel = endsWith(lowerPath, ".xml");
        const bool isInferenceModel = isOnnxModel || isOpenVinoModel;
        auto appendFallbackReason = [&](const std::string& reason) {
            if (reason.empty()) {
                return;
            }
            if (!fallbackReason.empty()) {
                fallbackReason += "; ";
            }
            fallbackReason += reason;
        };
        const size_t requestedColon = requestedDevice.find(':');
        const std::string requestedBase = requestedDevice.substr(0, requestedColon);
        const std::string requestedId = requestedColon == std::string::npos
            ? std::string{}
            : requestedDevice.substr(requestedColon);
        auto deviceWithRequestedId = [&](std::string base) {
            return base + requestedId;
        };

        auto makeInferenceAlgorithm = [&](const std::string& selectedDevice) -> std::unique_ptr<Algorithm> {
            if (isOnnxModel) {
                if (subtypeLower == "tracking") {
                    return std::make_unique<AlgorithmOnReid>(
                        mConfig, loadPath, selectedDevice, concurrency, modelCfg.inputWidth, modelCfg.inputHeight);
                }
                return wrapIfOcr(std::make_unique<AlgorithmOnYolo>(
                    mConfig, loadPath, classNames, selectedDevice, concurrency, modelCfg.inputWidth, modelCfg.inputHeight));
            }
            if (subtypeLower == "tracking") {
                return std::make_unique<AlgorithmOvReid>(
                    mConfig, loadPath, selectedDevice, concurrency, modelCfg.inputWidth, modelCfg.inputHeight);
            }
            return wrapIfOcr(std::make_unique<AlgorithmOvYolo>(
                mConfig, loadPath, classNames, selectedDevice, concurrency, modelCfg.inputWidth, modelCfg.inputHeight));
        };

        if (isInferenceModel) {
            std::vector<std::string> candidates;
            auto addCandidate = [&](const std::string& candidate) {
                if (std::find(candidates.begin(), candidates.end(), candidate) == candidates.end()) {
                    candidates.push_back(candidate);
                }
            };

            if (isOnnxModel) {
                auto addOnnxIfAvailable = [&](const std::string& base) {
                    const std::string candidate = deviceWithRequestedId(base);
                    std::string deviceErr;
                    if (isOnnxDeviceAvailable(candidate, deviceErr)) {
                        addCandidate(candidate);
                        return true;
                    }
                    appendFallbackReason(base + ": " + deviceErr);
                    return false;
                };

                if (requestedBase == "AUTO") {
                    (void)addOnnxIfAvailable("TENSORRT");
                    (void)addOnnxIfAvailable("CUDA");
                    addCandidate("CPU");
                }
                else if (requestedBase == "TENSORRT") {
                    (void)addOnnxIfAvailable("TENSORRT");
                    if (!forceInferenceDevice) {
                        (void)addOnnxIfAvailable("CUDA");
                        addCandidate("CPU");
                    }
                }
                else if (requestedBase == "CUDA") {
                    (void)addOnnxIfAvailable("CUDA");
                    if (!forceInferenceDevice) {
                        addCandidate("CPU");
                    }
                }
                else if (requestedBase == "CPU") {
                    addCandidate("CPU");
                }
                else {
                    appendFallbackReason("unsupported ONNX Runtime device: " + requestedDevice);
                    if (!forceInferenceDevice) {
                        addCandidate("CPU");
                    }
                }
            }
            else if (requestedBase == "AUTO") {
                // OpenVINO AUTO is a policy request; CPU remains an allowed effective device.
                addCandidate("CPU");
            }
            else {
                std::string deviceErr;
                if (isOpenVinoDeviceAvailable(requestedDevice, deviceErr)) {
                    addCandidate(requestedDevice);
                }
                else {
                    appendFallbackReason(deviceErr);
                }
                if (!forceInferenceDevice && requestedBase != "CPU") {
                    addCandidate("CPU");
                }
            }

            if (candidates.empty()) {
                InferenceDeviceDecision unavailable = make_inference_device_decision(
                    requestedDevice, "UNAVAILABLE", fallbackReason);
                std::string strictErr;
                if (!inference_device_decision_allowed(unavailable, forceInferenceDevice, strictErr)) {
                    return failLoad(std::move(strictErr));
                }
                return failLoad("No available inference device for request: " + requestedDevice);
            }

            for (const auto& candidate : candidates) {
                effectiveDevice = candidate;
                algorithm = makeInferenceAlgorithm(effectiveDevice);
                if (algorithm && algorithm->createState()) {
                    break;
                }
                algorithm.reset();
                appendFallbackReason("initialization failed on " + effectiveDevice);

                if (forceInferenceDevice && requestedBase != "AUTO") {
                    InferenceDeviceDecision unavailable = make_inference_device_decision(
                        requestedDevice, "UNAVAILABLE", fallbackReason);
                    std::string strictErr;
                    (void)inference_device_decision_allowed(unavailable, true, strictErr);
                    return failLoad(std::move(strictErr));
                }
            }

            if (!algorithm) {
                return failLoad("Failed to load model from: " + loadPath + " (" + fallbackReason + ")");
            }
        }
	    else if (endsWith(lowerPath, ".dll") || endsWith(lowerPath, ".so") || endsWith(lowerPath, ".dylib")) {
	        // 动态库插件算法（行为算法/自定义算法）
	        algorithm = wrapIfOcr(std::make_unique<AlgorithmPlugin>(
                mConfig, loadPath, algoCodeForInit, loadPath, concurrency));
	    }
	    else if (endsWith(lowerPath, ".rknn") || endsWith(lowerPath, ".om")) {
	        // 国产硬件模型：统一交给兼容动态库处理，模型路径传递给插件
	        std::string compatLib = resolveCompatLib();
	        const int preprocessMode = mConfig ? mConfig->rknpuPreprocessMode : 0;
	        AlgorithmPluginPreprocessConfig preprocess;
	        preprocess.inputWidth = modelCfg.inputWidth;
	        preprocess.inputHeight = modelCfg.inputHeight;
	        preprocess.mode = preprocessMode;
	        algorithm = wrapIfOcr(std::make_unique<AlgorithmPlugin>(
	            mConfig,
	            compatLib,
	            algoCodeForInit,
	            loadPath,
	            concurrency,
	            preprocess
	        ));
	    }
	    else if (isTensorrtEngineModelFile(lowerPath)) {
	        if (!mConfig || mConfig->tensorrtEnginePluginPath.empty()) {
	            return failLoad("TensorRT engine model requires 'tensorrtEnginePluginPath' in config.json");
	        }
	        algorithm = wrapIfOcr(std::make_unique<AlgorithmPlugin>(
                mConfig, mConfig->tensorrtEnginePluginPath, algoCodeForInit, loadPath, concurrency));
	    }
	    else {
	        return failLoad("Unsupported model format. Use .onnx/.xml/.rknn/.om or plugin (.dll/.so/.dylib)");
	    }

        if (!isInferenceModel && (!algorithm || !algorithm->createState())) {
            algorithm.reset();
            return failLoad("Failed to load model from: " + loadPath);
	    }

        const InferenceDeviceDecision deviceDecision = make_inference_device_decision(
            requestedDevice, effectiveDevice, fallbackReason);
        std::string decisionErr;
        if (!inference_device_decision_allowed(deviceDecision, forceInferenceDevice, decisionErr)) {
            algorithm.reset();
            return failLoad(std::move(decisionErr));
	    }

	        // 添加到 map
	        AlgorithmInfo& info = mAlgorithmMap[code];
	        info.algorithm = std::move(algorithm);
	        info.modelPath = modelPath;
	        info.decryptedDir = decryptedDir;
	        info.classNames = classNames;
	        info.isLoaded = true;
	        info.isBuiltin = false;
	        info.requestedDevice = deviceDecision.requestedDevice;
	        info.effectiveDevice = deviceDecision.effectiveDevice;
	        info.deviceDegraded = deviceDecision.degraded;
	        info.deviceDegradeReason = deviceDecision.reason;
	        info.lastUnusedTimestampMs = 0;
	        info.controlCodes.clear();
	        info.refCount = 0;

        LOGI("Algorithm '%s' loaded successfully from: %s (effectiveDevice=%s, requestedDevice=%s, degraded=%s, reason=%s)",
             code.c_str(), modelPath.c_str(), deviceDecision.effectiveDevice.c_str(),
             deviceDecision.requestedDevice.c_str(), deviceDecision.degraded ? "true" : "false",
             deviceDecision.reason.c_str());
        errMsg.clear();
        mStats.algorithmLoadSuccess++;
        mStats.lastUpdateTimestamp = getCurTimestamp();
        return true;
    }

	    bool Scheduler::unloadAlgorithm(const std::string& code, std::string& errMsg) {
	        std::scoped_lock lock(mAlgorithmMtx);

        auto it = mAlgorithmMap.find(code);
        if (it == mAlgorithmMap.end()) {
            errMsg = "Algorithm '" + code + "' not found";
            mStats.algorithmUnloadFailure++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
            return false;
        }

        // 检查引用计数，确保没有正在使用
        if (it->second.refCount > 0) {
            errMsg = "Algorithm '" + code + "' is currently in use (refCount=" + std::to_string(it->second.refCount.load()) + ")";
            mStats.algorithmUnloadFailure++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
            return false;
        }

	        // 删除算法实例
	        it->second.algorithm.reset();
	            if (!it->second.decryptedDir.empty()) {
	                try {
	                    std::filesystem::remove_all(it->second.decryptedDir);
	                }
                catch (const std::filesystem::filesystem_error&) {}
            }

        mAlgorithmMap.erase(it);

        LOGI("Algorithm '%s' unloaded successfully", code.c_str());
        mStats.algorithmUnloadSuccess++;
        mStats.lastUpdateTimestamp = getCurTimestamp();
        return true;
    }

		    Algorithm* Scheduler::getAlgorithm(const std::string& code) {
		        std::scoped_lock lock(mAlgorithmMtx);

		        if (auto it = mAlgorithmMap.find(code); it != mAlgorithmMap.end()) {
		            return it->second.algorithm.get();
		        }

		        return nullptr;
		    }

	    Algorithm* Scheduler::acquireAlgorithm(const std::string& code) {
	        std::scoped_lock lock(mAlgorithmMtx);

        auto it = mAlgorithmMap.find(code);
        if (it == mAlgorithmMap.end()) {
            return nullptr;
        }
	        if (!it->second.algorithm) {
	            return nullptr;
	        }

	        if (const int prev = it->second.refCount.fetch_add(1); prev <= 0) {
	            it->second.lastUnusedTimestampMs = 0;
	        }
		        return it->second.algorithm.get();
		    }

    void Scheduler::releaseAlgorithm(const std::string& code) {
        std::scoped_lock lock(mAlgorithmMtx);

        auto it = mAlgorithmMap.find(code);
        if (it == mAlgorithmMap.end()) {
            return;
        }
	        int cur = it->second.refCount.load();
	        while (cur > 0) {
	            if (it->second.refCount.compare_exchange_weak(cur, cur - 1)) {
	                if (const int after = cur - 1; after <= 0 && it->second.controlCodes.empty()) {
	                    it->second.lastUnusedTimestampMs = (int64_t)getCurTimestamp();
	                }
	                break;
	            }
	        }
	    }

    std::vector<std::string> Scheduler::listAlgorithms() {
        std::scoped_lock lock(mAlgorithmMtx);

        std::vector<std::string> result;

        // 已加载的算法
        for (const auto& pair : mAlgorithmMap) {
            result.push_back(pair.first);
        }

        return result;
    }

    bool Scheduler::getAlgorithmDeviceDecision(
        std::string_view code,
        InferenceDeviceDecision& decision) {
        std::scoped_lock lock(mAlgorithmMtx);
        const auto it = mAlgorithmMap.find(code);
        if (it == mAlgorithmMap.end()) {
            return false;
        }
        decision.requestedDevice = it->second.requestedDevice;
        decision.effectiveDevice = it->second.effectiveDevice;
        decision.degraded = it->second.deviceDegraded;
        decision.reason = it->second.deviceDegradeReason;
        return true;
    }

    bool Scheduler::ensureAlgorithmLoaded(const std::string& code, std::string& errMsg) {
        int defaultConcurrency = 1;
        if (mConfig) {
            defaultConcurrency = std::max(1, mConfig->modelConcurrency);
        }
        return ensureAlgorithmLoaded(code, defaultConcurrency, errMsg);
    }

    bool Scheduler::ensureAlgorithmLoaded(const std::string& code, int concurrency, std::string& errMsg) {
        return ensureAlgorithmLoaded(code, concurrency, false, errMsg);
    }

    bool Scheduler::ensureAlgorithmLoaded(
        const std::string& code,
        int concurrency,
        bool forceInferenceDevice,
        std::string& errMsg) {
        {
            std::scoped_lock lock(mAlgorithmMtx);
            auto it = mAlgorithmMap.find(code);
            if (it != mAlgorithmMap.end()) {
                const InferenceDeviceDecision decision{
                    it->second.requestedDevice,
                    it->second.effectiveDevice,
                    it->second.deviceDegraded,
                    it->second.deviceDegradeReason,
                };
                return inference_device_decision_allowed(decision, forceInferenceDevice, errMsg);
            }
        }

        // Support per-control instance key: <algorithmCode>__<PRECISION>__<W>x<H>
        std::string algorithmCode = code;
        ModelConfig modelCfg = normalizeModelConfig("FP32", 640, 640);
        (void)parseAlgorithmInstanceKey(code, algorithmCode, modelCfg);

        std::string baseCode;
        std::string device;
        if (!parseAlgorithmDevice(algorithmCode, baseCode, device)) {
            errMsg = "Invalid algorithm device suffix: " + algorithmCode;
            return false;
        }

        // 查找预设映射
        std::string modelPathBase;
        std::vector<std::string> classNames;
        std::string algorithmSubtype = "detection";
        bool matched = false;
        if (const auto* meta = find_builtin_algorithm_meta(baseCode)) {
            modelPathBase = mConfig->modelDir + "/" + meta->relativePath;
            classNames = meta->classNames;
            if (!meta->subtype.empty()) {
                algorithmSubtype = meta->subtype;
            }
            matched = true;
        }

        if (!matched) {
            errMsg = "No preset model mapping for code: " + baseCode;
            return false;
        }

        // Precision is implemented by selecting model file variants when present.
        const std::string modelPath = selectModelPathByPrecision(modelPathBase, modelCfg.precision);

        if (concurrency < 1) {
            concurrency = 1;
        }
        bool ok = loadAlgorithm(
            code, modelPath, classNames, device, algorithmSubtype, errMsg, concurrency,
            forceInferenceDevice);
        if (!ok && errMsg.find("already loaded") != std::string::npos) {
            // 允许并发启动的情况下，另一线程可能已加载成功
            ok = true;
        }

        if (ok) {
            std::scoped_lock lock(mAlgorithmMtx);
            auto it = mAlgorithmMap.find(code);
            if (it != mAlgorithmMap.end()) {
                const InferenceDeviceDecision decision{
                    it->second.requestedDevice,
                    it->second.effectiveDevice,
                    it->second.deviceDegraded,
                    it->second.deviceDegradeReason,
                };
                if (!inference_device_decision_allowed(decision, forceInferenceDevice, errMsg)) {
                    return false;
                }
                it->second.isBuiltin = true;
            }
            else {
                errMsg = "Algorithm '" + code + "' disappeared after loading";
                return false;
            }
        }

        return ok;
    }

    // ============== 模型复用管理实现 ==============

	    void Scheduler::bindControlToAlgorithm(const std::string& algorithmCode, const std::string& controlCode) {
	        std::scoped_lock lock(mAlgorithmMtx);

	        auto it = mAlgorithmMap.find(algorithmCode);
	        if (it != mAlgorithmMap.end()) {
	            if (it->second.controlCodes.insert(controlCode).second) {
	                if (const int prev = it->second.refCount.fetch_add(1); prev <= 0) {
	                    it->second.lastUnusedTimestampMs = 0;
	                }
	            }
	            LOGI("Control '%s' bound to algorithm '%s', refCount=%d",
	                 controlCode.c_str(), algorithmCode.c_str(), it->second.refCount.load());
	        }
	    }

	    void Scheduler::unbindControlFromAlgorithm(const std::string& algorithmCode, const std::string& controlCode) {
	        std::scoped_lock lock(mAlgorithmMtx);

	        auto it = mAlgorithmMap.find(algorithmCode);
	        if (it != mAlgorithmMap.end()) {
	            if (it->second.controlCodes.erase(controlCode) > 0 && it->second.refCount.load() > 0) {
	                if (const int after = it->second.refCount.fetch_sub(1) - 1; after <= 0) {
	                    it->second.lastUnusedTimestampMs = (int64_t)getCurTimestamp();
	                }
	            }
	            LOGI("Control '%s' unbound from algorithm '%s', refCount=%d",
	                 controlCode.c_str(), algorithmCode.c_str(), it->second.refCount.load());
	        }
	    }

	    void Scheduler::tryAutoUnloadAlgorithm(const std::string& algorithmCode) {
	        std::scoped_lock lock(mAlgorithmMtx);

        auto it = mAlgorithmMap.find(algorithmCode);
        if (it != mAlgorithmMap.end() && it->second.refCount <= 0 && it->second.controlCodes.empty()) {
            // 引用计数为0时自动删除（按 TTL 延迟可配置）
            int ttlSeconds = 0;
            if (mConfig) {
                ttlSeconds = std::max(0, mConfig->modelCacheSeconds);
            }
            if (ttlSeconds > 0) {
                const auto nowMs = static_cast<int64_t>(getCurTimestamp());
                if (it->second.lastUnusedTimestampMs <= 0) {
                    it->second.lastUnusedTimestampMs = nowMs;
                    return;
                }
                int64_t ttlMs = (int64_t)ttlSeconds * 1000;
                if ((nowMs - it->second.lastUnusedTimestampMs) < ttlMs) {
                    return;
                }
            }

                LOGI("Auto-unloading unused algorithm '%s'", algorithmCode.c_str());

                it->second.algorithm.reset();
                if (!it->second.decryptedDir.empty()) {
                    try {
                        std::filesystem::remove_all(it->second.decryptedDir);
                    }
                    catch (const std::filesystem::filesystem_error&) {}
                }
                mAlgorithmMap.erase(it);
                mStats.algorithmUnloadSuccess++;
                mStats.lastUpdateTimestamp = getCurTimestamp();
        }
    }

    // ============== 资源自动调节实现 ==============

    void Scheduler::updateResourceInfo() {
        std::scoped_lock updateLock(mResourceUpdateMtx);

        double cpuUsage = 0.0;
        double memoryUsage = 0.0;
        const int64_t nowTs = getCurTimestamp();

#ifdef _WIN32
        // Windows 平台获取 CPU 和内存使用率
        MEMORYSTATUSEX memInfo;
        memInfo.dwLength = sizeof(MEMORYSTATUSEX);
        GlobalMemoryStatusEx(&memInfo);
        memoryUsage = memInfo.dwMemoryLoad;

        // 简化的 CPU 使用率计算
        static FILETIME prevIdleTime, prevKernelTime, prevUserTime;
        FILETIME idleTime, kernelTime, userTime;
        GetSystemTimes(&idleTime, &kernelTime, &userTime);

        ULONGLONG idle = (((ULONGLONG)idleTime.dwHighDateTime) << 32) | idleTime.dwLowDateTime;
        ULONGLONG kernel = (((ULONGLONG)kernelTime.dwHighDateTime) << 32) | kernelTime.dwLowDateTime;
        ULONGLONG user = (((ULONGLONG)userTime.dwHighDateTime) << 32) | userTime.dwLowDateTime;

        ULONGLONG prevIdle = (((ULONGLONG)prevIdleTime.dwHighDateTime) << 32) | prevIdleTime.dwLowDateTime;
        ULONGLONG prevKernel = (((ULONGLONG)prevKernelTime.dwHighDateTime) << 32) | prevKernelTime.dwLowDateTime;
        ULONGLONG prevUser = (((ULONGLONG)prevUserTime.dwHighDateTime) << 32) | prevUserTime.dwLowDateTime;

        ULONGLONG idleDiff = idle - prevIdle;
        ULONGLONG totalDiff = (kernel - prevKernel) + (user - prevUser);

        if (totalDiff > 0) {
            cpuUsage = 100.0 * (1.0 - (double)idleDiff / totalDiff);
        }

        prevIdleTime = idleTime;
        prevKernelTime = kernelTime;
        prevUserTime = userTime;
#elif defined(__linux__)
	        // Linux 平台：优先使用 /proc/meminfo 的 MemAvailable，避免 page cache 造成误判；
	        // 回退时至少把 bufferram 计入可用内存。
	        std::uint64_t memTotalBytes = 0;
	        std::uint64_t memAvailableBytes = 0;
	        if (readLinuxMemInfoAvailableBytes(memTotalBytes, memAvailableBytes)) {
	            memoryUsage = computeLinuxMemoryUsagePercent(memTotalBytes, memAvailableBytes);
	        }
	        else if (struct sysinfo si; sysinfo(&si) == 0 && si.totalram > 0) {
	            const std::uint64_t memUnit = si.mem_unit > 0 ? static_cast<std::uint64_t>(si.mem_unit) : 1ULL;
	            const std::uint64_t totalBytes = static_cast<std::uint64_t>(si.totalram) * memUnit;
	            const std::uint64_t freeBytes = static_cast<std::uint64_t>(si.freeram) * memUnit;
	            const std::uint64_t bufferBytes = static_cast<std::uint64_t>(si.bufferram) * memUnit;
	            const std::uint64_t availableBytes =
	                (freeBytes > totalBytes || bufferBytes > totalBytes - freeBytes)
	                    ? totalBytes
	                    : (freeBytes + bufferBytes);
	            memoryUsage = computeLinuxMemoryUsagePercent(totalBytes, availableBytes);
	        }

	        static CpuTimes prevCpuTimes;
	        if (CpuTimes curCpuTimes; readProcStatCpuTimes(curCpuTimes)) {
	            if (prevCpuTimes.total > 0) {
	                cpuUsage = computeCpuUsagePercent(prevCpuTimes, curCpuTimes);
	            }
	            prevCpuTimes = curCpuTimes;
	        }
#else
        // Other platforms: keep best-effort defaults (0.0). Industrial deployments are typically Windows/Linux.
#endif

        // ========== pressure snapshot (queues + drops) ==========
        int currentControls = 0;
        int maxPullPktQueueSize = 0;
        int maxPushFrameQueueSize = 0;
        int pullPktQueueHighWorkers = 0;
        int pullPktQueueSevereWorkers = 0;
        int pushFrameQueueHighWorkers = 0;
        int pushFrameQueueSevereWorkers = 0;

        const int pullCap = AvPullStream::MAX_VIDEO_PKT_QUEUE_SIZE;
        const int pushCap = AvPushStream::MAX_VIDEO_FRAME_QUEUE_SIZE;
        const int pullHigh = std::max(1, pullCap * 3 / 4);
        const int pullSevere = std::max(1, pullCap * 9 / 10);
        const int pushHigh = std::max(1, pushCap * 3 / 4);
        const int pushSevere = std::max(1, pushCap * 9 / 10);

        {
            std::scoped_lock lock(mWorkerMapMtx);
            currentControls = static_cast<int>(mWorkerMap.size());
            for (const auto& kv : mWorkerMap) {
                Worker* worker = kv.second;
                if (!worker) {
                    continue;
                }

                int q = worker->getSourceInputQueueSize();
                maxPullPktQueueSize = std::max(maxPullPktQueueSize, q);
                if (q >= pullHigh) {
                    pullPktQueueHighWorkers++;
                }
                if (q >= pullSevere) {
                    pullPktQueueSevereWorkers++;
                }

                if (worker->mPushStream) {
                    int pushQueueSize = worker->mPushStream->getVideoFrameQSize();
                    maxPushFrameQueueSize = std::max(maxPushFrameQueueSize, pushQueueSize);
                    if (pushQueueSize >= pushHigh) {
                        pushFrameQueueHighWorkers++;
                    }
                    if (pushQueueSize >= pushSevere) {
                        pushFrameQueueSevereWorkers++;
                    }
                }
            }
        }

        uint64_t droppedPullPacketsDelta = 0;
        uint64_t droppedDecodePacketsDelta = 0;
        uint64_t droppedPushFramesDelta = 0;
        uint64_t droppedAlarmFramesDelta = 0;
        int64_t dropWindowMs = 0;
        double droppedPullPacketsPerSecond = 0.0;
        double droppedDecodePacketsPerSecond = 0.0;
        double droppedPushFramesPerSecond = 0.0;
        double droppedAlarmFramesPerSecond = 0.0;

        const uint64_t droppedPullPacketsTotal = mStats.droppedPullPackets.load();
        const uint64_t droppedDecodePacketsTotal = mStats.droppedDecodePackets.load();
        const uint64_t droppedPushFramesTotal = mStats.droppedPushFrames.load();
        const uint64_t droppedAlarmFramesTotal = mStats.droppedAlarmFrames.load();

        if (mLastDropCalcTimestamp > 0 && nowTs > mLastDropCalcTimestamp) {
            dropWindowMs = nowTs - mLastDropCalcTimestamp;

            if (droppedPullPacketsTotal >= mLastDroppedPullPackets) {
                droppedPullPacketsDelta = droppedPullPacketsTotal - mLastDroppedPullPackets;
            }
            if (droppedDecodePacketsTotal >= mLastDroppedDecodePackets) {
                droppedDecodePacketsDelta = droppedDecodePacketsTotal - mLastDroppedDecodePackets;
            }
            if (droppedPushFramesTotal >= mLastDroppedPushFrames) {
                droppedPushFramesDelta = droppedPushFramesTotal - mLastDroppedPushFrames;
            }
            if (droppedAlarmFramesTotal >= mLastDroppedAlarmFrames) {
                droppedAlarmFramesDelta = droppedAlarmFramesTotal - mLastDroppedAlarmFrames;
            }

            if (dropWindowMs > 0) {
                const double scale = 1000.0 / static_cast<double>(dropWindowMs);
                droppedPullPacketsPerSecond = static_cast<double>(droppedPullPacketsDelta) * scale;
                droppedDecodePacketsPerSecond = static_cast<double>(droppedDecodePacketsDelta) * scale;
                droppedPushFramesPerSecond = static_cast<double>(droppedPushFramesDelta) * scale;
                droppedAlarmFramesPerSecond = static_cast<double>(droppedAlarmFramesDelta) * scale;
            }
        }

        mLastDropCalcTimestamp = nowTs;
        mLastDroppedPullPackets = droppedPullPacketsTotal;
        mLastDroppedDecodePackets = droppedDecodePacketsTotal;
        mLastDroppedPushFrames = droppedPushFramesTotal;
        mLastDroppedAlarmFrames = droppedAlarmFramesTotal;
        // ===========================================================

        std::scoped_lock lock(mResourceMtx);
        mResourceInfo.cpuUsage = cpuUsage;
        mResourceInfo.memoryUsage = memoryUsage;

        mResourceInfo.currentControls = currentControls;
        mResourceInfo.lastCheckTime = nowTs;

        mResourceInfo.maxPullPktQueueSize = maxPullPktQueueSize;
        mResourceInfo.maxPushFrameQueueSize = maxPushFrameQueueSize;
        mResourceInfo.pullPktQueueHighWorkers = pullPktQueueHighWorkers;
        mResourceInfo.pullPktQueueSevereWorkers = pullPktQueueSevereWorkers;
        mResourceInfo.pushFrameQueueHighWorkers = pushFrameQueueHighWorkers;
        mResourceInfo.pushFrameQueueSevereWorkers = pushFrameQueueSevereWorkers;

        mResourceInfo.droppedPullPacketsDelta = droppedPullPacketsDelta;
        mResourceInfo.droppedDecodePacketsDelta = droppedDecodePacketsDelta;
        mResourceInfo.droppedPushFramesDelta = droppedPushFramesDelta;
        mResourceInfo.droppedAlarmFramesDelta = droppedAlarmFramesDelta;
        mResourceInfo.dropWindowMs = dropWindowMs;
        mResourceInfo.droppedPullPacketsPerSecond = droppedPullPacketsPerSecond;
        mResourceInfo.droppedDecodePacketsPerSecond = droppedDecodePacketsPerSecond;
        mResourceInfo.droppedPushFramesPerSecond = droppedPushFramesPerSecond;
        mResourceInfo.droppedAlarmFramesPerSecond = droppedAlarmFramesPerSecond;

        // ========== dynamic pending admission ==========
        int basePendingUpper = mMaxPendingControls.load();
        if (mConfig) {
            basePendingUpper = std::max(1, mConfig->maxPendingControls);
        }
        int nextPendingUpper = basePendingUpper;
        if (mResourceInfo.cpuUsage > 95 || mResourceInfo.memoryUsage > 95 ||
            droppedPushFramesPerSecond > 20.0 || droppedDecodePacketsPerSecond > 20.0) {
            nextPendingUpper = 1;
        }
        if (nextPendingUpper < 1) {
            nextPendingUpper = 1;
        }
        mMaxPendingControls.store(nextPendingUpper);
        mResourceInfo.maxPendingControls = nextPendingUpper;
        // =============================================

        // ========== auto tune maxControls (admission-only) ==========
        {
            int upperBound = mResourceInfo.maxControlsUpperBound;
            if (upperBound < 1) {
                upperBound = 1;
                mResourceInfo.maxControlsUpperBound = 1;
            }
            if (mResourceInfo.currentControls > upperBound) {
                upperBound = mResourceInfo.currentControls;
                mResourceInfo.maxControlsUpperBound = upperBound;
            }

            int prev = mResourceInfo.maxControls;
            int next = prev;
            if (next < 1) {
                next = 1;
            }
            if (next > upperBound) {
                next = upperBound;
            }

            const bool resourceHigh = (mResourceInfo.cpuUsage > 90 || mResourceInfo.memoryUsage > 90);
	            if (const bool backpressureHigh =
	                    (mResourceInfo.pushFrameQueueSevereWorkers >= std::max(1, mResourceInfo.currentControls / 5)) ||
	                    (mResourceInfo.pullPktQueueSevereWorkers >= std::max(1, mResourceInfo.currentControls / 5)) ||
	                    (mResourceInfo.droppedPushFramesPerSecond > 20.0) ||
	                    (mResourceInfo.droppedDecodePacketsPerSecond > 20.0) ||
	                    (mResourceInfo.droppedPullPacketsPerSecond > 20.0);
	                resourceHigh || backpressureHigh) {
	                // 资源紧张/数据阻塞：减少“新增布控允许的上限”到当前布控数（只影响新增，不强制停止现有布控）
	                int target = mResourceInfo.currentControls;
	                if (target < 1) {
	                    target = 1;
	                }
                if (next > target) {
                    next = target;
                }
            }
            else if (mResourceInfo.cpuUsage < 70 && mResourceInfo.memoryUsage < 70 &&
                     mResourceInfo.droppedPushFramesPerSecond < 1.0 && mResourceInfo.droppedDecodePacketsPerSecond < 1.0 &&
                     next < upperBound) {
                // 资源充足：缓慢恢复到 upperBound（每次+1），避免频繁抖动
                next++;
            }

            if (next < 1) {
                next = 1;
            }
            if (next > upperBound) {
                next = upperBound;
            }

            // Never report an admission max lower than current running controls.
            next = std::max(next, mResourceInfo.currentControls);

            if (next != prev && next < prev) {
                LOGW("Admission tighten: CPU %.1f%% Mem %.1f%%, backpressure(severe push=%d, severe pull=%d, dropPush=%.1f/s, dropDec=%.1f/s) => maxControls %d -> %d (upperBound=%d)",
                     mResourceInfo.cpuUsage, mResourceInfo.memoryUsage,
                     mResourceInfo.pushFrameQueueSevereWorkers, mResourceInfo.pullPktQueueSevereWorkers,
                     mResourceInfo.droppedPushFramesPerSecond, mResourceInfo.droppedDecodePacketsPerSecond,
                     prev, next, upperBound);
            }
            mResourceInfo.maxControls = next;
        }
        // ===========================================================

        int desiredStride = 1;
        if (mResourceInfo.cpuUsage > 95 || mResourceInfo.memoryUsage > 95) {
            desiredStride = 5;
        }
        else if (mResourceInfo.cpuUsage > 90 || mResourceInfo.memoryUsage > 90) {
            desiredStride = 4;
        }
        else if (mResourceInfo.cpuUsage > 80 || mResourceInfo.memoryUsage > 80) {
            desiredStride = 3;
        }
        else if (mResourceInfo.cpuUsage > 70 || mResourceInfo.memoryUsage > 70) {
            desiredStride = 2;
        }

        if (mResourceInfo.currentControls > 40) {
            desiredStride = std::max(desiredStride, 5);
        }
        else if (mResourceInfo.currentControls > 32) {
            desiredStride = std::max(desiredStride, 4);
        }
        else if (mResourceInfo.currentControls > 24) {
            desiredStride = std::max(desiredStride, 3);
        }
        else if (mResourceInfo.currentControls > 12) {
            desiredStride = std::max(desiredStride, 2);
        }

        // backpressure-based tuning
        if (mResourceInfo.pushFrameQueueSevereWorkers >= std::max(1, mResourceInfo.currentControls / 5) ||
            mResourceInfo.pullPktQueueSevereWorkers >= std::max(1, mResourceInfo.currentControls / 5) ||
            mResourceInfo.droppedPushFramesPerSecond > 20.0 || mResourceInfo.droppedDecodePacketsPerSecond > 20.0) {
            desiredStride = std::max(desiredStride, 5);
        }
        else if (mResourceInfo.pushFrameQueueHighWorkers >= std::max(1, mResourceInfo.currentControls / 3) ||
                 mResourceInfo.pullPktQueueHighWorkers >= std::max(1, mResourceInfo.currentControls / 3) ||
                 mResourceInfo.droppedPushFramesPerSecond > 5.0 || mResourceInfo.droppedDecodePacketsPerSecond > 5.0) {
            desiredStride = std::max(desiredStride, 3);
        }

        if (desiredStride < 1) {
            desiredStride = 1;
        }

        // Hysteresis to avoid stride oscillation around threshold boundaries.
        const int tunedStride = mDetectStrideHysteresis.update(desiredStride, getCurTime());
        mResourceInfo.detectStride = tunedStride;
        mDetectStride.store(tunedStride);
    }

    bool Scheduler::canAddControl(std::string& errMsg) {
        const int64_t nowTs = getCurTimestamp();

        // Refresh snapshot with throttling: updateResourceInfo() is relatively heavy (scans workers).
        bool needUpdate = false;
        {
            std::scoped_lock lock(mResourceMtx);
            if (mResourceInfo.lastCheckTime <= 0 || (nowTs - mResourceInfo.lastCheckTime) > 1000) {
                needUpdate = true;
            }
        }
        if (needUpdate) {
            updateResourceInfo();
        }

        std::scoped_lock lock(mResourceMtx);

        const int controls = mResourceInfo.currentControls;
        const int pending = mPendingControls.load();
        const int projected = controls + pending;

        const bool cpuCritical = mResourceInfo.cpuUsage > 95;
        const bool memCritical = mResourceInfo.memoryUsage > 95;

        const bool severeBackpressure =
            (mResourceInfo.pushFrameQueueSevereWorkers >= std::max(1, controls / 5)) ||
            (mResourceInfo.pullPktQueueSevereWorkers >= std::max(1, controls / 5)) ||
            (mResourceInfo.droppedPushFramesPerSecond > 20.0) ||
            (mResourceInfo.droppedDecodePacketsPerSecond > 20.0) ||
            (mResourceInfo.droppedPullPacketsPerSecond > 20.0);

        if (projected >= mResourceInfo.maxControls) {
            errMsg = "Maximum control limit reached (" + std::to_string(mResourceInfo.maxControls) +
                     "). Current=" + std::to_string(controls) +
                     ", Pending=" + std::to_string(pending) +
                     ", CPU=" + std::to_string((int)mResourceInfo.cpuUsage) +
                     "%, Mem=" + std::to_string((int)mResourceInfo.memoryUsage) +
                     "%, PushQmax=" + std::to_string(mResourceInfo.maxPushFrameQueueSize) +
                     ", PullQmax=" + std::to_string(mResourceInfo.maxPullPktQueueSize) +
                     ", DropPush=" + std::to_string((int)mResourceInfo.droppedPushFramesPerSecond) + "/s" +
                     ", DropDec=" + std::to_string((int)mResourceInfo.droppedDecodePacketsPerSecond) + "/s" +
                     (severeBackpressure ? " (backpressure_high)" : "");
            return false;
        }

        if (cpuCritical) {
            errMsg = "CPU usage too high (" + std::to_string((int)mResourceInfo.cpuUsage) + "%)";
            return false;
        }

        if (memCritical) {
            errMsg = "Memory usage too high (" + std::to_string((int)mResourceInfo.memoryUsage) + "%)";
            return false;
        }

        if (severeBackpressure) {
            errMsg = "System backpressure too high, reject new control. "
                     "PushQmax=" + std::to_string(mResourceInfo.maxPushFrameQueueSize) +
                     ", PullQmax=" + std::to_string(mResourceInfo.maxPullPktQueueSize) +
                     ", SeverePushWorkers=" + std::to_string(mResourceInfo.pushFrameQueueSevereWorkers) +
                     ", SeverePullWorkers=" + std::to_string(mResourceInfo.pullPktQueueSevereWorkers) +
                     ", DropPush=" + std::to_string((int)mResourceInfo.droppedPushFramesPerSecond) + "/s" +
                     ", DropDec=" + std::to_string((int)mResourceInfo.droppedDecodePacketsPerSecond) + "/s";
            return false;
        }

        return true;
    }

    bool Scheduler::reserveControlSlot(std::string& errMsg) {
        std::scoped_lock admissionLock(mAdmissionMtx);
        int pendingUpper = mMaxPendingControls.load();
	        if (pendingUpper < 1) {
	            pendingUpper = 1;
	            mMaxPendingControls.store(1);
	        }
	        if (const int pending = mPendingControls.load(); pending >= pendingUpper) {
	            errMsg = "Too many pending control starts (" + std::to_string(pending) + "/" + std::to_string(pendingUpper) + "), please retry";
	            return false;
	        }
        if (!canAddControl(errMsg)) {
            return false;
        }
        mPendingControls++;
        return true;
    }

    void Scheduler::releaseControlSlot() {
        std::scoped_lock admissionLock(mAdmissionMtx);
        int pending = mPendingControls.load();
        if (pending > 0) {
            mPendingControls--;
        }
    }

    ResourceInfo Scheduler::getResourceInfo() {
        std::scoped_lock lock(mResourceMtx);
        mResourceInfo.currentDecodeChannels = mCurrentDecodeChannels.load();
        mResourceInfo.currentEncodeChannels = mCurrentEncodeChannels.load();
        mResourceInfo.maxPendingControls = mMaxPendingControls.load();
        return mResourceInfo;
    }

    void Scheduler::setMaxControls(int maxControls) {
        std::scoped_lock lock(mResourceMtx);
        if (maxControls < 1) {
            maxControls = 1;
        }
        mResourceInfo.maxControlsUpperBound = maxControls;
        mResourceInfo.maxControls = maxControls;
        LOGI("MaxControls upperBound set to %d", maxControls);
    }

    int Scheduler::getDetectStride() {
        int stride = mDetectStride.load();
        if (stride < 1) {
            stride = 1;
        }
        return stride;
    }

    bool Scheduler::reserveDecodeChannel(std::string& errMsg) {
        std::scoped_lock lock(mDecodeChannelMtx);
        int maxChannels = mConfig->maxHardwareDecodeChannels;
        if (maxChannels > 0) {
            int current = mCurrentDecodeChannels.load();
            if (current >= maxChannels) {
                errMsg = "Hardware decode channels exhausted: " + std::to_string(current) + "/" + std::to_string(maxChannels);
                return false;
            }
        }
        mCurrentDecodeChannels++;
        int current = mCurrentDecodeChannels.load();
        LOGI("Reserved decode channel: %d/%d", current, maxChannels);
        return true;
    }

    void Scheduler::releaseDecodeChannel() {
        std::scoped_lock lock(mDecodeChannelMtx);
        int current = mCurrentDecodeChannels.load();
        if (current > 0) {
            mCurrentDecodeChannels--;
            current = mCurrentDecodeChannels.load();
            LOGI("Released decode channel: %d", current);
        }
    }

    bool Scheduler::reserveEncodeChannel(std::string& errMsg) {
        std::scoped_lock lock(mEncodeChannelMtx);
        int maxChannels = mConfig->maxHardwareEncodeChannels;
        if (maxChannels > 0) {
            int current = mCurrentEncodeChannels.load();
            if (current >= maxChannels) {
                errMsg = "Hardware encode channels exhausted: " + std::to_string(current) + "/" + std::to_string(maxChannels);
                return false;
            }
        }
        mCurrentEncodeChannels++;
        int current = mCurrentEncodeChannels.load();
        LOGI("Reserved encode channel: %d/%d", current, maxChannels);
        return true;
    }

    void Scheduler::releaseEncodeChannel() {
        std::scoped_lock lock(mEncodeChannelMtx);
        int current = mCurrentEncodeChannels.load();
        if (current > 0) {
            mCurrentEncodeChannels--;
            current = mCurrentEncodeChannels.load();
            LOGI("Released encode channel: %d", current);
        }
    }

    SchedulerStatsSnapshot Scheduler::getSchedulerStatsSnapshot() {
        SchedulerStatsSnapshot snapshot;
        snapshot.controlAddRequests = mStats.controlAddRequests.load();
        snapshot.controlAddSuccess = mStats.controlAddSuccess.load();
        snapshot.controlAddFailure = mStats.controlAddFailure.load();
        snapshot.controlCancelRequests = mStats.controlCancelRequests.load();
        snapshot.controlCancelSuccess = mStats.controlCancelSuccess.load();
        snapshot.controlCancelFailure = mStats.controlCancelFailure.load();
        snapshot.controlAddTotalMs = mStats.controlAddTotalMs.load();
        snapshot.controlAddMaxMs = mStats.controlAddMaxMs.load();
        snapshot.controlAddLastMs = mStats.controlAddLastMs.load();
        snapshot.controlCancelTotalMs = mStats.controlCancelTotalMs.load();
        snapshot.controlCancelMaxMs = mStats.controlCancelMaxMs.load();
        snapshot.controlCancelLastMs = mStats.controlCancelLastMs.load();
        snapshot.workerDeleteQueued = mStats.workerDeleteQueued.load();
        snapshot.workerDeleteProcessed = mStats.workerDeleteProcessed.load();
        snapshot.alarmQueued = mStats.alarmQueued.load();
        snapshot.alarmDropped = mStats.alarmDropped.load();
        snapshot.alarmProcessed = mStats.alarmProcessed.load();
        snapshot.algorithmLoadSuccess = mStats.algorithmLoadSuccess.load();
        snapshot.algorithmLoadFailure = mStats.algorithmLoadFailure.load();
        snapshot.algorithmUnloadSuccess = mStats.algorithmUnloadSuccess.load();
        snapshot.algorithmUnloadFailure = mStats.algorithmUnloadFailure.load();
        snapshot.pullReadErrors = mStats.pullReadErrors.load();
        snapshot.pullReconnectAttempts = mStats.pullReconnectAttempts.load();
        snapshot.pullReconnectSuccess = mStats.pullReconnectSuccess.load();
        snapshot.pushWriteErrors = mStats.pushWriteErrors.load();
        snapshot.pushReconnectAttempts = mStats.pushReconnectAttempts.load();
        snapshot.pushReconnectSuccess = mStats.pushReconnectSuccess.load();
        snapshot.droppedPullPackets = mStats.droppedPullPackets.load();
        snapshot.droppedDecodePackets = mStats.droppedDecodePackets.load();
        snapshot.droppedPushFrames = mStats.droppedPushFrames.load();
        snapshot.droppedAlarmFrames = mStats.droppedAlarmFrames.load();
        snapshot.alarmNotifyQueued = mStats.alarmNotifyQueued.load();
        snapshot.alarmNotifySent = mStats.alarmNotifySent.load();
        snapshot.alarmNotifyFailed = mStats.alarmNotifyFailed.load();
        snapshot.alarmNotifyRetried = mStats.alarmNotifyRetried.load();

        snapshot.apiInferAllowed = mStats.apiInferAllowed.load();
        snapshot.apiInferSkippedMinInterval = mStats.apiInferSkippedMinInterval.load();
        snapshot.apiInferSkippedCircuitOpen = mStats.apiInferSkippedCircuitOpen.load();
        snapshot.apiInferSuccess = mStats.apiInferSuccess.load();
        snapshot.apiInferFailure = mStats.apiInferFailure.load();
        snapshot.apiInferRetried = mStats.apiInferRetried.load();
        snapshot.apiInferCircuitOpened = mStats.apiInferCircuitOpened.load();
        snapshot.apiInferLatencyTotalMs = mStats.apiInferLatencyTotalMs.load();
        snapshot.apiInferLatencyMaxMs = mStats.apiInferLatencyMaxMs.load();
        snapshot.apiInferLatencyLastMs = mStats.apiInferLatencyLastMs.load();

        snapshot.lastUpdateTimestamp = mStats.lastUpdateTimestamp.load();
        snapshot.detectStride = getDetectStride();
        snapshot.currentControls = getWorkerSize();
        {
            std::scoped_lock lock(mTobeDeletedWorkerQ_mtx);
            snapshot.deleteQueueSize = mTobeDeletedWorkerQ.size();
        }
        {
            std::scoped_lock lock(mAlarmQ_mtx);
            snapshot.alarmQueueSize = mAlarmQ.size();
        }
        return snapshot;
    }

    void Scheduler::statsIncPullReadErrors(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.pullReadErrors.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncPullReconnectAttempts(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.pullReconnectAttempts.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncPullReconnectSuccess(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.pullReconnectSuccess.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncPushWriteErrors(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.pushWriteErrors.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncPushReconnectAttempts(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.pushReconnectAttempts.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncPushReconnectSuccess(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.pushReconnectSuccess.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncDroppedPullPackets(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.droppedPullPackets.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncDroppedDecodePackets(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.droppedDecodePackets.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncDroppedPushFrames(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.droppedPushFrames.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncDroppedAlarmFrames(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.droppedAlarmFrames.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferAllowed(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferAllowed.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferSkippedMinInterval(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferSkippedMinInterval.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferSkippedCircuitOpen(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferSkippedCircuitOpen.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferSuccess(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferSuccess.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferFailure(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferFailure.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferRetried(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferRetried.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsIncApiInferCircuitOpened(uint64_t count) {
        if (count == 0) {
            return;
        }
        mStats.apiInferCircuitOpened.fetch_add(count);
        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::statsObserveApiInferLatencyMs(uint64_t latencyMs) {
        mStats.apiInferLatencyTotalMs.fetch_add(latencyMs);
        mStats.apiInferLatencyLastMs.store(latencyMs);

        uint64_t prevMax = mStats.apiInferLatencyMaxMs.load();
        while (latencyMs > prevMax && !mStats.apiInferLatencyMaxMs.compare_exchange_weak(prevMax, latencyMs)) {}

        mStats.lastUpdateTimestamp = getCurTimestamp();
    }

    void Scheduler::enqueueAlarmNotify(std::string_view url, std::string_view data, std::string_view token) {
        if (url.empty()) {
            return;
        }
        AlarmNotifyTask task;
        task.url.assign(url.data(), url.size());
        task.data.assign(data.data(), data.size());
        task.token.assign(token.data(), token.size());
        task.attempt = 0;
        task.nextAttemptMs = getCurTime();
        {
            std::scoped_lock lock(mAlarmNotifyMtx);
            mAlarmNotifyQ.push_back(std::move(task));
        }
        mStats.alarmNotifyQueued.fetch_add(1);
        mStats.lastUpdateTimestamp = getCurTimestamp();
        mAlarmNotifyCv.notify_one();
    }

    void Scheduler::alarmNotifyThread(Scheduler* arg) {
        auto* scheduler = arg;
        if (scheduler) {
            scheduler->handleAlarmNotify();
        }
    }

    void Scheduler::handleAlarmNotify() {
        Request request;

        while (mState.load()) {
            AlarmNotifyTask task;
            bool hasTask = false;
            int64_t sleepMs = 0;

            {
                std::unique_lock lock(mAlarmNotifyMtx);
                if (mAlarmNotifyQ.empty()) {
                    mAlarmNotifyCv.wait_for(lock, std::chrono::milliseconds(200), [this]() {
                        return !mState.load() || !mAlarmNotifyQ.empty();
                    });
                }
                if (!mState.load()) {
                    return;
                }
                if (mAlarmNotifyQ.empty()) {
                    continue;
                }

                const int64_t now = getCurTime();
                int64_t earliest = 0;
                const size_t n = mAlarmNotifyQ.size();
                for (size_t i = 0; i < n; ++i) {
                    AlarmNotifyTask cand = std::move(mAlarmNotifyQ.front());
                    mAlarmNotifyQ.pop_front();
                    if (!hasTask && cand.nextAttemptMs <= now) {
                        task = std::move(cand);
                        hasTask = true;
                    }
                    else {
                        if (earliest == 0 || cand.nextAttemptMs < earliest) {
                            earliest = cand.nextAttemptMs;
                        }
                        mAlarmNotifyQ.push_back(std::move(cand));
                    }
                }

                if (!hasTask) {
                    sleepMs = 50;
                    if (earliest > 0 && earliest > now) {
                        sleepMs = std::min<int64_t>(200, earliest - now);
                        if (sleepMs < 1) {
                            sleepMs = 1;
                        }
                    }
                }
            }

            if (!mState.load()) {
                return;
            }

            if (!hasTask) {
                if (sleepMs > 0) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(sleepMs));
                }
                continue;
            }

	        // Keep retries infinite; use short timeouts to avoid blocking queue for too long.
	        if (std::string response; request.post(task.url.c_str(), task.data, response, task.token, 2, 3)) {
	            mStats.alarmNotifySent.fetch_add(1);
	            mStats.lastUpdateTimestamp = getCurTimestamp();
	            continue;
	        }

            mStats.alarmNotifyFailed.fetch_add(1);
            task.attempt++;
            int64_t backoff = computeAlarmNotifyBackoffMs(task.attempt);
            task.nextAttemptMs = getCurTime() + backoff;

            {
                std::scoped_lock lock(mAlarmNotifyMtx);
                mAlarmNotifyQ.push_back(std::move(task));
            }
            mStats.alarmNotifyRetried.fetch_add(1);
            mStats.lastUpdateTimestamp = getCurTimestamp();
        }
    }

    void Scheduler::resourceMonitorThread(Scheduler* arg) {
        auto* scheduler = arg;
        scheduler->handleResourceMonitor();
    }

    void Scheduler::handleResourceMonitor() {
        while (mState.load()) {
            updateResourceInfo();
            cleanupExpiredAlgorithms();
            handleLicenseLeaseRenew();
            std::this_thread::sleep_for(std::chrono::seconds(5));  // 每5秒更新一次
        }
    }

	    void Scheduler::cleanupExpiredAlgorithms() {
        int ttlSeconds = 0;
        if (mConfig) {
            ttlSeconds = std::max(0, mConfig->modelCacheSeconds);
        }
        // ttlSeconds == 0 表示不做延迟（仍可能由 tryAutoUnloadAlgorithm 立刻释放），这里无需周期清理
        if (ttlSeconds <= 0) {
            return;
        }

        const auto nowMs = static_cast<int64_t>(getCurTimestamp());
        int64_t ttlMs = (int64_t)ttlSeconds * 1000;

        std::scoped_lock lock(mAlgorithmMtx);

        for (auto it = mAlgorithmMap.begin(); it != mAlgorithmMap.end(); ) {
            AlgorithmInfo& info = it->second;
            if (info.refCount.load() > 0 || !info.controlCodes.empty()) {
                info.lastUnusedTimestampMs = 0;
                ++it;
                continue;
            }

            if (info.lastUnusedTimestampMs <= 0) {
                info.lastUnusedTimestampMs = nowMs;
                ++it;
                continue;
            }

            if ((nowMs - info.lastUnusedTimestampMs) < ttlMs) {
                ++it;
                continue;
            }

	            LOGI("Auto-unloading unused algorithm '%s' by TTL", it->first.c_str());
	            info.algorithm.reset();
	            if (!info.decryptedDir.empty()) {
	                try {
	                    std::filesystem::remove_all(info.decryptedDir);
	                }
                catch (const std::filesystem::filesystem_error&) {}
            }

            it = mAlgorithmMap.erase(it);
            mStats.algorithmUnloadSuccess++;
            mStats.lastUpdateTimestamp = getCurTimestamp();
        }
    }

    std::string Scheduler::getNodeId() {
        if (const char* envNodeId = std::getenv("BEACON_NODE_ID"); envNodeId && *envNodeId) {
            return std::string(envNodeId);
        }
        if (mConfig && !mConfig->code.empty()) {
            return mConfig->code;
        }
        if (const char* envHostname = std::getenv("HOSTNAME"); envHostname && *envHostname) {
            return std::string(envHostname);
        }
        if (const char* envComputerName = std::getenv("COMPUTERNAME"); envComputerName && *envComputerName) {
            return std::string(envComputerName);
        }
        return "node";
    }

    static bool isLicenseManagerEnabled(const AVSAnalyzer::Config* config) {
        if (!config) {
            return false;
        }
        std::string t = config->licenseType;
        std::transform(t.begin(), t.end(), t.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return t == "pool" || t == "manager";
    }

	    static bool postLmJson(
	        const AVSAnalyzer::Config* config,
	        const std::string& path,
	        const Json::Value& body,
        Json::Value& out,
        std::string& errMsg
    ) {
        if (!config) {
            errMsg = "server not ready";
            return false;
        }

        const std::string url = config->adminHost + path;

        Json::StreamWriterBuilder builder;
        builder["indentation"] = "";
        const std::string data = Json::writeString(builder, body);

        Request request;
        std::string response;
        if (!request.post(url.c_str(), data, response, config->openApiToken)) {
            errMsg = "license_manager_unavailable";
            return false;
        }

        Json::CharReaderBuilder rbuilder;
        const std::unique_ptr<Json::CharReader> reader(rbuilder.newCharReader());
        JSONCPP_STRING errs;
        if (!reader->parse(response.data(), response.data() + response.size(), &out, &errs) || !errs.empty()) {
            errMsg = "license_manager_unavailable";
            return false;
        }

        return true;
    }

    bool Scheduler::acquireControlLease(Control* control, std::string& errMsg) {
        if (!isLicenseManagerEnabled(mConfig)) {
            return true;
        }
        if (!control) {
            errMsg = "invalid request parameter";
            return false;
        }

        int ttlSeconds = 120;
        if (mConfig) {
            ttlSeconds = std::max(30, std::min(600, mConfig->licenseLeaseTtlSeconds));
        }

        LicenseLeaseAcquireInput input;
        input.nodeId = getNodeId();
        input.controlCode = control->code;
        input.streamCode = control->streamCode;
        input.algorithmCode = control->algorithmCode;
        input.ttlSeconds = ttlSeconds;
        Json::Value body = buildLicenseLeaseAcquirePayload(input);

        Json::Value resp;
        if (!postLmJson(mConfig, "/open/license/lease/acquire", body, resp, errMsg)) {
            return false;
        }

        const int code = resp.get("code", 0).asInt();
        const std::string msg = resp.get("msg", "error").asString();
        if (code != 1000) {
            errMsg = msg.empty() ? "license_invalid" : msg;
            return false;
        }

        const Json::Value data = resp.get("data", Json::Value(Json::objectValue));
        const std::string leaseId = data.get("lease_id", "").asString();
        if (leaseId.empty()) {
            errMsg = "license_invalid";
            return false;
        }

        control->licenseLeaseId = leaseId;
        control->licenseLastRenewOkTimestamp = getCurTimestamp();
        control->licenseGraceUntilTimestamp = 0;
        const LicenseThreadPriorityHint hint = parseLicenseThreadPriorityHint(
            data.get("thread_priority", Json::Value(Json::objectValue)));
        control->licenseThreadPriorityEnabled = hint.enabled;
        control->licenseThreadPriorityStreamRank = hint.streamRank;
        control->licenseThreadPriorityFirstNActiveStreams = hint.firstNActiveStreams;
        control->licenseThreadPriorityNiceValue = hint.niceValue;
        errMsg = "success";
        return true;
    }

    bool Scheduler::renewLeaseId(
        const std::string& leaseId,
        int ttlSeconds,
        LicenseThreadPriorityHint* outHint,
        std::string& errMsg) {
        if (!isLicenseManagerEnabled(mConfig)) {
            if (outHint) {
                *outHint = LicenseThreadPriorityHint{};
            }
            return true;
        }
        if (!mConfig) {
            errMsg = "server not ready";
            return false;
        }
        if (leaseId.empty()) {
            return true;
        }

        Json::Value body;
        body["lease_id"] = leaseId;
        body["ttl_seconds"] = std::max(30, std::min(600, ttlSeconds));

        Json::Value resp;
        if (!postLmJson(mConfig, "/open/license/lease/renew", body, resp, errMsg)) {
            return false;
        }

        const int code = resp.get("code", 0).asInt();
        const std::string msg = resp.get("msg", "error").asString();
        if (code != 1000) {
            errMsg = msg.empty() ? "lease_renew_failed" : msg;
            return false;
        }
        if (outHint) {
            const Json::Value data = resp.get("data", Json::Value(Json::objectValue));
            *outHint = parseLicenseThreadPriorityHint(data.get("thread_priority", Json::Value(Json::objectValue)));
        }
        errMsg = "success";
        return true;
    }

    void Scheduler::releaseControlLease(const std::string& leaseId) {
        if (!isLicenseManagerEnabled(mConfig)) {
            return;
        }
        if (!mConfig || leaseId.empty()) {
            return;
        }

        Json::Value body;
        body["lease_id"] = leaseId;
        Json::Value resp;
        std::string err;
        postLmJson(mConfig, "/open/license/lease/release", body, resp, err);
    }

    void Scheduler::handleLicenseLeaseRenew() {
        if (!isLicenseManagerEnabled(mConfig)) {
            return;
        }

        int ttlSeconds = 120;
        int graceSeconds = 600;
        if (mConfig) {
            ttlSeconds = clampLicenseLeaseTtlSeconds(mConfig->licenseLeaseTtlSeconds);
            graceSeconds = std::max(0, mConfig->licenseGraceSeconds);
        }

        const int64_t nowTs = getCurTimestamp();
        const int64_t intervalMs = computeLicenseLeaseRenewIntervalMs(ttlSeconds);
        static int64_t lastRenewTs = 0;
        if (lastRenewTs > 0 && (nowTs - lastRenewTs) < intervalMs) {
            return;
        }
        lastRenewTs = nowTs;

        struct Item {
            std::string controlCode;
            std::string streamCode;
            std::string algorithmCode;
            std::string leaseId;
        };
        std::vector<Item> items;
        {
            std::scoped_lock lock(mWorkerMapMtx);
            for (auto& kv : mWorkerMap) {
                Worker* worker = kv.second;
                if (!worker || !worker->mControl) {
                    continue;
                }
                if (worker->mControl->licenseLeaseId.empty()) {
                    continue;
                }
                Item item;
                item.controlCode = worker->mControl->code;
                item.streamCode = worker->mControl->streamCode;
                item.algorithmCode = worker->mControl->algorithmCode;
                item.leaseId = worker->mControl->licenseLeaseId;
                items.push_back(item);
            }
        }

        std::vector<std::string> toStop;
        for (const auto& item : items) {
            std::string err;
            LicenseThreadPriorityHint renewHint;
	            bool ok = renewLeaseId(item.leaseId, ttlSeconds, &renewHint, err);

	            if (!ok && (err == "lease_not_found" || err == "lease_expired")) {
	                // Lease may have been reclaimed (Analyzer restart / LM downtime). Try re-acquire.
	                Control tmp;
	                tmp.code = item.controlCode;
	                tmp.streamCode = item.streamCode;
	                tmp.algorithmCode = item.algorithmCode;
	                std::string acquireErr;
	                if (acquireControlLease(&tmp, acquireErr)) {
	                    std::scoped_lock lock(mWorkerMapMtx);
	                    if (auto f = mWorkerMap.find(item.controlCode); f != mWorkerMap.end() && f->second && f->second->mControl) {
	                        f->second->mControl->licenseLeaseId = tmp.licenseLeaseId;
	                        f->second->mControl->licenseLastRenewOkTimestamp = nowTs;
	                        f->second->mControl->licenseGraceUntilTimestamp = 0;
	                        f->second->updateLicenseThreadPriorityHint(
	                            tmp.licenseThreadPriorityEnabled,
	                            tmp.licenseThreadPriorityStreamRank,
	                            tmp.licenseThreadPriorityFirstNActiveStreams,
	                            tmp.licenseThreadPriorityNiceValue);
	                    }
	                    continue;
	                }
	                err = acquireErr;
	            }

	            if (ok) {
	                std::scoped_lock lock(mWorkerMapMtx);
	                if (auto f = mWorkerMap.find(item.controlCode);
	                        f != mWorkerMap.end() &&
	                        f->second &&
	                        f->second->mControl &&
	                        f->second->mControl->licenseLeaseId == item.leaseId) {
	                    f->second->mControl->licenseLastRenewOkTimestamp = nowTs;
	                    f->second->mControl->licenseGraceUntilTimestamp = 0;
	                    f->second->updateLicenseThreadPriorityHint(
	                        renewHint.enabled,
	                        renewHint.streamRank,
	                        renewHint.firstNActiveStreams,
	                        renewHint.niceValue);
	                }
	                continue;
	            }

            bool shouldStop = false;
	            {
	                std::scoped_lock lock(mWorkerMapMtx);
	                auto f = mWorkerMap.find(item.controlCode);
	                if (f != mWorkerMap.end() && f->second && f->second->mControl) {
	                    Control* control = f->second->mControl.get();
	                    shouldStop = shouldStopAfterRenewFailure(nowTs, graceSeconds, control->licenseGraceUntilTimestamp);
	                }
	            }

            if (shouldStop) {
                if (graceSeconds <= 0) {
                    LOGW("License renew failed (no grace), stopping control: code=%s, err=%s", item.controlCode.c_str(), err.c_str());
                }
                else {
                    LOGW("License renew failed past grace, stopping control: code=%s, err=%s", item.controlCode.c_str(), err.c_str());
                }
                toStop.push_back(item.controlCode);
            }
            else {
                LOGW("License renew failed (grace): code=%s, err=%s", item.controlCode.c_str(), err.c_str());
            }
        }

        for (const auto& controlCode : toStop) {
            Control ctrl;
            ctrl.code = controlCode;
            int result_code = 0;
            std::string result_msg;
            apiControlCancel(&ctrl, result_code, result_msg);
            LOGW("Stopped by license grace: code=%s, result_code=%d, msg=%s", controlCode.c_str(), result_code, result_msg.c_str());
        }
    }

}
