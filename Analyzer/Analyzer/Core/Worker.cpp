#include "Worker.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include "DetectSchedule.h"
#include "Scheduler.h"
#include "Config.h"
#include "AlarmEncodeProfile.h"
#include "AlarmQueuePolicy.h"
#include "ApiAlgorithmSupport.h"
#include "Analyzer.h"
#include "Control.h"
#include "Algorithm.h"
#include "AlarmImageMode.h"
#include "DetectObjectJson.h"
#include "PoseRenderer.h"
#include "LineCrossing.h"
#include "LicenseThreadPriority.h"
#include "AvPushStream.h"
#include "DecodedFrameQueue.h"
#include "Frame.h"
#include "SharedDecodeFrameGate.h"
#include "SharedDecodeSession.h"
#include "Utils/Request.h"
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <cctype>
#include <tuple>
#include <stdexcept>
#include <string_view>
#include <json/json.h>
#include <opencv2/opencv.hpp>

extern "C" {
#include "libswscale/swscale.h"
#include <libavutil/imgutils.h>
#include <libswresample/swresample.h>
}

namespace AVSAnalyzer {

    namespace {

        constexpr size_t kDecodedFrameQueueMaxFrames = 3;

        bool writeBgrImageFile(const std::string& pathAbs, int width, int height, const unsigned char* buf) {
            if (pathAbs.empty() || width <= 0 || height <= 0 || buf == nullptr) {
                return false;
            }
            try {
                cv::Mat image(height, width, CV_8UC3);
                const size_t bytes =
                    static_cast<size_t>(width) * static_cast<size_t>(height) * 3u;
                std::memcpy(image.data, buf, bytes);
                return cv::imwrite(pathAbs, image);
            }
            catch (const cv::Exception& ex) {
                LOGE("writeBgrImageFile failed: %s", ex.what());
            }
            catch (...) { // NOSONAR
                LOGE("writeBgrImageFile failed: unknown");
            }
            return false;
        }

        bool writeFrameImageFile(
            Frame* frame,
            int width,
            int height,
            const std::string& pathAbs,
            bool preferRawSnapshot) {
            if (frame == nullptr) {
                return false;
            }
            const unsigned char* buf = frame->getBuf();
            if (preferRawSnapshot && frame->hasAlarmRawSnapshot()) {
                buf = frame->getAlarmRawSnapshot();
            }
            return writeBgrImageFile(pathAbs, width, height, buf);
        }

        Json::Value parseJsonObjectOrEmpty(std::string_view text) {
            Json::Value out(Json::objectValue);
            if (text.empty()) {
                return out;
            }
            Json::CharReaderBuilder builder;
            JSONCPP_STRING errs;
            const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
            if (reader && reader->parse(text.data(), text.data() + text.size(), &out, &errs) && errs.empty() && out.isObject()) {
                return out;
            }
            return Json::Value(Json::objectValue);
        }

        Json::Value parseJsonArrayOrEmpty(std::string_view text) {
            Json::Value out(Json::arrayValue);
            if (text.empty()) {
                return out;
            }
            Json::CharReaderBuilder builder;
            JSONCPP_STRING errs;
            const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
            if (reader && reader->parse(text.data(), text.data() + text.size(), &out, &errs) && errs.empty() && out.isArray()) {
                return out;
            }
            return Json::Value(Json::arrayValue);
        }

        std::string serializeDetectsJson(const std::vector<DetectObject>& detects) {
            if (detects.empty()) {
                return "";
            }
            Json::Value arr(Json::arrayValue);
            for (const auto& d : detects) {
                arr.append(detectObjectToJson(d));
            }
            Json::StreamWriterBuilder builder;
            builder["indentation"] = "";
            builder["emitUTF8"] = true;
            return Json::writeString(builder, arr);
        }

        cv::Scalar parseRgbToBgrScalar(const std::string& rgb, const cv::Scalar& fallback) {
            int r = 0;
            int g = 0;
            int b = 0;
            std::string s = rgb;
            s.erase(std::remove_if(s.begin(), s.end(), [](unsigned char ch) { return std::isspace(ch); }), s.end());
            const size_t p1 = s.find(',');
            const size_t p2 = (p1 == std::string::npos) ? std::string::npos : s.find(',', p1 + 1);
            if (p1 == std::string::npos || p2 == std::string::npos) {
                return fallback;
            }
            try {
                r = std::stoi(s.substr(0, p1));
                g = std::stoi(s.substr(p1 + 1, p2 - p1 - 1));
                b = std::stoi(s.substr(p2 + 1));
            }
            catch (const std::invalid_argument&) {
                return fallback;
            }
            catch (const std::out_of_range&) {
                return fallback;
            }
            r = std::max(0, std::min(255, r));
            g = std::max(0, std::min(255, g));
            b = std::max(0, std::min(255, b));
            return cv::Scalar(b, g, r);
        }

        void drawWorkerOverlays(const Control* control, cv::Mat& image, const std::vector<DetectObject>& detects) {
            if (control == nullptr) {
                return;
            }

            const int width = image.cols;
            const int height = image.rows;
            const cv::Scalar regionColor = parseRgbToBgrScalar(control->overlayRegionColor, cv::Scalar(0, 0, 255));
            const int regionThickness = std::max(1, control->overlayRegionThickness);

            const cv::Scalar lineColor = parseRgbToBgrScalar(control->overlayLineColor, cv::Scalar(0, 0, 255));
            const int lineThickness = std::max(1, control->overlayLineThickness);

            const cv::Scalar detectColor = parseRgbToBgrScalar(control->overlayDetectColor, cv::Scalar(0, 0, 255));
            const int detectThickness = std::max(1, control->overlayDetectThickness);
            const int detectFontSize = std::max(6, control->overlayDetectFontSize);
            const double detectFontScale = detectFontSize / 24.0;

            if (control->drawType == "line" && !control->lineCoordinates.empty()) {
                Line line = Line::fromString(control->lineCoordinates, width, height);
                if (line.p1 != cv::Point() || line.p2 != cv::Point()) {
                    cv::line(image, line.p1, line.p2, lineColor, lineThickness, cv::LINE_AA);
                }
            }

            if (!control->recognitionRegions_points.empty()) {
                cv::polylines(image, control->recognitionRegions_points, true, regionColor, regionThickness, cv::LINE_AA);
            }
            else if (!control->recognitionRegion_points.empty()) {
                cv::polylines(
                    image,
                    control->recognitionRegion_points,
                    control->recognitionRegion_points.size(),
                    regionColor,
                    regionThickness,
                    cv::LINE_AA);
            }

            for (const auto& detect : detects) {
                if (!detect.happen) {
                    continue;
                }

                std::stringstream classScoreSs;
                classScoreSs << std::setprecision(1) << detect.class_score;
                const std::string title = detect.class_name + ":" + classScoreSs.str();

                if (detect.hasSegmentation && detect.segmentation.size() >= 3) {
                    std::vector<cv::Point> contour;
                    contour.reserve(detect.segmentation.size());
                    for (const auto& point : detect.segmentation) {
                        contour.emplace_back(static_cast<int>(point.x), static_cast<int>(point.y));
                    }
                    const std::vector<std::vector<cv::Point>> contours = { contour };
                    cv::polylines(image, contours, true, detectColor, detectThickness, cv::LINE_AA);
                }
                else if (detect.hasObb) {
                    const auto& pts = detect.obb;
                    for (int index = 0; index < 4; ++index) {
                        const cv::Point p1(static_cast<int>(pts[index].x), static_cast<int>(pts[index].y));
                        const cv::Point p2(static_cast<int>(pts[(index + 1) % 4].x), static_cast<int>(pts[(index + 1) % 4].y));
                        cv::line(image, p1, p2, detectColor, detectThickness, cv::LINE_AA);
                    }
                }
                else {
                    cv::rectangle(
                        image,
                        cv::Rect(detect.x1, detect.y1, detect.x2 - detect.x1, detect.y2 - detect.y1),
                        detectColor,
                        detectThickness,
                        cv::LINE_AA,
                        0);
                }

                const int h = detect.y2 - detect.y1;
                cv::putText(
                    image,
                    title,
                    cv::Point(detect.x1, detect.y1 + (h / 3)),
                    cv::FONT_HERSHEY_SIMPLEX,
                    detectFontScale,
                    detectColor,
                    detectThickness,
                    cv::LINE_AA);
            }

            thread_local PoseRenderer poseRenderer;
            poseRenderer.setDrawBoundingBox(false);
            for (const auto& detect : detects) {
                if (detect.happen && detect.hasPose) {
                    poseRenderer.renderPose(image, detect, 0.3f);
                }
            }

            cv::putText(
                image,
                control->algorithmCode,
                cv::Point(control->osdAlgoX, control->osdAlgoY),
                cv::FONT_HERSHEY_COMPLEX,
                2,
                cv::Scalar(0, 0, 255),
                2);
            std::stringstream fpsStream;
            fpsStream << std::setprecision(4) << control->checkFps;
            const std::string fpsTitle = "FPS:" + fpsStream.str();
            cv::putText(
                image,
                fpsTitle,
                cv::Point(control->osdFpsX, control->osdFpsY),
                cv::FONT_HERSHEY_COMPLEX,
                2,
                cv::Scalar(0, 0, 255),
                1,
                cv::LINE_AA);
        }

        int drainAlarmEncoderPackets(
            bool recordVideo,
            AVCodecContext* videoCodecCtx,
            AVPacket* pkt,
            AVFormatContext* fmtCtx,
            const AVStream* videoStream,
            const char* stage) {
            if (!recordVideo || videoCodecCtx == nullptr || pkt == nullptr || fmtCtx == nullptr || videoStream == nullptr) {
                return AVERROR_EOF;
            }
            int ret = avcodec_receive_packet(videoCodecCtx, pkt);
            while (ret >= 0) {
                pkt->stream_index = videoStream->id;
                const int writeFrameRet = av_interleaved_write_frame(fmtCtx, pkt);
                if (writeFrameRet < 0) {
                    LOGE("alarm encoder: write frame error=%d stage=%s", writeFrameRet, (stage ? stage : ""));
                }
                av_packet_unref(pkt);
                ret = avcodec_receive_packet(videoCodecCtx, pkt);
            }
            if (ret < 0 && ret != AVERROR(EAGAIN) && ret != AVERROR_EOF) {
                LOGE("alarm encoder: avcodec_receive_packet error=%d stage=%s", ret, (stage ? stage : ""));
            }
            return ret;
        }

