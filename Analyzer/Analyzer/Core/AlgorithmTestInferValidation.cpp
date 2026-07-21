#include "AlgorithmTestInferValidation.h"

#include <algorithm>
#include <cctype>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace AVSAnalyzer {
    namespace {
        std::string join_csv(const std::vector<std::string>& items) {
            std::ostringstream oss;
            for (size_t i = 0; i < items.size(); i++) {
                if (i) {
                    oss << ",";
                }
                oss << items[i];
            }
            return oss.str();
        }

        bool parse_float_strict(const Json::Value& v, float& out, std::string& errMsg, const std::string& key) {
            if (v.isNumeric()) {
                out = v.asFloat();
                return true;
            }
            if (v.isString()) {
                try {
                    out = std::stof(v.asString());
                    return true;
                }
                catch (...) {
                    errMsg = key + " must be a number";
                    return false;
                }
            }
            errMsg = key + " must be a number";
            return false;
        }
    }

    bool validate_algorithm_test_infer_request(const Json::Value& root, std::string& errMsg) {
        const std::set<std::string> allowed = {
            "code",
            "image_base64",
            "confThresh",
            "nmsThresh",
        };

        std::vector<std::string> unsupported;
        for (const auto& key : root.getMemberNames()) {
            if (allowed.find(key) == allowed.end()) {
                unsupported.push_back(key);
            }
        }
        if (!unsupported.empty()) {
            std::sort(unsupported.begin(), unsupported.end());
            errMsg = "unsupported params: " + join_csv(unsupported);
            return false;
        }

        if (root.isMember("confThresh")) {
            float conf = 0.0f;
            if (!parse_float_strict(root.get("confThresh", Json::Value()), conf, errMsg, "confThresh")) {
                return false;
            }
            if (conf < 0.0f || conf > 1.0f) {
                errMsg = "confThresh out of range (expected 0~1)";
                return false;
            }
        }

        if (root.isMember("nmsThresh")) {
            float nms = 0.0f;
            if (!parse_float_strict(root.get("nmsThresh", Json::Value()), nms, errMsg, "nmsThresh")) {
                return false;
            }
            if (nms < 0.0f || nms > 1.0f) {
                errMsg = "nmsThresh out of range (expected 0~1)";
                return false;
            }
        }

        errMsg = "ok";
        return true;
    }

} // namespace AVSAnalyzer

