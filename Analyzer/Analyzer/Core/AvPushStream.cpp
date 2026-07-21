#include "AvPushStream.h"
#include "Config.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include "Control.h"
#include "Frame.h"
#include "Worker.h"
#include "Analyzer.h"
#include "Scheduler.h"
#include "Utils/Pts.h"
#include <opencv2/opencv.hpp>
#if defined(__has_include)
#  if __has_include(<opencv2/freetype.hpp>)
#    include <opencv2/freetype.hpp> // Optional (opencv_contrib)
#  endif
#endif
#include <filesystem>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <ctime>
#include <stdexcept>
extern "C" {
#include "libswscale/swscale.h"
#include <libavutil/imgutils.h>
#include <libavutil/error.h>
#include <libswresample/swresample.h>
}
#ifdef _MSC_VER
#pragma warning(disable: 4996)
#endif

namespace AVSAnalyzer {
    namespace {
        bool fontFileExists(const std::string& path) {
            if (path.empty()) {
                return false;
            }
            std::error_code ec;
            return std::filesystem::exists(std::filesystem::path(path), ec);
        }

        std::string pickFreeTypeFontPath() {
#ifdef _WIN32
            const char* candidates[] = {
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
            };
#else
            const char* candidates[] = {
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            };
#endif
            for (const char* candidate : candidates) {
                if (candidate && fontFileExists(candidate)) {
                    return std::string(candidate);
                }
            }
            return "";
        }
    }

    AvPushStream::AvPushStream(Worker* worker) :
        mWorker(worker)
    {
        LOGI("");
    }

    AvPushStream::~AvPushStream()
    {
        LOGI("");
        closeConnect();
        clearVideoFrameQueue();
    }


