cmake_minimum_required(VERSION 3.16.0)

# Build: libbeacon_compat.{dll,so,dylib}
#
# This is a stub delivery artifact used for "国产硬件模型" formats such as:
# - .rknn (Rockchip)
# - .om   (Huawei Ascend)
#
# Industrial delivery rule:
# - Provide a buildable/shared library with clear errors by default.
# - Integrators can replace this library with hardware-SDK-backed implementations.

project(beacon_compat LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)

add_library(beacon_compat SHARED compat_plugin.cpp)

target_include_directories(beacon_compat PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../Analyzer/Core
)

# Ensure the output file name is exactly:
# - Windows: libbeacon_compat.dll
# - Linux:   libbeacon_compat.so
# - macOS:   libbeacon_compat.dylib
set_target_properties(beacon_compat PROPERTIES
  PREFIX ""
  OUTPUT_NAME "libbeacon_compat"
)

