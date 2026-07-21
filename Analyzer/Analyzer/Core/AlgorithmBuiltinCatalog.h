#ifndef ANALYZER_ALGORITHM_BUILTIN_CATALOG_H
#define ANALYZER_ALGORITHM_BUILTIN_CATALOG_H

#include <string>
#include <string_view>
#include <vector>

namespace AVSAnalyzer {

enum class BuiltinAlgorithmEngine {
    Onnx,
    OpenVino
};

struct BuiltinAlgorithmMeta {
    std::string code;
    std::string relativePath;
    std::vector<std::string> classNames;
    BuiltinAlgorithmEngine engine;
    std::string subtype;
};

const std::vector<BuiltinAlgorithmMeta>& builtin_algorithm_catalog();
const BuiltinAlgorithmMeta* find_builtin_algorithm_meta(std::string_view code);

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHM_BUILTIN_CATALOG_H
