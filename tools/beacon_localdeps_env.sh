#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${BEACON_ROOT_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
MODE="${1:-summary}"

fail() {
  echo "[beacon-localdeps] $*" >&2
  exit 1
}

append_unique() {
  local value="$1"
  shift
  local item
  for item in "$@"; do
    [[ "$item" == "$value" ]] && return 0
  done
  return 1
}

merge_path_var() {
  local existing="${1:-}"
  shift
  local -a merged=()
  local -a existing_parts=()
  local candidate
  for candidate in "$@"; do
    [[ -n "$candidate" && -d "$candidate" ]] || continue
    if ! append_unique "$candidate" "${merged[@]}"; then
      merged+=("$candidate")
    fi
  done
  IFS=':' read -r -a existing_parts <<< "${existing}"
  for candidate in "${existing_parts[@]}"; do
    [[ -n "$candidate" ]] || continue
    if ! append_unique "$candidate" "${merged[@]}"; then
      merged+=("$candidate")
    fi
  done
  if ((${#merged[@]} > 0)); then
    local result
    printf -v result '%s:' "${merged[@]}"
    result="${result%:}"
    printf '%s' "${result}"
    return 0
  fi
  printf '%s' ""
}

merge_csv_var() {
  local result="${1:-}"
  shift
  local candidate
  for candidate in "$@"; do
    [[ -n "${candidate}" ]] || continue
    case ",${result}," in
      *",${candidate},"*) ;;
      *) result="${result:+${result},}${candidate}" ;;
    esac
  done
  printf '%s' "${result}"
}

pick_first_dir() {
  local candidate
  for candidate in "$@"; do
    [[ -n "$candidate" && -d "$candidate" ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

shopt -s nullglob

LOCALDEPS_DIR="${BEACON_LOCALDEPS_DIR:-}"
if [[ -z "${LOCALDEPS_DIR}" ]]; then
  for candidate in \
    "${ROOT_DIR}/third_party/localdeps" \
    "${ROOT_DIR}/deps/localdeps"; do
    if [[ -d "${candidate}/sysroot" ]]; then
      LOCALDEPS_DIR="${candidate}"
      break
    fi
  done
fi

[[ -n "${LOCALDEPS_DIR}" ]] || fail "unable to locate localdeps directory under ${ROOT_DIR}"
[[ -d "${LOCALDEPS_DIR}/sysroot" ]] || fail "missing sysroot under ${LOCALDEPS_DIR}"

SYSROOT_DIR="${BEACON_SYSROOT_DIR:-${LOCALDEPS_DIR}/sysroot}"
ONNXRUNTIME_DIR="${BEACON_ONNXRUNTIME_DIR:-$(pick_first_dir \
  "${LOCALDEPS_DIR}"/src/onnxruntime-*-gpu-* \
  "${LOCALDEPS_DIR}"/src/onnxruntime-* || true)}"
OPENVINO_RUNTIME_DIR="${BEACON_OPENVINO_RUNTIME_DIR:-$(pick_first_dir "${LOCALDEPS_DIR}"/src/l_openvino_toolkit_*/runtime || true)}"

SYSROOT_INCLUDE_DIR="${SYSROOT_DIR}/usr/include"
SYSROOT_JSONCPP_INCLUDE_DIR="${SYSROOT_INCLUDE_DIR}/jsoncpp"
SYSROOT_MULTIARCH_INCLUDE_DIRS=("${SYSROOT_INCLUDE_DIR}/"*-linux-gnu)
SYSROOT_MULTIARCH_LIB_DIRS=("${SYSROOT_DIR}/usr/lib/"*-linux-gnu)
if [[ -n "${OPENVINO_RUNTIME_DIR}" ]]; then
  OPENVINO_ARCH_LIB_DIRS=("${OPENVINO_RUNTIME_DIR}/lib/"*)
else
  OPENVINO_ARCH_LIB_DIRS=()
fi

CPATH_VALUE="$(merge_path_var \
  "${CPATH:-}" \
  "${SYSROOT_INCLUDE_DIR}" \
  "${SYSROOT_JSONCPP_INCLUDE_DIR}" \
  "${SYSROOT_MULTIARCH_INCLUDE_DIRS[@]}" \
  "${ONNXRUNTIME_DIR}/include" \
  "${OPENVINO_RUNTIME_DIR}/include" \
  "${OPENVINO_RUNTIME_DIR}/3rdparty/tbb/include")"

LIBRARY_PATH_VALUE="$(merge_path_var \
  "${LIBRARY_PATH:-}" \
  "${SYSROOT_MULTIARCH_LIB_DIRS[@]}" \
  "${ONNXRUNTIME_DIR}/lib" \
  "${OPENVINO_ARCH_LIB_DIRS[@]}" \
  "${OPENVINO_RUNTIME_DIR}/3rdparty/tbb/lib")"

LD_LIBRARY_PATH_VALUE="$(merge_path_var \
  "${LD_LIBRARY_PATH:-}" \
  "${SYSROOT_MULTIARCH_LIB_DIRS[@]}" \
  "${ONNXRUNTIME_DIR}/lib" \
  "${OPENVINO_ARCH_LIB_DIRS[@]}" \
  "${OPENVINO_RUNTIME_DIR}/3rdparty/tbb/lib")"

NO_PROXY_VALUE="$(merge_csv_var "${NO_PROXY:-${no_proxy:-}}" "127.0.0.1" "localhost" "::1")"

shopt -u nullglob

case "${MODE}" in
  --print)
    printf 'export BEACON_ROOT_DIR=%q\n' "${ROOT_DIR}"
    printf 'export BEACON_LOCALDEPS_DIR=%q\n' "${LOCALDEPS_DIR}"
    printf 'export BEACON_SYSROOT_DIR=%q\n' "${SYSROOT_DIR}"
    if [[ -n "${ONNXRUNTIME_DIR}" ]]; then
      printf 'export BEACON_ONNXRUNTIME_DIR=%q\n' "${ONNXRUNTIME_DIR}"
    fi
    if [[ -n "${OPENVINO_RUNTIME_DIR}" ]]; then
      printf 'export BEACON_OPENVINO_RUNTIME_DIR=%q\n' "${OPENVINO_RUNTIME_DIR}"
    fi
    printf 'export CPATH=%q\n' "${CPATH_VALUE}"
    printf 'export LIBRARY_PATH=%q\n' "${LIBRARY_PATH_VALUE}"
    printf 'export LD_LIBRARY_PATH=%q\n' "${LD_LIBRARY_PATH_VALUE}"
    printf 'export NO_PROXY=%q\n' "${NO_PROXY_VALUE}"
    printf 'export no_proxy=%q\n' "${NO_PROXY_VALUE}"
    ;;
  summary|--summary)
    echo "BEACON_ROOT_DIR=${ROOT_DIR}"
    echo "BEACON_LOCALDEPS_DIR=${LOCALDEPS_DIR}"
    echo "BEACON_SYSROOT_DIR=${SYSROOT_DIR}"
    echo "BEACON_ONNXRUNTIME_DIR=${ONNXRUNTIME_DIR}"
    echo "BEACON_OPENVINO_RUNTIME_DIR=${OPENVINO_RUNTIME_DIR}"
    echo "CPATH=${CPATH_VALUE}"
    echo "LIBRARY_PATH=${LIBRARY_PATH_VALUE}"
    echo "LD_LIBRARY_PATH=${LD_LIBRARY_PATH_VALUE}"
    echo "NO_PROXY=${NO_PROXY_VALUE}"
    ;;
  *)
    fail "unknown mode: ${MODE}"
    ;;
esac
