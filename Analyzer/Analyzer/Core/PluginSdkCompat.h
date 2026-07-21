#ifndef BEACON_PLUGIN_SDK_COMPAT_H
#define BEACON_PLUGIN_SDK_COMPAT_H

#include <stdint.h>

#ifdef __cplusplus
inline constexpr uint32_t BEACON_COMPAT_BACKEND_INFO_V1_ABI_VERSION = 1;
#else
#define BEACON_COMPAT_BACKEND_INFO_V1_ABI_VERSION 1
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct BeaconCompatBackendInfoV1 {
    uint32_t abi_version;
    const char* shim_name;
    const char* backend_name;
    const char* backend_mode;
    const char* backend_library_path;
    const char* last_error;
    uint8_t is_stub;
    uint8_t reserved0;
    uint8_t reserved1;
    uint8_t reserved2;
} BeaconCompatBackendInfoV1;

typedef const BeaconCompatBackendInfoV1* (*BeaconGetCompatBackendInfoV1Fn)();

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // BEACON_PLUGIN_SDK_COMPAT_H
