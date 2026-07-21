#include "LicenseLeaseRenewPolicy.h"

#include <algorithm>

namespace AVSAnalyzer {

int clampLicenseLeaseTtlSeconds(int configuredTtlSeconds) {
    return std::max(30, std::min(600, configuredTtlSeconds));
}

int64_t computeLicenseLeaseRenewIntervalMs(int ttlSeconds) {
    const int normalizedTtl = clampLicenseLeaseTtlSeconds(ttlSeconds);
    return std::max<int64_t>(10 * 1000, static_cast<int64_t>(normalizedTtl) * 1000 / 2);
}

bool shouldStopAfterRenewFailure(int64_t nowTs, int graceSeconds, int64_t& graceUntilTimestamp) {
    if (graceSeconds <= 0) {
        return true;
    }
    if (graceUntilTimestamp <= 0) {
        graceUntilTimestamp = nowTs + static_cast<int64_t>(graceSeconds) * 1000;
        return false;
    }
    return nowTs > graceUntilTimestamp;
}

}
