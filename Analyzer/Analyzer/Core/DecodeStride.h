#pragma once

#include "Control.h"

#include <algorithm>
#include <exception>
#include <stdexcept>
#include <string>

#include <json/json.h>

namespace AVSAnalyzer {

inline void applyDecodeStrideFromJson(const Json::Value& root, Control& control) {
    int stride = std::max(1, control.decodeStride);

    try {
        if (root["decodeStride"].isNumeric()) {
            stride = root["decodeStride"].asInt();
        } else if (root["decodeStride"].isString()) {
            stride = std::stoi(root["decodeStride"].asString());
        }
    } catch (const std::invalid_argument&) {
        stride = std::max(1, control.decodeStride);
    } catch (const std::out_of_range&) {
        stride = std::max(1, control.decodeStride);
    }

    stride = std::max(1, std::min(60, stride));
    control.decodeStride = stride;
}

}  // namespace AVSAnalyzer
