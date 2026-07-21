#ifndef ANALYZER_ALARM_NOTIFY_BACKOFF_H
#define ANALYZER_ALARM_NOTIFY_BACKOFF_H

#include <cstdint>

namespace AVSAnalyzer {

// Exponential backoff for alarm notify retries (ms).
// - attempt=0 => 1000ms
// - attempt=1 => 2000ms
// - capped at 30000ms
int64_t computeAlarmNotifyBackoffMs(int attempt);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_ALARM_NOTIFY_BACKOFF_H

