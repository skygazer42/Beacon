#include "ApiInferGuard.h"

#include <cassert>

using namespace AVSAnalyzer;

static void test_min_interval() {
    ApiInferGuard guard;
    ApiInferGuardConfig cfg;
    cfg.minIntervalMs = 1000;
    guard.setConfig(cfg);

    std::string reason;
    assert(guard.tryAcquire(1000, &reason) == true);
    assert(reason.empty());

    assert(guard.tryAcquire(1500, &reason) == false);
    assert(reason == "min_interval");

    assert(guard.tryAcquire(2000, &reason) == true);
    assert(reason.empty());
}

static void test_circuit_breaker_open_and_recover() {
    ApiInferGuard guard;
    ApiInferGuardConfig cfg;
    cfg.circuitBreakerFails = 3;
    cfg.circuitBreakerOpenSeconds = 5;
    guard.setConfig(cfg);

    std::string reason;
    assert(guard.tryAcquire(0, &reason) == true);
    bool opened = false;
    guard.recordResult(false, 0, &opened);
    assert(opened == false);

    assert(guard.tryAcquire(1000, &reason) == true);
    guard.recordResult(false, 1000, &opened);
    assert(opened == false);

    assert(guard.tryAcquire(2000, &reason) == true);
    guard.recordResult(false, 2000, &opened);
    assert(opened == true);

    // circuit should be open until 2000+5000=7000
    assert(guard.tryAcquire(6500, &reason) == false);
    assert(reason == "circuit_open");

    assert(guard.tryAcquire(7000, &reason) == true);
    assert(reason.empty());
}

static void test_success_resets_failures() {
    ApiInferGuard guard;
    ApiInferGuardConfig cfg;
    cfg.circuitBreakerFails = 2;
    cfg.circuitBreakerOpenSeconds = 10;
    guard.setConfig(cfg);

    std::string reason;
    assert(guard.tryAcquire(0, &reason) == true);
    bool opened = false;
    guard.recordResult(false, 0, &opened);
    assert(opened == false);

    guard.recordResult(true, 500, &opened);
    assert(opened == false);

    // After success, failure count should reset, so one more failure should not open.
    assert(guard.tryAcquire(1000, &reason) == true);
    guard.recordResult(false, 1000, &opened);
    assert(opened == false);
}

int main() {
    test_min_interval();
    test_circuit_breaker_open_and_recover();
    test_success_resets_failures();
    return 0;
}