    bool AvPushStream::connect() {

        std::string pushStreamUrl = mWorker->mControl->pushStreamUrl;
        int videoWidth = mWorker->mControl->videoWidth;
        int videoHeight = mWorker->mControl->videoHeight;
        int videoFps = mWorker->mControl->videoFps;

        // Ensure previous state is fully released before (re)connecting.
        closeConnect();

        // ========== 使用配置的推流参数 ==========
        std::string pushVideoCodec = mWorker->mControl->pushVideoCodec;
        int pushVideoBitrate = mWorker->mControl->pushVideoBitrate;  // kbps
        int pushVideoFps = mWorker->mControl->pushVideoFps;
        int pushVideoWidth = mWorker->mControl->pushVideoWidth;
        int pushVideoHeight = mWorker->mControl->pushVideoHeight;
        int pushVideoGop = mWorker->mControl->pushVideoGop;
        // ========================================
        if (pushVideoBitrate <= 0) {
            pushVideoBitrate = 2000;
        }
        if (pushVideoFps <= 0) {
            pushVideoFps = (videoFps > 0) ? videoFps : 25;
        }
        if (pushVideoWidth <= 0) {
            pushVideoWidth = (videoWidth > 0) ? videoWidth : 1280;
        }
        if (pushVideoHeight <= 0) {
            pushVideoHeight = (videoHeight > 0) ? videoHeight : 720;
        }
        if (pushVideoGop <= 0) {
            pushVideoGop = std::max(1, pushVideoFps * 2);
        }

        if (avformat_alloc_output_context2(&mFmtCtx, nullptr, "rtsp", pushStreamUrl.data()) < 0) {
            LOGI("avformat_alloc_output_context2 error: pushStreamUrl=%s", pushStreamUrl.data());
            return false;
        }

        // init video start
        // ========== 根据配置选择编码器 ==========
        AVCodecID codecId = AV_CODEC_ID_H264;  // 默认 H.264
        if (pushVideoCodec == "h265" || pushVideoCodec == "hevc") {
            codecId = AV_CODEC_ID_H265;
        } else if (pushVideoCodec == "vp8") {
            codecId = AV_CODEC_ID_VP8;
        } else if (pushVideoCodec == "vp9") {
            codecId = AV_CODEC_ID_VP9;
        }

        const AVCodec* videoCodec = avcodec_find_encoder(codecId);
        if (!videoCodec) {
            LOGI("avcodec_find_encoder error: codec=%s, pushStreamUrl=%s", pushVideoCodec.c_str(), pushStreamUrl.data());
            closeConnect();
            return false;
        }
        LOGI("Push stream using codec: %s, resolution: %dx%d, bitrate: %d kbps, fps: %d, gop: %d",
             pushVideoCodec.c_str(), pushVideoWidth, pushVideoHeight, pushVideoBitrate, pushVideoFps, pushVideoGop);
        // ========================================
        mVideoCodecCtx = avcodec_alloc_context3(videoCodec);
        if (!mVideoCodecCtx) {
            LOGI("avcodec_alloc_context3 error: pushStreamUrl=%s", pushStreamUrl.data());
            closeConnect();
            return false;
        }

        // ========== 使用配置的码率参数 ==========
        int bit_rate = pushVideoBitrate * 1000;  // kbps 转换为 bps
        // VBR: Variable BitRate - 可变码率
        mVideoCodecCtx->flags |= AV_CODEC_FLAG_QSCALE;
        mVideoCodecCtx->rc_min_rate = bit_rate / 2;
        mVideoCodecCtx->rc_max_rate = bit_rate / 2 + bit_rate;
        mVideoCodecCtx->bit_rate = bit_rate;
        // ========================================

        mVideoCodecCtx->codec_id = videoCodec->id;
        mVideoCodecCtx->pix_fmt = AV_PIX_FMT_YUV420P;
        mVideoCodecCtx->codec_type = AVMEDIA_TYPE_VIDEO;

        // ========== 使用配置的分辨率和帧率 ==========
        mVideoCodecCtx->width = pushVideoWidth;
        mVideoCodecCtx->height = pushVideoHeight;
        // Use ms timebase, PTS driven by Frame.timestampMs (monotonic ms).
        mVideoCodecCtx->time_base = { 1, 1000 };
        mVideoCodecCtx->framerate = { pushVideoFps, 1 };
        mVideoCodecCtx->gop_size = pushVideoGop;
        // ========================================

        mVideoCodecCtx->max_b_frames = 0;
        // 控制编码线程数，避免大规模布控时 FFmpeg 内部线程爆炸
        int encodeThreads = 0;
        if (mWorker && mWorker->mScheduler && mWorker->mScheduler->getConfig()) {
            encodeThreads = mWorker->mScheduler->getConfig()->ffmpegEncodeThreadCount;
        }
        if (encodeThreads > 0) {
            mVideoCodecCtx->thread_count = encodeThreads;
        }
        mVideoCodecCtx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;   //添加PPS、SPS
        AVDictionary* video_codec_options = nullptr;

        //H.264
        if (mVideoCodecCtx->codec_id == AV_CODEC_ID_H264) {
            av_dict_set(&video_codec_options, "preset", "superfast", 0);
            av_dict_set(&video_codec_options, "tune", "zerolatency", 0);
        }
        //H.265
        if (mVideoCodecCtx->codec_id == AV_CODEC_ID_H265) {
            av_dict_set(&video_codec_options, "preset", "ultrafast", 0);
            av_dict_set(&video_codec_options, "tune", "zero-latency", 0);
        }
        if (avcodec_open2(mVideoCodecCtx, videoCodec, &video_codec_options) < 0) {
            LOGI("avcodec_open2 error: pushStreamUrl=%s", pushStreamUrl.data());
            av_dict_free(&video_codec_options);
            closeConnect();
            return false;
        }
        av_dict_free(&video_codec_options);
        mVideoStream = avformat_new_stream(mFmtCtx, videoCodec);
        if (!mVideoStream) {
            LOGI("avformat_new_stream error: pushStreamUrl=%s", pushStreamUrl.data());
            closeConnect();
            return false;
        }
        mVideoStream->id = mFmtCtx->nb_streams - 1;
        // stream的time_base参数非常重要，它表示将现实中的一秒钟分为多少个时间基, 在下面调用avformat_write_header时自动完成
        avcodec_parameters_from_context(mVideoStream->codecpar, mVideoCodecCtx);
        mVideoIndex = mVideoStream->id;
        // init video end

        av_dump_format(mFmtCtx, 0, pushStreamUrl.data(), 1);

        // open output url
        if (!(mFmtCtx->oformat->flags & AVFMT_NOFILE) &&
            (avio_open(&mFmtCtx->pb, pushStreamUrl.data(), AVIO_FLAG_WRITE) < 0)) {
            LOGI("avio_open error: pushStreamUrl=%s",pushStreamUrl.data());
            closeConnect();
            return false;
        }


        AVDictionary* fmt_options = nullptr;
        av_dict_set(&fmt_options, "rw_timeout", "30000000", 0); //设置rtmp/http-flv连接超时（单位 us）
        av_dict_set(&fmt_options, "stimeout", "30000000", 0);   //设置rtsp连接超时（单位 us）
        av_dict_set(&fmt_options, "rtsp_transport", "tcp", 0);

        mFmtCtx->video_codec_id = mFmtCtx->oformat->video_codec;

        if (avformat_write_header(mFmtCtx, &fmt_options) < 0) { // 调用该函数会将所有stream的time_base，自动设置一个值，通常是1/90000或1/1000，这表示一秒钟表示的时间基长度
            LOGI("avformat_write_header error: pushStreamUrl=%s", pushStreamUrl.data());
            av_dict_free(&fmt_options);
            closeConnect();
            return false;
        }
        av_dict_free(&fmt_options);

        mConnectCount++;

        return true;
    }
    bool AvPushStream::reConnect() {
        if (mWorker && mWorker->mScheduler) {
            mWorker->mScheduler->statsIncPushReconnectAttempts(1);
        }

        if (connect()) {
            LOGI("Push stream reconnect success after %d attempts", mConnectCount);
            if (mWorker && mWorker->mScheduler) {
                mWorker->mScheduler->statsIncPushReconnectSuccess(1);
            }
            return true;
        }
        else {
            LOGW("Push stream reconnect failed, will retry... (attempt #%d)", mConnectCount);
            return false;
        }

    }
    void AvPushStream::closeConnect() {
        LOGI("");

        clearVideoFrameQueue();

        std::this_thread::sleep_for(std::chrono::milliseconds(1));

        if (mFmtCtx) {
            // 推流需要释放start
            if (mFmtCtx && !(mFmtCtx->oformat->flags & AVFMT_NOFILE) && mFmtCtx->pb) {
                avio_close(mFmtCtx->pb);
                mFmtCtx->pb = nullptr;
            }
            // 推流需要释放end


            avformat_free_context(mFmtCtx);
            mFmtCtx = nullptr;
        }

        if (mVideoCodecCtx) {
            if (mVideoCodecCtx->extradata) {
                av_free(mVideoCodecCtx->extradata);
                mVideoCodecCtx->extradata = nullptr;
            }

            avcodec_close(mVideoCodecCtx);
            avcodec_free_context(&mVideoCodecCtx);
            mVideoCodecCtx = nullptr;
            mVideoIndex = -1;
        }
        mVideoStream = nullptr;
    }

