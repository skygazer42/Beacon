#include "Frame.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <exception>
#include <new>
#include <limits>
#include <cstring>

namespace AVSAnalyzer {
	namespace {
		size_t computeDefaultMaxFrames(size_t frameBytes, size_t budgetBytes) {
			if (frameBytes == 0) {
				return 1;
			}
			size_t v = budgetBytes / frameBytes;
			if (v < 1) {
				v = 1;
			}
			// Avoid pathological huge counts when frame size is small (tests, small streams).
			const size_t cap = 200;
			return std::min(v, cap);
		}

		size_t readEnvMaxFrames() {
			const char* raw = std::getenv("BEACON_FRAMEPOOL_MAX_FRAMES");
			if (!raw || !*raw) {
				return 0;
			}
			errno = 0;
			char* end = nullptr;
			unsigned long long value = std::strtoull(raw, &end, 10);
			if (end == raw) {
				return 0;
			}
			if (errno != 0) {
				return 0;
			}
			if (value == 0) {
				return 0;
			}
			if (value > static_cast<unsigned long long>(std::numeric_limits<size_t>::max())) {
				return 0;
			}
			return static_cast<size_t>(value);
		}

		size_t readEnvBudgetMb() {
			const char* raw = std::getenv("BEACON_FRAMEPOOL_BUDGET_MB");
			if (!raw || !*raw) {
				return 0;
			}
			errno = 0;
			char* end = nullptr;
			unsigned long long value = std::strtoull(raw, &end, 10);
			if (end == raw) {
				return 0;
			}
			if (errno != 0) {
				return 0;
			}
			if (value == 0) {
				return 0;
			}
			if (value > 10240ULL) { // 10GB upper bound safety
				return 0;
			}
			return static_cast<size_t>(value);
		}

			size_t computePoolMaxFrames(size_t frameBytes) {
				if (const size_t maxFromEnv = readEnvMaxFrames(); maxFromEnv > 0) {
					return maxFromEnv;
				}

				size_t budgetMb = readEnvBudgetMb();
				if (budgetMb == 0) {
				budgetMb = 128;
			}
			const size_t budgetBytes = budgetMb * 1024ULL * 1024ULL;
			return computeDefaultMaxFrames(frameBytes, budgetBytes);
		}
	}

	Frame::Frame(int bufInitSize) {
        //LOGI("");
		mBufInitSize = std::max(0, bufInitSize);
		mBuf.resize(static_cast<size_t>(mBufInitSize));
	}
	    void Frame::setBuf(const unsigned char* buf, int size) {

	        if (this->mBufInitSize == size) {
	            this->mBufSize = size;
	            std::memcpy(mBuf.data(), buf, static_cast<size_t>(size));
	        }
	        else {
	            LOGE("Frame::setBuf size=%d over max", size);
	            this->mBufSize = -1;
        }

    }
    void Frame::setSize(int size) {
        if (this->mBufInitSize == size) {
            this->mBufSize = size;
        }
        else {
            LOGE("Frame::setSize size=%d over max", size);
            this->mBufSize = -1;
        }
	    }
	    unsigned char* Frame::getBuf() {
	        return mBuf.empty() ? nullptr : mBuf.data();
	    }
    int Frame::getSize() const {
        return this->mBufSize;
    }
    int Frame::getCapacity() const {
		return this->mBufInitSize;
	}
    void Frame::setAlarmRawSnapshot(const unsigned char* buf, int size) {
        if (!buf || size <= 0) {
            mAlarmRawSnapshot.clear();
            return;
        }
        mAlarmRawSnapshot.assign(buf, buf + size);
    }
    void Frame::clearAlarmRawSnapshot() {
        mAlarmRawSnapshot.clear();
    }
    const unsigned char* Frame::getAlarmRawSnapshot() const {
        if (mAlarmRawSnapshot.empty()) {
            return nullptr;
        }
        return mAlarmRawSnapshot.data();
    }
    int Frame::getAlarmRawSnapshotSize() const {
        return static_cast<int>(mAlarmRawSnapshot.size());
    }
    bool Frame::hasAlarmRawSnapshot() const {
        return !mAlarmRawSnapshot.empty();
    }
			    FramePool::FramePool(int size) :mSize(size)
			    {
			        LOGI("");
		        // FramePool is used for large BGR frames (often 720p/1080p). If the producer is
		        // faster than the consumer (weak machines), unbounded allocations will quickly
		        // exhaust memory and crash the process.
			        mMaxFrames = computePoolMaxFrames(static_cast<size_t>(mSize));
			    }
    FramePool::~FramePool()
    {
        LOGI("");
        clearFrameQ();
    }

	    void FramePool::clearFrameQ() {
	        std::scoped_lock lock(mFrameQ_mtx);
	        while (!mFrameQ.empty())
	        {
	            mFrameQ.pop();
	            if (mAllocatedFrames > 0) {
	                mAllocatedFrames--;
	            }
	        }
	    }
		    Frame* FramePool::gain() {
		        std::unique_ptr<Frame> owned;
		        int sizeToAlloc = 0;

			        {
			            std::scoped_lock lock(mFrameQ_mtx);
			            if (!mFrameQ.empty()) {
			                owned = std::move(mFrameQ.front());
			                mFrameQ.pop();
			                return owned.release();
	            }
	            if (mMaxFrames > 0 && mAllocatedFrames >= mMaxFrames) {
	                return nullptr;
		            }
		            // Reserve one slot for allocation (do it outside the lock).
		            mAllocatedFrames++;
					sizeToAlloc = mSize;
		        }

		        try {
		            owned = std::make_unique<Frame>(sizeToAlloc);
		        }
		        catch (const std::bad_alloc&) {
		            std::scoped_lock lock(mFrameQ_mtx);
		            if (mAllocatedFrames > 0) {
		                mAllocatedFrames--;
		            }
		            return nullptr;
		        }

	        return owned.release();
	    }
			    void FramePool::giveBack(Frame* frame) {
			        if (!frame) {
			            return;
			        }
			        std::unique_ptr<Frame> owned(frame);
			        std::scoped_lock lock(mFrameQ_mtx);
					// Resolution-change hardening: if the Frame capacity mismatches current pool size,
					// do not put it back (would later cause "花屏"/OOB). Drop it and free memory.
					if (owned->getCapacity() != mSize) {
					if (mAllocatedFrames > 0) {
						mAllocatedFrames--;
					}
					return;
				}
		        mFrameQ.push(std::move(owned));

		    }

			void FramePool::resetSize(int size) {
				if (size <= 0) {
					return;
				}
				std::scoped_lock lock(mFrameQ_mtx);
				if (size == mSize) {
					return;
				}

				while (!mFrameQ.empty()) {
					mFrameQ.pop();
					if (mAllocatedFrames > 0) {
						mAllocatedFrames--;
					}
				}

			mSize = size;
			mMaxFrames = computePoolMaxFrames(static_cast<size_t>(mSize));
		}
}
