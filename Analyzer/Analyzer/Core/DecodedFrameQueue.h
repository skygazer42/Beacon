#ifndef ANALYZER_DECODED_FRAME_QUEUE_H
#define ANALYZER_DECODED_FRAME_QUEUE_H

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <functional>
#include <mutex>

#include "Frame.h"

namespace AVSAnalyzer {

class DecodedFrameQueue {
public:
    using Releaser = std::function<void(Frame*)>;

    explicit DecodedFrameQueue(size_t maxFrames, Releaser releaser = Releaser{});
    ~DecodedFrameQueue();

    void push(Frame* frame);
    bool pop(Frame*& frame);
    void clear();
    size_t size() const;

private:
    void releaseFrame(Frame* frame) const;

    size_t mMaxFrames = 1;
    Releaser mReleaser;
    mutable std::mutex mMtx;
    std::deque<Frame*> mQueue;
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_DECODED_FRAME_QUEUE_H
