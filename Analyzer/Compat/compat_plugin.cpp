#include "PluginSdkCompat.h"
#include "PluginSdkV3.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace {

using LibraryHandle = std::uintptr_t;
using SymbolAddress = std::uintptr_t;

struct CompatBackendState {
    std::mutex mutex;
    bool initialized = false;
    bool delegated = false;
    LibraryHandle handle = 0;
    const BeaconAlgorithmPluginV3* plugin = nullptr;
    std::string backend_name{"beacon_compat_stub"};
    std::string backend_mode{"stub"};
    std::string backend_library_path{};
    std::string last_error{"BEACON_COMPAT_BACKEND_PATH not set; using stub backend"};
};

struct CompatBackendStateHolder {
    inline static CompatBackendState state{};
};

CompatBackendState& compat_backend_state() {
    return CompatBackendStateHolder::state;
}

#ifdef _WIN32
std::string get_last_loader_error() {
    const DWORD err = GetLastError();
    if (err == 0) {
        return "unknown loader error";
    }
    LPSTR buffer = nullptr;
    const DWORD size = FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        err,
        MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
        reinterpret_cast<LPSTR>(&buffer),
        0,
        nullptr
    );
    std::string message = (size && buffer) ? std::string(buffer, size) : std::string("unknown loader error");
    if (buffer) {
        LocalFree(buffer);
    }
    return message;
}

LibraryHandle open_library(const char* path) {
    return reinterpret_cast<LibraryHandle>(LoadLibraryA(path));
}

void close_library(LibraryHandle handle) {
    if (handle) {
        FreeLibrary(reinterpret_cast<HMODULE>(handle));
    }
}

SymbolAddress resolve_symbol(LibraryHandle handle, const char* name) {
    if (!handle) {
        return 0;
    }
    return reinterpret_cast<SymbolAddress>(GetProcAddress(reinterpret_cast<HMODULE>(handle), name));
}
#else
std::string get_last_loader_error() {
    const char* err = dlerror();
    return err ? std::string(err) : std::string("unknown loader error");
}

LibraryHandle open_library(const char* path) {
    return reinterpret_cast<LibraryHandle>(dlopen(path, RTLD_NOW | RTLD_LOCAL)); //NOSONAR - POSIX dlopen returns void*
}

void close_library(LibraryHandle handle) {
    if (handle) {
        dlclose(reinterpret_cast<void*>(handle)); //NOSONAR - POSIX dlclose uses void*
    }
}

SymbolAddress resolve_symbol(LibraryHandle handle, const char* name) {
    if (!handle) {
        return 0;
    }
    dlerror();
    return reinterpret_cast<SymbolAddress>(dlsym(reinterpret_cast<void*>(handle), name)); //NOSONAR - POSIX dlsym uses void*
}
	#endif

			void log_once(const char* algorithm_code, const char* model_path, const char* last_error) {
			    static std::once_flag logged_once;
			    std::call_once(logged_once, [algorithm_code, model_path, last_error]() {
			        std::fprintf(
			            stderr,
	        "[beacon_compat] ERROR: libbeacon_compat is using stub fallback.\n"
	        "[beacon_compat] Requested algorithm_code=%s, model_path=%s\n"
	        "[beacon_compat] Reason: %s\n"
	        "[beacon_compat] Set BEACON_COMPAT_BACKEND_PATH to a hardware-SDK-backed plugin\n"
	        "[beacon_compat] (e.g., RKNN/Ascend runtime) for .rknn/.om models.\n",
	        algorithm_code ? algorithm_code : "",
	        model_path ? model_path : "",
	        last_error ? last_error : "stub backend active"
	    );
		        std::fflush(stderr);
		    });
	}

