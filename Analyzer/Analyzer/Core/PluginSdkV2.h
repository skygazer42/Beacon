#ifndef BEACON_PLUGIN_SDK_V2_H
#define BEACON_PLUGIN_SDK_V2_H

#include <stdint.h>

#ifdef __cplusplus
inline constexpr uint32_t BEACON_PLUGIN_SDK_V2_ABI_VERSION = 2;
#else
#define BEACON_PLUGIN_SDK_V2_ABI_VERSION 2
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Image buffer passed to plugin:
// - Format: BGR (8-bit), same as OpenCV CV_8UC3.
// - Stride: bytes per row.
typedef struct BeaconPluginImageV2 {
    const unsigned char* bgr;
    int32_t width;
    int32_t height;
    int32_t stride;
} BeaconPluginImageV2;

// One detection result.
// class_name is optional and should be UTF-8 when provided.
typedef struct BeaconPluginDetectV2 {
    int32_t x1;
    int32_t y1;
    int32_t x2;
    int32_t y2;
    float score;
    int32_t class_id;
    const char* class_name;
} BeaconPluginDetectV2;

typedef struct BeaconPluginInstanceV2Impl* BeaconPluginInstanceV2;

// Stable C ABI function table.
// Host (Analyzer) will:
// - call create() N times for concurrency
// - call detect() on instances (round-robin + per-instance mutex)
// - call destroy() on shutdown
typedef struct BeaconAlgorithmPluginV2 {
    uint32_t abi_version;      // must be BEACON_PLUGIN_SDK_V2_ABI_VERSION
    const char* plugin_name;   // optional

    BeaconPluginInstanceV2 (*create)(const char* algorithm_code, const char* model_path);
    void (*destroy)(BeaconPluginInstanceV2 instance);

    // Returns:
    // - >=0: number of detections written to out_dets (clamped by max_dets)
    // - <0 : error
    int32_t (*detect)(
        BeaconPluginInstanceV2 instance,
        const BeaconPluginImageV2* image,
        float conf_thresh,
        float nms_thresh,
        BeaconPluginDetectV2* out_dets,
        int32_t max_dets
    );
} BeaconAlgorithmPluginV2;

// Plugin MUST export this symbol to enable SDK v2:
//   const BeaconAlgorithmPluginV2* BeaconGetAlgorithmPluginV2();
typedef const BeaconAlgorithmPluginV2* (*BeaconGetAlgorithmPluginV2Fn)();

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // BEACON_PLUGIN_SDK_V2_H
