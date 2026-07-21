#ifndef BEACON_PLUGIN_SDK_V2_H
#define BEACON_PLUGIN_SDK_V2_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

static const uint32_t BEACON_PLUGIN_SDK_V2_ABI_VERSION = 2U;

typedef struct BeaconPluginImageV2 {
    const unsigned char* bgr;
    int32_t width;
    int32_t height;
    int32_t stride;
} BeaconPluginImageV2;

typedef struct BeaconPluginDetectV2 {
    int32_t x1;
    int32_t y1;
    int32_t x2;
    int32_t y2;
    float score;
    int32_t class_id;
    const char* class_name;
} BeaconPluginDetectV2;

typedef struct BeaconPluginInstanceV2Opaque* BeaconPluginInstanceV2;

typedef struct BeaconAlgorithmPluginV2 {
    uint32_t abi_version;
    const char* plugin_name;

    BeaconPluginInstanceV2 (*create)(const char* algorithm_code, const char* model_path);
    void (*destroy)(BeaconPluginInstanceV2 instance);

    int32_t (*detect)(
        BeaconPluginInstanceV2 instance,
        const BeaconPluginImageV2* image,
        float conf_thresh,
        float nms_thresh,
        BeaconPluginDetectV2* out_dets,
        int32_t max_dets
    );
} BeaconAlgorithmPluginV2;

typedef const BeaconAlgorithmPluginV2* (*BeaconGetAlgorithmPluginV2Fn)();

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // BEACON_PLUGIN_SDK_V2_H
