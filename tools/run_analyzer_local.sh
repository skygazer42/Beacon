#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

eval "$("${ROOT_DIR}/tools/beacon_localdeps_env.sh" --print)"

ANALYZER_BIN="${BEACON_ANALYZER_BIN:-${ROOT_DIR}/Analyzer/build/Analyzer}"
CONFIG_PATH="${BEACON_CONFIG_PATH:-${ROOT_DIR}/config.json}"

[[ -x "${ANALYZER_BIN}" ]] || {
  echo "[run-analyzer] missing binary: ${ANALYZER_BIN}" >&2
  echo "[run-analyzer] build it first with: bash tools/build_analyzer_local.sh" >&2
  exit 1
}

exec "${ANALYZER_BIN}" -f "${CONFIG_PATH}"
