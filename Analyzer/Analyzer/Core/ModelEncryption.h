#ifndef ANALYZER_MODEL_ENCRYPTION_H
#define ANALYZER_MODEL_ENCRYPTION_H

#include <cstdint>
#include <string>

namespace AVSAnalyzer {

struct ModelEncryptionConfig {
    bool enabled = false;
    std::string key{};
    std::string suffix{".enc"};
    std::string decryptDir{};
};

// Resolve `requestedPath` and decrypt if needed.
//
// Supported inputs:
// - Base path (e.g. /models/y.onnx): if file missing but `${base}${suffix}` exists, it decrypts.
// - Explicit encrypted path (e.g. /models/y.onnx.enc): if `enabled`, it decrypts to y.onnx.
//
// When decrypting, files are written under `${decryptDir}/<algo-subdir>/` (derived from algorithmCode).
bool resolveAndMaybeDecryptModel(
    const ModelEncryptionConfig& cfg,
    const std::string& algorithmCode,
    const std::string& requestedPath,
    std::string& outPath,
    std::string& outDecryptedDir,
    std::string& errMsg
);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_MODEL_ENCRYPTION_H
