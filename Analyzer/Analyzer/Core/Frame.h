#ifndef ANALYZER_FRAME_H
#define ANALYZER_FRAME_H
#include <cstdint>
#include <vector>
#include <queue>
#include <mutex>
#include <memory>
#include <string>

namespace AVSAnalyzer {
		struct Frame
		{
			Frame() = delete;
			explicit Frame(int bufInitSize);
			~Frame() = default;
		void setBuf(const unsigned char* buf, int size);
		// No-copy: mark current buffer as filled with `size` bytes.
		// Useful when external code writes directly into `getBuf()` (e.g., sws_scale output).
		void setSize(int size);
		unsigned char* getBuf();
		int getSize() const;
		int getCapacity() const;
		void setAlarmRawSnapshot(const unsigned char* buf, int size);
		void clearAlarmRawSnapshot();
		const unsigned char* getAlarmRawSnapshot() const;
		int getAlarmRawSnapshotSize() const;
		bool hasAlarmRawSnapshot() const;

		bool happen = false;// 是否发生事件
		float happenScore = 0;// 发生事件的分数
		int regionIndex = -1; // 0-based recognition region index (best-effort); -1 when unknown
		int64_t timestampMs = 0; // 单调时间戳（ms，getCurTime），用于报警视频 PTS（抽帧不快放）
		int width = 0;
		int height = 0;
		int channel = 0;
		int fps = 0;
		int sourceQueueSize = 0;
		std::string userDataJson{}; // Optional per-frame metadata JSON (e.g. behavior internal targets/duration)
		std::string detectsJson{}; // Optional per-frame detect objects JSON for alarm export/LabelMe.

		int mBufInitSize = 0;//buf初始化时的长度
		int mBufSize = 0;
		std::vector<unsigned char> mBuf;
		std::vector<unsigned char> mAlarmRawSnapshot;

	};
		class FramePool
		{
		public:
			FramePool() = delete;
			explicit FramePool(int size);
			~FramePool();
		Frame* gain();// 获取一个实例
		void giveBack(Frame* frame);// 归还一个实例
		// Reset pool to a new frame byte-size. Existing idle frames are freed immediately.
		// In-flight frames will be dropped on giveBack() if their capacity mismatches.
		void resetSize(int size);
	private:
		int mSize;
		size_t mMaxFrames = 0;        // 允许分配的最大 Frame 数（总量上限）
		size_t mAllocatedFrames = 0;  // 已分配的 Frame 数（包含已归还到池中的）
		std::queue<std::unique_ptr<Frame>>  mFrameQ;
		std::mutex          mFrameQ_mtx;
		void clearFrameQ();


	};

}

#endif //ANALYZER_FRAME_H
