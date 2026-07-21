#include "GenerateAlarmVideo.h"
#include "Config.h"
#include "AlarmEncodeProfile.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include <json/json.h>
#include "Utils/Request.h"
#include "Frame.h"
#include <iostream>
#include <fstream>
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <exception>
#include <set>
#include <utility>
#include <chrono>
#include <opencv2/opencv.hpp>
extern "C" {
#include "libswscale/swscale.h"
#include <libavutil/imgutils.h>
#include <libswresample/swresample.h>
}

#ifdef _MSC_VER
#pragma warning(disable: 4996)
#endif

namespace AVSAnalyzer {


    Alarm::Alarm(const AlarmVideoConfig& videoConfig, const char* controlCodeValue,
        const std::string& videoType, int imageCount, std::shared_ptr<FramePool> framePool)
        : width(videoConfig.width),
          height(videoConfig.height),
          fps(videoConfig.fps),
          happenTimestamp(videoConfig.happenTimestamp),
          happenImageIndex(videoConfig.happenImageIndex),
          controlCode(controlCodeValue ? controlCodeValue : ""),
          videoType(videoType),
          imageCount(imageCount),
          framePool(std::move(framePool)) {
        //LOGI("");
    }
    Alarm::~Alarm() {
        //LOGI("");

        for (size_t i = 0; i < this->frames.size(); i++)
        {
            Frame* frame = this->frames[i];
	            if (framePool) {
	                framePool->giveBack(frame);
	            }
	            else {
	                std::unique_ptr<Frame> owned(frame);
	            }
	        }
	        frames.clear();

    }
    GenerateAlarmVideo::GenerateAlarmVideo(Config* config, Alarm* alarm) :
        mConfig(config), mAlarm(alarm)
    {
        //LOGI("");
        av_log_set_level(AV_LOG_ERROR);

    }

    GenerateAlarmVideo::~GenerateAlarmVideo()
    {
        //LOGI("");
        destoryCodecCtx();

    }

