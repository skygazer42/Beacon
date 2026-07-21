#include "BehaviorApiConfig.h"

#include <cassert>
#include <cmath>

using namespace AVSAnalyzer;

namespace AVSAnalyzer {
std::vector<std::string> parseBehaviorTargetsLowerCsv(const std::string& objectCodeCsv);
}

int main() {
    {
        const auto targets = parseBehaviorTargetsLowerCsv(" Person , ,CAR, bike ,,");
        assert(targets.size() == 3);
        assert(targets[0] == "person");
        assert(targets[1] == "car");
        assert(targets[2] == "bike");
    }

    {
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"crowd\",\"minCount\":7}", "any", "person,car");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Crowd);
        assert(cfg.crowdMinCount == 7);
        assert(cfg.targetsLower.size() == 2);
        assert(cfg.targetsLower[0] == "person");
        assert(cfg.targetsLower[1] == "car");
    }

    {
        // v4.709: behavior debug flag should be parsed (helps troubleshooting behavior decisions).
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"crowd\",\"minCount\":7,\"debug\":true}", "any", "person");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Crowd);
        assert(cfg.debug);
    }

    {
        // Fallback: allow behaviorAlgorithmCode itself to be a builtin label.
        auto cfg = parseBehaviorApiConfig("{\"apiVersion\":2}", "Loitering", "person");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Loitering);
    }

    {
        // v4.646: CROSSCOUNT builtin behavior (line crossing counting) should be recognized.
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"crosscount\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::CrossCount);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "crosscount");
    }

    {
        // v4.434-6: alternate spellings should normalize to CrossCount.
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"cross_count\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::CrossCount);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "crosscount");
    }

    {
        // v4.434-6: kebab-case spelling should also normalize to CrossCount.
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"cross-count\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::CrossCount);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "crosscount");
    }

    {
        // v4.434-6: behaviorAlgorithmCode fallback should also recognize CrossCount.
        auto cfg = parseBehaviorApiConfig("{\"apiVersion\":2}", "CrossCount", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::CrossCount);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "crosscount");
    }

    {
        // v4.437-5: legacy alias NOONE should normalize to absence.
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"noone\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Absence);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "absence");
    }

    {
        // v4.437-5: legacy alias LEAVE should normalize to unattended.
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"leave\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Unattended);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "unattended");
    }

    {
        // v4.720: CROWD should support <= threshold operator to trigger when count is low.
        auto cfg = parseBehaviorApiConfig(
            "{\"apiType\":\"v2\",\"builtinBehavior\":\"crowd\",\"countOp\":\"le\",\"maxCount\":0}",
            "any",
            "person");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Crowd);
        assert(cfg.crowdTriggerOp == CountTriggerOp::LE);
        assert(cfg.crowdMaxCount == 0);
    }

    {
        // v4.643: SUPER builtin behavior + center-point ratios (any point inside bbox).
        auto cfg = parseBehaviorApiConfig(
            "{\"apiType\":\"v2\",\"builtinBehavior\":\"super\",\"centerPointX\":0.2,\"centerPointY\":0.9}",
            "any",
            "person");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Super);
        assert(std::fabs(cfg.centerPointX - 0.2f) < 1e-6f);
        assert(std::fabs(cfg.centerPointY - 0.9f) < 1e-6f);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "super");
    }

    {
        // v4.705: MOTION builtin behavior + custom event name + displacement threshold.
        auto cfg = parseBehaviorApiConfig(
            "{\"apiType\":\"v2\",\"builtinBehavior\":\"motion\",\"eventName\":\"WANDER\",\"motionMinDisplacement\":18}",
            "any",
            "person");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Motion);
        assert(cfg.motionEventName == "WANDER");
        assert(cfg.motionMinDisplacement == 18);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "motion");
    }

    {
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"occlusion\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::Occlusion);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "occlusion");
    }

    {
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"grayscreen\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::GrayScreen);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "grayscreen");
    }

    {
        auto cfg = parseBehaviorApiConfig("{\"apiType\":\"v2\",\"builtinBehavior\":\"corruptscreen\"}", "any", "");
        assert(cfg.apiVersion == 2);
        assert(cfg.builtinBehavior == BuiltinBehaviorType::CorruptScreen);
        assert(builtinBehaviorTypeToString(cfg.builtinBehavior) == "corruptscreen");
    }

    return 0;
}
