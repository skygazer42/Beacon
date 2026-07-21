cmake_minimum_required(VERSION 3.16.0)
project(Analyzer)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17 -pthread ")

option(BEACON_ENABLE_OTEL "Enable OpenTelemetry tracing (OTLP/HTTP exporter)" OFF)

SET(CMAKE_CXX_FLAGS_DEBUG "$ENV{CXXFLAGS} -O0 -Wall -g2 -ggdb")
SET(CMAKE_CXX_FLAGS_RELEASE "$ENV{CXXFLAGS} -O3 -Wall")

file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/../PROJECT_VERSION" BEACON_PROJECT_VERSION LIMIT_COUNT 1)
if(NOT BEACON_PROJECT_VERSION)
  set(BEACON_PROJECT_VERSION "v0.0.0")
endif()

set(ARCH_X86_64 "x86_64")
set(ARCH_AARCH64 "aarch64")
message(STATUS "System architecture: ${CMAKE_SYSTEM_PROCESSOR}")

set(BEACON_SYSROOT_DIR "$ENV{BEACON_SYSROOT_DIR}" CACHE PATH "Optional dependency sysroot")
set(BEACON_ONNXRUNTIME_DIR "$ENV{BEACON_ONNXRUNTIME_DIR}" CACHE PATH "ONNX Runtime C/C++ package root")
set(BEACON_OPENVINO_RUNTIME_DIR "$ENV{BEACON_OPENVINO_RUNTIME_DIR}" CACHE PATH "OpenVINO runtime root")
set(BEACON_FFMPEG_ROOT "/usr/local/ffmpeg" CACHE PATH "Optional custom FFmpeg prefix")

# third lib start
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../MediaServer/source/3rdpart/jsoncpp/include)
if(BEACON_SYSROOT_DIR)
  include_directories(${BEACON_SYSROOT_DIR}/usr/include)
  if(CMAKE_LIBRARY_ARCHITECTURE)
    include_directories(${BEACON_SYSROOT_DIR}/usr/include/${CMAKE_LIBRARY_ARCHITECTURE})
    link_directories(${BEACON_SYSROOT_DIR}/usr/lib/${CMAKE_LIBRARY_ARCHITECTURE})
  endif()
endif()
if(BEACON_FFMPEG_ROOT)
  include_directories(${BEACON_FFMPEG_ROOT}/include)
  link_directories(${BEACON_FFMPEG_ROOT}/lib)
endif()
find_package(OpenCV REQUIRED) #opencv

include(CheckIncludeFileCXX)
check_include_file_cxx("event2/event.h" BEACON_HAVE_LIBEVENT_HEADERS)
if(NOT BEACON_HAVE_LIBEVENT_HEADERS)
  message(FATAL_ERROR
    "Missing libevent development headers (event2/event.h). "
    "Install libevent-dev or build through tools/build_analyzer_local.sh with a prepared localdeps sysroot.")
endif()

if(BEACON_ONNXRUNTIME_DIR)
  include_directories(${BEACON_ONNXRUNTIME_DIR}/include)
  link_directories(${BEACON_ONNXRUNTIME_DIR}/lib)
endif()

if(BEACON_OPENVINO_RUNTIME_DIR)
  include_directories(${BEACON_OPENVINO_RUNTIME_DIR}/include)
  include_directories(${BEACON_OPENVINO_RUNTIME_DIR}/3rdparty/tbb/include)
  link_directories(${BEACON_OPENVINO_RUNTIME_DIR}/3rdparty/tbb/lib)
  if(${ARCH_X86_64} STREQUAL ${CMAKE_SYSTEM_PROCESSOR})
    link_directories(${BEACON_OPENVINO_RUNTIME_DIR}/lib/intel64)
  elseif(${ARCH_AARCH64} STREQUAL ${CMAKE_SYSTEM_PROCESSOR})
    link_directories(${BEACON_OPENVINO_RUNTIME_DIR}/lib/aarch64)
  endif()
endif()
	
# third lib end

if(BEACON_ENABLE_OTEL)
  message(STATUS "BEACON_ENABLE_OTEL=ON: building Analyzer with OpenTelemetry support")

  # Industrial builds: prefer system-provided dependencies (vcpkg / distro packages / prebuilt SDK).
  #
  # We intentionally do NOT FetchContent opentelemetry-cpp here because it can recursively clone
  # large dependency trees (vcpkg, submodules, etc.), which makes CI/builds flaky and slow.
  find_package(opentelemetry-cpp CONFIG REQUIRED)
endif()

