#include "AlgorithmLoadValidation.h"

#include <cassert>
#include <string>
#include <vector>

using namespace AVSAnalyzer;

static void test_detection_onnx_requires_classnames() {
    std::string err;
    std::vector<std::string> classNames;
    bool ok = validate_algorithm_load_request(
        "alg-1",
        "/tmp/a.onnx",
        classNames,
        AlgorithmSubtype::Detection,
        err
    );
    assert(ok == false);
    assert(err == "classNames array is required");
}

static void test_tracking_onnx_allows_empty_classnames() {
    std::string err;
    std::vector<std::string> classNames;
    bool ok = validate_algorithm_load_request(
        "trk-1",
        "/tmp/reid.onnx",
        classNames,
        AlgorithmSubtype::Tracking,
        err
    );
    assert(ok == true);
}

static void test_plugin_allows_empty_classnames() {
    std::string err;
    std::vector<std::string> classNames;
    bool ok = validate_algorithm_load_request(
        "plg-1",
        "C:/beacon/plugins/alg.dll",
        classNames,
        AlgorithmSubtype::Detection,
        err
    );
    assert(ok == true);
}

static void test_ocr_subtype_requires_classnames_for_onnx() {
    std::string err;
    std::vector<std::string> classNames;
    bool ok = validate_algorithm_load_request(
        "ocr-1",
        "/tmp/xcocr.onnx",
        classNames,
        AlgorithmSubtype::Ocr,
        err
    );
    assert(ok == false);
    assert(err == "classNames array is required");
}

static void test_parse_algorithm_subtype_ocr() {
    assert(normalize_algorithm_subtype("ocr") == "ocr");
    assert(parse_algorithm_subtype("ocr") == AlgorithmSubtype::Ocr);
}

static void test_inference_device_decision_reports_requested_effective_and_reason() {
    const InferenceDeviceDecision decision = make_inference_device_decision(
        "GPU:1",
        "CPU",
        "CUDAExecutionProvider not available"
    );
    assert(decision.requestedDevice == "CUDA:1");
    assert(decision.effectiveDevice == "CPU");
    assert(decision.degraded);
    assert(decision.reason == "CUDAExecutionProvider not available");
}

static void test_force_inference_device_rejects_only_real_fallbacks() {
    std::string err;
    const InferenceDeviceDecision degraded = make_inference_device_decision(
        "TRT",
        "CUDA",
        "TensorrtExecutionProvider not available"
    );
    assert(!inference_device_decision_allowed(degraded, true, err));
    assert(err.find("TENSORRT") != std::string::npos);
    assert(err.find("CUDA") != std::string::npos);

    err.clear();
    assert(inference_device_decision_allowed(degraded, false, err));
    assert(err.empty());

    const InferenceDeviceDecision automatic = make_inference_device_decision(
        "AUTO",
        "CPU",
        "accelerators unavailable"
    );
    assert(!automatic.degraded);
    assert(automatic.reason.empty());
    assert(inference_device_decision_allowed(automatic, true, err));
}

int main() {
    test_detection_onnx_requires_classnames();
    test_tracking_onnx_allows_empty_classnames();
    test_plugin_allows_empty_classnames();
    test_ocr_subtype_requires_classnames_for_onnx();
    test_parse_algorithm_subtype_ocr();
    test_inference_device_decision_reports_requested_effective_and_reason();
    test_force_inference_device_rejects_only_real_fallbacks();
    return 0;
}
