#include "AlgorithmInstanceKey.h"

#include <algorithm>
#include <cctype>
#include <exception>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace AVSAnalyzer {
namespace {

std::string toUpper(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return value;
}

int clampDim(int value, int fallback) {
    if (value <= 0) {
        return fallback;
    }
    // Prevent accidental OOM / unreasonable shapes; keep it simple.
    const int kMax = 8192;
    return std::min(value, kMax);
}

std::string normalizePrecision(std::string value) {
    value = toUpper(value);
    if (value == "F16") value = "FP16";
    if (value == "F32") value = "FP32";
    if (value == "I8") value = "INT8";

    if (value == "FP32" || value == "FP16" || value == "INT8") {
        return value;
    }
    // Unknown / empty precision => industrial-safe default.
    return "FP32";
}

std::string makeVariantPath(const std::string& basePath, const std::string& suffixLower) {
    if (basePath.empty()) {
        return basePath;
    }
    std::filesystem::path p(basePath);
    const std::string stem = p.stem().string();
    if (const std::string ext = p.extension().string(); !ext.empty()) {  // includes dot
        return (p.parent_path() / (stem + suffixLower + ext)).string();
    }
    return (p.parent_path() / (stem + suffixLower)).string();
}

}  // namespace

ModelConfig normalizeModelConfig(const std::string& precision, int inputWidth, int inputHeight) {
    ModelConfig cfg;
    cfg.precision = normalizePrecision(precision);
    cfg.inputWidth = clampDim(inputWidth, 640);
    cfg.inputHeight = clampDim(inputHeight, 640);
    return cfg;
}

std::string buildAlgorithmInstanceKey(const std::string& algorithmCode, const ModelConfig& cfg) {
    ModelConfig normalized = normalizeModelConfig(cfg.precision, cfg.inputWidth, cfg.inputHeight);
    std::string key = algorithmCode;
    key.append("__");
    key.append(normalized.precision);
    key.append("__");
    key.append(std::to_string(normalized.inputWidth));
    key.push_back('x');
    key.append(std::to_string(normalized.inputHeight));
    return key;
}

bool parseAlgorithmInstanceKey(const std::string& key, std::string& algorithmCode, ModelConfig& cfg) {
    if (key.empty()) {
        return false;
    }

    // Do not clobber outputs on parse failure; callers often rely on fallback values.
    std::string parsedAlgorithmCode;
    ModelConfig parsedCfg = cfg;

    // Parse from right to left to avoid issues when algorithmCode contains underscores.
    const std::string delim = "__";
    size_t p2 = key.rfind(delim);
    if (p2 == std::string::npos) {
        return false;
    }
    size_t p1 = key.rfind(delim, p2 - 1);
    if (p1 == std::string::npos) {
        return false;
    }

    parsedAlgorithmCode = key.substr(0, p1);
    std::string precision = key.substr(p1 + delim.size(), p2 - (p1 + delim.size()));
    std::string sizePart = key.substr(p2 + delim.size());
    if (parsedAlgorithmCode.empty() || precision.empty() || sizePart.empty()) {
        return false;
    }

    size_t xPos = sizePart.find('x');
    if (xPos == std::string::npos) {
        return false;
    }
    int w = 0;
    int h = 0;
    try {
        w = std::stoi(sizePart.substr(0, xPos));
        h = std::stoi(sizePart.substr(xPos + 1));
    }
    catch (const std::invalid_argument&) {
        return false;
    }
    catch (const std::out_of_range&) {
        return false;
    }

    parsedCfg = normalizeModelConfig(precision, w, h);
    algorithmCode = parsedAlgorithmCode;
    cfg = parsedCfg;
    return true;
}

std::string selectModelPathByPrecision(const std::string& basePath, const std::string& precision) {
    const std::string p = normalizePrecision(precision);
    if (p == "FP32") {
        return basePath;
    }

    std::string suffixLower = "";
    if (p == "FP16") {
        suffixLower = "_fp16";
    }
    else if (p == "INT8") {
        suffixLower = "_int8";
    }
    else {
        return basePath;
    }

    std::string variant = makeVariantPath(basePath, suffixLower);
    if (std::error_code ec; !variant.empty() && std::filesystem::exists(std::filesystem::path(variant), ec)) {
        return variant;
    }
    return basePath;
}

}  // namespace AVSAnalyzer
