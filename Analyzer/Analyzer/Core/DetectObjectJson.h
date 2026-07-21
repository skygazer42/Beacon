#pragma once

#include <string>

#include <json/value.h>

#include "Algorithm.h"

namespace AVSAnalyzer {

Json::Value detectObjectToJson(const DetectObject& d);

// Best-effort parser:
// - Accepts bbox/class fields (numeric or string)
// - Accepts pose keypoints in multiple common formats:
//     1) keypoints: [{x,y,confidence}, ...]
//     2) keypoints: [[x,y,c], ...]
//     3) keypoints: [x,y,c,x,y,c,...]
// - Accepts segmentation polygon in multiple common formats:
//     1) polygon: [[x,y], ...]
//     2) polygon: [{x,y}, ...]
//     3) polygon: [x,y,x,y,...]
// - Also accepts pose.keypoints in the same formats.
bool parseDetectObjectFromJson(const Json::Value& item, DetectObject& out, std::string* errMsg = nullptr);

}  // namespace AVSAnalyzer
