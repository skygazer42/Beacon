cmake_minimum_required(VERSION 3.16)
project(beacon_algorithm_plugin_demo)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(plugin_demo SHARED
    plugin_demo.cpp
)

# Keep the output name stable across platforms.
set_target_properties(plugin_demo PROPERTIES OUTPUT_NAME "plugin_demo")

# On Windows, export symbols via __declspec(dllexport) in code.
if (WIN32)
  target_compile_definitions(plugin_demo PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()