	    void AvPushStream::addVideoFrame(Frame* frame) {
	        std::unique_lock lock(mVideoFrameQ_mtx);

        // 当生产速度快于编码/推流速度时，主动丢弃最旧帧，避免堆积导致内存飙升或卡死
        uint64_t dropped = 0;
        while (mVideoFrameQ.size() >= MAX_VIDEO_FRAME_QUEUE_SIZE) {
            Frame* drop = mVideoFrameQ.front();
            mVideoFrameQ.pop();
            mWorker->mVideoFramePool->giveBack(drop);
            mDropFrameLogCount++;
            dropped++;
            if (mDropFrameLogCount % 30 == 1) {
                LOGW("Video frame queue full (%d), drop oldest to relieve back-pressure", MAX_VIDEO_FRAME_QUEUE_SIZE);
            }
        }

        mVideoFrameQ.push(frame);
        mVideoFrameQ_cv.notify_one();

        if (dropped > 0 && mWorker && mWorker->mScheduler) {
            mWorker->mScheduler->statsIncDroppedPushFrames(dropped);
        }
    }
		    int AvPushStream::getVideoFrameQSize() {
		        std::scoped_lock lock(mVideoFrameQ_mtx);
		        return static_cast<int>(mVideoFrameQ.size());
		    }