	    bool GenerateAlarmVideo::initCodecCtx(const char* url, const char* formatName) {

        if (avformat_alloc_output_context2(&mFmtCtx, nullptr, formatName, url) < 0) {
            LOGE("avformat_alloc_output_context2 error");
            return false;
        }

        // 初始化视频编码器 start
        const AVCodec* videoCodec = avcodec_find_encoder(AV_CODEC_ID_H264);
        if (!videoCodec) {
            LOGE("avcodec_find_decoder error");
            return false;
        }
	        mVideoCodecCtx = avcodec_alloc_context3(videoCodec);
	        if (!mVideoCodecCtx) {
	            LOGE("avcodec_alloc_context3 error");
	            return false;
	        }
	        std::string profile = "balanced";
	        if (mConfig) {
	            profile = mConfig->alarmEncodeProfile;
	        }
	        std::string lowerProfile = profile;
	        std::transform(lowerProfile.begin(), lowerProfile.end(), lowerProfile.begin(),
	            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
	        if (lowerProfile.empty()) {
	            lowerProfile = "balanced";
	        }
	        bool lowCpu = (lowerProfile == "low_cpu");

	        AlarmEncodeSettings settings = pickAlarmEncodeSettings(profile, mAlarm->width, mAlarm->height);
	        LOGI("alarm video: profile=%s bitrate=%d preset=%s crf=%s threads=%d",
	             lowerProfile.c_str(), settings.bit_rate, settings.preset.c_str(), settings.crf.c_str(), settings.thread_count);

	        mVideoCodecCtx->rc_min_rate = settings.rc_min_rate;
	        mVideoCodecCtx->rc_max_rate = settings.rc_max_rate;
	        mVideoCodecCtx->bit_rate = settings.bit_rate;
	        mVideoCodecCtx->rc_buffer_size = settings.rc_buffer_size;

	        //ABR：Average Bitrate - 平均码率
	    //    mVideoCodecCtx->bit_rate = bit_rate;

        mVideoCodecCtx->codec_id = videoCodec->id;
        mVideoCodecCtx->pix_fmt = AV_PIX_FMT_YUV420P;// 不支持AV_PIX_FMT_BGR24直接进行编码
        mVideoCodecCtx->codec_type = AVMEDIA_TYPE_VIDEO;
        mVideoCodecCtx->width = mAlarm->width;
        mVideoCodecCtx->height = mAlarm->height;

        // ========== 优化：固定时间基为标准值，避免视频不稳定 ==========
        // 使用固定的时间基 1/90000（MPEG标准）确保视频时间戳稳定
        mVideoCodecCtx->time_base = { 1, 90000 };
        mVideoCodecCtx->framerate = { mAlarm->fps, 1 };
        // ================================================================

        // ========== 优化：改进编码参数以提升质量和减少丢帧 ==========
        // 使用更短的GOP以支持更快的seek和减少错误累积
        mVideoCodecCtx->gop_size = mAlarm->fps;  // 1秒一个关键帧

	        // 启用B帧以提升压缩率和质量（改善丢帧问题）
	        // B帧可以提高编码效率，减少码率波动导致的丢帧
	        mVideoCodecCtx->max_b_frames = lowCpu ? 0 : 2;

	        // 使用多线程编码以提升性能（减少编码延迟导致的丢帧）
	        mVideoCodecCtx->thread_count = settings.thread_count;
	        mVideoCodecCtx->thread_type = FF_THREAD_FRAME;  // 帧级并行
	        // ================================================================

        unsigned char sps_pps[] = { 0x00 ,0x00 ,0x01,0x67,0x42,0x00 ,0x2a ,0x96 ,0x35 ,0x40 ,0xf0 ,0x04 ,
                            0x4f ,0xcb ,0x37 ,0x01 ,0x01 ,0x01 ,0x40 ,0x00 ,0x01 ,0xc2 ,0x00 ,0x00 ,0x57 ,
                            0xe4 ,0x01 ,0x00 ,0x00 ,0x00 ,0x01 ,0x68 ,0xce ,0x3c ,0x80, 0x00 };

        mVideoCodecCtx->extradata_size = sizeof(sps_pps);
        mVideoCodecCtx->extradata = (uint8_t*)av_mallocz(mVideoCodecCtx->extradata_size);
        memcpy(mVideoCodecCtx->extradata, sps_pps, mVideoCodecCtx->extradata_size);

        AVDictionary* video_codec_options = nullptr;
        av_dict_set(&video_codec_options, "profile", "high", 0);  // 使用high profile提升压缩率
        av_dict_set(&video_codec_options, "preset", settings.preset.c_str(), 0);
        av_dict_set(&video_codec_options, "crf", settings.crf.c_str(), 0);
        av_dict_set(&video_codec_options, "tune", lowCpu ? "zerolatency" : "film", 0);
        av_dict_set(&video_codec_options, "rc-lookahead", lowCpu ? "0" : "40", 0);

        if (avcodec_open2(mVideoCodecCtx, videoCodec, &video_codec_options) < 0) {
            LOGE("avcodec_open2 error");
            return false;
        }

        mVideoStream = avformat_new_stream(mFmtCtx, videoCodec);
        if (!mVideoStream) {
            LOGE("avformat_new_stream error");
            return false;
        }
        mVideoStream->id = mFmtCtx->nb_streams - 1;
        // stream的time_base参数非常重要，它表示将现实中的一秒钟分为多少个时间基, 在下面调用avformat_write_header时自动完成
        avcodec_parameters_from_context(mVideoStream->codecpar, mVideoCodecCtx);
        mVideoIndex = mVideoStream->id;
        // 初始化视频编码器 end



        av_dump_format(mFmtCtx, 0, url, 1);

        // open output url
        if (!(mFmtCtx->oformat->flags & AVFMT_NOFILE) &&
            (avio_open(&mFmtCtx->pb, url, AVIO_FLAG_WRITE) < 0)) {
            LOGE("avio_open error url=%s", url);
            return false;
        }

        AVDictionary* fmt_options = nullptr;

        mFmtCtx->video_codec_id = mFmtCtx->oformat->video_codec;

        if (avformat_write_header(mFmtCtx, &fmt_options) < 0) { // 调用该函数会将所有stream的time_base，自动设置一个值，通常是1/90000或1/1000，这表示一秒钟表示的时间基长度
            LOGE("avformat_write_header error");
            return false;
        }

        return true;
    }
    void GenerateAlarmVideo::destoryCodecCtx() {

        if (mFmtCtx) {
            // 推流需要释放start
            if (mFmtCtx && !(mFmtCtx->oformat->flags & AVFMT_NOFILE)) {
                avio_close(mFmtCtx->pb);
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


    }
    bool GenerateAlarmVideo::genAlarmVideo() {
        // C++ 17创建文件夹 https://pythonjishu.com/cgnqifmjqqrgjnj/


        if (!mAlarm) {
            return false;
        }

        std::filesystem::path prefixDir = std::filesystem::path(mConfig->uploadDir) / "alarm";
        try {
            if (!std::filesystem::exists(prefixDir)) {
                std::filesystem::create_directory(prefixDir);
            }
        }
        catch (std::filesystem::filesystem_error& e) {
            std::cout <<"genAlarmVideo() create_directory1 error:" << e.what() << std::endl;
            return false;
        }

        prefixDir /= mAlarm->controlCode;
        try {
            if (!std::filesystem::exists(prefixDir)) {
                std::filesystem::create_directory(prefixDir);
            }
        }
        catch (std::filesystem::filesystem_error& e) {
            std::cout << "genAlarmVideo() create_directory2 error:" << e.what() << std::endl;
            return false;
        }
        std::string ymdhms_rd = getCurFormatTimeStr("%Y%m%d%H%M%S") + "_" + std::to_string(getRandomInt());
        prefixDir /= ymdhms_rd;
        try {
            if (!std::filesystem::exists(prefixDir)) {
                std::filesystem::create_directory(prefixDir);
            }
        }
        catch (std::filesystem::filesystem_error& e) {
            std::cout << "genAlarmVideo() create_directory3 error:" << e.what() << std::endl;
            return false;
        }

        std::string relativeDir = "alarm/" + mAlarm->controlCode + "/" + ymdhms_rd;

        std::string videoType = mAlarm->videoType;
        std::transform(videoType.begin(), videoType.end(), videoType.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (videoType.empty()) {
            videoType = "mp4";
        }

        bool recordVideo = videoType != "none";
        std::string formatName = "mp4";
        std::string videoExt = "mp4";
        if (videoType == "ts" || videoType == "mpegts") {
            formatName = "mpegts";
            videoExt = "ts";
        }
        else if (videoType == "flv") {
            formatName = "flv";
            videoExt = "flv";
        }

        const auto totalFrames = static_cast<int>(mAlarm->frames.size());
        if (totalFrames <= 0) {
            LOGE("genAlarmVideo() no frames");
            return false;
        }

        // ========== 扩展：根据coverPosition计算封面帧位置 ==========
        int coverIndex = mAlarm->happenImageIndex;
        std::string coverPos = mAlarm->coverPosition;
        if (coverPos == "front") {
            coverIndex = 0;  // 第一帧作为封面
        }
        else if (coverPos == "middle") {
            coverIndex = totalFrames / 2;  // 中间帧作为封面
        }
        else if (coverPos == "back") {
            coverIndex = totalFrames - 1;  // 最后一帧作为封面
        }
        else if (coverPos == "custom") {
            // 使用 happenImageIndex 作为自定义位置
            coverIndex = mAlarm->happenImageIndex;
        }
        // 边界检查
        if (coverIndex < 0) coverIndex = 0;
        if (coverIndex >= totalFrames) coverIndex = totalFrames - 1;
        // ==============================================================

        int imageCount = mAlarm->imageCount;
        if (imageCount < 0) imageCount = 0;
        if (imageCount > totalFrames) imageCount = totalFrames;
        bool saveImages = imageCount > 0;

        std::string video_path;
        std::string video_path_abs;
        if (recordVideo) {
            video_path = relativeDir + "/main." + videoExt;
            video_path_abs = mConfig->uploadDir + "/" + video_path;
        }

        std::string image_path;
        std::string image_path_abs;
        if (saveImages) {
            image_path = relativeDir + "/main.jpg";
            image_path_abs = mConfig->uploadDir + "/" + image_path;
        }

        if (recordVideo && !initCodecCtx(video_path_abs.data(), formatName.c_str())) {
            std::cout << "genAlarmVideo() initCodecCtx error" << std::endl;
            recordVideo = false;
            video_path.clear();
            video_path_abs.clear();
        }

        int width = mAlarm->width;
        int height = mAlarm->height;

        std::set<int> imageIndices;
        if (saveImages) {
            imageIndices.insert(coverIndex);
            int extraCount = imageCount - 1;
            if (extraCount > 0) {
                int step = std::max(1, totalFrames / (extraCount + 1));
                int saved = 0;
                for (int offset = 1; offset <= extraCount; ++offset) {
                    int idx = offset * step;
                    if (idx >= totalFrames) {
                        break;
                    }
                    if (idx == coverIndex) {
                        continue;
                    }
                    imageIndices.insert(idx);
                    saved++;
                }
            }
        }

        AVFrame* frame_yuv420p = nullptr;
        uint8_t* frame_yuv420p_buff = nullptr;
        AVPacket* pkt = nullptr;
        SwsContext* sws_ctx = nullptr;
        int64_t  frameCount = 1;

        int ret = -1;
        int receive_packet_count = -1;

        const uint8_t* srcSlice[1];
        int srcStride[1] = { width * 3 };
        if (recordVideo) {
            frame_yuv420p = av_frame_alloc();
            frame_yuv420p->format = mVideoCodecCtx->pix_fmt;
            frame_yuv420p->width = width;
            frame_yuv420p->height = height;

            int frame_yuv420p_buff_size = av_image_get_buffer_size(AV_PIX_FMT_YUV420P, width, height, 1);
            frame_yuv420p_buff = (uint8_t*)av_malloc(frame_yuv420p_buff_size);
            av_image_fill_arrays(frame_yuv420p->data, frame_yuv420p->linesize,
                frame_yuv420p_buff,
                AV_PIX_FMT_YUV420P,
                width, height, 1);

            pkt = av_packet_alloc();// 编码后的视频帧

            // ========== 优化：使用高质量缩放算法，修复Linux花屏问题 ==========
            // SWS_BICUBIC 提供更好的图像质量，减少花屏和失真
            // SWS_FULL_CHR_H_INT 和 SWS_ACCURATE_RND 提升色度和精度
            sws_ctx = sws_getContext(width, height,
                AV_PIX_FMT_BGR24,
                width, height,
                AV_PIX_FMT_YUV420P,
                SWS_BICUBIC | SWS_FULL_CHR_H_INT | SWS_ACCURATE_RND,
                nullptr, nullptr, nullptr);
            // ====================================================================

            if (!sws_ctx) {
                LOGE("genAlarmVideo() sws_getContext error");
                recordVideo = false;
            }
        }

        // ========== 修复：立即释放已处理的帧，减少内存占用 ==========
        // 优化策略：在处理每一帧后立即释放，而不是等到所有帧都处理完
        // 特别是当不生成视频时（videoType == "none"），只需要保存图片，
        // 保存完图片后立即释放帧可以大幅降低内存占用
        // ================================================================

        int extra_image_index = 1;
        for (size_t i = 0; i < mAlarm->frames.size(); i++)
        {
            Frame* frame = mAlarm->frames[i];

            // 检查是否需要保存图片
            if (saveImages && imageIndices.find(static_cast<int>(i)) != imageIndices.end()) {
                cv::Mat happenImage_cvmat(height, width, CV_8UC3, frame->getBuf());
                if (static_cast<int>(i) == coverIndex) {
                    cv::imwrite(image_path_abs, happenImage_cvmat);
                }
                else {
                    std::string extra_path_abs = (prefixDir / ("extra_" + std::to_string(extra_image_index) + ".jpg")).string();
                    cv::imwrite(extra_path_abs, happenImage_cvmat);
                    extra_image_index++;
                }
                // OpenCV Mat 会在作用域结束时自动释放，不持有原始数据
            }

            if (recordVideo) {
                // frame_bgr 转 frame_yuv420p
                srcSlice[0] = frame->getBuf();
                sws_scale(sws_ctx, srcSlice, srcStride, 0, height,
                    frame_yuv420p->data, frame_yuv420p->linesize);

                // ========== 优化：固定pts计算，确保视频时间戳稳定 ==========
                // 使用 90000 时间基（MPEG标准），计算固定间隔的pts
                int64_t pts_increment = 90000 / mAlarm->fps;  // 每帧的pts增量
                frame_yuv420p->pts = (frameCount - 1) * pts_increment;
                frame_yuv420p->pkt_dts = frame_yuv420p->pts;
                frame_yuv420p->pkt_duration = pts_increment;
                frame_yuv420p->pkt_pos = frameCount;
                // ==============================================================

                ret = avcodec_send_frame(mVideoCodecCtx, frame_yuv420p);
                if (ret >= 0) {
                    receive_packet_count = 0;
                    while (true) {
                        ret = avcodec_receive_packet(mVideoCodecCtx, pkt);
                        if (ret >= 0) {

                            pkt->stream_index = mVideoIndex;
                            pkt->pos = frameCount;
                            pkt->duration = frame_yuv420p->pkt_duration;

                            int wframe = av_write_frame(mFmtCtx, pkt);
                            if (wframe < 0) {
                                LOGE("writePkt : wframe=%d", wframe);
                            }
                            av_packet_unref(pkt);
                            ++receive_packet_count;

                            if (receive_packet_count > 1) {
                                LOGI("avcodec_receive_packet success: receive_packet_count=%d", receive_packet_count);
                            }
                        }
                        else {
                            break;
                        }
                    }
                }
                else {
                    LOGE("avcodec_send_frame error : ret=%d", ret);
                }
                frameCount++;
            }

            // ========== 修复：立即释放当前帧，避免内存累积 ==========
            // 在循环内立即释放帧，而不是等到循环结束
            // 这样可以避免大量帧同时占用内存
	            if (mAlarm->framePool) {
	                mAlarm->framePool->giveBack(frame);
	            }
	            else {
	                std::unique_ptr<Frame> owned(frame);
	            }

            // 立即从向量中清除引用，释放vector的内部存储
            mAlarm->frames[i] = nullptr;
            // ===========================================================
        }

        // 清空向量（此时所有元素都已是nullptr）
        mAlarm->frames.clear();

        if (recordVideo) {
            avcodec_send_frame(mVideoCodecCtx, nullptr);
            while (true) {
                ret = avcodec_receive_packet(mVideoCodecCtx, pkt);
                if (ret >= 0) {
                    pkt->stream_index = mVideoIndex;
                    int wframe = av_write_frame(mFmtCtx, pkt);
                    if (wframe < 0) {
                        LOGE("writePkt : wframe=%d", wframe);
                    }
                    av_packet_unref(pkt);
                }
                else {
                    break;
                }
            }

            av_write_trailer(mFmtCtx);//写文件尾
        }

        if (pkt) {
            av_packet_unref(pkt);
            av_packet_free(&pkt);
            pkt = nullptr;
        }

        if (frame_yuv420p_buff) {
            av_free(frame_yuv420p_buff);
            frame_yuv420p_buff = nullptr;
        }

        if (frame_yuv420p) {
            av_frame_free(&frame_yuv420p);
            frame_yuv420p = nullptr;
        }
        if (sws_ctx) {
            sws_freeContext(sws_ctx);
            sws_ctx = nullptr;
        }

        // ========== 优化：视频生成完成后立即推送，减少触发延迟 ==========
        // 延迟应该在视频生成之前处理（如在Worker中），这里视频生成完成后立即推送
        // 可选推送延迟（如果配置了延迟）已移到 Worker 模块
        // ================================================================

        //上传报警信息start
        std::string url = mConfig->adminHost + "/alarm/openAdd";
        Json::Value param;
        param["control_code"] = mAlarm->controlCode;
        param["desc"] = "";
        param["video_path"] = video_path;
        param["image_path"] = image_path;

        // ========== 扩展参数：布控配置信息 ==========
        param["algorithm_code"] = mAlarm->algorithmCode;
        param["object_code"] = mAlarm->objectCode;
        param["recognition_region"] = mAlarm->recognitionRegion;
        param["class_thresh"] = mAlarm->classThresh;
        param["overlap_thresh"] = mAlarm->overlapThresh;
        param["min_interval"] = static_cast<Json::Int64>(mAlarm->minInterval);

        // ========== 扩展参数：视频流信息 ==========
        param["stream_code"] = mAlarm->stream.streamCode;
        param["stream_app"] = mAlarm->stream.streamApp;
        param["stream_name"] = mAlarm->stream.streamName;
        param["stream_url"] = mAlarm->stream.streamUrl;
        // ==========================================

        // ========== 本地写入报警结果描述（result.json） ==========
        // 工业交付：本地报警目录内增加一个可离线解析的结果文件，便于取证/归档/二次开发。
        try {
            param["happen_timestamp_ms"] = static_cast<Json::Int64>(mAlarm->happenTimestamp);
            param["cover_position"] = mAlarm->coverPosition;
            param["cover_index"] = coverIndex;
            param["video_type"] = videoType;
            param["image_count"] = imageCount;

            Json::StreamWriterBuilder file_builder;
            file_builder["indentation"] = "  ";
            file_builder["emitUTF8"] = true;
            std::string file_json = Json::writeString(file_builder, param);

            std::string result_json_path_abs = mConfig->uploadDir + "/" + relativeDir + "/result.json";
            std::ofstream ofs(result_json_path_abs, std::ios::out | std::ios::binary);
            if (ofs.is_open()) {
                ofs.write(file_json.data(), static_cast<std::streamsize>(file_json.size()));
                ofs.close();
            }
        }
        catch (const std::exception&) { // NOSONAR
            // best-effort: never block alarm delivery
        }
        // ==========================================================

        Json::StreamWriterBuilder wbuilder;
        wbuilder["indentation"] = "";
        wbuilder["emitUTF8"] = true;
        std::string data = Json::writeString(wbuilder, param);
        Request request;
        std::string response;
	        const bool postOk = request.post(url.c_str(), data, response, mConfig->openApiToken);
	        if (!postOk) {
	            LOGW("alarm openAdd request failed: url=%s", url.c_str());
	        }

        LOGI("\n \t request:%s \n \t response:%s",
            url.data(),
            response.data());


        return true;

    }


}
