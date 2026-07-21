#include "beacon_plugin_sdk_v2.h"

struct BeaconPluginInstanceV2Opaque {
    int reserved = 0;
};

namespace {
    BeaconPluginInstanceV2 demo_create(const char* /*algorithm_code*/, const char* /*model_path*/) {
        static BeaconPluginInstanceV2Opaque demo_state{};
        return &demo_state;
    }

    void demo_destroy(BeaconPluginInstanceV2 /*instance*/) {
        // The demo instance has static storage so there is nothing to release.
    }

    int32_t demo_detect(
        BeaconPluginInstanceV2 /*instance*/,
        const BeaconPluginImageV2* image,
        float /*conf_thresh*/,
        float /*nms_thresh*/,
        BeaconPluginDetectV2* out_dets,
        int32_t max_dets
    ) {
        if (!image || !image->bgr || image->width <= 0 || image->height <= 0 || image->stride <= 0) {
            return -1;
        }
        if (!out_dets || max_dets <= 0) {
            return 0;
        }

        BeaconPluginDetectV2 d{};
        d.x1 = image->width / 4;
        d.y1 = image->height / 4;
        d.x2 = image->width * 3 / 4;
        d.y2 = image->height * 3 / 4;
        d.score = 0.99f;
        d.class_id = 0;
        d.class_name = "demo";

        out_dets[0] = d;
        return 1;
    }

    const BeaconAlgorithmPluginV2 kPlugin = {
        BEACON_PLUGIN_SDK_V2_ABI_VERSION,
        "plugin_demo",
        demo_create,
        demo_destroy,
        demo_detect
    };
}  // namespace

#if defined(_WIN32)
#define BEACON_PLUGIN_EXPORT extern "C" __declspec(dllexport)
#else
#define BEACON_PLUGIN_EXPORT extern "C" __attribute__((visibility("default")))
#endif

BEACON_PLUGIN_EXPORT const BeaconAlgorithmPluginV2* BeaconGetAlgorithmPluginV2() {
    return &kPlugin;
}
