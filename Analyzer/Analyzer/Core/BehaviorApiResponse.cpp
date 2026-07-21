#include "BehaviorApiResponse.h"

namespace AVSAnalyzer {

static const Json::Value* pick_user_data_node(const Json::Value& result) {
    if (!result.isObject()) {
        return nullptr;
    }

    const Json::Value& ud = result["user_data"];
    if (ud.isObject()) {
        return &ud;
    }

    const Json::Value& ud2 = result["userData"];
    if (ud2.isObject()) {
        return &ud2;
    }

    const Json::Value& meta = result["metadata"];
    if (meta.isObject()) {
        const Json::Value& ud3 = meta["user_data"];
        if (ud3.isObject()) {
            return &ud3;
        }
    }

    return nullptr;
}

bool extractBehaviorUserData(const Json::Value& result, Json::Value& outUserData) {
    outUserData = Json::Value(Json::objectValue);

    const Json::Value* node = pick_user_data_node(result);
    if (!node) {
        return false;
    }
    if (!node->isObject()) {
        return false;
    }
    if (node->getMemberNames().empty()) {
        return false;
    }

    outUserData = *node;
    return true;
}

}  // namespace AVSAnalyzer

