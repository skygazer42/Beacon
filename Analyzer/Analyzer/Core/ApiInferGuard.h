#ifndef ANALYZER_API_INFER_GUARD_H
#define ANALYZER_API_INFER_GUARD_H

#include <cstdint>
#include <string>

namespace AVSAnalyzer {

struct ApiInferGuardConfig {
    // Minimum interval between allowed API inference calls (monotonic ms).
    // 0 means disabled.
    int64_t minIntervalMs = 0;

    // Circuit breaker: consecutive failures threshold to open the circuit.
    // 0 means disabled.
    int circuitBreakerFails = 0;

    // Circuit open duration in seconds (only effective when circuitBreakerFails > 0).
    int circuitBreakerOpenSeconds = 0;
};

struct ApiInferGuardState {
    int64_t lastAcquireMs = 0;
    int consecutiveFailures = 0;
    int64_t circuitOpenUntilMs = 0;
};

class ApiInferGuard {
public:
    ApiInferGuard() = default;
    explicit ApiInferGuard(ApiInferGuardConfig cfg) : mCfg(cfg) {}

    void setConfig(ApiInferGuardConfig cfg) { mCfg = cfg; }
    ApiInferGuardConfig config() const { return mCfg; }

    ApiInferGuardState state() const { return mState; }

    // Try to acquire a "token" for calling external API inference.
    // Returns true if allowed; false if blocked by min-interval or circuit-open.
    // When allowed, it records the acquire timestamp for min-interval accounting.
    bool tryAcquire(int64_t nowMonoMs, std::string* reason = nullptr);

    // Record the result of an API inference attempt.
    // ok=true resets failures and closes circuit.
    // ok=false increments consecutive failure count and may open circuit.
    // If circuit was opened by this call, circuitOpened will be set to true.
    void recordResult(bool ok, int64_t nowMonoMs, bool* circuitOpened = nullptr);

private:
    ApiInferGuardConfig mCfg{};
    ApiInferGuardState mState{};
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_API_INFER_GUARD_H

