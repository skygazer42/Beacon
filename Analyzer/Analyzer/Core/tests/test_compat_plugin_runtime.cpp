#include "PluginSdkCompat.h"
#include "PluginSdkV3.h"

#include <cassert>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <string>
#include <vector>

namespace {

using ResetFn = void (*)();
using GetCountFn = int (*)();

struct DlHandle {
    void* handle = nullptr;
    explicit DlHandle(void* value) : handle(value) {}
    ~DlHandle() {
        if (handle) {
            dlclose(handle);
            handle = nullptr;
        }
    }
    DlHandle(const DlHandle&) = delete;
    DlHandle& operator=(const DlHandle&) = delete;
};

std::string getenv_str(const char* key) {
    const char* value = std::getenv(key);
    return value ? std::string(value) : std::string();
}

template <typename Fn>
Fn load_symbol(void* handle, const char* name) {
    void* symbol = dlsym(handle, name);
    return reinterpret_cast<Fn>(symbol);
}

DlHandle load_library(const std::string& path) {
    void* handle = dlopen(path.c_str(), RTLD_NOW);
    assert(handle != nullptr);
    return DlHandle(handle);
}

void expect_stub_mode(const std::string& compat_path) {
    unsetenv("BEACON_COMPAT_BACKEND_PATH");

    DlHandle compat = load_library(compat_path);
    auto get_info = load_symbol<BeaconGetCompatBackendInfoV1Fn>(compat.handle, "BeaconGetCompatBackendInfoV1");
    assert(get_info != nullptr);

    const BeaconCompatBackendInfoV1* info = get_info();
    assert(info != nullptr);
    assert(info->abi_version == BEACON_COMPAT_BACKEND_INFO_V1_ABI_VERSION);
    assert(info->shim_name != nullptr);
    assert(info->backend_name != nullptr);
    assert(info->backend_mode != nullptr);
    assert(std::strcmp(info->backend_mode, "stub") == 0);
    assert(info->is_stub != 0);
}

void expect_delegated_mode(const std::string& compat_path, const std::string& dummy_path) {
    setenv("BEACON_COMPAT_BACKEND_PATH", dummy_path.c_str(), 1);

    DlHandle dummy = load_library(dummy_path);
    auto reset = load_symbol<ResetFn>(dummy.handle, "BeaconDummyV3ResetCounts");
    auto get_create = load_symbol<GetCountFn>(dummy.handle, "BeaconDummyV3GetCreateCount");
    auto get_destroy = load_symbol<GetCountFn>(dummy.handle, "BeaconDummyV3GetDestroyCount");
    auto get_detect = load_symbol<GetCountFn>(dummy.handle, "BeaconDummyV3GetDetectCount");
    assert(reset && get_create && get_destroy && get_detect);
    reset();

    DlHandle compat = load_library(compat_path);
    auto get_info = load_symbol<BeaconGetCompatBackendInfoV1Fn>(compat.handle, "BeaconGetCompatBackendInfoV1");
    auto get_plugin = load_symbol<BeaconGetAlgorithmPluginV3Fn>(compat.handle, "BeaconGetAlgorithmPluginV3");
    assert(get_info != nullptr);
    assert(get_plugin != nullptr);

    const BeaconCompatBackendInfoV1* info = get_info();
    assert(info != nullptr);
    assert(info->abi_version == BEACON_COMPAT_BACKEND_INFO_V1_ABI_VERSION);
    assert(info->backend_mode != nullptr);
    assert(std::strcmp(info->backend_mode, "delegated") == 0);
    assert(info->is_stub == 0);
    assert(info->backend_name != nullptr);
    assert(std::strcmp(info->backend_name, "beacon_dummy_v3") == 0);
    assert(info->backend_library_path != nullptr);
    assert(dummy_path == info->backend_library_path);

    const BeaconAlgorithmPluginV3* plugin = get_plugin();
    assert(plugin != nullptr);
    assert(plugin->create != nullptr);
    assert(plugin->destroy != nullptr);
    assert(plugin->detect != nullptr);

    BeaconPluginInstanceV3 instance = plugin->create("dummy_algo", "dummy_model");
    assert(instance != nullptr);

    std::vector<unsigned char> pixels(3U * 4U * 4U, 0);
    BeaconPluginImageV3 image{
        pixels.data(),
        4,
        4,
        12,
    };
    BeaconPluginDetectV3 dets[4]{};
    const int32_t det_count = plugin->detect(instance, &image, 0.25f, 0.45f, dets, 4);
    assert(det_count == 1);
    assert(dets[0].class_name != nullptr);
    assert(std::strcmp(dets[0].class_name, "dummy") == 0);
    plugin->destroy(instance);

    assert(get_create() == 1);
    assert(get_detect() == 1);
    assert(get_destroy() == 1);
}

}  // namespace

int main() {
    const std::string compat_path = getenv_str("BEACON_TEST_COMPAT_PLUGIN_PATH");
    const std::string dummy_path = getenv_str("BEACON_TEST_DUMMY_PLUGIN_V3_PATH");
    assert(!compat_path.empty());
    assert(!dummy_path.empty());

    const std::string mode = getenv_str("BEACON_TEST_COMPAT_RUNTIME_MODE");
    assert(!mode.empty());

    if (mode == "stub") {
        expect_stub_mode(compat_path);
        return 0;
    }
    if (mode == "delegated") {
        expect_delegated_mode(compat_path, dummy_path);
        return 0;
    }

    assert(false && "unknown runtime mode");
    return 1;
}