	    bool AvPushStream::getVideoFrame(Frame*& frame) {
	        std::unique_lock lock(mVideoFrameQ_mtx);
	        // Avoid busy-loop when queue is empty (weak machines / many streams).
	        mVideoFrameQ_cv.wait_for(lock, std::chrono::milliseconds(50), [this]() {
	            return !mWorker || !mWorker->getState() || !mVideoFrameQ.empty();
	        });

        if (!mVideoFrameQ.empty()) {
            frame = mVideoFrameQ.front();
            mVideoFrameQ.pop();
            return true;
        }

        return false;

    }
	    void AvPushStream::clearVideoFrameQueue() {

	        std::scoped_lock lock(mVideoFrameQ_mtx);
	        while (!mVideoFrameQ.empty())
	        {
	            Frame* frame = mVideoFrameQ.front();
	            mVideoFrameQ.pop();
	            mWorker->mVideoFramePool->giveBack(frame);
	        }
	    }

    void AvPushStream::renderOSDImage(cv::Mat& frame) {
        if (!mWorker || !mWorker->mControl) {
            return;
        }

        const Control* control = mWorker->mControl.get();
        if (control->osdImagePath.empty()) {
            return;
        }
        if (control->osdImageAlpha <= 0.0f) {
            return;
        }
        if (frame.empty() || frame.type() != CV_8UC3) {
            return;
        }

        const int x = control->osdImageX;
        const int y = control->osdImageY;
        const float scale = (control->osdImageScale > 0.0f) ? control->osdImageScale : 1.0f;
        const float globalAlpha = std::min(1.0f, std::max(0.0f, control->osdImageAlpha));

        // Cache per thread (each push thread renders its own frames).
        static thread_local std::string cachedPath;
        static thread_local float cachedScale = -1.0f;
        static thread_local cv::Mat cachedBgra; // scaled BGRA
        static thread_local int cachedLoadFailures = 0;

        if (cachedPath != control->osdImagePath || std::fabs(cachedScale - scale) > 1e-6f) {
            cachedPath = control->osdImagePath;
            cachedScale = scale;
            cachedBgra.release();

            cv::Mat img = cv::imread(control->osdImagePath, cv::IMREAD_UNCHANGED);
            if (img.empty()) {
                // Avoid per-frame log spam.
                if (cachedLoadFailures % 60 == 0) {
                    LOGW("OSD image load failed: %s", control->osdImagePath.c_str());
                }
                cachedLoadFailures++;
                return;
            }

            if (scale != 1.0f) {
	                try {
	                    cv::resize(img, img, cv::Size(), scale, scale, cv::INTER_AREA);
	                }
	                catch (const cv::Exception&) {
	                    // fallback to unscaled
	                }
	            }

            if (img.channels() == 4) {
                cachedBgra = img;
            }
            else if (img.channels() == 3) {
                cv::cvtColor(img, cachedBgra, cv::COLOR_BGR2BGRA);
            }
            else if (img.channels() == 1) {
                cv::cvtColor(img, cachedBgra, cv::COLOR_GRAY2BGRA);
            }
            else {
                LOGW("OSD image unsupported channel count: %d", img.channels());
                return;
            }

            cachedLoadFailures = 0;
        }

        if (cachedBgra.empty()) {
            return;
        }

        const int imgW = cachedBgra.cols;
        const int imgH = cachedBgra.rows;
        if (imgW <= 0 || imgH <= 0) {
            return;
        }

        int dstX0 = std::max(0, x);
        int dstY0 = std::max(0, y);
        int dstX1 = std::min(frame.cols, x + imgW);
        int dstY1 = std::min(frame.rows, y + imgH);

        if (dstX0 >= dstX1 || dstY0 >= dstY1) {
            return;
        }

        const int srcX0 = dstX0 - x;
        const int srcY0 = dstY0 - y;
        const int copyW = dstX1 - dstX0;
        const int copyH = dstY1 - dstY0;

        for (int row = 0; row < copyH; ++row) {
            cv::Vec3b* dst = frame.ptr<cv::Vec3b>(dstY0 + row) + dstX0;
            const cv::Vec4b* src = cachedBgra.ptr<cv::Vec4b>(srcY0 + row) + srcX0;
            for (int col = 0; col < copyW; ++col) {
                const float a = (static_cast<float>(src[col][3]) / 255.0f) * globalAlpha;
                if (a <= 0.0f) {
                    continue;
                }
                const float ia = 1.0f - a;
                dst[col][0] = static_cast<unsigned char>(dst[col][0] * ia + src[col][0] * a);
                dst[col][1] = static_cast<unsigned char>(dst[col][1] * ia + src[col][1] * a);
                dst[col][2] = static_cast<unsigned char>(dst[col][2] * ia + src[col][2] * a);
            }
        }
    }

