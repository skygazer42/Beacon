#pragma once

#include <cstdint>

namespace AVSAnalyzer {

int clampLicenseLeaseTtlSeconds(int configuredTtlSeconds);
int64_t computeLicenseLeaseRenewIntervalMs(int ttlSeconds);
bool shouldStopAfterRenewFailure(int64_t nowTs, int graceSeconds, int64_t& graceUntilTimestamp);

}
