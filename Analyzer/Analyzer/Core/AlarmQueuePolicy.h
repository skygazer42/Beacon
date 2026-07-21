#ifndef ANALYZER_ALARM_QUEUE_POLICY_H
#define ANALYZER_ALARM_QUEUE_POLICY_H

#include <cstddef>
#include <string>

namespace AVSAnalyzer {

// Decide the maximum number of BGR frames kept in Worker alarm queue.
// Goal:
// - When alarm video is disabled (alarmVideoType == "none"), keep the queue small
//   to reduce per-control memory footprint on weak machines.
// - When alarm video is enabled, keep legacy behavior (queue max == alarmPrefixFrames).
size_t pickAlarmVideoQueueMaxFrames(const std::string& alarmVideoType, int alarmImageCount, int alarmPrefixFrames);

}

#endif // ANALYZER_ALARM_QUEUE_POLICY_H

