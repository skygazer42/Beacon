#ifndef ANALYZER_SHARED_DECODE_SESSION_H
#define ANALYZER_SHARED_DECODE_SESSION_H

#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace AVSAnalyzer {

class AvPullStream;
class Scheduler;
class Worker;
struct Control;

class SharedDecodeSession {
public:
    SharedDecodeSession(Scheduler* scheduler, const std::string& key, const Control& control);
    ~SharedDecodeSession();

    bool start(std::string& msg);
    void requestStop();
    bool getState() const;

    const std::string& getKey() const;
    void subscribe(Worker* worker);
    void unsubscribe(Worker* worker);
    void copyVideoInfoTo(Control* control) const;

private:
    static void decodeThread(SharedDecodeSession* arg);
    void handleDecode();
    void fanOutDecodedFrame(
        const unsigned char* buf,
        int size,
        int width,
        int height,
        int fps,
        int sourceQueueSize,
        int64_t timestampMs);

    Scheduler* mScheduler = nullptr;
    std::string mKey{};
    std::unique_ptr<Control> mControl;
    std::unique_ptr<AvPullStream> mPullStream;
    std::atomic<bool> mState{ false };
    std::vector<std::thread> mThreads;
    std::vector<Worker*> mSubscribers;
    mutable std::mutex mSubscribersMtx;
    bool mHasDecodeChannel = false;
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_SHARED_DECODE_SESSION_H