void initialize_backend_locked(CompatBackendState& state) {
    const char* backend_path = std::getenv("BEACON_COMPAT_BACKEND_PATH");
    const std::string requested_path = (backend_path && *backend_path) ? std::string(backend_path) : std::string();

    if (state.delegated && requested_path == state.backend_library_path) {
        return;
    }

    state.initialized = true;
    state.delegated = false;
    state.plugin = nullptr;
    state.backend_name = "beacon_compat_stub";
    state.backend_mode = "stub";

    if (state.handle) {
        close_library(state.handle);
        state.handle = 0;
    }

    if (requested_path.empty()) {
        state.backend_library_path.clear();
        state.last_error = "BEACON_COMPAT_BACKEND_PATH not set; using stub backend";
        return;
    }

    state.backend_library_path = requested_path;
    state.handle = open_library(requested_path.c_str());
    if (!state.handle) {
        state.last_error = "failed to load backend library: " + get_last_loader_error();
        return;
    }

    auto sym = resolve_symbol(state.handle, "BeaconGetAlgorithmPluginV3");
    if (!sym) {
        state.last_error = "backend library missing BeaconGetAlgorithmPluginV3";
        close_library(state.handle);
        state.handle = 0;
        return;
    }

    auto get_plugin = reinterpret_cast<BeaconGetAlgorithmPluginV3Fn>(sym);
    state.plugin = get_plugin ? get_plugin() : nullptr;
    if (!state.plugin ||
        state.plugin->abi_version != BEACON_PLUGIN_SDK_V3_ABI_VERSION ||
        !state.plugin->create ||
        !state.plugin->destroy ||
        !state.plugin->detect) {
        state.last_error = "backend plugin returned invalid SDK v3 table";
        state.plugin = nullptr;
        close_library(state.handle);
        state.handle = 0;
        return;
    }

    state.delegated = true;
    state.backend_mode = "delegated";
    state.backend_name = (state.plugin->plugin_name && *state.plugin->plugin_name)
                             ? state.plugin->plugin_name
                             : "delegated_sdk_v3_backend";
    state.last_error.clear();
}

const BeaconAlgorithmPluginV3* ensure_backend_plugin() {
    auto& state = compat_backend_state();
    std::scoped_lock lock(state.mutex);
    initialize_backend_locked(state);
    return state.plugin;
}

BeaconPluginInstanceV3 compat_create(const char* algorithm_code, const char* model_path) {
    if (const auto* plugin = ensure_backend_plugin()) {
        return plugin->create(algorithm_code, model_path);
    }

    const auto& state = compat_backend_state();
    log_once(algorithm_code, model_path, state.last_error.c_str());
    return nullptr;
}

void compat_destroy(BeaconPluginInstanceV3 instance) {
    if (const auto* plugin = ensure_backend_plugin()) {
        plugin->destroy(instance);
    }
}

int32_t compat_detect(
    BeaconPluginInstanceV3 instance,
    const BeaconPluginImageV3* image,
    float conf_thresh,
    float nms_thresh,
    BeaconPluginDetectV3* out_dets,
    int32_t max_dets
) {
    if (const auto* plugin = ensure_backend_plugin()) {
        return plugin->detect(instance, image, conf_thresh, nms_thresh, out_dets, max_dets);
    }
    return -1;
}

const BeaconCompatBackendInfoV1* compat_backend_info() {
    static BeaconCompatBackendInfoV1 info{
        BEACON_COMPAT_BACKEND_INFO_V1_ABI_VERSION,
        "libbeacon_compat",
        nullptr,
        nullptr,
        nullptr,
        nullptr,
        1,
        0,
        0,
        0,
    };

    auto& state = compat_backend_state();
    std::scoped_lock lock(state.mutex);
    initialize_backend_locked(state);

    info.backend_name = state.backend_name.c_str();
    info.backend_mode = state.backend_mode.c_str();
    info.backend_library_path = state.backend_library_path.empty() ? nullptr : state.backend_library_path.c_str();
    info.last_error = state.last_error.empty() ? nullptr : state.last_error.c_str();
    info.is_stub = state.delegated ? 0 : 1;
    return &info;
}

const BeaconAlgorithmPluginV3 g_plugin_v3 = {
    BEACON_PLUGIN_SDK_V3_ABI_VERSION,
    "beacon_compat_shim",
    &compat_create,
    &compat_destroy,
    &compat_detect,
};

}  // namespace

#if defined(_WIN32)
extern "C" __declspec(dllexport) const BeaconAlgorithmPluginV3* BeaconGetAlgorithmPluginV3() {
    return &g_plugin_v3;
}
extern "C" __declspec(dllexport) const BeaconCompatBackendInfoV1* BeaconGetCompatBackendInfoV1() {
    return compat_backend_info();
}
#else
extern "C" const BeaconAlgorithmPluginV3* BeaconGetAlgorithmPluginV3() {
    return &g_plugin_v3;
}
extern "C" const BeaconCompatBackendInfoV1* BeaconGetCompatBackendInfoV1() {
    return compat_backend_info();
}
#endif
