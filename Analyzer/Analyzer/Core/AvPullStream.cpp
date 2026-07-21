#include "AvPullStream.h"
#include "Config.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include "Scheduler.h"
#include "Control.h"

#include <vector>

namespace AVSAnalyzer {
    AvPullStream::AvPullStream(
        Scheduler* scheduler,
        Control* control,
        std::function<bool()> getStateFn,
        std::function<void()> fatalHandler) :
        mScheduler(scheduler),
        mControl(control),
        mGetStateFn(std::move(getStateFn)),
        mFatalHandler(std::move(fatalHandler))
    {
        LOGI("");
    }

	    AvPullStream::~AvPullStream()
	    {
	        LOGI("");
	        try {
	            closeConnect();
	        }
	        catch (...) {
	        }
	        try {
	            clearPacketPool();
	        }
	        catch (...) {
	        }
	    }

	    bool AvPullStream::connect() {
	        Control* control = mControl;
	        if (!control) {
	            LOGE("pull stream control is null");
	            return false;
	        }
	
	        std::string streamUrl = control->streamUrl;
	        // Ensure previous state is fully released before (re)connecting.
	        closeConnect();

        AVDictionary* fmt_options = nullptr;
        av_dict_set(&fmt_options, "rtsp_transport", "tcp", 0); //设置rtsp底层网络协议 tcp or udp
        av_dict_set(&fmt_options, "stimeout", "10000000", 0);   //设置rtsp连接超时（单位 us）1秒=1000000
        av_dict_set(&fmt_options, "rw_timeout", "1000000", 0); //设置rtmp/http-flv连接超时（单位 us）
        //av_dict_set(&fmt_options, "timeout", "1000000", 0);//设置udp/http超时（单位 us）

        AVFormatContext* fmtCtx = nullptr;
        int ret = avformat_open_input(&fmtCtx, streamUrl.data(), nullptr, &fmt_options);
        av_dict_free(&fmt_options);

        if (ret != 0) {
            LOGE("avformat_open_input error: url=%s ret=%d", streamUrl.data(), ret);
            if (fmtCtx) {
                avformat_free_context(fmtCtx);
                fmtCtx = nullptr;
            }
            return false;
        }


        if (avformat_find_stream_info(fmtCtx, nullptr) < 0) {
            LOGE("avformat_find_stream_info error");
            avformat_close_input(&fmtCtx);
            return false;
        }

        // video start
        int videoIndex = av_find_best_stream(fmtCtx, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);


	        if (videoIndex > -1) {
	            const AVCodecParameters* videoCodecPar = fmtCtx->streams[videoIndex]->codecpar;

            const AVCodec* videoCodec = nullptr;
            if (!videoCodec) {
                videoCodec = avcodec_find_decoder(videoCodecPar->codec_id);
                if (!videoCodec) {
                    LOGE("avcodec_find_decoder error");
                    avformat_close_input(&fmtCtx);
                    return false;
                }
            }

            AVCodecContext* videoCodecCtx = avcodec_alloc_context3(videoCodec);
            if (!videoCodecCtx) {
                LOGE("avcodec_alloc_context3 error");
                avformat_close_input(&fmtCtx);
                return false;
            }

	            if (avcodec_parameters_to_context(videoCodecCtx, videoCodecPar) != 0) {
	                LOGE("avcodec_parameters_to_context error");
	                avcodec_free_context(&videoCodecCtx);
	                avformat_close_input(&fmtCtx);
	                return false;
	            }
		            // 控制解码线程数，避免大规模布控时 FFmpeg 内部线程爆炸
		            if (mScheduler && mScheduler->getConfig()) {
		                int decodeThreads = mScheduler->getConfig()->ffmpegDecodeThreadCount;
		                if (decodeThreads > 0) {
		                    videoCodecCtx->thread_count = decodeThreads;
		                }
		            }

		            // v4.633: optional FFmpeg fast decode knobs (quality tradeoffs).
		            // Only touches decoder-side flags; does not change algorithm semantics.
		            if (control) {
		                if (control->ffmpegSkipLoopFilter) {
		                    videoCodecCtx->skip_loop_filter = AVDISCARD_ALL;
		                }
		                if (control->ffmpegSkipIdct) {
		                    videoCodecCtx->skip_idct = AVDISCARD_ALL;
		                }
		            }
	            if (avcodec_open2(videoCodecCtx, videoCodec, nullptr) < 0) {
	                LOGE("avcodec_open2 error");
	                avcodec_free_context(&videoCodecCtx);
	                avformat_close_input(&fmtCtx);
	                return false;
	            }
            AVStream* videoStream = fmtCtx->streams[videoIndex];
		            if (0 == videoStream->avg_frame_rate.den) {
	
		                LOGE("videoIndex=%d,videoStream->avg_frame_rate.den = 0", videoIndex);
	
		                control->videoFps = 25;
		            }
		            else {
		                control->videoFps = videoStream->avg_frame_rate.num / videoStream->avg_frame_rate.den;
		            }


	            control->videoWidth = videoCodecCtx->width;
	            control->videoHeight = videoCodecCtx->height;
	            control->videoChannel = 3;
	            control->videoIndex = videoIndex;

	            {
	                std::scoped_lock lock(mConnectMtx);
	                mFmtCtx = fmtCtx;
	                mVideoCodecCtx = videoCodecCtx;
	                mVideoStream = videoStream;
	            }

        }
        else {
            LOGE("av_find_best_stream video error videoIndex=%d", videoIndex);
            avformat_close_input(&fmtCtx);
            return false;
        }
        // Video initialization end.


        // audio start

        // audio end


	        if (control->videoIndex <= -1) {
	            return false;
	        }

        mConnectCount++;

        return true;

    }

