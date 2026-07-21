#ifndef BEACON_PLUGIN_SDK_V3_H
#define BEACON_PLUGIN_SDK_V3_H

#include <stdint.h>

#ifdef __cplusplus
inline constexpr uint32_t BEACON_PLUGIN_SDK_V3_ABI_VERSION = 3;
inline constexpr int BEACON_PLUGIN_SDK_V3_MAX_KEYPOINTS = 17;
#else
#define BEACON_PLUGIN_SDK_V3_ABI_VERSION 3
#define BEACON_PLUGIN_SDK_V3_MAX_KEYPOINTS 17
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Image buffer passed to plugin:
// - Format: BGR (8-bit), same as OpenCV CV_8UC3.
// - Stride: bytes per row.
typedef struct BeaconPluginImageV3 {
    const unsigned char* bgr;
    int32_t width;
    int32_t height;
    int32_t stride;
} BeaconPluginImageV3;

typedef struct BeaconPluginKeypointV3 {
    float x;
    float y;
    float confidence;
} BeaconPluginKeypointV3;

// One detection result.
// - class_name is optional and should be UTF-8 when provided.
// - If has_pose != 0, keypoints is COCO-17 (17*(x,y,confidence)).
typedef struct BeaconPluginDetectV3 {
    int32_t x1;
    int32_t y1;
    int32_t x2;
    int32_t y2;
    float score;
    int32_t class_id;
    const char* class_name;

    uint8_t has_pose;
    uint8_t reserved0;
    uint8_t reserved1;
    uint8_t reserved2;
    BeaconPluginKeypointV3 keypoints[BEACON_PLUGIN_SDK_V3_MAX_KEYPOINTS];
} BeaconPluginDetectV3;

typedef struct BeaconPluginInstanceV3Impl* BeaconPluginInstanceV3;

// Stable C ABI function table.
// Host (Analyzer) will:
// - call create() N times for concurrency
// - call detect() on instances (round-robin + per-instance mutex)
// - call destroy() on shutdown
typedef struct BeaconAlgorithmPluginV3 {
    uint32_t abi_version;      // must be BEACON_PLUGIN_SDK_V3_ABI_VERSION
    const char* plugin_name;   // optional

    BeaconPluginInstanceV3 (*create)(const char* algorithm_code, const char* model_path);
    void (*destroy)(BeaconPluginInstanceV3 instance);

    // Returns:
    // - >=0: number of detections written to out_dets (clamped by max_dets)
    // - <0 : error
    int32_t (*detect)(
        BeaconPluginInstanceV3 instance,
        const BeaconPluginImageV3* image,
        float conf_thresh,
        float nms_thresh,
        BeaconPluginDetectV3* out_dets,
        int32_t max_dets
    );
} BeaconAlgorithmPluginV3;

// Plugin MUST export this symbol to enable SDK v3:
//   const BeaconAlgorithmPluginV3* BeaconGetAlgorithmPluginV3();
typedef const BeaconAlgorithmPluginV3* (*BeaconGetAlgorithmPluginV3Fn)();

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // BEACON_PLUGIN_SDK_V3_H
