#ifndef ANALYZER_SERVER_H
#define ANALYZER_SERVER_H

#include <atomic>
#include <thread>

namespace AVSAnalyzer {
class Scheduler;
}

class Server {
public:
    Server();
    ~Server();

    void start(AVSAnalyzer::Scheduler* scheduler);
    void stop();

private:
    void run(AVSAnalyzer::Scheduler* scheduler);
    std::atomic<bool> mStopRequested{ false };
    std::atomic<bool> mStarted{ false };
    std::thread mThread;
};

#endif // ANALYZER_SERVER_H
