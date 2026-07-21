#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_CXX="${CXX:-clang++}"
CXX_BIN="$DEFAULT_CXX"
if ! command -v "$CXX_BIN" >/dev/null 2>&1; then
  if command -v g++ >/dev/null 2>&1; then
    CXX_BIN="g++"
  elif command -v c++ >/dev/null 2>&1; then
    CXX_BIN="c++"
  else
    echo "[analyzer] error: compiler not found: $DEFAULT_CXX (and no g++/c++ fallback)" >&2
    exit 1
  fi
fi

echo "[analyzer] compiler: $CXX_BIN"

TEST_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/beacon-analyzer-tests.XXXXXX")"
cleanup() {
  rm -rf -- "$TEST_TMP_DIR"
}
trap cleanup EXIT
export TMPDIR="$TEST_TMP_DIR"

CORE="Analyzer/Analyzer/Core"
TESTS="$CORE/tests"
JSONCPP_INCLUDE="MediaServer/source/3rdpart/jsoncpp/include"
JSONCPP_SOURCES=(
  MediaServer/source/3rdpart/jsoncpp/src/lib_json/json_value.cpp
  MediaServer/source/3rdpart/jsoncpp/src/lib_json/json_reader.cpp
  MediaServer/source/3rdpart/jsoncpp/src/lib_json/json_writer.cpp
)

compile_run() {
  local name="$1"
  shift
  local binary="$TEST_TMP_DIR/beacon_test_${name}"
  echo "[analyzer] test: $name"
  "$CXX_BIN" -std=c++17 "$@" -o "$binary"
  "$binary"
}

compile_run alarm_queue_policy \
  -I "$CORE" \
  "$TESTS/test_alarm_queue_policy.cpp" \
  "$CORE/AlarmQueuePolicy.cpp"

compile_run algorithm_load_validation \
  -I "$CORE" \
  "$TESTS/test_algorithm_load_validation.cpp" \
  "$CORE/AlgorithmLoadValidation.cpp"

compile_run api_infer_guard \
  -I "$CORE" \
  "$TESTS/test_api_infer_guard.cpp" \
  "$CORE/ApiInferGuard.cpp"

compile_run behavior_api_config_parse \
  -I "$CORE" -I "$JSONCPP_INCLUDE" \
  "$TESTS/test_behavior_api_config_parse.cpp" \
  "$CORE/BehaviorApiConfig.cpp" \
  "${JSONCPP_SOURCES[@]}"

compile_run behavior_event_postprocess \
  -I "$CORE" -I "$JSONCPP_INCLUDE" \
  "$TESTS/test_behavior_event_postprocess.cpp" \
  "$CORE/BehaviorEventPostprocess.cpp" \
  "${JSONCPP_SOURCES[@]}"

compile_run decoded_frame_queue \
  -I "$CORE" \
  "$TESTS/test_decoded_frame_queue.cpp" \
  "$CORE/DecodedFrameQueue.cpp" \
  "$CORE/Frame.cpp"

compile_run frame_pool \
  -I "$CORE" \
  "$TESTS/test_frame_pool.cpp" \
  "$CORE/Frame.cpp"

compile_run license_lease_renew_policy \
  -I "$CORE" \
  "$TESTS/test_license_lease_renew_policy.cpp" \
  "$CORE/LicenseLeaseRenewPolicy.cpp"

compile_run local_license \
  -I "$CORE" -I "$JSONCPP_INCLUDE" \
  "$TESTS/test_local_license.cpp" \
  "$CORE/Config.cpp" \
  "$CORE/LocalLicense.cpp" \
  "${JSONCPP_SOURCES[@]}"

compile_run model_encryption_resolve \
  -I "$CORE" \
  "$TESTS/test_model_encryption_resolve.cpp" \
  "$CORE/ModelEncryption.cpp"

compile_run recognition_regions_parse \
  -I "$CORE" \
  "$TESTS/test_recognition_regions_parse.cpp" \
  "$CORE/RecognitionRegions.cpp" \
  "$CORE/Utils/CalcuIOU.cpp"

compile_run reid_tracker_assoc \
  -I "$CORE" \
  "$TESTS/test_reid_tracker_assoc.cpp" \
  "$CORE/ReidTracker.cpp" \
  "$CORE/ReidFeature.cpp"

