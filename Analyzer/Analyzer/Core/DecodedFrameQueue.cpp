#include "DecodedFrameQueue.h"
#include <memory>

namespace AVSAnalyzer {

DecodedFrameQueue::DecodedFrameQueue(size_t maxFrames, Releaser releaser)
    : mMaxFrames(maxFrames > 0 ? maxFrames : 1), mReleaser(std::move(releaser)) {}

DecodedFrameQueue::~DecodedFrameQueue() {
    clear();
}

	void DecodedFrameQueue::releaseFrame(Frame* frame) const {
	    if (!frame) {
	        return;
	    }
	    if (mReleaser) {
	        mReleaser(frame);
	        return;
	    }
	    std::unique_ptr<Frame> owned(frame);
	}

	void DecodedFrameQueue::push(Frame* frame) {
	    if (!frame) {
	        return;
	    }
	    std::scoped_lock lock(mMtx);
	    while (mQueue.size() >= mMaxFrames) {
	        Frame* dropped = mQueue.front();
	        mQueue.pop_front();
	        releaseFrame(dropped);
    }
    mQueue.push_back(frame);
	}

	bool DecodedFrameQueue::pop(Frame*& frame) {
	    std::scoped_lock lock(mMtx);
	    if (mQueue.empty()) {
	        frame = nullptr;
	        return false;
	    }
    frame = mQueue.front();
    mQueue.pop_front();
    return true;
	}

	void DecodedFrameQueue::clear() {
	    std::scoped_lock lock(mMtx);
	    while (!mQueue.empty()) {
	        Frame* frame = mQueue.front();
	        mQueue.pop_front();
	        releaseFrame(frame);
    }
	}

	size_t DecodedFrameQueue::size() const {
	    std::scoped_lock lock(mMtx);
	    return mQueue.size();
	}

}  // namespace AVSAnalyzer