set(source
        Analyzer/Core/Utils/CalcuIOU.cpp
        Analyzer/Core/Utils/Request.cpp
        Analyzer/Core/Utils/Pts.cpp
        Analyzer/Core/AlarmEncodeProfile.cpp
        Analyzer/Core/AlarmNotifyBackoff.cpp
        Analyzer/Core/AlarmQueuePolicy.cpp
        Analyzer/Core/AlgorithmLoadValidation.cpp
        Analyzer/Core/AlgorithmDeviceSuffix.cpp
        Analyzer/Core/AlgorithmBuiltinCatalog.cpp
        Analyzer/Core/AlgorithmTestInferValidation.cpp
        Analyzer/Core/AlgorithmXcOcr.cpp
		        Analyzer/Core/DetectStrideHysteresis.cpp
		        Analyzer/Core/Algorithm.cpp
		        Analyzer/Core/AlgorithmInstanceKey.cpp
	        Analyzer/Core/AlgorithmPipeline.cpp
	        Analyzer/Core/AlgorithmPlugin.cpp
	        Analyzer/Core/DetectObjectJson.cpp
	        Analyzer/Core/DetectObjectGeometry.cpp
	        Analyzer/Core/ImagePreprocess.cpp
	        Analyzer/Core/AlgorithmOnYolo.cpp
	        Analyzer/Core/AlgorithmOnReid.cpp
	        Analyzer/Core/AlgorithmOvYolo.cpp
	        Analyzer/Core/AlgorithmOvReid.cpp
        Analyzer/Core/YoloDetectionPostprocess.cpp
        Analyzer/Core/YoloSegmentationPostprocess.cpp
        Analyzer/Core/YoloOutputLayout.cpp
        Analyzer/Core/ApiAlgorithmSupport.cpp
        Analyzer/Core/ApiInferGuard.cpp
        Analyzer/Core/Analyzer.cpp
        Analyzer/Core/BehaviorApiPayload.cpp
        Analyzer/Core/BehaviorApiResponse.cpp
        Analyzer/Core/BehaviorApiConfig.cpp
        Analyzer/Core/BehaviorEventPostprocess.cpp
        Analyzer/Core/DecodedFrameQueue.cpp
        Analyzer/Core/TargetSizeFilter.cpp
        Analyzer/Core/RecognitionRegions.cpp
        Analyzer/Core/AvPullStream.cpp
        Analyzer/Core/AvPushStream.cpp
        Analyzer/Core/BehaviorAnalysis.cpp
        Analyzer/Core/ByteTrack.cpp
        Analyzer/Core/Config.cpp
        Analyzer/Core/ControlAlgorithmCodes.cpp
        Analyzer/Core/LocalLicense.cpp
        Analyzer/Core/DetectSchedule.cpp
        Analyzer/Core/EngineModelSupport.cpp
        Analyzer/Core/Frame.cpp
        Analyzer/Core/GenerateAlarmVideo.cpp
        Analyzer/Core/LinuxMemoryUsage.cpp
        Analyzer/Core/LicenseLeaseRenewPolicy.cpp
        Analyzer/Core/LicenseThreadPriority.cpp
        Analyzer/Core/LineCrossing.cpp
        Analyzer/Core/OverlayStyle.cpp
        Analyzer/Core/PipelineModeAdvanced.cpp
        Analyzer/Core/ReidFeature.cpp
        Analyzer/Core/SharedDecodeFrameGate.cpp
        Analyzer/Core/SharedDecodeKey.cpp
        Analyzer/Core/SharedDecodeSession.cpp
        Analyzer/Core/FaceDb.cpp
        Analyzer/Core/ReidTracker.cpp
        Analyzer/Core/ModelEncryption.cpp
        Analyzer/Core/PoseRenderer.cpp
        Analyzer/Core/ProcStatCpu.cpp
        Analyzer/Core/Scheduler.cpp
        Analyzer/Core/Otel.cpp
        Analyzer/Core/Server.cpp
        Analyzer/Core/Tracker.cpp
        Analyzer/Core/Worker.cpp
        Analyzer/Core/YoloPosePostprocess.cpp
        Analyzer/main.cpp)

add_executable(Analyzer ${source})
target_compile_definitions(Analyzer PRIVATE BEACON_PROJECT_VERSION="${BEACON_PROJECT_VERSION}")
target_link_libraries(Analyzer ${OpenCV_LIBS})
target_link_libraries(Analyzer event curl jsoncpp avformat avcodec avutil swscale swresample pthread)
if(NOT WIN32)
  target_link_libraries(Analyzer dl)
endif()
target_link_libraries(Analyzer onnxruntime) #onnxruntime
if(${ARCH_X86_64} STREQUAL ${CMAKE_SYSTEM_PROCESSOR})
  target_link_libraries(Analyzer tbb openvino openvino_intel_cpu_plugin openvino_intel_gpu_plugin) #openvino(x86_64)
elseif(${ARCH_AARCH64} STREQUAL ${CMAKE_SYSTEM_PROCESSOR})
  target_link_libraries(Analyzer tbb openvino openvino_arm_cpu_plugin) #openvino(aarch64)
endif()

if(BEACON_ENABLE_OTEL)
  target_compile_definitions(Analyzer PRIVATE BEACON_ENABLE_OTEL=1)

  if(TARGET opentelemetry-cpp::otlp_http_exporter)
    target_link_libraries(Analyzer opentelemetry-cpp::otlp_http_exporter)
  elseif(TARGET opentelemetry-cpp::opentelemetry_cpp)
    # Some builds (e.g. DLL builds) expose a single umbrella target.
    target_link_libraries(Analyzer opentelemetry-cpp::opentelemetry_cpp)
  else()
    message(FATAL_ERROR "BEACON_ENABLE_OTEL=ON but OpenTelemetry CMake targets were not found")
  endif()
endif()

# Optional delivery artifact: 国产硬件兼容动态库（stub）
add_subdirectory(Compat)