compile_run shared_decode_manager \
  -I "$CORE" \
  "$TESTS/test_shared_decode_manager.cpp" \
  "$CORE/SharedDecodeKey.cpp" \
  "$CORE/SharedDecodeManager.cpp"

compile_run yolo_output_layout \
  -I "$CORE" \
  "$TESTS/test_yolo_output_layout.cpp" \
  "$CORE/YoloOutputLayout.cpp"

compile_run yolo_pose_postprocess \
  -I "$CORE" \
  "$TESTS/test_yolo_pose_postprocess.cpp" \
  "$CORE/YoloPosePostprocess.cpp"

PLUGIN_SO="$TEST_TMP_DIR/beacon_dummy_plugin_v3.so"
echo "[analyzer] fixture: dummy_plugin_v3"
"$CXX_BIN" -std=c++17 -fPIC -shared \
  -I "$CORE" \
  "$TESTS/dummy_plugin_v3.cpp" \
  -o "$PLUGIN_SO"

COMPAT_PLUGIN_SRC="Analyzer/Compat/compat_plugin.cpp"
COMPAT_PLUGIN_SO="$TEST_TMP_DIR/libbeacon_compat_test.so"
if [[ ! -f "$COMPAT_PLUGIN_SRC" ]]; then
  echo "[analyzer] error: required compat fixture source not found: $COMPAT_PLUGIN_SRC" >&2
  exit 1
fi
echo "[analyzer] fixture: compat_plugin"
"$CXX_BIN" -std=c++17 -fPIC -shared \
  -I "$CORE" \
  "$COMPAT_PLUGIN_SRC" \
  -ldl \
  -o "$COMPAT_PLUGIN_SO"

echo "[analyzer] test: compat_plugin_runtime (stub)"
COMPAT_RUNTIME_BINARY="$TEST_TMP_DIR/beacon_test_compat_plugin_runtime"
"$CXX_BIN" -std=c++17 \
  -I "$CORE" \
  "$TESTS/test_compat_plugin_runtime.cpp" \
  -ldl \
  -o "$COMPAT_RUNTIME_BINARY"
BEACON_TEST_COMPAT_PLUGIN_PATH="$COMPAT_PLUGIN_SO" \
BEACON_TEST_DUMMY_PLUGIN_V3_PATH="$PLUGIN_SO" \
BEACON_TEST_COMPAT_RUNTIME_MODE=stub \
  "$COMPAT_RUNTIME_BINARY"
echo "[analyzer] test: compat_plugin_runtime (delegated)"
BEACON_TEST_COMPAT_PLUGIN_PATH="$COMPAT_PLUGIN_SO" \
BEACON_TEST_DUMMY_PLUGIN_V3_PATH="$PLUGIN_SO" \
BEACON_TEST_COMPAT_RUNTIME_MODE=delegated \
  "$COMPAT_RUNTIME_BINARY"

if ! command -v pkg-config >/dev/null 2>&1 || ! pkg-config --exists opencv4; then
  echo "[analyzer] error: OpenCV 4 development files are required for the core Analyzer test set (pkg-config opencv4 not found)" >&2
  exit 1
fi
read -r -a OPENCV_CFLAGS <<<"$(pkg-config --cflags opencv4)"
read -r -a OPENCV_LIBS <<<"$(pkg-config --libs opencv4)"

compile_run image_preprocess \
  -I "$CORE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_image_preprocess.cpp" \
  "$CORE/ImagePreprocess.cpp" \
  "${OPENCV_LIBS[@]}"

echo "[analyzer] test: algorithm_plugin_destroy"
ALGORITHM_PLUGIN_DESTROY_BINARY="$TEST_TMP_DIR/beacon_test_algorithm_plugin_destroy"
"$CXX_BIN" -std=c++17 \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_algorithm_plugin_destroy.cpp" \
  "$CORE/AlgorithmPlugin.cpp" \
  "$CORE/Algorithm.cpp" \
  "$CORE/Config.cpp" \
  "${JSONCPP_SOURCES[@]}" \
  -ldl "${OPENCV_LIBS[@]}" \
  -o "$ALGORITHM_PLUGIN_DESTROY_BINARY"
BEACON_TEST_DUMMY_PLUGIN_V3_PATH="$PLUGIN_SO" \
  "$ALGORITHM_PLUGIN_DESTROY_BINARY"

