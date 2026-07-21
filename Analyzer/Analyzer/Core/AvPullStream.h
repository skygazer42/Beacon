#ifndef ANALYZER_AVPULLSTREAM_H
#define ANALYZER_AVPULLSTREAM_H
#include <queue>
#include <functional>
#include <mutex>
#include <condition_variable>
#include "ReconnectRequestFlag.h"

extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
}
namespace AVSAnalyzer {
		class Scheduler;
		class SharedDecodeSession;
		struct Control;

		class AvPullStream
		{
		public:
		AvPullStream(
			Scheduler* scheduler,
			Control* control,
			std::function<bool()> getStateFn,
			std::function<void()> fatalHandler = {});
		~AvPullStream();

		// 队列大小限制常量 - 防止内存溢出
			static const int MAX_VIDEO_PKT_QUEUE_SIZE = 30;  // 最大缓存30帧（约1秒@30fps）
			static const int MAX_PACKET_POOL_SIZE = 60;      // 复用池上限

			bool connect();     // 连接流媒体服务
			bool reConnect();   // 重连流媒体服务
			void closeConnect();// 关闭流媒体服务的连接

			// Safe way for decode thread to request a reconnect; handled by read thread.
			bool requestReconnect() { return mReconnectRequested.request(); }
			bool getVideoPkt(AVPacket*& pkt, int& pktQSize);// 从队列获取的pkt，一定要主动释放!!!
			int getVideoPktQSize(); // 获取当前视频包队列大小（用于监控/限流）
			void releaseVideoPkt(AVPacket* pkt);

			static void readThread(AvPullStream* arg); // 拉流媒体流
			void handleRead();

		private:
			friend class SharedDecodeSession;

			int mConnectCount = 0;
			AVFormatContext* mFmtCtx = nullptr;
			// 视频帧
			AVCodecContext* mVideoCodecCtx = nullptr;
			AVStream* mVideoStream = nullptr;
			// Protect connect/close/reconnect from racing with decode thread using mVideoCodecCtx.
			// Lock order note: decode thread may lock packet-queue mutex first, then this mutex.
			// closeConnect() must NOT hold this mutex while clearing the packet queue to avoid deadlocks.
			std::mutex mConnectMtx;
			Scheduler* mScheduler;
			Control* mControl;
			std::function<bool()> mGetStateFn;
		std::function<void()> mFatalHandler;
		int mDropPktLogCount = 0;

		bool pushVideoPkt(AVPacket* pkt);
		void clearVideoPktQueue();
		AVPacket* acquirePacket();
		void clearPacketPool();
		std::queue <AVPacket*>  mVideoPktQ;
		std::mutex              mVideoPktQ_mtx;
		std::queue <AVPacket*>  mPktPool;
		std::mutex              mPktPool_mtx;

		ReconnectRequestFlag mReconnectRequested{};
	};


}
#endif //ANALYZER_AVPULLSTREAM_H
