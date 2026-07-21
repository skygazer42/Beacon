#include "AlarmQueuePolicy.h"

#include <cassert>

using namespace AVSAnalyzer;

int main() {
    // With alarm video enabled, keep legacy behavior: queue max == prefix frames.
    assert(pickAlarmVideoQueueMaxFrames("mp4", 1, 30) == 30);

    // With alarm video disabled, queue max should be much smaller (memory protection).
    const size_t q1 = pickAlarmVideoQueueMaxFrames("none", 1, 30);
    assert(q1 >= 1);
    assert(q1 <= 2);

    const size_t q2 = pickAlarmVideoQueueMaxFrames("none", 5, 30);
    assert(q2 == 11);

    return 0;
}

