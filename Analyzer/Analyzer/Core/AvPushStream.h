#ifndef ANALYZER_AVPUSHSTREAM_H
#define ANALYZER_AVPUSHSTREAM_H
#include <queue>
#include <mutex>
#include <condition_variable>
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
}

namespace cv {
	class Mat;
}

namespace AVSAnalyzer {
	class Worker;
	struct Frame;

		class AvPushStream
		{
			public:
				explicit AvPushStream(Worker* worker);
				~AvPushStream();
				// 队列大小限制，防止生产过快导致内存飙升/阻塞
				static const int MAX_VIDEO_FRAME_QUEUE_SIZE = 60; // 约2秒缓存（@30fps）

				bool connect();     // 连接流媒体服务
				bool reConnect();   // 重连流媒体服务
				void closeConnect();// 关闭流媒体服务的连接
				void addVideoFrame(Frame* frame);
				int getVideoFrameQSize();
				void clearVideoFrameQueue();
				static void encodeVideoThread(AvPushStream* arg); // 编码视频帧并推流
				void handleEncodeVideo();

		private:
			void renderOSD(cv::Mat& frame); // 渲染 OSD 文字到视频帧
			void renderOSDImage(cv::Mat& frame); // 渲染 OSD 贴图到视频帧
			int mConnectCount = 0;
			AVFormatContext* mFmtCtx = nullptr;

			//视频帧
			AVCodecContext* mVideoCodecCtx = nullptr;
			AVStream* mVideoStream = nullptr;
			int mVideoIndex = -1;
			Worker* mWorker;
			int mDropFrameLogCount = 0;

		//视频帧
		std::queue <Frame*> mVideoFrameQ;
		std::mutex          mVideoFrameQ_mtx;
		std::condition_variable mVideoFrameQ_cv;
		bool getVideoFrame(Frame*& frame);


	};

}
#endif //ANALYZER_AVPUSHSTREAM_H
