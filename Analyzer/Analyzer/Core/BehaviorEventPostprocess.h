#ifndef ANALYZER_BEHAVIOR_EVENT_POSTPROCESS_H
#define ANALYZER_BEHAVIOR_EVENT_POSTPROCESS_H

#include <cstdint>
#include <string>
#include <vector>

namespace AVSAnalyzer {

enum class BehaviorEventPostprocessMode {
    None = 0,
    Absence = 1,
    Unattended = 2,
};

struct BehaviorEventPostprocessConfig {
    bool enabled = false;
    BehaviorEventPostprocessMode mode = BehaviorEventPostprocessMode::None;
    int64_t thresholdMs = 0; // requires continuous rawHappen=true for this duration
};

// Parse postprocess config from control.behaviorConfig JSON (best-effort).
// Industrial defaults:
// - For objectCode=absence/unattended: enabled by default with 3s threshold.
// - Otherwise: enabled only when behaviorConfig.postprocess is set.
BehaviorEventPostprocessConfig parseBehaviorEventPostprocessConfig(
    const std::string& behaviorConfigJson,
    const std::string& objectCode);

class BehaviorEventPostprocessor {
public:
    BehaviorEventPostprocessor() = default;
    explicit BehaviorEventPostprocessor(const BehaviorEventPostprocessConfig& config);

    void setConfig(const BehaviorEventPostprocessConfig& config);
    const BehaviorEventPostprocessConfig& config() const;

    bool enabled() const;
    void reset();

    // Returns gated event state.
    bool update(bool rawHappen, int64_t nowMs);

    bool isActive() const { return mActive; }
    int64_t startMs() const { return mStartMs; }
    int64_t activeDurationMs(int64_t nowMs) const;

private:
    BehaviorEventPostprocessConfig mConfig{};
    bool mActive = false;
    int64_t mStartMs = 0;
};

// Per-region variant of BehaviorEventPostprocessor.
// Used by absence/unattended builtin behavior when multiple recognition regions exist:
// - Each region gates independently
// - update() returns the first region index that passes the gate, or -1
class PerRegionBehaviorEventPostprocessor {
public:
    PerRegionBehaviorEventPostprocessor() = default;

    void setConfig(const BehaviorEventPostprocessConfig& config, size_t regionCount);
    const BehaviorEventPostprocessConfig& config() const;
    bool enabled() const;
    size_t regionCount() const;
    void reset();

    // rawHappenPerRegion[i]=true means region i should be considered "raw happen" this tick.
    // Returns region index that is gated true, or -1 when no region triggers.
    int update(const std::vector<bool>& rawHappenPerRegion, int64_t nowMs);

    int64_t activeDurationMs(size_t regionIndex, int64_t nowMs) const;

private:
    BehaviorEventPostprocessConfig mConfig{};
    std::vector<BehaviorEventPostprocessor> mRegions;
};

} // namespace AVSAnalyzer

#endif // ANALYZER_BEHAVIOR_EVENT_POSTPROCESS_H
