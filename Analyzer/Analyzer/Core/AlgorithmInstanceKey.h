#ifndef ANALYZER_ALGORITHM_INSTANCE_KEY_H
#define ANALYZER_ALGORITHM_INSTANCE_KEY_H

#include <string>

namespace AVSAnalyzer {

struct ModelConfig {
    std::string precision;  // FP32/FP16/INT8
    int inputWidth = 640;
    int inputHeight = 640;
};

ModelConfig normalizeModelConfig(const std::string& precision, int inputWidth, int inputHeight);

// Internal reuse key for model instances (per-control granularity).
// Format: <algorithmCode>__<PRECISION>__<W>x<H>
std::string buildAlgorithmInstanceKey(const std::string& algorithmCode, const ModelConfig& cfg);

bool parseAlgorithmInstanceKey(const std::string& key, std::string& algorithmCode, ModelConfig& cfg);

// Precision is best-effort and implemented via model file variants:
// - FP32 => basePath
// - FP16 => prefer *_fp16.<ext>
// - INT8 => prefer *_int8.<ext>
// If variant not found, falls back to basePath.
std::string selectModelPathByPrecision(const std::string& basePath, const std::string& precision);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_ALGORITHM_INSTANCE_KEY_H

