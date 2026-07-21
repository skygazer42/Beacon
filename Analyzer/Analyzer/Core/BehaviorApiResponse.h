#pragma once

#include <json/json.h>

namespace AVSAnalyzer {

// Extract user-defined metadata from a behavior API response `result` object.
//
// Supported shapes:
// - result.user_data (object)
// - result.userData (object)
// - result.metadata.user_data (object)
//
// Returns true and sets outUserData when a non-empty object is found.
bool extractBehaviorUserData(const Json::Value& result, Json::Value& outUserData);

}  // namespace AVSAnalyzer