    // ========== OSD 渲染函数 ==========
    void AvPushStream::renderOSD(cv::Mat& frame) {
        if (!mWorker || !mWorker->mControl) {
            return;
        }

        const Control* control = mWorker->mControl.get();

        // 检查是否启用 OSD
        if (!control->osdEnabled) {
            return;
        }

        // 先渲染贴图（可作为中文/Logo 兜底）
        renderOSDImage(frame);

        // 仅启用贴图时允许 osdText 为空
        if (control->osdText.empty()) {
            return;
        }

        // 替换变量
        std::string text = control->osdText;

	        // {time} - 当前时间
	        {
	            size_t pos = text.find("{time}");
	            if (pos != std::string::npos) {
	                time_t now = time(nullptr);
	                char timeStr[64];
	                std::tm tm_buf{};
#ifdef _WIN32
	                localtime_s(&tm_buf, &now);
#else
	                localtime_r(&now, &tm_buf);
#endif
	                strftime(timeStr, sizeof(timeStr), "%Y-%m-%d %H:%M:%S", &tm_buf);
	                text.replace(pos, 6, timeStr);
	            }
	        }

        // {stream_name} - 视频流名称
        {
            size_t pos = text.find("{stream_name}");
            if (pos != std::string::npos) {
                text.replace(pos, 13, control->streamName);
            }
        }

        // {algorithm_name} - 算法名称
        {
            size_t pos = text.find("{algorithm_name}");
            if (pos != std::string::npos) {
                text.replace(pos, 16, control->algorithmCode);
            }
        }

        // 解析字体颜色 (RGB 格式: "255,255,255" - 用户输入为 R,G,B 顺序)
        cv::Scalar textColor(255, 255, 255); // 默认白色
        {
            std::string colorStr = control->osdFontColor;
            size_t pos1 = colorStr.find(',');
            size_t pos2 = colorStr.find(',', pos1 + 1);
            if (pos1 != std::string::npos && pos2 != std::string::npos) {
	                try {
	                    int r = std::stoi(colorStr.substr(0, pos1));
	                    int g = std::stoi(colorStr.substr(pos1 + 1, pos2 - pos1 - 1));
	                    int b = std::stoi(colorStr.substr(pos2 + 1));
	                    textColor = cv::Scalar(b, g, r); // OpenCV uses BGR order
	                } catch (const std::invalid_argument&) {
	                    // 使用默认颜色
	                } catch (const std::out_of_range&) {
	                    // 使用默认颜色
	                }
	            }
	        }

        // 计算文字位置
        int x = control->osdX;
	        int y = control->osdY;
	        int fontSize = control->osdFontSize;

	        // 根据预定义位置计算坐标
	        if (const std::string position = control->osdPosition; position != "custom") {
	            // 使用 OpenCV 测量文字大小（近似，对于中文不完全准确）
	            int baseline = 0;
	            double fontScale = fontSize / 24.0; // 基准字体大小为 24
	            cv::Size textSize = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, fontScale, 2, &baseline);

            int margin = 10;
            if (position == "top-left") {
                x = margin;
                y = textSize.height + margin;
            }
            else if (position == "top-right") {
                x = frame.cols - textSize.width - margin;
                y = textSize.height + margin;
            }
            else if (position == "bottom-left") {
                x = margin;
                y = frame.rows - margin;
            }
            else if (position == "bottom-right") {
                x = frame.cols - textSize.width - margin;
                y = frame.rows - margin;
            }
        }

