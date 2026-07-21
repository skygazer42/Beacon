#include "AlgorithmPlugin.h"

#include <cassert>
#include <cstddef>
#include <dlfcn.h>
#include <string>

namespace {
using ResetFn = void (*)();
using GetCountFn = int (*)();

struct DlHandle {
    void* handle = nullptr;
    DlHandle() = default;
    explicit DlHandle(void* h) : handle(h) {}
    ~DlHandle() {
        if (handle) {
            dlclose(handle);
            handle = nullptr;
        }
    }
    DlHandle(const DlHandle&) = delete;
    DlHandle& operator=(const DlHandle&) = delete;
};

template <typename Fn>
Fn load_fn(void* handle, const char* name) {
    void* sym = dlsym(handle, name);
    if (!sym) {
        return nullptr;
    }
    return reinterpret_cast<Fn>(sym);
}

std::string getenv_str(const char* key) {
    const char* v = std::getenv(key);
    return v ? std::string(v) : std::string();
}
}  // namespace

int main() {
    const std::string plugin_path = getenv_str("BEACON_TEST_DUMMY_PLUGIN_V3_PATH");
    assert(!plugin_path.empty());

    DlHandle lib(dlopen(plugin_path.c_str(), RTLD_NOW));
    assert(lib.handle != nullptr);

    auto reset = load_fn<ResetFn>(lib.handle, "BeaconDummyV3ResetCounts");
    auto get_create = load_fn<GetCountFn>(lib.handle, "BeaconDummyV3GetCreateCount");
    auto get_destroy = load_fn<GetCountFn>(lib.handle, "BeaconDummyV3GetDestroyCount");
    assert(reset && get_create && get_destroy);

    reset();
    assert(get_create() == 0);
    assert(get_destroy() == 0);

    constexpr int kConcurrency = 2;
    {
        auto* plugin = new AVSAnalyzer::AlgorithmPlugin(
            /*config=*/nullptr,
            /*libraryPath=*/plugin_path,
            /*algorithmCode=*/"dummy_algo",
            /*modelPath=*/"dummy_model",
            /*concurrency=*/kConcurrency
        );
        assert(plugin != nullptr);
        assert(plugin->createState());
        delete plugin;
        plugin = nullptr;
    }

    // IMPORTANT: We keep one dlopen handle alive (this test) so AlgorithmPlugin's dlclose
    // does not unload the shared object, allowing us to query counters after destructor.
    assert(get_create() == kConcurrency);
    assert(get_destroy() == kConcurrency);
    return 0;
}

