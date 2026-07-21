#ifndef ANALYZER_JSON_BOOL_H
#define ANALYZER_JSON_BOOL_H

#include <algorithm>
#include <cctype>
#include <string>

#include <json/value.h>

namespace AVSAnalyzer {

inline bool parseJsonBool(const Json::Value& root, const char* key, bool defaultValue) {
    if (key == nullptr || *key == '\0') {
        return defaultValue;
    }
    if (!root.isObject()) {
        return defaultValue;
    }

    const Json::Value& value = root[key];
    if (value.isNull()) {
        return defaultValue;
    }
    if (value.isBool()) {
        return value.asBool();
    }
    if (value.isNumeric()) {
        return value.asInt() != 0;
    }
    if (value.isString()) {
        std::string v = value.asString();
        std::transform(v.begin(), v.end(), v.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (v == "1" || v == "true" || v == "yes" || v == "on") {
            return true;
        }
        if (v == "0" || v == "false" || v == "no" || v == "off") {
            return false;
        }
        return defaultValue;
    }

    return defaultValue;
}

} // namespace AVSAnalyzer

#endif // ANALYZER_JSON_BOOL_H

