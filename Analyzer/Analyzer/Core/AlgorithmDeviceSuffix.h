#ifndef ANALYZER_ALGORITHM_DEVICE_SUFFIX_H
#define ANALYZER_ALGORITHM_DEVICE_SUFFIX_H

#include <string>
#include <string_view>

namespace AVSAnalyzer {

// Parse algorithm code suffix to extract base code and device string.
//
// Supported suffixes (case-insensitive):
// - _cpu  => CPU
// - _gpu  => GPU (ONNX runtime will map GPU->CUDA internally)
// - _trt  => TRT (ONNX runtime will map TRT->TENSORRT internally)
// - _auto => AUTO
// - _npu  => NPU
//
// v4.17: add optional numeric device id suffix for multi-GPU:
// - _gpu1 => GPU:1
// - _trt0 => TRT:0
//
// If no suffix is present, device defaults to CPU and baseCode == code.
void parseAlgorithmDeviceSuffix(std::string_view code, std::string& baseCode, std::string& device);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_ALGORITHM_DEVICE_SUFFIX_H