compile_run detect_object_geometry \
  -I "$CORE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_detect_object_geometry.cpp" \
  "$CORE/DetectObjectGeometry.cpp" \
  "${OPENCV_LIBS[@]}"

compile_run detect_object_json \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_detect_object_json.cpp" \
  "$CORE/DetectObjectJson.cpp" \
  "${JSONCPP_SOURCES[@]}" \
  "${OPENCV_LIBS[@]}"

compile_run xcocr_postprocess \
  -I "$CORE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_xcocr_postprocess.cpp" \
  "$CORE/AlgorithmXcOcr.cpp" \
  "$CORE/Algorithm.cpp" \
  "${OPENCV_LIBS[@]}"

compile_run yolo_detection_postprocess_obb \
  -I "$CORE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_yolo_detection_postprocess_obb.cpp" \
  "$CORE/YoloDetectionPostprocess.cpp" \
  "${OPENCV_LIBS[@]}"

compile_run yolo_segmentation_postprocess \
  -I "$CORE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_yolo_segmentation_postprocess.cpp" \
  "$CORE/YoloDetectionPostprocess.cpp" \
  "$CORE/YoloSegmentationPostprocess.cpp" \
  "${OPENCV_LIBS[@]}"

PIPELINE_SOURCES=(
  "$CORE/PipelineModeAdvanced.cpp"
  "$CORE/Algorithm.cpp"
  "$CORE/DetectObjectGeometry.cpp"
  "$CORE/FaceDb.cpp"
  "$CORE/RecognitionRegions.cpp"
  "$CORE/ReidFeature.cpp"
  "$CORE/Utils/CalcuIOU.cpp"
)
compile_run pipeline_mode3_mode4 \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_pipeline_mode3_mode4.cpp" \
  "${PIPELINE_SOURCES[@]}" \
  "${JSONCPP_SOURCES[@]}" \
  "${OPENCV_LIBS[@]}"

compile_run pipeline_mode6_mode7 \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_pipeline_mode6_mode7.cpp" \
  "${PIPELINE_SOURCES[@]}" \
  "${JSONCPP_SOURCES[@]}" \
  "${OPENCV_LIBS[@]}"

compile_run pipeline_mode8_mode9 \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_pipeline_mode8_mode9.cpp" \
  "${PIPELINE_SOURCES[@]}" \
  "${JSONCPP_SOURCES[@]}" \
  "${OPENCV_LIBS[@]}"

ANALYZER_RUNTIME_SOURCES=(
  "$CORE/Analyzer.cpp"
  "$CORE/Algorithm.cpp"
  "$CORE/ApiAlgorithmSupport.cpp"
  "$CORE/BehaviorApiConfig.cpp"
  "$CORE/BehaviorApiPayload.cpp"
  "$CORE/BehaviorApiResponse.cpp"
  "$CORE/BehaviorEventPostprocess.cpp"
  "$CORE/DetectObjectGeometry.cpp"
  "$CORE/DetectObjectJson.cpp"
  "$CORE/PipelineModeAdvanced.cpp"
  "$CORE/RecognitionRegions.cpp"
  "$CORE/TargetSizeFilter.cpp"
  "$CORE/Utils/CalcuIOU.cpp"
)
compile_run behavior_api_crowd_threshold_runtime \
  -ffunction-sections -fdata-sections \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_behavior_api_crowd_threshold_runtime.cpp" \
  "${ANALYZER_RUNTIME_SOURCES[@]}" \
  "${JSONCPP_SOURCES[@]}" \
  "${OPENCV_LIBS[@]}" \
  -Wl,--gc-sections -lpthread

compile_run behavior_api_crosscount_runtime \
  -ffunction-sections -fdata-sections \
  -I "$CORE" -I "$JSONCPP_INCLUDE" "${OPENCV_CFLAGS[@]}" \
  "$TESTS/test_behavior_api_crosscount_runtime.cpp" \
  "${ANALYZER_RUNTIME_SOURCES[@]}" \
  "${JSONCPP_SOURCES[@]}" \
  "${OPENCV_LIBS[@]}" \
  -Wl,--gc-sections -lpthread

compile_run face_db_vptree \
  -I "$CORE" \
  "$TESTS/test_face_db_vptree.cpp" \
  "$CORE/FaceDb.cpp" \
  "$CORE/ReidFeature.cpp"

echo "[analyzer] OK (29 core tests)"
