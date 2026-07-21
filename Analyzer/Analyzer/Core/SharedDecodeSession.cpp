#include "SharedDecodeSession.h"

#include "AvPullStream.h"
#include "Control.h"
#include "Scheduler.h"
#include "Worker.h"
#include "Utils/Common.h"
#include "Utils/Log.h"

#include <algorithm>

extern "C" {
#include "libswscale/swscale.h"
#include <libavutil/imgutils.h>
}

namespace AVSAnalyzer {

namespace {
struct DecodeBufferRefs {
    int& width;
    int& height;
    AVPixelFormat& inputPixFmt;
    int& frameBgrBuffSize;
    uint8_t*& frameBgrBuff;
    SwsContext*& swsCtx;
    AVFrame* frameBgr;
    Control* control;
    int64_t& lastRebuildMs;
    uint64_t& rebuildLogSeq;
};

bool rebuildDecodeBuffers(DecodeBufferRefs& refs, int newWidth, int newHeight, AVPixelFormat newPixFmt) {
    if (newWidth <= 0 || newHeight <= 0 || newPixFmt == AV_PIX_FMT_NONE) {
        return false;
    }

    const int64_t nowMs = getCurTime();
    if (refs.lastRebuildMs > 0 && (nowMs - refs.lastRebuildMs) < 500) {
        if (refs.rebuildLogSeq % 30 == 0) {
            LOGW("SharedDecodeSession::handleDecode: resolution flapping, skip rebuild "
                 "(old=%dx%d fmt=%d new=%dx%d fmt=%d)",
                 refs.width, refs.height, static_cast<int>(refs.inputPixFmt),
                 newWidth, newHeight, static_cast<int>(newPixFmt));
        }
        refs.rebuildLogSeq++;
        return false;
    }
    refs.lastRebuildMs = nowMs;

    const int newBgrBuffSize = av_image_get_buffer_size(AV_PIX_FMT_BGR24, newWidth, newHeight, 1);
    if (newBgrBuffSize <= 0) {
        LOGE("SharedDecodeSession::handleDecode: rebuild av_image_get_buffer_size failed: %d", newBgrBuffSize);
        return false;
    }

    auto* newBgrBuff = static_cast<uint8_t*>(av_malloc(newBgrBuffSize));
    if (!newBgrBuff) {
        LOGE("SharedDecodeSession::handleDecode: rebuild av_malloc failed: size=%d", newBgrBuffSize);
        return false;
    }

    SwsContext* newSwsCtx = sws_getContext(
        newWidth,
        newHeight,
        newPixFmt,
        newWidth,
        newHeight,
        AV_PIX_FMT_BGR24,
        SWS_BICUBIC,
        nullptr,
        nullptr,
        nullptr);
    if (!newSwsCtx) {
        LOGE("SharedDecodeSession::handleDecode: rebuild sws_getContext failed");
        av_free(newBgrBuff);
        return false;
    }

    const int oldWidth = refs.width;
    const int oldHeight = refs.height;
    const AVPixelFormat oldPixFmt = refs.inputPixFmt;

    if (refs.swsCtx) {
        sws_freeContext(refs.swsCtx);
    }
    if (refs.frameBgrBuff) {
        av_free(refs.frameBgrBuff);
    }

    refs.width = newWidth;
    refs.height = newHeight;
    refs.inputPixFmt = newPixFmt;
    refs.frameBgrBuffSize = newBgrBuffSize;
    refs.frameBgrBuff = newBgrBuff;
    refs.swsCtx = newSwsCtx;

    if (refs.control) {
        refs.control->videoWidth = newWidth;
        refs.control->videoHeight = newHeight;
        refs.control->videoChannel = 3;
    }

    av_image_fill_arrays(refs.frameBgr->data, refs.frameBgr->linesize, refs.frameBgrBuff, AV_PIX_FMT_BGR24, refs.width, refs.height, 1);
    LOGW("SharedDecodeSession::handleDecode: resolution/pix_fmt change: %dx%d fmt=%d -> %dx%d fmt=%d",
         oldWidth, oldHeight, static_cast<int>(oldPixFmt),
         newWidth, newHeight, static_cast<int>(newPixFmt));
    return true;
}
}  // namespace

SharedDecodeSession::SharedDecodeSession(Scheduler* scheduler, const std::string& key, const Control& control)
    : mScheduler(scheduler), mKey(key), mControl(std::make_unique<Control>(control)) {}

SharedDecodeSession::~SharedDecodeSession() {
    requestStop();

    for (auto& th : mThreads) {
        if (th.joinable()) {
            th.join();
        }
    }
    mThreads.clear();

    mPullStream.reset();

    if (mHasDecodeChannel && mScheduler) {
        mScheduler->releaseDecodeChannel();
        mHasDecodeChannel = false;
    }
}

bool SharedDecodeSession::start(std::string& msg) {
    if (!mControl) {
        msg = "shared decode control is null";
        return false;
	    }

	    try {
	        if (mControl->enableHardwareDecode && mScheduler) {
	            if (std::string channelErr; !mScheduler->reserveDecodeChannel(channelErr)) {
	                msg = "reserve shared decode channel failed: " + channelErr;
	                return false;
	            }
	            mHasDecodeChannel = true;
	        }

        auto pull = std::make_unique<AvPullStream>(
            mScheduler,
            mControl.get(),
            [this]() { return this->getState(); },
            [this]() { this->requestStop(); });

        if (!pull->connect()) {
            msg = "shared pull stream connect error";
            pull.reset();
            if (mHasDecodeChannel && mScheduler) {
                mScheduler->releaseDecodeChannel();
                mHasDecodeChannel = false;
            }
            return false;
        }

        mPullStream = std::move(pull);
        mState.store(true);

        mThreads.emplace_back(AvPullStream::readThread, mPullStream.get());
        mThreads.emplace_back(SharedDecodeSession::decodeThread, this);

        return true;
    }
    catch (const std::exception& ex) { // NOSONAR
        requestStop();
        for (auto& th : mThreads) {
            if (th.joinable()) {
                th.join();
            }
        }
        mThreads.clear();
        mPullStream.reset();
        if (mHasDecodeChannel && mScheduler) {
            mScheduler->releaseDecodeChannel();
            mHasDecodeChannel = false;
        }
        msg = std::string("shared decode session start exception: ") + ex.what();
        return false;
    }
    catch (...) { // NOSONAR
        requestStop();
        for (auto& th : mThreads) {
            if (th.joinable()) {
                th.join();
            }
        }
        mThreads.clear();
        mPullStream.reset();
        if (mHasDecodeChannel && mScheduler) {
            mScheduler->releaseDecodeChannel();
            mHasDecodeChannel = false;
        }
        msg = "shared decode session start exception: unknown";
        return false;
    }
}

void SharedDecodeSession::requestStop() {
    mState.store(false);
}

bool SharedDecodeSession::getState() const {
    return mState.load();
}

const std::string& SharedDecodeSession::getKey() const {
    return mKey;
}

