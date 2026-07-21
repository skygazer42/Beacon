#include "PluginSdkV3.h"

#include <atomic>
#include <cstdint>

namespace {
std::atomic<int> g_create_count{0};
std::atomic<int> g_destroy_count{0};
std::atomic<int> g_detect_count{0};

struct DummyInstance {
    int id;
};

static const char kDummyClassName[] = "dummy";

BeaconPluginInstanceV3 dummy_create(const char* algorithm_code, const char* model_path) {
    (void)algorithm_code;
    (void)model_path;
    int id = g_create_count.fetch_add(1) + 1;
    return reinterpret_cast<BeaconPluginInstanceV3>(new DummyInstance{ id });
}

void dummy_destroy(BeaconPluginInstanceV3 instance) {
    if (!instance) {
        return;
    }
    g_destroy_count.fetch_add(1);
    delete reinterpret_cast<DummyInstance*>(instance);
}

int32_t dummy_detect(
    BeaconPluginInstanceV3 instance,
    const BeaconPluginImageV3* in,
    float score_threshold,
    float nms_threshold,
    BeaconPluginDetectV3* out,
    int32_t out_capacity
) {
    (void)instance;
    (void)in;
    (void)score_threshold;
    (void)nms_threshold;
    g_detect_count.fetch_add(1);

    if (!out || out_capacity <= 0) {
        return 0;
    }

    BeaconPluginDetectV3 d{};
    d.x1 = 0;
    d.y1 = 0;
    d.x2 = 10;
    d.y2 = 10;
    d.score = 0.9f;
    d.class_id = 0;
    d.class_name = kDummyClassName;
    d.has_pose = 0;
    out[0] = d;
    return 1;
}

const BeaconAlgorithmPluginV3 kPlugin = {
    BEACON_PLUGIN_SDK_V3_ABI_VERSION,
    "beacon_dummy_v3",
    &dummy_create,
    &dummy_destroy,
    &dummy_detect,
};
}  // namespace

extern "C" {

const BeaconAlgorithmPluginV3* BeaconGetAlgorithmPluginV3() {
    return &kPlugin;
}

void BeaconDummyV3ResetCounts() {
    g_create_count.store(0);
    g_destroy_count.store(0);
    g_detect_count.store(0);
}

int BeaconDummyV3GetCreateCount() {
    return g_create_count.load();
}

int BeaconDummyV3GetDestroyCount() {
    return g_destroy_count.load();
}

int BeaconDummyV3GetDetectCount() {
    return g_detect_count.load();
}

}  // extern "C"
