#include "SharedDecodeKey.h"

#include <algorithm>
#include <cctype>

namespace AVSAnalyzer {

namespace {

std::string trimCopy(std::string value) {
    auto notSpace = [](unsigned char ch) { return std::isspace(ch) == 0; };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
    value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
    return value;
}

}  // namespace

DecodeReuseKey makeDecodeReuseKey(
    const std::string& streamUrl,
    bool ffmpegSkipLoopFilter,
    bool ffmpegSkipIdct) {
    DecodeReuseKey key;
    key.value = trimCopy(streamUrl);
    key.value += "|slf=";
    key.value += ffmpegSkipLoopFilter ? "1" : "0";
    key.value += "|sidct=";
    key.value += ffmpegSkipIdct ? "1" : "0";
    return key;
}

}  // namespace AVSAnalyzer