	void SharedDecodeSession::subscribe(Worker* worker) {
	    if (!worker) {
	        return;
	    }
	    std::scoped_lock lock(mSubscribersMtx);
	    auto it = std::find(mSubscribers.begin(), mSubscribers.end(), worker);
	    if (it == mSubscribers.end()) {
	        mSubscribers.push_back(worker);
	    }
	}

	void SharedDecodeSession::unsubscribe(Worker* worker) {
	    if (!worker) {
	        return;
	    }
	    std::scoped_lock lock(mSubscribersMtx);
	    auto it = std::remove(mSubscribers.begin(), mSubscribers.end(), worker);
	    if (it != mSubscribers.end()) {
	        mSubscribers.erase(it, mSubscribers.end());
	    }
}

void SharedDecodeSession::copyVideoInfoTo(Control* control) const {
    if (!control || !mControl) {
        return;
    }
    control->videoWidth = mControl->videoWidth;
    control->videoHeight = mControl->videoHeight;
    control->videoChannel = mControl->videoChannel;
    control->videoIndex = mControl->videoIndex;
    control->videoFps = mControl->videoFps;
}

void SharedDecodeSession::decodeThread(SharedDecodeSession* arg) {
    auto* session = arg;
    try {
        if (session) {
            session->handleDecode();
        }
    }
    catch (const std::exception& ex) { // NOSONAR
        LOGE("SharedDecodeSession::decodeThread exception: %s", ex.what());
        if (session) {
            session->requestStop();
        }
    }
    catch (...) { // NOSONAR
        LOGE("SharedDecodeSession::decodeThread exception: unknown");
        if (session) {
            session->requestStop();
        }
    }
}

void SharedDecodeSession::handleDecode() {
    if (!mPullStream || !mControl) {
        LOGE("SharedDecodeSession::handleDecode: pull stream/control is null");
        requestStop();
        return;
    }

	    int width = 0;
	    int height = 0;
	    AVPixelFormat inputPixFmt = AV_PIX_FMT_NONE;
	    {
	        std::scoped_lock lock(mPullStream->mConnectMtx);
	        if (!mPullStream->mVideoCodecCtx) {
	            LOGE("SharedDecodeSession::handleDecode: video codec context is null");
	            requestStop();
	            return;
        }
        width = mPullStream->mVideoCodecCtx->width;
        height = mPullStream->mVideoCodecCtx->height;
        inputPixFmt = mPullStream->mVideoCodecCtx->pix_fmt;
    }
    if (width <= 0 || height <= 0 || inputPixFmt == AV_PIX_FMT_NONE) {
        LOGE("SharedDecodeSession::handleDecode: invalid decode params width=%d height=%d pix_fmt=%d",
             width, height, static_cast<int>(inputPixFmt));
        requestStop();
        return;
    }

    AVPacket* pkt = nullptr;
    int pktQSize = 0;

    AVFrame* frameYuv = av_frame_alloc();
    AVFrame* frameBgr = av_frame_alloc();
    if (!frameYuv || !frameBgr) {
        LOGE("SharedDecodeSession::handleDecode: av_frame_alloc failed");
        if (frameYuv) {
            av_frame_free(&frameYuv);
        }
        if (frameBgr) {
            av_frame_free(&frameBgr);
        }
        requestStop();
        return;
    }

    int frameBgrBuffSize = av_image_get_buffer_size(AV_PIX_FMT_BGR24, width, height, 1);
    if (frameBgrBuffSize <= 0) {
        LOGE("SharedDecodeSession::handleDecode: av_image_get_buffer_size failed: %d", frameBgrBuffSize);
        av_frame_free(&frameYuv);
        av_frame_free(&frameBgr);
        requestStop();
        return;
    }

    auto* frameBgrBuff = static_cast<uint8_t*>(av_malloc(frameBgrBuffSize));
    if (!frameBgrBuff) {
        LOGE("SharedDecodeSession::handleDecode: av_malloc failed: size=%d", frameBgrBuffSize);
        av_frame_free(&frameYuv);
        av_frame_free(&frameBgr);
        requestStop();
        return;
    }
    av_image_fill_arrays(frameBgr->data, frameBgr->linesize, frameBgrBuff, AV_PIX_FMT_BGR24, width, height, 1);

    SwsContext* swsCtx = sws_getContext(
        width,
        height,
        inputPixFmt,
        width,
        height,
        AV_PIX_FMT_BGR24,
        SWS_BICUBIC,
        nullptr,
        nullptr,
        nullptr);
    if (!swsCtx) {
        LOGE("SharedDecodeSession::handleDecode: sws_getContext failed");
        av_free(frameBgrBuff);
        av_frame_free(&frameYuv);
        av_frame_free(&frameBgr);
        requestStop();
        return;
    }

    int fps = mControl->videoFps;
    int64_t lastRebuildMs = 0;
    uint64_t rebuildLogSeq = 0;
    int continuityDecodeErrorCount = 0;
    DecodeBufferRefs decodeBufferRefs{
        width,
        height,
        inputPixFmt,
        frameBgrBuffSize,
        frameBgrBuff,
        swsCtx,
        frameBgr,
        mControl.get(),
        lastRebuildMs,
        rebuildLogSeq,
    };

    while (getState()) {
        if (!mPullStream->getVideoPkt(pkt, pktQSize)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }

        if (pktQSize > 5) {
            if (mScheduler) {
                mScheduler->statsIncDroppedDecodePackets(1);
            }
            mPullStream->releaseVideoPkt(pkt);
            continue;
        }

	        bool decoded = false;
	        bool sendOk = false;
	        int ret = -1;
	        {
	            std::scoped_lock lock(mPullStream->mConnectMtx);
	            if (!mPullStream->mVideoCodecCtx) {
	                ret = -1;
	            }
	            else {
                ret = avcodec_send_packet(mPullStream->mVideoCodecCtx, pkt);
                if (ret == 0) {
                    sendOk = true;
                    ret = avcodec_receive_frame(mPullStream->mVideoCodecCtx, frameYuv);
                    if (ret == 0) {
                        decoded = true;
                    }
                }
            }
        }

        if (decoded) {
            continuityDecodeErrorCount = 0;
            const int curW = frameYuv->width;
            const int curH = frameYuv->height;
            AVPixelFormat curFmt = inputPixFmt;
            if (frameYuv->format != AV_PIX_FMT_NONE) {
                curFmt = static_cast<AVPixelFormat>(frameYuv->format);
            }
            if (curW > 0 && curH > 0 && curFmt != AV_PIX_FMT_NONE &&
                (curW != width || curH != height || curFmt != inputPixFmt) &&
                !rebuildDecodeBuffers(decodeBufferRefs, curW, curH, curFmt)) {
                mPullStream->releaseVideoPkt(pkt);
                continue;
            }

            sws_scale(
                swsCtx,
                frameYuv->data,
                frameYuv->linesize,
                0,
                height,
                frameBgr->data,
                frameBgr->linesize);

            const int64_t frameMonoMs = getCurTime();
            if (mControl && mControl->videoFps > 0) {
                fps = mControl->videoFps;
            }
            fanOutDecodedFrame(frameBgr->data[0], frameBgrBuffSize, width, height, fps, pktQSize, frameMonoMs);
        }
        else {
            if (ret == -1) {
                LOGW("SharedDecodeSession::handleDecode: codec context not ready (reconnecting?)");
            }
            else if (!sendOk) {
                continuityDecodeErrorCount++;
                LOGE("SharedDecodeSession::handleDecode: avcodec_send_packet error (count=%d) ret=%d",
                     continuityDecodeErrorCount, ret);
            }
            else {
                continuityDecodeErrorCount++;
                LOGE("SharedDecodeSession::handleDecode: avcodec_receive_frame error (count=%d) ret=%d",
                     continuityDecodeErrorCount, ret);
            }

            const int kDecodeFailReconnectThreshold = 50;
            if (continuityDecodeErrorCount >= kDecodeFailReconnectThreshold) {
                if (mPullStream->requestReconnect()) {
                    LOGW("SharedDecodeSession::handleDecode: continuous failures reached threshold=%d, requested reconnect",
                         kDecodeFailReconnectThreshold);
                }
                continuityDecodeErrorCount = 0;
            }
        }

        mPullStream->releaseVideoPkt(pkt);
    }

    av_frame_free(&frameYuv);
    av_frame_free(&frameBgr);
    if (frameBgrBuff) {
        av_free(frameBgrBuff);
    }
    if (swsCtx) {
        sws_freeContext(swsCtx);
    }
}

void SharedDecodeSession::fanOutDecodedFrame(
    const unsigned char* buf,
    int size,
    int width,
    int height,
    int fps,
    int sourceQueueSize,
    int64_t timestampMs) {
	    if (!buf || size <= 0) {
	        return;
	    }

	    std::scoped_lock lock(mSubscribersMtx);
	    for (auto* worker : mSubscribers) {
	        if (!worker || !worker->getState()) {
	            continue;
	        }
        worker->enqueueDecodedFrame(buf, size, width, height, fps, sourceQueueSize, timestampMs);
    }
}

}  // namespace AVSAnalyzer
