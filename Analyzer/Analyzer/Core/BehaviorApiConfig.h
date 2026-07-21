#ifndef ANALYZER_BEHAVIOR_API_CONFIG_H
#define ANALYZER_BEHAVIOR_API_CONFIG_H

#include <cstddef>
#include <string>
#include <vector>

namespace AVSAnalyzer {

enum class BuiltinBehaviorType {
    Intrusion = 0,
    Crowd = 1,
    Crossing = 2,
    Loitering = 3,
    Absence = 4,
    Unattended = 5,
    CrossCount = 6,
    Super = 7,
    Motion = 8,
    Occlusion = 9,
    GrayScreen = 10,
    CorruptScreen = 11,
};

enum class CountTriggerOp {
    GE = 0,
    LE = 1,
};

struct BehaviorApiConfig {
    int apiVersion = 1;  // 1=v1, 2=v2 (hybrid), 3=v3 (future)
    BuiltinBehaviorType builtinBehavior = BuiltinBehaviorType::Intrusion;

    float regionIouThresh = 0.5f;
    // SUPER: choose any point inside bbox as "center" for region hit-test.
    // range: [0,1] where (0,0)=top-left, (1,1)=bottom-right.
    float centerPointX = 0.5f;
    float centerPointY = 0.5f;
    int crowdMinCount = 5;
    CountTriggerOp crowdTriggerOp = CountTriggerOp::GE;
    int crowdMaxCount = 0;  // used when crowdTriggerOp == LE
    int loiteringSeconds = 10;
    int motionMinDisplacement = 12;  // pixels between track trajectory endpoints
    std::string motionEventName = "MOTION";

    // v4.709: enable verbose logs to help debug behavior API + builtin decisions.
    bool debug = false;

    // Lowercased CSV targets from objectCode (empty = match all)
    std::vector<std::string> targetsLower;
};

class BehaviorApiConfigCache {
public:
    const BehaviorApiConfig& get(
        const std::string& behaviorConfigJson,
        const std::string& behaviorAlgorithmCode,
        const std::string& objectCodeCsv);

    size_t parseCount() const { return mParseCount; }

private:
    BehaviorApiConfig mCached{};
    std::string mLastBehaviorConfigJson{};
    std::string mLastBehaviorAlgorithmCode{};
    std::string mLastObjectCodeCsv{};
    bool mHasValue = false;
    size_t mParseCount = 0;
};

BuiltinBehaviorType parseBuiltinBehaviorType(const std::string& value, BuiltinBehaviorType fallback = BuiltinBehaviorType::Intrusion);
std::string builtinBehaviorTypeToString(BuiltinBehaviorType t);
std::vector<std::string> parseBehaviorTargetsLowerCsv(const std::string& objectCodeCsv);

BehaviorApiConfig parseBehaviorApiConfig(
    const std::string& behaviorConfigJson,
    const std::string& behaviorAlgorithmCode,
    const std::string& objectCodeCsv);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_BEHAVIOR_API_CONFIG_H