        // 绘制半透明背景（如果启用）
        if (control->osdBgEnabled) {
            double fontScale = fontSize / 24.0;
            int baseline = 0;
            cv::Size textSize = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, fontScale, 2, &baseline);

            int padding = 5;
            cv::Rect bgRect(x - padding, y - textSize.height - padding,
                           textSize.width + padding * 2, textSize.height + baseline + padding * 2);

            // 确保背景矩形在图像范围内
            bgRect.x = std::max(0, bgRect.x);
            bgRect.y = std::max(0, bgRect.y);
            bgRect.width = std::min(bgRect.width, frame.cols - bgRect.x);
            bgRect.height = std::min(bgRect.height, frame.rows - bgRect.y);

            if (bgRect.width > 0 && bgRect.height > 0) {
                cv::Mat roi = frame(bgRect);
                cv::Mat overlay = roi.clone();
                overlay.setTo(cv::Scalar(0, 0, 0)); // 黑色背景
                cv::addWeighted(overlay, 0.5, roi, 0.5, 0, roi); // 50% 透明度
            }
        }

        // 绘制文字（支持中文需要 FreeType，这里使用 OpenCV 基础功能）
        // 注意：OpenCV 的 putText 对中文支持有限，完整支持需要 cv::freetype::putText
        double fontScale = fontSize / 24.0;
        int thickness = control->osdFontThickness;
        if (thickness < 1) {
            thickness = 1;
        }

#if defined(__has_include)
#  if __has_include(<opencv2/freetype.hpp>)
        // Use FreeType when available (proper CJK support). Initialize once per thread.
        static thread_local bool ftInitialized = false;
        static thread_local bool ftUsable = false;
        static thread_local cv::Ptr<cv::freetype::FreeType2> ft2;

        if (!ftInitialized) {
            ftInitialized = true;
            try {
                ft2 = cv::freetype::createFreeType2();
                const std::string fontPath = pickFreeTypeFontPath();
                if (!fontPath.empty()) {
                    ft2->loadFontData(fontPath, 0);
                    ftUsable = true;
                }
            }
            catch (const cv::Exception&) {
                ftUsable = false;
                ft2.release();
            }
        }

	        if (ftUsable && ft2) {
	            try {
	                ft2->putText(frame, text, cv::Point(x, y), fontSize, textColor, thickness, cv::LINE_AA, true);
	                return;
	            }
	            catch (const cv::Exception&) {
	                // fallthrough
	            }
	        }
