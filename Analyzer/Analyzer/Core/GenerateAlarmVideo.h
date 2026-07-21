#ifndef ANALYZER_GENERATEALARMVIDEO_H
#define ANALYZER_GENERATEALARMVIDEO_H
#include <vector>
#include <queue>
#include <mutex>
#include <string>
#include <memory>
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
}

namespace AVSAnalyzer {

	class Config;
	struct Frame;
	class FramePool;

    struct AlarmStreamInfo
    {
        std::string streamCode;
        std::string streamApp;
        std::string streamName;
        std::string streamUrl;
    };

    struct AlarmVideoConfig
    {
        int height = 0;
        int width = 0;
        int fps = 0;
        int64_t happenTimestamp = 0;
        int happenImageIndex = 0;
    };

	struct Alarm
	{
public:
		Alarm() = delete;
		Alarm(const AlarmVideoConfig& videoConfig, const char* controlCodeValue,
		      const std::string& videoType, int imageCount, std::shared_ptr<FramePool> framePool);
		~Alarm();

        Alarm(const Alarm&) = delete;
        Alarm& operator=(const Alarm&) = delete;
        Alarm(Alarm&&) = delete;
        Alarm& operator=(Alarm&&) = delete;
	public:
		int width = 0;
		int height = 0;
		int fps = 0;
		int64_t happenTimestamp = 0; //发生事件的时间戳（毫秒级）
		int		happenImageIndex = 0;//封面图index
		std::string controlCode;// 布控编号
		std::string videoType;   // 报警视频类型: mp4/ts/flv/none
		int imageCount = 1;      // 报警图片数量

		// ========== 扩展：封面帧位置设置 ==========
		std::string coverPosition = "middle";  // 封面帧位置: "front"(前), "middle"(中), "back"(后), "custom"(自定义index)
		// ==========================================

		std::shared_ptr<FramePool> framePool;
		std::vector<Frame*> frames;//组成报警视频的图片帧

		// ========== 扩展字段：布控配置信息 ==========
		std::string algorithmCode;      // 算法编号
		std::string objectCode;         // 目标分类编号
		std::string recognitionRegion;  // 检测区域坐标
		float classThresh = 0.5f;       // 分类阈值
		float overlapThresh = 0.5f;     // 重叠阈值
		int64_t minInterval = 0;        // 最小间隔（毫秒）
		AlarmStreamInfo stream;
	};


	class GenerateAlarmVideo
	{
	public:
		GenerateAlarmVideo() = delete;
		GenerateAlarmVideo(Config* config, Alarm* alarm);
		~GenerateAlarmVideo();
		GenerateAlarmVideo(const GenerateAlarmVideo&) = delete;
		GenerateAlarmVideo& operator=(const GenerateAlarmVideo&) = delete;
		GenerateAlarmVideo(GenerateAlarmVideo&&) = delete;
		GenerateAlarmVideo& operator=(GenerateAlarmVideo&&) = delete;

		bool genAlarmVideo();
	private:
		Config* mConfig;
		Alarm* mAlarm;
		bool initCodecCtx(const char* url, const char* formatName);
		void destoryCodecCtx();

		AVFormatContext* mFmtCtx = nullptr;
		//视频帧
		AVCodecContext* mVideoCodecCtx = nullptr;
		AVStream* mVideoStream = nullptr;
		int mVideoIndex = -1;
	};

}

#endif //ANALYZER_GENERATEALARMVIDEO_H
