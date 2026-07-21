# Project-Local Analyzer Dependencies

This directory is the project-local home for Linux Analyzer build/runtime dependencies.

Expected layout:

- `third_party/localdeps/sysroot/`
- `third_party/localdeps/src/onnxruntime-*`
- `third_party/localdeps/src/l_openvino_toolkit_*/runtime`
- `third_party/localdeps/pkgs/` (optional cache for `.deb` sysroot packages)

Use these helper scripts from the repo root:

```bash
bash tools/build_analyzer_local.sh
bash tools/run_analyzer_local.sh
```

To inspect the resolved environment:

```bash
bash tools/beacon_localdeps_env.sh
```

Notes:

- The actual dependency payload is intentionally ignored by Git.
- `third_party/localdeps/` is preferred over legacy `.beads/localdeps/`.
- `Admin/VideoAnalyzer.py` now injects the resolved local dependency paths when it starts `Analyzer`.

## How to prepare this directory

This repository currently expects Linux `Analyzer` runtime dependencies to be unpacked here, not fetched automatically by Git.

Recommended approach for this project:

1. Download the official ONNX Runtime Linux C/C++ archive package
2. Download the official OpenVINO Linux archive package
3. Reuse the bundled `runtime/3rdparty/tbb/` that comes with the OpenVINO archive
4. Unpack both archives into `third_party/localdeps/src/`

Choose packages by machine type:

| Machine type | ONNX Runtime package pattern | OpenVINO package pattern |
|--------------|------------------------------|--------------------------|
| Ubuntu 20.04 x86_64 | `onnxruntime-linux-x64-<version>.tgz` | `l_openvino_toolkit_ubuntu20_<version>_x86_64.tgz` |
| Ubuntu 22.04 x86_64 | `onnxruntime-linux-x64-<version>.tgz` | `l_openvino_toolkit_ubuntu22_<version>_x86_64.tgz` |
| Ubuntu 20 arm64 / aarch64 | `onnxruntime-linux-aarch64-<version>.tgz` | `l_openvino_toolkit_ubuntu20_<version>_arm64.tgz` |

The repository's current sample directories happen to be Ubuntu 20 x86_64, but the scripts only require the same directory shape:

- `third_party/localdeps/src/onnxruntime-*`
- `third_party/localdeps/src/l_openvino_toolkit_*/runtime`

Example matching the current repository layout:

```bash
ROOT_DIR="$(pwd)"
mkdir -p "$ROOT_DIR/third_party/localdeps/src"
cd "$ROOT_DIR/third_party/localdeps/src"

wget https://github.com/microsoft/onnxruntime/releases/download/v1.17.3/onnxruntime-linux-x64-1.17.3.tgz
printf '%s  %s\n' \
  'f2f11f9da1e3e19b22a8b378b9af57a58433f40e3db6a803e75c0ec0eba97a20' \
  'onnxruntime-linux-x64-1.17.3.tgz' | sha256sum -c -
tar -xzf onnxruntime-linux-x64-1.17.3.tgz

wget https://storage.openvinotoolkit.org/repositories/openvino/packages/2024.4/linux/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz
printf '%s  %s\n' \
  '8d2155b7eb599db9c60ba828748365c1a3f53730ab8539ac5fe2f738fdb51b95' \
  'l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz' | sha256sum -c -
tar -xzf l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz
```

These SHA256 values were calculated from the exact official x86_64 archives
shown above. When changing the version, platform, or architecture, record and
verify the corresponding archive checksum before extracting it.

Expected directory shape after unpacking:

```text
third_party/localdeps/src/
  onnxruntime-.../
    include/
      onnxruntime_cxx_api.h
    lib/
      libonnxruntime.so*
  l_openvino_toolkit_.../
    runtime/
      include/
        openvino/
          openvino.hpp
      lib/
        intel64/ or aarch64/
          libopenvino.so*
      3rdparty/
        tbb/
          include/
            oneapi/
              tbb.h
          lib/
            libtbb.so*
```

Expected verification:

```bash
ROOT_DIR="$(pwd)"
test -f "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/include/onnxruntime_cxx_api.h" && echo "ort_header=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/lib/libonnxruntime.so.1.17.3" && echo "ort_lib=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/include/openvino/openvino.hpp" && echo "openvino_header=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/lib/intel64/libopenvino.so.2024.4.0" && echo "openvino_lib=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/3rdparty/tbb/lib/libtbb.so.12.13" && echo "tbb_lib=ok"
```

Important:

- For this project, TBB normally does **not** need a separate download. It is consumed from the OpenVINO archive.
- If different versions or architectures are used, keep the same directory pattern: `onnxruntime-.../include+lib` and `l_openvino_.../runtime/include+lib+3rdparty/tbb`.
- After unpacking, verify the resolved environment with `bash tools/beacon_localdeps_env.sh`.
- For a non-standard layout, configure CMake with `BEACON_SYSROOT_DIR`, `BEACON_ONNXRUNTIME_DIR`, `BEACON_OPENVINO_RUNTIME_DIR`, and `BEACON_FFMPEG_ROOT` instead of editing `Analyzer/CMakeLists.txt`.