#  endif
#endif

        // Fallback: Hershey fonts (may not fully support Chinese).
        cv::putText(frame, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX,
                   fontScale, textColor, thickness, cv::LINE_AA);
    }
    // ========================================

	    void AvPushStream::handleEncodeVideo() {
	        uint64_t priorityGeneration = 0;
	        if (mWorker) {
	            mWorker->maybeRefreshCurrentThreadPriority(priorityGeneration, "push_encode");
	        }
	        if (!mWorker || !mWorker->mControl) {
	            LOGE("push stream worker/control is null");
	            return;
	        }
	        const Control* control = mWorker->mControl.get();
	        int width = control->videoWidth;
	        int height = control->videoHeight;

	        // ========== 使用配置的推流分辨率 ==========
	        int pushWidth = control->pushVideoWidth;
	        int pushHeight = control->pushVideoHeight;
	        // ========================================

        Frame* videoFrame = nullptr; // 未编码的视频帧（bgr格式）

        AVFrame* frame_yuv420p = av_frame_alloc();
        if (!frame_yuv420p) {
            LOGE("av_frame_alloc failed");
            if (mWorker) {
                mWorker->remove();
            }
            return;
        }
        frame_yuv420p->format = mVideoCodecCtx->pix_fmt;
        frame_yuv420p->width = pushWidth;   // 使用推流分辨率
        frame_yuv420p->height = pushHeight; // 使用推流分辨率

        int frame_yuv420p_buff_size = av_image_get_buffer_size(AV_PIX_FMT_YUV420P, pushWidth, pushHeight, 1);
        if (frame_yuv420p_buff_size <= 0) {
            LOGE("av_image_get_buffer_size failed: %d", frame_yuv420p_buff_size);
            av_frame_free(&frame_yuv420p);
            if (mWorker) {
                mWorker->remove();
            }
            return;
        }
        auto* frame_yuv420p_buff = static_cast<uint8_t*>(av_malloc(frame_yuv420p_buff_size));
        if (!frame_yuv420p_buff) {
            LOGE("av_malloc failed: size=%d", frame_yuv420p_buff_size);
            av_frame_free(&frame_yuv420p);
            if (mWorker) {
                mWorker->remove();
            }
            return;
        }
        av_image_fill_arrays(frame_yuv420p->data, frame_yuv420p->linesize,
            frame_yuv420p_buff,
            AV_PIX_FMT_YUV420P,
            pushWidth, pushHeight, 1);

        // ========== BGR 转 YUV420P 并支持缩放 ==========
        SwsContext* sws_ctx = sws_getContext(width, height,
            AV_PIX_FMT_BGR24,
            pushWidth, pushHeight,  // 输出使用推流分辨率，支持自动缩放
            AV_PIX_FMT_YUV420P,
            SWS_BILINEAR, nullptr, nullptr, nullptr);
        if (!sws_ctx) {
            LOGE("sws_getContext error");
            av_free(frame_yuv420p_buff);
	            frame_yuv420p_buff = nullptr;
            av_frame_free(&frame_yuv420p);
            if (mWorker) {
                mWorker->remove();
            }
            return;
        }
        // ========================================
        const uint8_t* srcSlice[1];
        int srcStride[1] = { width * 3 };

        AVPacket* pkt = av_packet_alloc();// 编码后的视频帧
        if (!pkt) {
            LOGE("av_packet_alloc failed");
            av_free(frame_yuv420p_buff);
	            frame_yuv420p_buff = nullptr;
            av_frame_free(&frame_yuv420p);
            sws_freeContext(sws_ctx);
            if (mWorker) {
                mWorker->remove();
            }
            return;
        }
        int64_t  encodeSuccessCount = 0;
        int64_t  frameCount = 0;
        int      writeErrorCount = 0;  // 写入错误计数
        int      reconnectDelayMs = 1000; // 初始重连间隔
        int      pushFps = mWorker && mWorker->mControl ? mWorker->mControl->pushVideoFps : 25;
        if (pushFps <= 0) {
            pushFps = 25;
        }
        const int64_t frameDurationMs = std::max<int64_t>(1, 1000 / std::max(1, pushFps));
        int64_t baseTimestampMs = 0;
        int64_t lastPtsMs = -1;

	        int ret = -1;
        while (mWorker->getState())
        {
            if (mWorker) {
                mWorker->maybeRefreshCurrentThreadPriority(priorityGeneration, "push_encode");
            }
            if (getVideoFrame(videoFrame)) {

                // ========== OSD 渲染 ==========
                // 将 BGR 帧包装为 cv::Mat 以便进行 OSD 渲染
                cv::Mat frameMat(height, width, CV_8UC3, videoFrame->getBuf());
                renderOSD(frameMat);
                // ==============================

                // frame_bgr 转 frame_yuv420p
                srcSlice[0] = videoFrame->getBuf();
                sws_scale(sws_ctx, srcSlice, srcStride, 0, height,
                    frame_yuv420p->data, frame_yuv420p->linesize);
	                int64_t tsMs = (videoFrame->timestampMs > 0) ? videoFrame->timestampMs : getCurTime();
	                if (mWorker && mWorker->mVideoFramePool) {
	                    mWorker->mVideoFramePool->giveBack(videoFrame);
	                }
	                else {
	                    std::unique_ptr<Frame> owned(videoFrame);
	                }
	                videoFrame = nullptr;

                int64_t ptsMs = normalizePtsMsWithMinStep(tsMs, baseTimestampMs, lastPtsMs, frameDurationMs);

                // IMPORTANT: frame->pts must be in codec time_base (ms).
                frame_yuv420p->pts = ptsMs;
                frame_yuv420p->pkt_dts = ptsMs;
                frame_yuv420p->pkt_duration = frameDurationMs;

                frame_yuv420p->pkt_pos = -1;

		                ret = avcodec_send_frame(mVideoCodecCtx, frame_yuv420p);
		                if (ret >= 0) {
		                    ret = avcodec_receive_packet(mVideoCodecCtx, pkt);
		                    while (ret >= 0) {
		                        encodeSuccessCount++;

	                        pkt->stream_index = mVideoIndex;

	                        pkt->pos = -1;
	                        // Rescale packet timestamps from codec time_base (ms) to stream time_base.
	                        av_packet_rescale_ts(pkt, mVideoCodecCtx->time_base, mVideoStream->time_base);

	                        ret = av_interleaved_write_frame(mFmtCtx, pkt);
	                        if (ret < 0) {
	                            LOGE("av_interleaved_write_frame error : ret=%d", ret);
	                            writeErrorCount++;
	                            if (mWorker && mWorker->mScheduler) {
	                                mWorker->mScheduler->statsIncPushWriteErrors(1);
	                            }

	                            // 无限重试推流：每次失败后指数退避，但不设重试上限
	                            LOGW("Push stream write failed (count=%d), will reconnect after %d ms", writeErrorCount, reconnectDelayMs);
	                            std::this_thread::sleep_for(std::chrono::milliseconds(reconnectDelayMs));
	                            reconnectDelayMs = std::min(reconnectDelayMs * 2, 30000); // 退避上限30s

	                            if (reConnect()) {
	                                writeErrorCount = 0;
	                                reconnectDelayMs = 1000;
	                                frameCount = 0;  // 重置帧计数
	                                encodeSuccessCount = 0;
	                                baseTimestampMs = 0;
	                                lastPtsMs = -1;
	                                LOGI("Push stream reconnected successfully");
	                            } else {
	                                LOGW("Push stream reconnect failed, will keep retrying...");
	                            }
	                        } else {
	                            writeErrorCount = 0;          // 重置错误计数
	                            reconnectDelayMs = 1000;      // 成功后恢复默认退避
	                        }
	                        av_packet_unref(pkt);
	                        ret = avcodec_receive_packet(mVideoCodecCtx, pkt);
	                    }

	                    if (ret < 0 && ret != AVERROR(EAGAIN) && ret != AVERROR_EOF) {
	                        LOGE("avcodec_receive_packet error : ret=%d", ret);
	                    }
	                }
	                else {
	                    LOGE("avcodec_send_frame error : ret=%d", ret);
	                }

                frameCount++;
            }
            else {
                // getVideoFrame() already waits on condition_variable.
            }
        }

        //av_write_trailer(mFmtCtx);//写文件尾

        av_packet_unref(pkt);
        av_packet_free(&pkt);
	        pkt = nullptr;


        av_free(frame_yuv420p_buff);
	        frame_yuv420p_buff = nullptr;

        av_frame_free(&frame_yuv420p);
        frame_yuv420p = nullptr;

        sws_freeContext(sws_ctx);
    }
    void AvPushStream::encodeVideoThread(AvPushStream* arg) {
        auto* pushStream = arg;
        try {
            pushStream->handleEncodeVideo();
        }
	        catch (const std::exception& ex) { // NOSONAR
	            LOGE("AvPushStream::encodeVideoThread exception: %s", ex.what());
	            if (pushStream && pushStream->mWorker) {
	                pushStream->mWorker->remove();
	            }
	        }
	        catch (...) { // NOSONAR
	            LOGE("AvPushStream::encodeVideoThread exception: unknown");
	            if (pushStream && pushStream->mWorker) {
	                pushStream->mWorker->remove();
	            }
	        }
    }


}
