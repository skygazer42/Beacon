#include "LicenseLeaseRenewPolicy.h"

#include <cassert>
#include <cstdint>

using namespace AVSAnalyzer;

int main() {
    assert(clampLicenseLeaseTtlSeconds(0) == 30);
    assert(clampLicenseLeaseTtlSeconds(120) == 120);
    assert(clampLicenseLeaseTtlSeconds(999) == 600);

    assert(computeLicenseLeaseRenewIntervalMs(30) == 15000);
    assert(computeLicenseLeaseRenewIntervalMs(120) == 60000);
    assert(computeLicenseLeaseRenewIntervalMs(600) == 300000);

    int64_t graceUntil = 0;
    assert(shouldStopAfterRenewFailure(/*nowTs=*/1000, /*graceSeconds=*/0, graceUntil) == true);
    assert(graceUntil == 0);

    graceUntil = 0;
    assert(shouldStopAfterRenewFailure(/*nowTs=*/1000, /*graceSeconds=*/600, graceUntil) == false);
    assert(graceUntil == 601000);

    assert(shouldStopAfterRenewFailure(/*nowTs=*/2000, /*graceSeconds=*/600, graceUntil) == false);
    assert(graceUntil == 601000);

    assert(shouldStopAfterRenewFailure(/*nowTs=*/601001, /*graceSeconds=*/600, graceUntil) == true);
    assert(graceUntil == 601000);

    return 0;
}