        bool sendAlarmEncoderFrame(
            bool recordVideo,
            AVCodecContext* videoCodecCtx,
            AVPacket* pkt,
            AVFormatContext* fmtCtx,
            const AVStream* videoStream,
            const AVFrame* frame,
            const char* stage) {
            if (!recordVideo || videoCodecCtx == nullptr) {
                return false;
            }
            const int kMaxTries = 5;
            for (int attempt = 0; attempt < kMaxTries; ++attempt) {
                const int ret = avcodec_send_frame(videoCodecCtx, frame);
                if (ret >= 0) {
                    return true;
                }
                if (ret == AVERROR(EAGAIN)) {
                    drainAlarmEncoderPackets(recordVideo, videoCodecCtx, pkt, fmtCtx, videoStream, stage);
                    continue;
                }
                if (ret == AVERROR_EOF) {
                    return false;
                }
                LOGE("alarm encoder: avcodec_send_frame error=%d stage=%s", ret, (stage ? stage : ""));
                return false;
            }
            LOGE("alarm encoder: avcodec_send_frame EAGAIN too many times stage=%s", (stage ? stage : ""));
            return false;
        }

    }  // namespace

    Worker::Worker(Scheduler* scheduler, Control* control)
        : WorkerOwnedResources{
            control ? std::make_unique<Control>(*control) : std::make_unique<Control>(),
            scheduler,
            nullptr,
            nullptr,
            nullptr
        }
    {

        mControl->startTimestamp = getCurTimestamp();
        if (mScheduler && mScheduler->getConfig()) {
            const Config* config = mScheduler->getConfig();
            mAlarmPrefixFrames = std::max(1, config->alarmPrefixFrames);
            mAlarmTotalFrames = std::max(mAlarmPrefixFrames, config->alarmTotalFrames);

            mAlarmMergeWindowMs = static_cast<int64_t>(std::max(1, std::min(3600, config->alarmMergeWindowSeconds))) * 1000;
            mAlarmSegmentMaxMs = static_cast<int64_t>(std::max(1, std::min(3600, config->alarmSegmentMaxSeconds))) * 1000;

            // Prefer time-based min segment length: alarmVideoSeconds (independent of fps).
            if (config->alarmVideoSeconds > 0) {
                mAlarmMinSegmentMs = static_cast<int64_t>(config->alarmVideoSeconds) * 1000;
            } else {
                int fpsFallback = (mControl->videoFps > 0) ? mControl->videoFps : 25;
                mAlarmMinSegmentMs = static_cast<int64_t>(std::max(mAlarmPrefixFrames, mAlarmTotalFrames)) * 1000 / std::max(1, fpsFallback);
            }
            if (mAlarmMinSegmentMs < 0) {
                mAlarmMinSegmentMs = 0;
            }
            if (mAlarmSegmentMaxMs > 0) {
                mAlarmMinSegmentMs = std::min(mAlarmMinSegmentMs, mAlarmSegmentMaxMs);
            }
        }
        else {
            mAlarmTotalFrames = std::max(mAlarmPrefixFrames, mAlarmTotalFrames);
            mAlarmMinSegmentMs = std::min<int64_t>(mAlarmSegmentMaxMs, 6 * 1000);
        }

        std::string videoType = mControl->alarmVideoType;
        std::transform(videoType.begin(), videoType.end(), videoType.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        mControl->alarmVideoType = videoType;
        mAlarmNeedFrames = mControl->forceFrameAlarm || (videoType != "none") || (mControl->alarmImageCount > 0);
        if (mAlarmNeedFrames) {
            mAlarmVideoQueueMaxFrames = pickAlarmVideoQueueMaxFrames(videoType, mControl->alarmImageCount, mAlarmPrefixFrames);
        } else {
            mAlarmVideoQueueMaxFrames = 0;
        }

        LOGI("");

        if (mControl) {
            mLicenseThreadPriorityEnabled.store(mControl->licenseThreadPriorityEnabled ? 1 : 0);
            mLicenseThreadPriorityStreamRank.store(mControl->licenseThreadPriorityStreamRank);
            mLicenseThreadPriorityFirstNActiveStreams.store(mControl->licenseThreadPriorityFirstNActiveStreams);
            mLicenseThreadPriorityNiceValue.store(mControl->licenseThreadPriorityNiceValue);
        }
    }

    Worker::~Worker()
    {
        LOGI("");

        std::this_thread::sleep_for(std::chrono::milliseconds(1));

        requestStop();

        for (auto& th : mThreads) {
            if (th.joinable()) {
                th.join();
            }
        }
        mThreads.clear();

        // Alarm encode thread is owned by AlarmSession (not part of mThreads).
        // Ensure it is stopped + joined before we tear down pools/resources.
        if (mAlarmSession) {
            stopAlarmSession(mAlarmSession.get());
            mAlarmSession.reset();
        }

        clearAlarmVideoFrameQ();
        mDecodedFrameQ.reset();
        mPushStream.reset();
        mAnalyzer.reset();

        // 释放硬件编码通道
        if (mHasEncodeChannel) {
            if (mScheduler) {
                mScheduler->releaseEncodeChannel();
            }
            mHasEncodeChannel = false;
        }

        mControl.reset();
        // 最后一步释放 mFramePool
        mVideoFramePool.reset();

    }
    bool Worker::ensureLocalAlgorithmLoaded(const std::string& code, const char* label, std::string& msg) const {
        if (!mScheduler) {
            msg = "scheduler is null";
            return false;
        }
        if (code.empty() || code == "wensou" || code == "api") {
            return true;
        }
        std::string err;
        int concurrency = mControl ? mControl->modelConcurrency : 1;
        if (concurrency < 1) {
            concurrency = 1;
        }
        const bool forceInferenceDevice = mControl && mControl->forceInferenceDevice;
        if (!mScheduler->ensureAlgorithmLoaded(code, concurrency, forceInferenceDevice, err)) {
            msg = std::string("load algorithm failed") +
                  (label ? std::string(" (") + label + ")" : std::string("")) +
                  ": " + err;
            return false;
        }
        if (mControl && label != nullptr && std::string_view(label) == "basic") {
            InferenceDeviceDecision decision;
            if (!mScheduler->getAlgorithmDeviceDecision(code, decision)) {
                msg = "load algorithm failed (basic): device decision unavailable";
                return false;
            }
            mControl->requestedInferenceDevice = decision.requestedDevice;
            mControl->effectiveInferenceDevice = decision.effectiveDevice;
            mControl->inferenceDeviceDegraded = decision.degraded;
            mControl->inferenceDeviceReason = decision.reason;
        }
        return true;
    }
    bool Worker::start(std::string& msg) {
        try {

        // 确保算法按需加载成功（仅当算法需要本地模型时才尝试加载）
        const bool useBasicApiInference =
            shouldUseBasicApiInference(mControl->usePipelineMode, mControl->algorithmPipelineMode, mControl->api_url);
        // Base detection algorithm (local inference only)
        if (const bool isPipelineMode5 = mControl->usePipelineMode && mControl->algorithmPipelineMode == 5;
            !useBasicApiInference && !isPipelineMode5) {
            const std::string& instanceKey =
                (!mControl->algorithmInstanceKey.empty() ? mControl->algorithmInstanceKey : mControl->algorithmCode);
            if (!ensureLocalAlgorithmLoaded(instanceKey, "basic", msg)) {
                return false;
            }
        }

        // Pipeline mode: ensure all referenced local algorithms are loaded before Analyzer() is constructed.
        if (mControl->usePipelineMode) {
            int mode = mControl->algorithmPipelineMode;
            if (mode == 2) {
                std::string trackingLower = mControl->trackingAlgorithmCode;
                std::transform(trackingLower.begin(), trackingLower.end(), trackingLower.begin(),
                    [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                if (!trackingLower.empty() && trackingLower != "bytetrack" &&
                    !ensureLocalAlgorithmLoaded(mControl->trackingAlgorithmCode, "tracking", msg)) {
                    return false;
                }
            }
            if ((mode == 3 || mode == 4) &&
                !mControl->classificationAlgorithmCode.empty() &&
                !ensureLocalAlgorithmLoaded(mControl->classificationAlgorithmCode, "classification", msg)) {
                return false;
            }
            if (mode >= 1 && mode <= 4 &&
                !mControl->behaviorAlgorithmCode.empty() &&
                !ensureLocalAlgorithmLoaded(mControl->behaviorAlgorithmCode, "behavior", msg)) {
                return false;
            }
        }

        // Hierarchical secondary algorithm (local inference only)
        if (mControl->enableHierarchicalAlgorithm &&
            !mControl->secondaryAlgorithmCode.empty() &&
            mControl->secondaryApi_url.empty() &&
            !ensureLocalAlgorithmLoaded(mControl->secondaryAlgorithmCode, "secondary", msg)) {
            return false;
        }

        std::string channelErr;
	        auto cleanupStartFailure = [&]() {
	            mState.store(false);
	            if (mDecodedFrameQ) {
	                mDecodedFrameQ.reset();
	            }
	            mPushStream.reset();
	            mAnalyzer.reset();
	            mVideoFramePool.reset();
	            if (mHasEncodeChannel && mScheduler) {
	                mScheduler->releaseEncodeChannel();
	                mHasEncodeChannel = false;
            }
            if (mSharedDecodeSession && mScheduler && !mSharedDecodeKey.empty()) {
                mScheduler->releaseSharedDecodeSession(mSharedDecodeKey, mSharedDecodeSubscribed ? this : nullptr);
                mSharedDecodeSubscribed = false;
                mSharedDecodeSession = nullptr;
                mSharedDecodeKey.clear();
            }
        };

	        if (!mScheduler->acquireSharedDecodeSession(mControl.get(), mSharedDecodeSession, mSharedDecodeKey, msg) ||
	            !mSharedDecodeSession) {
	            cleanupStartFailure();
	            return false;
	        }
	        mSharedDecodeSession->copyVideoInfoTo(mControl.get());
	        if (!mControl->parseRecognitionRegion()) {
	            msg = "parseRecognitionRegion() error";
	            cleanupStartFailure();
	            return false;
	        }

        if (mControl->pushStream) {
            if (mControl && mControl->enableHardwareEncode) {
                if (!mScheduler->reserveEncodeChannel(channelErr)) {
                    msg = "reserve encode channel failed: " + channelErr;
                    cleanupStartFailure();
                    return false;
                }
                mHasEncodeChannel = true;
            }

	            mPushStream = std::make_unique<AvPushStream>(this);
	            if (!mPushStream->connect()) {
	                msg = "push stream connect error";
	                cleanupStartFailure();
	                return false;
	            }
	        }

        const int videoBgrSize = mControl->videoHeight * mControl->videoWidth * mControl->videoChannel;
        if (videoBgrSize <= 0) {
            msg = "invalid shared decoded frame size";
            cleanupStartFailure();
            return false;
        }

        this->mVideoFramePool = std::make_shared<FramePool>(videoBgrSize);
	        this->mDecodedFrameQ = std::make_unique<DecodedFrameQueue>(
	            kDecodedFrameQueueMaxFrames,
	            [this](Frame* frame) { this->releaseDecodedFrame(frame); });
	        mAnalyzer = std::make_unique<Analyzer>(mScheduler, mControl.get());

	        mState.store(true);// 将执行状态设置为true

	        mThreads.emplace_back(Worker::decodeVideoThread, this);

	        if (mAlarmNeedFrames) {
	            mThreads.emplace_back(Worker::generateAlarmThread, this);
	        }


	        if (mControl->pushStream && mControl->videoIndex > -1) {
	            mThreads.emplace_back(AvPushStream::encodeVideoThread, mPushStream.get());
	        }

	        for (auto& th : mThreads) {
	            (void)th.native_handle();
	        }

        mSharedDecodeSession->subscribe(this);
        mSharedDecodeSubscribed = true;

        return true;
        }
        catch (const std::exception& ex) { // NOSONAR
            // 超量布控/资源不足时，std::thread / new / make_shared 可能抛异常；必须兜底避免进程崩溃
            requestStop();
            msg = std::string("worker start exception: ") + ex.what();
            return false;
        }
        catch (...) { // NOSONAR
            requestStop();
            msg = "worker start exception: unknown";
            return false;
        }
    }


    bool Worker::getState() {
        return mState.load();
    }
    LicenseThreadPriorityHint Worker::getLicenseThreadPriorityHint() const {
        LicenseThreadPriorityHint hint;
        hint.enabled = mLicenseThreadPriorityEnabled.load() != 0;
        hint.streamRank = mLicenseThreadPriorityStreamRank.load();
        hint.firstNActiveStreams = mLicenseThreadPriorityFirstNActiveStreams.load();
        hint.niceValue = mLicenseThreadPriorityNiceValue.load();
        return hint;
    }
    void Worker::updateLicenseThreadPriorityHint(bool enabled, int streamRank, int firstNActiveStreams, int niceValue) {
        if (mControl) {
            mControl->licenseThreadPriorityEnabled = enabled;
            mControl->licenseThreadPriorityStreamRank = streamRank;
            mControl->licenseThreadPriorityFirstNActiveStreams = firstNActiveStreams;
            mControl->licenseThreadPriorityNiceValue = niceValue;
        }
        mLicenseThreadPriorityEnabled.store(enabled ? 1 : 0);
        mLicenseThreadPriorityStreamRank.store(streamRank);
        mLicenseThreadPriorityFirstNActiveStreams.store(firstNActiveStreams);
        mLicenseThreadPriorityNiceValue.store(niceValue);
        mLicenseThreadPriorityGeneration.fetch_add(1);
    }
    void Worker::maybeRefreshCurrentThreadPriority(uint64_t& lastSeenGeneration, const char* threadName) {
        const uint64_t generation = mLicenseThreadPriorityGeneration.load();
        if (generation == lastSeenGeneration) {
            return;
        }
	        lastSeenGeneration = generation;

	        const LicenseThreadPriorityHint hint = getLicenseThreadPriorityHint();
	        if (std::string err; !applyCurrentThreadPriorityBestEffort(hint, &err)) {
	            LOGW(
	                "license thread priority apply failed thread=%s enabled=%d rank=%d/%d nice=%d err=%s",
	                (threadName ? threadName : "unknown"),
	                hint.enabled ? 1 : 0,
	                hint.streamRank,
                hint.firstNActiveStreams,
                targetThreadNiceValue(hint),
                err.c_str());
            return;
        }

        LOGI(
            "license thread priority refreshed thread=%s enabled=%d rank=%d/%d nice=%d",
            (threadName ? threadName : "unknown"),
            hint.enabled ? 1 : 0,
            hint.streamRank,
            hint.firstNActiveStreams,
            targetThreadNiceValue(hint));
    }
    void Worker::requestStop() {
        mState.store(false);
        if (mSharedDecodeSession && mScheduler && !mSharedDecodeKey.empty()) {
            mScheduler->releaseSharedDecodeSession(mSharedDecodeKey, mSharedDecodeSubscribed ? this : nullptr);
            mSharedDecodeSubscribed = false;
            mSharedDecodeSession = nullptr;
            mSharedDecodeKey.clear();
        }
        mAlarmVideoFrameQ_cv.notify_all();
        // Wake alarm encoder thread if it is waiting on condition variable.
        if (mAlarmSession) {
            {
                std::scoped_lock lock(mAlarmSession->queueMtx);
                mAlarmSession->stop = true;
            }
            mAlarmSession->queueCv.notify_one();
        }
    }
    int Worker::getSourceInputQueueSize() const {
        return std::max(0, mSourceInputQueueSize.load());
    }
    void Worker::remove() {
        requestStop();
        if (mScheduler) {
            mScheduler->removeWorker(mControl.get());
        }
    }
    void Worker::generateAlarmThread(Worker* arg) {
        auto* worker = arg;
        try {
            worker->handleGenerateAlarm();
        }
        catch (const std::exception& ex) { // NOSONAR
            LOGE("generateAlarmThread exception: %s", ex.what());
            if (worker) {
                worker->remove();
            }
        }
        catch (...) { // NOSONAR
            LOGE("generateAlarmThread exception: unknown");
            if (worker) {
                worker->remove();
            }
        }
    }
    bool Worker::notifyFrameAlarm(Frame* triggerFrame) {
        if (!triggerFrame || !mScheduler || !mScheduler->getConfig() || !mControl) {
            return false;
        }

	        const Config* config = mScheduler->getConfig();
        if (!config) {
            return false;
        }

        const int width = mControl->videoWidth;
        const int height = mControl->videoHeight;
        if (width <= 0 || height <= 0) {
            LOGW("forceFrameAlarm: skip notify due to invalid video size w=%d h=%d", width, height);
            return false;
        }

        std::string baseDir = config->uploadDir + "/alarm";
        std::string controlDir = baseDir + "/" + mControl->code;
        std::string dirSuffix = getCurFormatTimeStr("%Y%m%d%H%M%S") + "_" + std::to_string(getRandomInt());
        std::string fullDir = controlDir + "/" + dirSuffix;
        try {
            std::filesystem::create_directories(fullDir);
        } catch (const std::filesystem::filesystem_error& e) {
            LOGE("forceFrameAlarm: create directories error: %s", e.what());
            return false;
        }

        const std::string relativeDir = "alarm/" + mControl->code + "/" + dirSuffix;
        const std::string imagePathRel = relativeDir + "/main.jpg";
        const std::string imagePathAbs = config->uploadDir + "/" + imagePathRel;

        try {
            cv::Mat cover(height, width, CV_8UC3, triggerFrame->getBuf());
            if (!cv::imwrite(imagePathAbs, cover)) {
                LOGE("forceFrameAlarm: imwrite failed: %s", imagePathAbs.c_str());
                return false;
            }
        } catch (const cv::Exception& e) {
            LOGE("forceFrameAlarm: imwrite exception: %s", e.what());
            return false;
        } catch (...) { // NOSONAR
            LOGE("forceFrameAlarm: imwrite exception: unknown");
            return false;
        }

        Json::Value param;
        param["control_code"] = mControl->code;
        param["desc"] = "";
        param["video_path"] = "";
        param["image_path"] = imagePathRel;
        param["algorithm_code"] = mControl->algorithmCode;
        param["object_code"] = mControl->objectCode;
        param["recognition_region"] = mControl->recognitionRegion;
        param["class_thresh"] = mControl->classThresh;
        param["overlap_thresh"] = mControl->overlapThresh;
        param["min_interval"] = static_cast<Json::Int64>(mControl->minInterval);
        if (triggerFrame->regionIndex >= 0) {
            param["region_index"] = triggerFrame->regionIndex;
        }
        param["stream_code"] = mControl->streamCode;
        param["stream_app"] = mControl->streamApp;
        param["stream_name"] = mControl->streamName;
        param["stream_url"] = mControl->streamUrl;

        Json::StreamWriterBuilder wbuilder;
        wbuilder["indentation"] = "";
        wbuilder["emitUTF8"] = true;
        const std::string data = Json::writeString(wbuilder, param);
        const std::string url = config->adminHost + "/alarm/openAdd";
        mScheduler->enqueueAlarmNotify(url, data, config->openApiToken);
        return true;
    }
    void Worker::handleGenerateAlarm() {
        uint64_t priorityGeneration = 0;
        maybeRefreshCurrentThreadPriority(priorityGeneration, "alarm_generate");

        Frame* videoFrame = nullptr; // 未编码的视频帧（bgr格式）

        std::deque<Frame*> prefixFrames;
        const auto prefix_size = static_cast<size_t>(std::max(1, mAlarmPrefixFrames)); // 事件发生前缓存的帧数量

	        auto clearPrefixFrames = [&]() {
	            while (!prefixFrames.empty()) {
	                Frame* p = prefixFrames.front();
	                prefixFrames.pop_front();
	                this->releaseFrame(p);
	            }
	        };

        auto computeSessionEnd = [&](const AlarmSession* session) -> std::tuple<int64_t, bool> {
            // Return end timestamp and whether it is clamped by max segment duration.
            if (!session) {
                return { 0, false };
            }
            const int64_t segmentStart = session->segmentStartMs;
            const int64_t minEnd = segmentStart + std::max<int64_t>(0, mAlarmMinSegmentMs);
            const int64_t maxEnd = segmentStart + std::max<int64_t>(1000, mAlarmSegmentMaxMs);
            const int64_t desiredEnd = std::max(minEnd, session->lastTriggerMs + std::max<int64_t>(1000, mAlarmMergeWindowMs));
            const int64_t endMs = std::min(maxEnd, desiredEnd);
            const bool clampedByMax = (endMs == maxEnd) && (desiredEnd > maxEnd);
            return { endMs, clampedByMax };
        };

        const bool forceFrameAlarm = (mControl != nullptr) && mControl->forceFrameAlarm;

        while (getState())
        {
            maybeRefreshCurrentThreadPriority(priorityGeneration, "alarm_generate");
            if (!getAlarmVideoFrame(videoFrame)) {
                continue;
            }

            if (!mAlarmNeedFrames) {
                releaseFrame(videoFrame);
                continue;
            }

            // Some legacy paths may not set timestampMs; fall back to monotonic now.
            const int64_t ts = (videoFrame->timestampMs > 0) ? videoFrame->timestampMs : getCurTime();

            if (forceFrameAlarm) {
                if (videoFrame->happen) {
                    (void)this->notifyFrameAlarm(videoFrame);
                }
                releaseFrame(videoFrame);
                videoFrame = nullptr;
                continue;
            }

            bool carryStartNextSegment = false;
            int64_t carryLastTriggerMs = 0;

            // Re-process the same frame when we cut a segment and need to start a new one immediately.
            while (videoFrame) {
                if (mAlarmSession) {
                    AlarmSession* session = mAlarmSession.get();

                    if (videoFrame->happen) {
                        session->lastTriggerMs = ts;
                    }

                    const auto [endMs, clampedByMax] = computeSessionEnd(session);
                    session->segmentEndMs = endMs;

                    if (ts <= session->segmentEndMs) {
                        // Adaptive sampling: when encoder queue pressure is high, keep fewer frames.
                        bool forceKeep = videoFrame->happen;
                        int sampleEveryN = 1;
                        if (!forceKeep && session->maxQueueSize > 0) {
                            size_t qSize = 0;
                            {
                                std::scoped_lock lock(session->queueMtx);
                                qSize = session->frameQueue.size();
                            }
                            const double ratio = static_cast<double>(qSize) / static_cast<double>(session->maxQueueSize);
                            if (ratio >= 0.8) {
                                sampleEveryN = 5;
                            } else if (ratio >= 0.6) {
                                sampleEveryN = 3;
                            } else if (ratio >= 0.4) {
                                sampleEveryN = 2;
                            }
                        }

                        session->enqueueSeq++;
	                        if (const bool keep = forceKeep || sampleEveryN <= 1 ||
	                            (session->enqueueSeq % static_cast<uint64_t>(sampleEveryN) == 0); keep) {
	                            enqueueAlarmFrame(session, videoFrame);
	                        } else {
	                            releaseFrame(videoFrame);
                        }
                        videoFrame = nullptr;
                        continue;
                    }

                    // Segment ended: decide whether to continue by cutting a new segment (max cap) or to close event.
                    const int64_t maxEnd = session->segmentStartMs + std::max<int64_t>(1000, mAlarmSegmentMaxMs);
                    const bool shouldContinue =
                        clampedByMax &&
                        (session->lastTriggerMs + std::max<int64_t>(1000, mAlarmMergeWindowMs) > maxEnd) &&
                        (ts - session->lastTriggerMs) <= std::max<int64_t>(1000, mAlarmMergeWindowMs);

                    carryStartNextSegment = shouldContinue;
                    carryLastTriggerMs = session->lastTriggerMs;

                    stopAlarmSession(session);
                    mAlarmSession.reset();
                    if (!shouldContinue) {
                        // cooldown starts after a full event finishes (not on hard cut).
                        mLastAlarmTimestamp = getCurTime();
                    }
                    continue;
                }

                // No active session: maintain prefix buffer
                while (prefixFrames.size() >= prefix_size) {
                    Frame* head = prefixFrames.front();
                    prefixFrames.pop_front();
                    releaseFrame(head);
                }
                prefixFrames.push_back(videoFrame);
                videoFrame = nullptr;

                const int64_t cooldownMs = std::max<int64_t>(0, mControl ? mControl->minInterval : 0);
                const bool cooldownOk = (mLastAlarmTimestamp <= 0) || ((ts - mLastAlarmTimestamp) > cooldownMs);

	                if (const bool shouldStart =
	                        (carryStartNextSegment && (ts - carryLastTriggerMs) <= std::max<int64_t>(1000, mAlarmMergeWindowMs)) ||
	                        (prefixFrames.back()->happen && cooldownOk);
	                    !shouldStart) {
	                    continue;
	                }

	                if (Frame* trigger = prefixFrames.back(); startAlarmSession(trigger)) {
	                    AlarmSession* session = mAlarmSession.get();
	                    if (session) {
                        // init time window
                        int64_t startMs = ts;
                        if (!prefixFrames.empty() && prefixFrames.front() && prefixFrames.front()->timestampMs > 0) {
                            startMs = prefixFrames.front()->timestampMs;
                        }
                        session->segmentStartMs = startMs;
                        session->basePtsMs = startMs;
                        session->lastTriggerMs = carryStartNextSegment ? carryLastTriggerMs : ts;

                        const auto [endMs, _clamped] = computeSessionEnd(session);
                        session->segmentEndMs = endMs;
                    }

                    // Drain prefix frames into encoder queue (no sampling for prefix).
                    while (!prefixFrames.empty()) {
                        Frame* p = prefixFrames.front();
                        prefixFrames.pop_front();
                        enqueueAlarmFrame(session, p);
                    }

                    carryStartNextSegment = false;
                    carryLastTriggerMs = 0;
                    // For normal event start, apply cooldown based on end time; we update mLastAlarmTimestamp when session closes.
                } else {
                    clearPrefixFrames();
                    // Start failed: protect against rapid retry storms.
                    mLastAlarmTimestamp = ts;
                }
                continue;
            }

        }

        clearPrefixFrames();
        if (mAlarmSession) {
            stopAlarmSession(mAlarmSession.get());
            mAlarmSession.reset();
        }


    }
    bool Worker::enqueueDecodedFrame(
        const unsigned char* buf,
        int size,
        int width,
        int height,
        int fps,
        int sourceQueueSize,
        int64_t timestampMs) {
        if (!buf || size <= 0 || !mDecodedFrameQ || !mVideoFramePool || !getState()) {
            return false;
        }

        mSourceInputQueueSize.store(std::max(0, sourceQueueSize));
        mVideoFramePool->resetSize(size);

        Frame* frame = mVideoFramePool->gain();
        if (!frame) {
            if (mScheduler) {
                mScheduler->statsIncDroppedDecodePackets(1);
            }
            return false;
        }

        frame->setBuf(buf, size);
        frame->width = width;
        frame->height = height;
        frame->channel = 3;
        frame->fps = fps;
        frame->sourceQueueSize = std::max(0, sourceQueueSize);
        frame->timestampMs = timestampMs;
        frame->happen = false;
        frame->happenScore = 0.0f;
        frame->regionIndex = -1;
        frame->userDataJson.clear();
        frame->detectsJson.clear();
        frame->clearAlarmRawSnapshot();

	        mDecodedFrameQ->push(frame);
	        return true;
	    }
		    void Worker::releaseFrame(Frame* frame) {
		        if (!frame) {
		            return;
		        }
		        if (mVideoFramePool) {
		            mVideoFramePool->giveBack(frame);
		        }
		        else {
		            std::unique_ptr<Frame> owned(frame);
		        }
		    }
	    void Worker::releaseDecodedFrame(Frame* frame) {
	        releaseFrame(frame);
	    }
    bool Worker::ensureDecodedFrameGeometry(const Frame* frame) {
        if (!frame || !mControl) {
            return false;
        }

        const int width = frame->width > 0 ? frame->width : mControl->videoWidth;
        const int height = frame->height > 0 ? frame->height : mControl->videoHeight;
	        if (width <= 0 || height <= 0) {
	            return false;
	        }

	        if (const bool changed = (mControl->videoWidth != width) || (mControl->videoHeight != height); changed) {
	            if (mAlarmSession) {
	                stopAlarmSession(mAlarmSession.get());
	                mAlarmSession.reset();
	            }
            clearAlarmVideoFrameQ();
            if (mPushStream) {
                mPushStream->clearVideoFrameQueue();
            }

            mControl->videoWidth = width;
            mControl->videoHeight = height;
            mControl->videoChannel = std::max(1, frame->channel);
            mControl->recognitionRegion_d.clear();
            mControl->recognitionRegion_points.clear();
            mControl->recognitionRegions_d.clear();
            mControl->recognitionRegions_points.clear();
            if (!mControl->parseRecognitionRegion()) {
                LOGW("Worker::ensureDecodedFrameGeometry: parseRecognitionRegion() failed after geometry change");
            }
            if (mVideoFramePool) {
                mVideoFramePool->resetSize(frame->getSize());
            }
        }

        if (frame->fps > 0) {
            mControl->videoFps = frame->fps;
        }

        return true;
    }
    void Worker::decodeVideoThread(Worker* arg) {
        auto* worker = arg;
        try {
            worker->handleDecodeVideo();
        }
        catch (const std::exception& ex) { // NOSONAR
            LOGE("decodeVideoThread exception: %s", ex.what());
            if (worker) {
                worker->remove();
            }
        }
        catch (...) { // NOSONAR
            LOGE("decodeVideoThread exception: unknown");
            if (worker) {
                worker->remove();
            }
        }
    }
    void Worker::handleDecodeVideo() {
        if (!mDecodedFrameQ) {
            LOGE("Worker::handleDecodeVideo: decoded frame queue is null");
            remove();
            return;
        }
        uint64_t priorityGeneration = 0;
        maybeRefreshCurrentThreadPriority(priorityGeneration, "decode");

        bool cur_is_check = false;
        int continuity_check_count = 0;
        const int continuity_check_max_time = 6000;
        int64_t continuity_check_start = getCurTime();
        int64_t continuity_check_end = 0;
        int64_t frameCount = 0;
        SharedDecodeFrameGate frameGate;
        std::vector<DetectObject> happenDetects;
        const AlarmImageModeSpec alarmImageMode =
            makeAlarmImageModeSpec(mControl ? mControl->alarmImageDrawMode : "boxed");
        const bool needAlarmRawSnapshots =
            mAlarmNeedFrames && mControl && mControl->alarmImageCount > 0 && alarmImageMode.captureRawSnapshot;
        DetectScheduleState detectScheduleState;
        int64_t lastPushTimestamp = 0;

        while (getState()) {
            maybeRefreshCurrentThreadPriority(priorityGeneration, "decode");
            Frame* sourceFrame = nullptr;
            if (!mDecodedFrameQ->pop(sourceFrame)) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            if (!sourceFrame) {
                continue;
            }

            if (!ensureDecodedFrameGeometry(sourceFrame)) {
                releaseDecodedFrame(sourceFrame);
                continue;
            }

            const int width = sourceFrame->width > 0 ? sourceFrame->width : mControl->videoWidth;
            const int height = sourceFrame->height > 0 ? sourceFrame->height : mControl->videoHeight;
            const int fps = sourceFrame->fps > 0 ? sourceFrame->fps : mControl->videoFps;
            const int sourceQueueSize = std::max(0, sourceFrame->sourceQueueSize);
            const int64_t frameMonoMs = sourceFrame->timestampMs > 0 ? sourceFrame->timestampMs : getCurTime();

            int drop_pkt_threshold = 5;
            if (mControl->pushStream && mPushStream) {
                const int pushQ = mPushStream->getVideoFrameQSize();
                const int maxQ = AvPushStream::MAX_VIDEO_FRAME_QUEUE_SIZE;
                if (pushQ > maxQ * 3 / 4) {
                    drop_pkt_threshold = 1;
                }
                else if (pushQ > maxQ / 2) {
                    drop_pkt_threshold = 3;
                }
            }

            if (sourceQueueSize > drop_pkt_threshold) {
                if (mScheduler) {
                    mScheduler->statsIncDroppedDecodePackets(1);
                }
                releaseDecodedFrame(sourceFrame);
                continue;
            }

            SharedDecodeFrameGateConfig gateConfig;
            if (mControl) {
                gateConfig.pullFrequency = mControl->pullFrequency;
                gateConfig.psEffectMinFps = mControl->psEffectMinFps;
                gateConfig.pushStream = mControl->pushStream;
                gateConfig.decodeStride = mControl->decodeStride;
            }
            if (!frameGate.shouldProcessFrame(gateConfig, frameMonoMs)) {
                releaseDecodedFrame(sourceFrame);
                continue;
            }

            frameCount++;

            bool happen = false;
            float happenScore = 0.0f;
            int regionIndex = -1;
            happenDetects.clear();
            std::string userDataJson;
            std::string detectsJson;

            int detectStride = 1;
            if (mScheduler) {
                detectStride = mScheduler->getDetectStride();
            }
            if (detectStride < 1) {
                detectStride = 1;
            }

            int dynamicDetectStride = detectStride;
            if (sourceQueueSize >= drop_pkt_threshold) {
                dynamicDetectStride = std::max(dynamicDetectStride, 4);
            }
            else if (sourceQueueSize >= 3) {
                dynamicDetectStride = std::max(dynamicDetectStride, 2);
            }

            const int64_t nowMonoMsForDetect = getCurTime();
            const bool shouldDetect = shouldRunBasicDetection(
                mControl->basicAlgoDetectMode,
                mControl->basicAlgoDetectInterval,
                frameCount,
                dynamicDetectStride,
                nowMonoMsForDetect,
                detectScheduleState);

            bool shouldPushFrame = false;
            int64_t nowMonoMs = 0;
            if (mControl->pushStream && mPushStream) {
                const int size = mPushStream->getVideoFrameQSize();
                const int highWatermark = std::max(1, AvPushStream::MAX_VIDEO_FRAME_QUEUE_SIZE / 2);
                if (size < highWatermark) {
                    int pushFps = mControl->pushVideoFps;
                    if (pushFps <= 0) {
                        pushFps = (fps > 0) ? fps : 25;
                    }
                    const int64_t intervalMs = std::max<int64_t>(1, 1000 / std::max(1, pushFps));
                    nowMonoMs = getCurTime();
                    if (lastPushTimestamp <= 0 || (nowMonoMs - lastPushTimestamp) >= intervalMs) {
                        shouldPushFrame = true;
                    }
                }
            }

            cv::Mat decodedImage(height, width, CV_8UC3, sourceFrame->getBuf(), width * 3);
            if (sourceQueueSize <= 1 && shouldDetect) {
                cur_is_check = mAnalyzer->handleVideoFrame(frameCount, decodedImage, happenDetects, happen, happenScore);
                regionIndex = mAnalyzer ? mAnalyzer->getLastRegionIndex() : -1;
                userDataJson = mAnalyzer ? mAnalyzer->getLastUserDataJson() : "";
                if (cur_is_check) {
                    continuity_check_count += 1;
                }
            }

            detectsJson = serializeDetectsJson(happenDetects);
            continuity_check_end = getCurTime();
            if (continuity_check_end - continuity_check_start > continuity_check_max_time) {
                mControl->checkFps =
                    float(continuity_check_count) /
                    (float(continuity_check_end - continuity_check_start) / 1000);
                continuity_check_count = 0;
                continuity_check_start = getCurTime();
            }

	            auto gainOutputFrame = [&](bool alarmFrame) {
	                Frame* frame = mVideoFramePool ? mVideoFramePool->gain() : nullptr;
	                if (!frame && mScheduler) {
                    if (alarmFrame) {
                        mScheduler->statsIncDroppedAlarmFrames(1);
                    }
                    else {
                        mScheduler->statsIncDroppedPushFrames(1);
                    }
                }
                return frame;
            };

            auto fillOutputMeta = [&](Frame* frame, bool clearAlarmRaw) {
                if (!frame) {
                    return;
                }
                frame->setSize(sourceFrame->getSize());
                frame->width = width;
                frame->height = height;
                frame->channel = std::max(1, sourceFrame->channel);
                frame->fps = fps;
                frame->sourceQueueSize = sourceQueueSize;
                frame->happen = happen;
                frame->happenScore = happenScore;
                frame->regionIndex = regionIndex;
                frame->timestampMs = frameMonoMs;
                frame->userDataJson = userDataJson;
                frame->detectsJson = detectsJson;
                if (clearAlarmRaw) {
                    frame->clearAlarmRawSnapshot();
                }
            };

            Frame* alarmFrame = nullptr;
            Frame* pushFrame = nullptr;

            if (mAlarmNeedFrames) {
                alarmFrame = gainOutputFrame(true);
                if (alarmFrame) {
                    alarmFrame->setBuf(sourceFrame->getBuf(), sourceFrame->getSize());
                    if (needAlarmRawSnapshots) {
                        alarmFrame->setAlarmRawSnapshot(sourceFrame->getBuf(), sourceFrame->getSize());
                    }
                    else {
                        alarmFrame->clearAlarmRawSnapshot();
                    }
                }
            }

            if (shouldPushFrame) {
                pushFrame = gainOutputFrame(false);
                if (pushFrame && !alarmFrame) {
                    pushFrame->setBuf(sourceFrame->getBuf(), sourceFrame->getSize());
                    pushFrame->clearAlarmRawSnapshot();
                }
            }

            Frame* overlayFrame = alarmFrame ? alarmFrame : pushFrame;
            if (overlayFrame) {
                cv::Mat overlayImage(height, width, CV_8UC3, overlayFrame->getBuf(), width * 3);
                drawWorkerOverlays(mControl.get(), overlayImage, happenDetects);
            }

            if (alarmFrame && pushFrame) {
                pushFrame->setBuf(alarmFrame->getBuf(), alarmFrame->getSize());
                pushFrame->clearAlarmRawSnapshot();
            }

            if (alarmFrame) {
                fillOutputMeta(alarmFrame, false);
                addAlarmVideoFrameQ(alarmFrame);
                alarmFrame = nullptr;
            }

            if (shouldPushFrame && pushFrame) {
                fillOutputMeta(pushFrame, true);
                mPushStream->addVideoFrame(pushFrame);
                if (nowMonoMs <= 0) {
                    nowMonoMs = getCurTime();
                }
                lastPushTimestamp = nowMonoMs;
                pushFrame = nullptr;
            }

            if (alarmFrame) {
                releaseDecodedFrame(alarmFrame);
            }
            if (pushFrame) {
                releaseDecodedFrame(pushFrame);
            }
            releaseDecodedFrame(sourceFrame);
        }
    }


	    void Worker::addAlarmVideoFrameQ(Frame* frame) {
	        if (!frame) {
	            return;
	        }
	        if (!mAlarmNeedFrames || mAlarmVideoQueueMaxFrames == 0) {
	            releaseFrame(frame);
	            return;
	        }
	        std::scoped_lock lock(mAlarmVideoFrameQ_mtx);

	        auto dropOnePreferNonEvidence = [&]() {
	            if (mAlarmVideoFrameQ.empty()) {
	                return false;
	            }
            // Prefer dropping the oldest non-evidence frame (happen=false) to keep evidence frames.
            auto it = std::find_if(mAlarmVideoFrameQ.begin(), mAlarmVideoFrameQ.end(),
                [](const Frame* f) { return f && !f->happen; });
            if (it == mAlarmVideoFrameQ.end()) {
                it = mAlarmVideoFrameQ.begin();
	            }
	            Frame* dropped = *it;
	            mAlarmVideoFrameQ.erase(it);
	            this->releaseFrame(dropped);
	            return true;
	        };

        uint64_t droppedCount = 0;
        while (mAlarmVideoFrameQ.size() >= mAlarmVideoQueueMaxFrames) {
            if (!dropOnePreferNonEvidence()) {
                break;
            }
            droppedCount++;
        }

        mAlarmVideoFrameQ.push_back(frame);

        if (droppedCount > 0 && mScheduler) {
            mScheduler->statsIncDroppedAlarmFrames(droppedCount);
        }
        mAlarmVideoFrameQ_cv.notify_one();

    }
    int Worker::getAlarmVideoFrameQSize() {
        std::scoped_lock lock(mAlarmVideoFrameQ_mtx);
        return static_cast<int>(mAlarmVideoFrameQ.size());
    }
    size_t Worker::getAlarmVideoQueueMaxFrames() {
        return mAlarmVideoQueueMaxFrames;
    }
    bool Worker::getAlarmVideoFrame(Frame*& frame) {
        std::unique_lock lock(mAlarmVideoFrameQ_mtx);
        mAlarmVideoFrameQ_cv.wait_for(lock, std::chrono::milliseconds(50), [this]() {
            return !getState() || !mAlarmVideoFrameQ.empty();
        });
        if (!mAlarmVideoFrameQ.empty()) {
            frame = mAlarmVideoFrameQ.front();
            mAlarmVideoFrameQ.pop_front();
            return true;
        }
        return false;
    }
    void Worker::clearAlarmVideoFrameQ() {

        std::scoped_lock lock(mAlarmVideoFrameQ_mtx);
	        while (!mAlarmVideoFrameQ.empty())
	        {
	            Frame* frame = mAlarmVideoFrameQ.front();
	            mAlarmVideoFrameQ.pop_front();
	            releaseFrame(frame);
	        }

    }

    bool Worker::startAlarmSession(Frame* triggerFrame) {
        if (!triggerFrame || mAlarmSession) {
            return false;
        }
        if (!mScheduler || !mScheduler->getConfig()) {
            return false;
        }

	        const Config* config = mScheduler->getConfig();
        std::string videoType = mControl->alarmVideoType;
        if (videoType.empty()) {
            videoType = "mp4";
        }
        std::string videoTypeLower = videoType;
        std::transform(videoTypeLower.begin(), videoTypeLower.end(), videoTypeLower.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        bool recordVideo = videoTypeLower != "none";
        int imageCount = mControl->alarmImageCount;
        if (imageCount < 0) {
            imageCount = 0;
        }

        std::string coverPos = mControl->alarmCoverPosition;
        std::transform(coverPos.begin(), coverPos.end(), coverPos.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (coverPos.empty()) {
            coverPos = "front";
        }
        if (coverPos != "front" && coverPos != "middle" && coverPos != "back" && coverPos != "custom") {
            coverPos = "front";
        }
        // If we are not recording alarm video, cover position is meaningless; fallback to front.
        if (!recordVideo) {
            coverPos = "front";
        }

        std::string baseDir = config->uploadDir + "/alarm";
        std::string controlDir = baseDir + "/" + mControl->code;
        std::string dirSuffix = getCurFormatTimeStr("%Y%m%d%H%M%S") + "_" + std::to_string(getRandomInt());
        std::string fullDir = controlDir + "/" + dirSuffix;
        try {
            std::filesystem::create_directories(fullDir);
        }
        catch (const std::filesystem::filesystem_error& e) {
            LOGE("startAlarmSession() create directories error: %s", e.what());
            return false;
        }

        std::string relativeDir = "alarm/" + mControl->code + "/" + dirSuffix;

        std::string videoExt = "mp4";
        if (videoTypeLower == "ts" || videoTypeLower == "mpegts") {
            videoExt = "ts";
        }
        else if (videoTypeLower == "flv") {
            videoExt = "flv";
        }

        std::string videoPathRel;
        std::string videoPathAbs;
        if (recordVideo) {
            videoPathRel = relativeDir + "/main." + videoExt;
            videoPathAbs = config->uploadDir + "/" + videoPathRel;
        }

	        const AlarmImageModeSpec alarmImageMode =
	            makeAlarmImageModeSpec(mControl ? mControl->alarmImageDrawMode : "boxed");
	        std::string imagePathRel;
	        std::string imagePathAbs;
	        std::string cleanImagePathRel;
	        std::string cleanImagePathAbs;
	        bool coverWritten = false;
	        bool cleanVariantWritten = false;
	        if (imageCount > 0) {
	            imagePathRel = relativeDir + "/main.jpg";
	            imagePathAbs = config->uploadDir + "/" + imagePathRel;
	            if (alarmImageMode.saveMainImageFromRawSnapshot) {
	                coverWritten = writeFrameImageFile(
	                    triggerFrame, mControl->videoWidth, mControl->videoHeight, imagePathAbs, true);
	            }
	            else if (coverPos == "front") {
	                coverWritten = writeFrameImageFile(
	                    triggerFrame, mControl->videoWidth, mControl->videoHeight, imagePathAbs, false);
	            }

	            if (alarmImageMode.saveCleanExtraImage) {
	                cleanImagePathRel = relativeDir + "/main_clean.jpg";
	                cleanImagePathAbs = config->uploadDir + "/" + cleanImagePathRel;
	                cleanVariantWritten = writeFrameImageFile(
	                    triggerFrame, mControl->videoWidth, mControl->videoHeight, cleanImagePathAbs, true);
	                if (!cleanVariantWritten) {
	                    cleanImagePathRel.clear();
	                    cleanImagePathAbs.clear();
	                }
	            }
	        }

	        Json::Value param;
	        param["control_code"] = mControl->code;
	        param["desc"] = "";
	        param["video_path"] = videoPathRel;
	        param["image_path"] = imagePathRel;
	        param["draw_type"] = alarmImageMode.mainImageDrawType;

        // ========== 扩展参数：布控配置信息 ==========
        param["algorithm_code"] = mControl->algorithmCode;
        param["object_code"] = mControl->objectCode;
        param["recognition_region"] = mControl->recognitionRegion;
        param["class_thresh"] = mControl->classThresh;
        param["overlap_thresh"] = mControl->overlapThresh;
        param["min_interval"] = static_cast<Json::Int64>(mControl->minInterval);
        if (triggerFrame->regionIndex >= 0) {
            param["region_index"] = triggerFrame->regionIndex; // 0-based
        }

	        Json::Value meta(Json::objectValue);
	        Json::Value userData = parseJsonObjectOrEmpty(triggerFrame ? triggerFrame->userDataJson : "");
	        if (!userData.empty()) {
	            meta["user_data"] = userData;
	        }
	        Json::Value detects = parseJsonArrayOrEmpty(triggerFrame ? triggerFrame->detectsJson : "");
	        if (!detects.empty()) {
	            meta["detects"] = detects;
	        }
	        if (!imagePathRel.empty()) {
	            meta["image_width"] = mControl->videoWidth;
	            meta["image_height"] = mControl->videoHeight;
	            Json::Value variants(Json::objectValue);
	            if (alarmImageMode.mainImageDrawType == 0) {
	                variants["clean"] = imagePathRel;
	                variants["labelme"] = imagePathRel;
	            }
	            else {
	                variants["boxed"] = imagePathRel;
	            }
	            if (!cleanImagePathRel.empty()) {
	                variants["clean"] = cleanImagePathRel;
	                variants["labelme"] = cleanImagePathRel;
	            }
	            if (!variants.empty()) {
	                meta["image_variants"] = variants;
	            }
	        }
	        if (!meta.empty()) {
	            param["metadata"] = meta;
	        }
	        if (!cleanImagePathRel.empty()) {
	            Json::Value extraImages(Json::arrayValue);
	            extraImages.append(cleanImagePathRel);
	            param["extra_images"] = extraImages;
	        }

        // ========== 扩展参数：视频流信息 ==========
        param["stream_code"] = mControl->streamCode;
        param["stream_app"] = mControl->streamApp;
        param["stream_name"] = mControl->streamName;
        param["stream_url"] = mControl->streamUrl;
        // ==========================================

        Json::StreamWriterBuilder wbuilder;
        wbuilder["indentation"] = "";
        wbuilder["emitUTF8"] = true;
        std::string data = Json::writeString(wbuilder, param);
        std::string url = config->adminHost + "/alarm/openAdd";
        if (mScheduler) {
            mScheduler->enqueueAlarmNotify(url, data, config->openApiToken);
        }
        LOGI("alarm notify queued url=%s", url.data());

        if (!recordVideo && imageCount <= 1) {
            return false;
        }

        mAlarmSession = std::make_unique<AlarmSession>();
        AlarmSession* session = mAlarmSession.get();
        session->recordVideo = recordVideo;
        session->regionIndex = triggerFrame->regionIndex;
        session->happenTimestampMs = getCurTimestamp();
        int fps = (mControl->videoFps > 0 ? mControl->videoFps : 25);
        int minFrames = 0;
        if (config->alarmVideoSeconds > 0) {
            minFrames = config->alarmVideoSeconds * fps;
        } else {
            minFrames = std::max(mAlarmPrefixFrames, config->alarmTotalFrames);
        }
        minFrames = std::max(mAlarmPrefixFrames, minFrames);
        session->totalFramesMin = minFrames;
        session->imageCount = imageCount;
        session->coverPosition = coverPos;
        session->coverCustomIndex = std::max(0, mControl->alarmCoverCustomIndex);
        session->coverWritten = coverWritten;
        session->imageSaved = (imageCount > 0 && coverWritten ? 1 : 0);
        session->imageInterval = (imageCount > 1 ? std::max(1, minFrames / imageCount) : 0);
        session->width = mControl->videoWidth;
        session->height = mControl->videoHeight;
        session->fps = fps;
        session->videoType = videoTypeLower;
        session->relativeDir = relativeDir;
        session->baseDirAbs = fullDir;
	        session->videoPathRel = videoPathRel;
	        session->videoPathAbs = videoPathAbs;
	        session->imagePathRel = imagePathRel;
	        session->imagePathAbs = imagePathAbs;
	        session->cleanImagePathRel = cleanImagePathRel;
	        session->cleanImagePathAbs = cleanImagePathAbs;
	        session->alarmImageDrawMode = alarmImageMode.mode;
	        session->mainImageDrawType = alarmImageMode.mainImageDrawType;
	        session->triggerUserDataJson = triggerFrame->userDataJson;
	        session->triggerDetectsJson = triggerFrame->detectsJson;
	        session->maxQueueSize = std::max<size_t>(5, std::min<size_t>(20, mAlarmVideoQueueMaxFrames));
        session->encodeThread = std::make_unique<std::thread>(&Worker::handleAlarmEncode, this, session);
        (void)session->encodeThread->native_handle();

        return true;
    }

    void Worker::enqueueAlarmFrame(AlarmSession* session, Frame* frame) {
        if (!session || !frame) {
            return;
        }
        std::unique_lock lock(session->queueMtx);
	        if (session->stop) {
	            lock.unlock();
	            releaseFrame(frame);
	            return;
	        }

	        auto dropOnePreferNonEvidence = [&]() {
	            if (session->frameQueue.empty()) {
	                return false;
	            }
            // Prefer dropping the oldest non-evidence frame to keep evidence frames.
            auto it = std::find_if(session->frameQueue.begin(), session->frameQueue.end(),
                [](const Frame* f) { return f && !f->happen; });
            if (it == session->frameQueue.end()) {
                it = session->frameQueue.begin();
	            }
	            Frame* dropped = *it;
	            session->frameQueue.erase(it);
	            this->releaseFrame(dropped);
	            if (mScheduler) {
	                mScheduler->statsIncDroppedAlarmFrames(1);
	            }
            return true;
        };

        while (session->frameQueue.size() >= session->maxQueueSize) {
            if (!dropOnePreferNonEvidence()) {
                break;
            }
        }

        session->frameQueue.push_back(frame);
        lock.unlock();
        session->queueCv.notify_one();
    }

    void Worker::stopAlarmSession(AlarmSession* session) {
        if (!session) {
            return;
        }
        {
            std::scoped_lock lock(session->queueMtx);
            session->stop = true;
        }
        session->queueCv.notify_one();
        if (session->encodeThread) {
            if (session->encodeThread->joinable()) {
                session->encodeThread->join();
            }
            session->encodeThread.reset();
        }
	        std::scoped_lock lock(session->queueMtx);
	        while (!session->frameQueue.empty()) {
	            Frame* frame = session->frameQueue.front();
	            session->frameQueue.pop_front();
	            releaseFrame(frame);
	        }
	    }

    void Worker::handleAlarmEncode(AlarmSession* session) {
        if (!session) {
            return;
        }
        uint64_t priorityGeneration = 0;
        maybeRefreshCurrentThreadPriority(priorityGeneration, "alarm_encode");

        bool recordVideo = session->recordVideo;
        AVFormatContext* fmtCtx = nullptr;
        AVCodecContext* videoCodecCtx = nullptr;
        AVStream* videoStream = nullptr;
        const AVCodec* videoCodec = nullptr;
        AVFrame* frame_yuv420p = nullptr;
        uint8_t* frame_yuv420p_buff = nullptr;
        AVPacket* pkt = nullptr;
        SwsContext* sws_ctx = nullptr;

        if (recordVideo && !session->videoPathAbs.empty()) {
            const char* formatName = "mp4";
            if (session->videoType == "ts" || session->videoType == "mpegts") {
                formatName = "mpegts";
            } else if (session->videoType == "flv") {
                formatName = "flv";
            }

            if (avformat_alloc_output_context2(&fmtCtx, nullptr, formatName, session->videoPathAbs.c_str()) < 0) {
                LOGE("alarm encoder: avformat_alloc_output_context2 error");
                recordVideo = false;
            }
        }

        if (recordVideo && fmtCtx) {
            videoCodec = avcodec_find_encoder(AV_CODEC_ID_H264);
            if (!videoCodec) {
                LOGE("alarm encoder: avcodec_find_encoder error");
                recordVideo = false;
            }
        }

	        if (recordVideo && fmtCtx && videoCodec) {
	            videoCodecCtx = avcodec_alloc_context3(videoCodec);
	            if (!videoCodecCtx) {
	                LOGE("alarm encoder: avcodec_alloc_context3 error");
	                recordVideo = false;
	            } else {
	                std::string profile = "balanced";
	                if (mScheduler && mScheduler->getConfig()) {
	                    profile = mScheduler->getConfig()->alarmEncodeProfile;
	                }
	                AlarmEncodeSettings settings = pickAlarmEncodeSettings(profile, session->width, session->height);
	                LOGI("alarm encoder: profile=%s bitrate=%d preset=%s tune=%s crf=%s bframes=%d lookahead=%d threads=%d",
	                     profile.c_str(), settings.bit_rate, settings.preset.c_str(), settings.tune.c_str(),
	                     settings.crf.c_str(), settings.max_b_frames, settings.rc_lookahead, settings.thread_count);

	                videoCodecCtx->rc_min_rate = settings.rc_min_rate;
	                videoCodecCtx->rc_max_rate = settings.rc_max_rate;
	                videoCodecCtx->bit_rate = settings.bit_rate;
	                videoCodecCtx->rc_buffer_size = settings.rc_buffer_size;
	                videoCodecCtx->codec_id = videoCodec->id;
	                videoCodecCtx->pix_fmt = AV_PIX_FMT_YUV420P;
	                videoCodecCtx->codec_type = AVMEDIA_TYPE_VIDEO;
	                videoCodecCtx->width = session->width;
	                videoCodecCtx->height = session->height;
	                videoCodecCtx->time_base = { 1, 1000 }; // ms timebase (PTS driven by Frame.timestampMs)
	                videoCodecCtx->framerate = { session->fps, 1 };
	                videoCodecCtx->gop_size = session->fps;
	                videoCodecCtx->max_b_frames = settings.max_b_frames;
	                videoCodecCtx->thread_count = settings.thread_count;
	                if (fmtCtx && (fmtCtx->oformat->flags & AVFMT_GLOBALHEADER)) {
	                    videoCodecCtx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
	                }

	                AVDictionary* video_codec_options = nullptr;
	                av_dict_set(&video_codec_options, "preset", settings.preset.c_str(), 0);
	                if (!settings.tune.empty()) {
	                    av_dict_set(&video_codec_options, "tune", settings.tune.c_str(), 0);
	                }
	                av_dict_set(&video_codec_options, "crf", settings.crf.c_str(), 0);
	                if (settings.rc_lookahead >= 0) {
	                    std::string lookahead = std::to_string(settings.rc_lookahead);
	                    av_dict_set(&video_codec_options, "rc-lookahead", lookahead.c_str(), 0);
	                }

	                if (avcodec_open2(videoCodecCtx, videoCodec, &video_codec_options) < 0) {
	                    LOGE("alarm encoder: avcodec_open2 error");
	                    recordVideo = false;
	                }
            }
        }

        if (recordVideo && fmtCtx && videoCodecCtx) {
            videoStream = avformat_new_stream(fmtCtx, videoCodec);
            if (!videoStream) {
                LOGE("alarm encoder: avformat_new_stream error");
                recordVideo = false;
            } else {
                videoStream->id = fmtCtx->nb_streams - 1;
                videoStream->time_base = videoCodecCtx->time_base;
                avcodec_parameters_from_context(videoStream->codecpar, videoCodecCtx);
                if (!(fmtCtx->oformat->flags & AVFMT_NOFILE) &&
                    avio_open(&fmtCtx->pb, session->videoPathAbs.c_str(), AVIO_FLAG_WRITE) < 0) {
                    LOGE("alarm encoder: avio_open error");
                    recordVideo = false;
                }
                if (recordVideo && avformat_write_header(fmtCtx, nullptr) < 0) {
                    LOGE("alarm encoder: avformat_write_header error");
                    recordVideo = false;
                }
            }
        }

        if (recordVideo && fmtCtx && videoCodecCtx) {
            frame_yuv420p = av_frame_alloc();
            frame_yuv420p->format = videoCodecCtx->pix_fmt;
            frame_yuv420p->width = session->width;
            frame_yuv420p->height = session->height;

            int frame_yuv420p_buff_size = av_image_get_buffer_size(AV_PIX_FMT_YUV420P, session->width, session->height, 1);
            frame_yuv420p_buff = (uint8_t*)av_malloc(frame_yuv420p_buff_size);
            av_image_fill_arrays(frame_yuv420p->data, frame_yuv420p->linesize,
                frame_yuv420p_buff,
                AV_PIX_FMT_YUV420P,
                session->width, session->height, 1);

            pkt = av_packet_alloc();

            sws_ctx = sws_getContext(session->width, session->height,
                AV_PIX_FMT_BGR24,
                session->width, session->height,
                AV_PIX_FMT_YUV420P,
                SWS_BILINEAR, nullptr, nullptr, nullptr);
            if (!sws_ctx) {
                LOGE("alarm encoder: sws_getContext error");
                recordVideo = false;
            }
        }

        // Encoder backpressure hardening:
        // - avcodec_send_frame may return EAGAIN when internal packet buffers are full.
        //   In that case we must drain receive_packet then retry, otherwise we drop frames.
	        const AlarmImageModeSpec alarmImageMode =
	            makeAlarmImageModeSpec(session ? session->alarmImageDrawMode : "boxed");
	        auto writeAlarmImage = [&](Frame* frame, const std::string& pathAbs, bool preferRawSnapshot) {
	            return writeFrameImageFile(frame, session ? session->width : 0, session ? session->height : 0, pathAbs, preferRawSnapshot);
	        };
	        int64_t frameCount = 0;
	        int extraIndex = 1;
	        const int64_t defaultFrameDurationMs = (session->fps > 0) ? std::max<int64_t>(1, 1000 / session->fps) : 40;
        const bool needCover = (session->imageCount > 0 && !session->imagePathAbs.empty());
        const std::string coverPos = session->coverPosition;
        int64_t coverTargetIndex = 0;
        if (needCover && !session->coverWritten && (coverPos == "middle" || coverPos == "custom")) {
            coverTargetIndex = std::max<int64_t>(1, session->totalFramesMin / 2);
            if (coverPos == "custom") {
                int64_t custom = session->coverCustomIndex;
                if (custom > 0) {
                    coverTargetIndex = custom;
                }
            }
            coverTargetIndex = std::max<int64_t>(1, std::min<int64_t>(session->totalFramesMin, coverTargetIndex));
        }
        Frame* lastFrameForCover = nullptr;
        while (true) {
            maybeRefreshCurrentThreadPriority(priorityGeneration, "alarm_encode");
            Frame* frame = nullptr;
            {
                std::unique_lock lock(session->queueMtx);
                session->queueCv.wait(lock, [session]() { return session->stop || !session->frameQueue.empty(); });
                if (session->frameQueue.empty()) {
                    if (session->stop) {
                        break;
                    }
                    continue;
                }
                frame = session->frameQueue.front();
                session->frameQueue.pop_front();
            }

            frameCount++;

	            // alarm cover (main.jpg) selection: middle/custom/back
	            if (needCover && !session->coverWritten && (coverPos == "middle" || coverPos == "custom") &&
	                coverTargetIndex > 0 && frameCount == coverTargetIndex) {
	                writeAlarmImage(frame, session->imagePathAbs, alarmImageMode.mode == "clean");
	                session->coverWritten = true;
	                if (session->imageSaved < session->imageCount) {
	                    session->imageSaved++;
	                }
	                if (lastFrameForCover) {
	                    releaseFrame(lastFrameForCover);
	                    lastFrameForCover = nullptr;
	                }
	            }

	            if (session->imageCount > session->imageSaved &&
	                session->imageInterval > 0 &&
	                (frameCount % session->imageInterval == 0)) {
	                std::string extra_path_abs = session->baseDirAbs + "/extra_" + std::to_string(extraIndex) + ".jpg";
	                writeAlarmImage(frame, extra_path_abs, alarmImageMode.mode == "clean");
	                session->imageSaved++;
	                extraIndex++;
            }

            if (recordVideo && videoCodecCtx && frame_yuv420p && sws_ctx) {
                int64_t tsMs = (frame->timestampMs > 0) ? frame->timestampMs : getCurTime();
                if (session->basePtsMs <= 0) {
                    session->basePtsMs = tsMs;
                }
                int64_t ptsMs = tsMs - session->basePtsMs;
                if (ptsMs < 0) {
                    ptsMs = 0;
                }
                if (session->lastPtsMs >= 0 && ptsMs <= session->lastPtsMs) {
                    ptsMs = session->lastPtsMs + 1;
                }
                session->lastPtsMs = ptsMs;

                const uint8_t* srcSlice[1] = { frame->getBuf() };
                int srcStride[1] = { session->width * 3 };
                sws_scale(sws_ctx, srcSlice, srcStride, 0, session->height,
                    frame_yuv420p->data, frame_yuv420p->linesize);

                frame_yuv420p->pts = frame_yuv420p->pkt_dts = ptsMs;
                frame_yuv420p->pkt_duration = defaultFrameDurationMs;

                if (sendAlarmEncoderFrame(recordVideo, videoCodecCtx, pkt, fmtCtx, videoStream, frame_yuv420p, "frame")) {
                    drainAlarmEncoderPackets(recordVideo, videoCodecCtx, pkt, fmtCtx, videoStream, "frame");
                }
            }

	            // Keep last frame for back-cover (or as a fallback if stream ends before target index).
	            if (needCover && !session->coverWritten && coverPos != "front") {
	                if (lastFrameForCover) {
	                    releaseFrame(lastFrameForCover);
	                }
	                lastFrameForCover = frame;
	                frame = nullptr;
	            }

	            if (frame) {
	                releaseFrame(frame);
	            }
	        }

	        if (needCover && !session->coverWritten && lastFrameForCover) {
	            writeAlarmImage(lastFrameForCover, session->imagePathAbs, alarmImageMode.mode == "clean");
	            session->coverWritten = true;
	            if (session->imageSaved < session->imageCount) {
	                session->imageSaved++;
            }
        }
	        if (lastFrameForCover) {
	            releaseFrame(lastFrameForCover);
	            lastFrameForCover = nullptr;
	        }

        if (recordVideo && videoCodecCtx && fmtCtx) {
            // Flush (NULL frame) with EAGAIN drain handling.
            (void)sendAlarmEncoderFrame(recordVideo, videoCodecCtx, pkt, fmtCtx, videoStream, nullptr, "flush");
            drainAlarmEncoderPackets(recordVideo, videoCodecCtx, pkt, fmtCtx, videoStream, "flush");
            av_write_trailer(fmtCtx);
        }

        // ========== 本地写入报警结果描述（result.json） ==========
        // 工业交付：本地报警目录内增加一个可离线解析的结果文件，便于取证/归档/二次开发。
        try {
            if (session && !session->baseDirAbs.empty()) {
                Json::Value param;
                param["control_code"] = mControl ? mControl->code : "";
                param["desc"] = "";
                param["video_path"] = session->videoPathRel;
                param["image_path"] = session->imagePathRel;

                // 扩展字段：布控配置信息
                param["algorithm_code"] = mControl ? mControl->algorithmCode : "";
                param["object_code"] = mControl ? mControl->objectCode : "";
                param["recognition_region"] = mControl ? mControl->recognitionRegion : "";
                param["class_thresh"] = mControl ? mControl->classThresh : 0.0f;
                param["overlap_thresh"] = mControl ? mControl->overlapThresh : 0.0f;
                param["min_interval"] = static_cast<Json::Int64>(mControl ? mControl->minInterval : 0);

                // 扩展字段：视频流信息
                param["stream_code"] = mControl ? mControl->streamCode : "";
                param["stream_app"] = mControl ? mControl->streamApp : "";
                param["stream_name"] = mControl ? mControl->streamName : "";
                param["stream_url"] = mControl ? mControl->streamUrl : "";

                // 扩展字段：生成信息
	                param["happen_timestamp_ms"] = static_cast<Json::Int64>(session->happenTimestampMs);
	                param["cover_position"] = session->coverPosition;
	                param["video_type"] = session->videoType;
	                param["image_count"] = session->imageCount;
	                param["draw_type"] = session->mainImageDrawType;
	                if (session->regionIndex >= 0) {
	                    param["region_index"] = session->regionIndex; // 0-based
	                }
	                if (!session->cleanImagePathRel.empty()) {
	                    Json::Value extraImages(Json::arrayValue);
	                    extraImages.append(session->cleanImagePathRel);
	                    param["extra_images"] = extraImages;
	                }

	                Json::Value meta(Json::objectValue);
	                Json::Value userData = parseJsonObjectOrEmpty(session->triggerUserDataJson);
	                if (!userData.empty()) {
	                    meta["user_data"] = userData;
	                }
	                Json::Value detects = parseJsonArrayOrEmpty(session->triggerDetectsJson);
	                if (!detects.empty()) {
	                    meta["detects"] = detects;
	                }
	                if (!session->imagePathRel.empty()) {
	                    meta["image_width"] = session->width;
	                    meta["image_height"] = session->height;
	                    Json::Value variants(Json::objectValue);
	                    if (session->mainImageDrawType == 0) {
	                        variants["clean"] = session->imagePathRel;
	                        variants["labelme"] = session->imagePathRel;
	                    }
	                    else {
	                        variants["boxed"] = session->imagePathRel;
	                    }
	                    if (!session->cleanImagePathRel.empty()) {
	                        variants["clean"] = session->cleanImagePathRel;
	                        variants["labelme"] = session->cleanImagePathRel;
	                    }
	                    if (!variants.empty()) {
	                        meta["image_variants"] = variants;
	                    }
	                }
	                if (!meta.empty()) {
	                    param["metadata"] = meta;
	                }

	                Json::StreamWriterBuilder file_builder;
                file_builder["indentation"] = "  ";
                file_builder["emitUTF8"] = true;
                const std::string file_json = Json::writeString(file_builder, param);

                const std::string result_json_path_abs = session->baseDirAbs + "/result.json";
                std::ofstream ofs(result_json_path_abs, std::ios::out | std::ios::binary);
                if (ofs.is_open()) {
                    ofs.write(file_json.data(), static_cast<std::streamsize>(file_json.size()));
                    ofs.close();
                }
            }
        }
        catch (...) { // NOSONAR
            // best-effort: never block alarm encoding
        }
        // ==========================================================

        if (pkt) {
            av_packet_unref(pkt);
            av_packet_free(&pkt);
        }
        if (frame_yuv420p_buff) {
            av_free(frame_yuv420p_buff);
        }
        if (frame_yuv420p) {
            av_frame_free(&frame_yuv420p);
        }
        if (sws_ctx) {
            sws_freeContext(sws_ctx);
        }
        if (fmtCtx) {
            if (!(fmtCtx->oformat->flags & AVFMT_NOFILE) && fmtCtx->pb) {
                avio_close(fmtCtx->pb);
            }
            avformat_free_context(fmtCtx);
        }
        if (videoCodecCtx) {
            avcodec_close(videoCodecCtx);
            avcodec_free_context(&videoCodecCtx);
        }
    }

}