    bool AvPullStream::reConnect() {
        if (mScheduler) {
            mScheduler->statsIncPullReconnectAttempts(1);
        }

        if (connect()) {
            LOGI("Reconnect success after %d attempts", mConnectCount);
            if (mScheduler) {
                mScheduler->statsIncPullReconnectSuccess(1);
            }
            return true;
        }
        else {
            LOGW("Reconnect failed, will retry... (attempt #%d)", mConnectCount);
            return false; // 调用方循环决定继续重试
        }
    }
    void AvPullStream::closeConnect() {

        LOGI("");

        clearVideoPktQueue();

	        std::this_thread::sleep_for(std::chrono::milliseconds(1));

	        std::scoped_lock lock(mConnectMtx);
	        if (mVideoCodecCtx) {

            avcodec_close(mVideoCodecCtx);
            avcodec_free_context(&mVideoCodecCtx);
            mVideoCodecCtx = nullptr;
            if (mControl) {
                mControl->videoIndex = -1;
            }
        }

        if (mFmtCtx) {
            // Pull stream cleanup uses avformat_close_input directly.
            avformat_close_input(&mFmtCtx);
            mFmtCtx = nullptr;
        }
        mVideoStream = nullptr;
    }

    bool AvPullStream::pushVideoPkt(AVPacket* pkt) {
        if (!pkt) {
            return false;
        }
        // 防止队列无限增长导致内存溢出 - 丢弃旧帧策略
        uint64_t dropped = 0;
        std::vector<AVPacket*> toRelease;

        {
            std::scoped_lock lock(mVideoPktQ_mtx);
            while (mVideoPktQ.size() >= MAX_VIDEO_PKT_QUEUE_SIZE) {
                AVPacket* oldPkt = mVideoPktQ.front();
                mVideoPktQ.pop();
                toRelease.push_back(oldPkt);
                mDropPktLogCount++;
                dropped++;
                if (mDropPktLogCount % 30 == 1) {
                    LOGW("Video packet queue full, dropping old frame. Queue size: %d", MAX_VIDEO_PKT_QUEUE_SIZE);
                }
            }

            mVideoPktQ.push(pkt);
        }

        for (AVPacket* oldPkt : toRelease) {
            releaseVideoPkt(oldPkt);
        }

        if (dropped > 0 && mScheduler) {
            mScheduler->statsIncDroppedPullPackets(dropped);
        }

        return true;

    }
    bool AvPullStream::getVideoPkt(AVPacket*& pkt, int& pktQSize) {

        std::scoped_lock lock(mVideoPktQ_mtx);
        if (mVideoPktQ.empty()) {
            return false;
        }
        pkt = mVideoPktQ.front();
        mVideoPktQ.pop();
        pktQSize = static_cast<int>(mVideoPktQ.size());
        return true;

	    }
	    int AvPullStream::getVideoPktQSize() {
	        std::scoped_lock lock(mVideoPktQ_mtx);
	        return static_cast<int>(mVideoPktQ.size());
	    }
    void AvPullStream::clearVideoPktQueue() {
        std::queue<AVPacket*> local;
        {
            std::scoped_lock lock(mVideoPktQ_mtx);
            local.swap(mVideoPktQ);
        }
        while (!local.empty()) {
            AVPacket* pkt = local.front();
            local.pop();
            releaseVideoPkt(pkt);
        }
	    }
	    AVPacket* AvPullStream::acquirePacket() {
	        std::scoped_lock lock(mPktPool_mtx);
	        if (!mPktPool.empty()) {
	            AVPacket* pkt = mPktPool.front();
	            mPktPool.pop();
	            return pkt;
        }
	        return av_packet_alloc();
	    }
	    void AvPullStream::releaseVideoPkt(AVPacket* pkt) {
        if (!pkt) {
            return;
	        }
	        av_packet_unref(pkt);
	        std::scoped_lock lock(mPktPool_mtx);
	        if (mPktPool.size() >= MAX_PACKET_POOL_SIZE) {
	            av_packet_free(&pkt);
	            return;
	        }
	        mPktPool.push(pkt);
	    }
	    void AvPullStream::clearPacketPool() {
	        std::scoped_lock lock(mPktPool_mtx);
	        while (!mPktPool.empty()) {
	            AVPacket* pkt = mPktPool.front();
	            mPktPool.pop();
	            av_packet_free(&pkt);
	    }
    }
	    void AvPullStream::handleRead() {
	        int continuity_error_count = 0;

	        while (!mGetStateFn || mGetStateFn())
	        {
	            if (mReconnectRequested.consume()) {
	                continuity_error_count++;
	                int backoffMs = std::min(continuity_error_count * 1000, 30000);
	                LOGW("Reconnect requested by decoder (count=%d), backoff %d ms then reconnect", continuity_error_count, backoffMs);
	                std::this_thread::sleep_for(std::chrono::milliseconds(backoffMs));
	                if (reConnect()) {
	                    continuity_error_count = 0;
	                    LOGI("reConnect success : mConnectCount=%d", mConnectCount);
	                }
	                continue;
	            }

	            if (!mFmtCtx) {
	                continuity_error_count++;
	                if (mScheduler) {
	                    mScheduler->statsIncPullReadErrors(1);
	                }
                int backoffMs = std::min(continuity_error_count * 1000, 30000);
                LOGW("Pull stream not connected (count=%d), backoff %d ms then reconnect", continuity_error_count, backoffMs);
                std::this_thread::sleep_for(std::chrono::milliseconds(backoffMs));

                if (reConnect()) {
                    continuity_error_count = 0;
                    LOGI("reConnect success : mConnectCount=%d", mConnectCount);
                }
                continue;
            }

            AVPacket* pkt = acquirePacket();
            if (!pkt) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            if (av_read_frame(mFmtCtx, pkt) >= 0) {
                continuity_error_count = 0;

                if (mControl && pkt->stream_index == mControl->videoIndex) {
                    pushVideoPkt(pkt);

                    std::this_thread::sleep_for(std::chrono::milliseconds(1));
                }
                else {
                    releaseVideoPkt(pkt);
                }
            }
            else {
                releaseVideoPkt(pkt);
                continuity_error_count++;
                if (mScheduler) {
                    mScheduler->statsIncPullReadErrors(1);
                }
                // 连续读取失败时采用无限重试+退避
                int backoffMs = std::min(continuity_error_count * 1000, 30000);
                LOGW("av_read_frame error (count=%d), backoff %d ms then reconnect", continuity_error_count, backoffMs);
                std::this_thread::sleep_for(std::chrono::milliseconds(backoffMs));

                if (reConnect()) {
                    continuity_error_count = 0;
                    LOGI("reConnect success : mConnectCount=%d", mConnectCount);
                }
            }
        }

    }
    void AvPullStream::readThread(AvPullStream* arg) {
        auto* pullStream = arg;
        try {
            pullStream->handleRead();
        }
	        catch (const std::exception& ex) { // NOSONAR
	            LOGE("AvPullStream::readThread exception: %s", ex.what());
	            if (pullStream && pullStream->mFatalHandler) {
	                pullStream->mFatalHandler();
	            }
	        }
	        catch (...) { // NOSONAR
	            LOGE("AvPullStream::readThread exception: unknown");
	            if (pullStream && pullStream->mFatalHandler) {
	                pullStream->mFatalHandler();
	            }
	        }
    }
}
