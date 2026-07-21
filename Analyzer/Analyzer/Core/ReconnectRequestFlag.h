#pragma once

#include <atomic>

namespace AVSAnalyzer {
class ReconnectRequestFlag {
public:
    bool request() {
        bool expected = false;
        return requested_.compare_exchange_strong(expected, true);
    }

    bool consume() { return requested_.exchange(false); }

    bool isRequested() const { return requested_.load(); }

private:
    std::atomic<bool> requested_{false};
};
}  // namespace AVSAnalyzer

