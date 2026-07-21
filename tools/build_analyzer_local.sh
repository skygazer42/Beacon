#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

eval "$("${ROOT_DIR}/tools/beacon_localdeps_env.sh" --print)"

BUILD_DIR="${BEACON_ANALYZER_BUILD_DIR:-${ROOT_DIR}/Analyzer/build}"
BUILD_TYPE="${BEACON_ANALYZER_BUILD_TYPE:-Release}"
BUILD_JOBS="${BEACON_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 4)}"

cmake -S "${ROOT_DIR}/Analyzer" -B "${BUILD_DIR}" -DCMAKE_BUILD_TYPE="${BUILD_TYPE}"
cmake --build "${BUILD_DIR}" -j"${BUILD_JOBS}"
