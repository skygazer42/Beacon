---
title: Linux 构建与打包
icon: fontawesome/brands/linux
---

# Linux 构建与打包

本文面向 **交付工程 / 发布工程 / 二次集成人员**。
目标是从 Linux 源码环境产出可交付的 Beacon 运行目录和 `Beacon-linux-x64.tar.gz`。

本篇默认前提如下：

- 已在 Linux 机器上拿到完整源码仓库
- 已按 [Linux 本机开发](local-linux.md) 把基础开发环境跑通
- 当前关注点不是“改代码联调”，而是“产出交付件”

---

## 0. 先明确本篇负责什么

本篇负责的是：

1. 从源码构建 Linux 产物
2. 识别 Linux 交付包里必须携带哪些文件
3. 组装标准运行目录
4. 压缩成 `Beacon-linux-x64.tar.gz`

本篇**不负责**：

- 客户现场如何安装：看 [Linux 用户部署](linux.md)
- 源码联调怎么做：看 [Linux 本机开发](local-linux.md)

---

## 1. Linux 交付包里通常要有什么

Linux 交付时，至少应能落出下面几类产物：

| 产物类型 | 典型内容 | 是否必须 |
|----------|----------|----------|
| Admin 运行环境 | `Admin/`、Python 虚拟环境、数据库迁移结果 | 是 |
| 前端静态资源 | `Admin/static/app-shell/` | 改过前端时必须重新生成 |
| Analyzer 主程序 | `Analyzer/build/Analyzer` 或 `Analyzer/Analyzer` | 是 |
| 动态库 / 插件库 | `.so`、`libbeacon_compat.so`、TensorRT 插件 `.so` | 按算法和硬件类型决定 |
| MediaServer 主程序 | `MediaServer`、`config.ini` | 完整视频链路必须 |
| 根配置与数据目录 | `config.json`、`data/models/`、`data/upload/`、`log/` | 是 |

---

## 2. Linux 构建机准备清单

开始构建前，先把“构建机上必须存在什么”核清楚。
这里建议分成四类检查：基础软件、`Admin` 依赖、`Analyzer` 依赖、交付材料。

### 2.1 基础软件清单

| 软件 / 工具 | 建议版本 | 用途 | 现场验证命令 |
|-------------|----------|------|--------------|
| Python | 3.10 或 3.11 | `Admin`、启动器、迁移脚本 | `python3 --version` |
| Node.js | 18+ | 前端构建 | `node --version` |
| npm | 9+ | 前端依赖安装 | `npm --version` |
| CMake | 3.16+ | `Analyzer` / `MediaServer` 构建 | `cmake --version` |
| GCC / G++ | 9+ | C++ 编译 | `gcc --version | head -n 1`、`g++ --version | head -n 1` |
| pkg-config | 任意可用版本 | 解析 OpenCV 等系统库 | `pkg-config --version` |
| FFmpeg 命令行 | 任意可用版本 | 联调与编解码验证 | `ffmpeg -version | head -n 1` |
| tar / rsync | 系统自带即可 | 组装交付包 | `tar --version | head -n 1`、`rsync --version | head -n 1` |

建议直接一次性执行：

```bash
python3 --version
node --version
npm --version
cmake --version
gcc --version | head -n 1
g++ --version | head -n 1
pkg-config --version
ffmpeg -version | head -n 1
tar --version | head -n 1
rsync --version | head -n 1
```

上面任何一项不存在，都不建议直接开始打包。

### 2.2 `Admin` 与前端构建前核对

`Admin` 和前端部分至少要能回答下面几个问题：

| 核对项 | 验证方式 | 通过标准 |
|--------|----------|----------|
| Python 依赖文件存在 | `test -f Admin/requirements-linux.txt && echo ok` | 输出 `ok` |
| Node 工程存在 | `test -f Admin/frontend/package.json && echo ok` | 输出 `ok` |
| Django 管理入口存在 | `test -f Admin/manage.py && echo ok` | 输出 `ok` |
| 前端构建输出目录存在过 | `test -d Admin/static/app-shell && echo ok || true` | 首次打包前不存在也正常，执行 `npm run build` 后应存在 |

### 2.3 `Analyzer` 构建前核对

Linux 下有两条路：

1. 使用仓库内置 `localdeps`
2. 不使用 `localdeps`，自行准备系统级 C++ 依赖

#### 2.3.1 使用 `localdeps` 时，构建机上至少要看到这些目录和文件

`tools/beacon_localdeps_env.sh` 当前会优先查找：

- `third_party/localdeps/sysroot`
- `third_party/localdeps/src/onnxruntime-*`
- `third_party/localdeps/src/l_openvino_toolkit_*/runtime`

建议直接核到文件级别：

```bash
test -d third_party/localdeps/sysroot && echo "localdeps_sysroot=ok"
find third_party/localdeps/src -maxdepth 2 -type f -name 'onnxruntime_cxx_api.h' | head
find third_party/localdeps/src -maxdepth 3 -type f -name 'libonnxruntime.so' | head
find third_party/localdeps/src -maxdepth 4 -type f -path '*/runtime/include/openvino/openvino.hpp' | head
find third_party/localdeps/src -maxdepth 5 -type f \( -name 'libopenvino.so' -o -name 'libopenvino.so.*' \) | head
find third_party/localdeps/src -maxdepth 6 -type f \( -name 'libtbb.so' -o -name 'libtbb.so.*' \) | head
```

再看一眼脚本最终解析出的环境：

```bash
bash tools/beacon_localdeps_env.sh
```

输出里至少应能看到：

- `BEACON_LOCALDEPS_DIR=...`
- `BEACON_SYSROOT_DIR=...`
- `BEACON_ONNXRUNTIME_DIR=...`
- `BEACON_OPENVINO_RUNTIME_DIR=...`
- `CPATH=...`
- `LIBRARY_PATH=...`
- `LD_LIBRARY_PATH=...`

这些值为空、路径不存在或明显指错目录时，不建议直接构建。

#### 2.3.2 不使用 `localdeps` 时，必须自己准备到什么程度

这条路不能只理解成“系统里装过 OpenCV / FFmpeg 就可以”。
当前 `Analyzer/CMakeLists.txt` 已经写了默认搜索路径，构建前至少要确认下列实物存在：

```bash
pkg-config --modversion opencv4
test -f /usr/include/curl/curl.h && echo "curl_header=ok"
test -f /usr/include/event2/event.h && echo "event_header=ok"
ldconfig -p | grep jsoncpp || true
test -f /usr/local/onnxruntime/include/onnxruntime_cxx_api.h && echo "onnxruntime_header=ok"
test -f /usr/local/onnxruntime/lib/libonnxruntime.so && echo "onnxruntime_lib=ok"
test -f /usr/local/openvino/include/openvino/openvino.hpp && echo "openvino_header=ok"
find /usr/local/openvino/lib -maxdepth 2 -type f | grep -E 'libopenvino|plugin' | head
test -f /usr/local/openvino/3rdparty/tbb/include/tbb/tbb.h && echo "tbb_header=ok"
find /usr/local/openvino/3rdparty/tbb/lib -maxdepth 1 -type f | grep tbb | head
```

建议目录结构至少满足：

```text
/usr/local/ffmpeg/
  include/
  lib/

/usr/local/onnxruntime/
  include/
    onnxruntime_cxx_api.h
  lib/
    libonnxruntime.so

/usr/local/openvino/
  include/
    openvino/
  lib/intel64/        # x86_64
  lib/aarch64/        # aarch64
  3rdparty/tbb/include/
  3rdparty/tbb/lib/
```

更完整的手工 CMake 说明、系统包安装命令、路径不一致时的处理方式，请直接参见 [Linux 本机开发](local-linux.md)。
其中 `ONNX Runtime`、`OpenVINO`、`TBB` 的官方包获取方式、当前仓库示例版本、下载解压命令、源码编译备用路线，集中写在 [Linux 本机开发](local-linux.md) 的这一节里，建议按那一节逐项准备后再回到本页继续打包。
如果当前重点不是“怎么编出来”，而是“Linux 交付时到底该带哪些 `.so`、放到哪、怎么核对”，可直接参见 [Linux 运行库参考](linux-runtime-libs.md)。

### 2.4 打包前还要准备的交付材料

除了“能编出来”，交付阶段还要把下面这些材料一并准备好：

| 材料 | 是否必须 | 说明 |
|------|----------|------|
| `config.json` | 是 | 根配置文件 |
| `data/models/` 内的真实模型文件 | 是 | 没有模型时只能启动，不能推理 |
| `license.json`、公钥、`cluster_id` 说明 | 正式环境必须 | 授权验收时会直接用到 |
| 摄像头 RTSP 地址或测试视频 | 建议 | 用于交付验收 |
| `MediaServer` 配置文件 `config.ini` | 是 | 视频链路必须 |
| 后端插件 `.so` | 按后端类型决定 | `.engine`、`.rknn`、`.om` 场景通常需要额外插件 |
| 运行库交付策略 | 是 | 必须明确“随包附带”还是“要求客户机预装” |

---

## 3. 推荐发布顺序

建议固定按下面顺序做，避免漏文件：

1. 先构建 `Admin`
2. 再构建前端静态资源
3. 再构建 `Analyzer`
4. 再构建 `MediaServer`
5. 按需构建 `libbeacon_compat.so`
6. 收集模型、配置、授权说明和运行库
7. 组装 Linux 运行目录
8. 压缩成 `Beacon-linux-x64.tar.gz`

不建议直接先做安装器或发源码。
对 Linux 交付来说，**运行目录包**才是最基础的交付件。

---

## 4. Linux 源码构建步骤

### 4.1 构建 Admin

```bash
cd Admin
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt
python manage.py migrate --noinput
cd ..
```

### 4.2 构建前端

仅在 `Admin/frontend/` 有改动时执行：

```bash
cd Admin/frontend
npm ci
npm run build
cd ../..
```

构建结果进入：

```text
Admin/static/app-shell/
```

### 4.3 构建 Analyzer

优先使用仓库内置脚本：

```bash
bash tools/build_analyzer_local.sh
```

常规产物位置：

```text
Analyzer/build/Analyzer
```

不使用 `localdeps` 时，可手动执行：

```bash
cmake -S Analyzer -B Analyzer/build -DCMAKE_BUILD_TYPE=Release
cmake --build Analyzer/build -j
```

### 4.4 构建 MediaServer

```bash
cd MediaServer/source
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j
cd ../../..
```

常规产物位置：

```text
MediaServer/source/release/linux/Release/MediaServer
MediaServer/source/release/linux/Release/config.ini
```

### 4.5 按需构建 Compat 兼容动态库

仅在 `.rknn`、`.om`、国产硬件兼容层场景需要：

```bash
cmake -S Analyzer/Compat -B Analyzer/Compat/build -DCMAKE_BUILD_TYPE=Release
cmake --build Analyzer/Compat/build -j
```

常规产物位置：

```text
Analyzer/Compat/build/libbeacon_compat.so
```

---

## 5. Linux `.so` 到底要带哪些

Linux 打包最容易漏的是运行库。建议按下面三类理解。

### 5.1 主程序运行库

这类 `.so` 用于让 `Analyzer`、`MediaServer` 或 Python 本身能启动。

示例：

- ONNX Runtime 动态库
- OpenVINO runtime 动态库
- FFmpeg 运行库
- OpenCV 运行库
- 厂商 SDK 运行库

常见处理方式：

- 优先放在程序可见目录
- 通过 `LD_LIBRARY_PATH` 暴露
- 交付前用 `ldd` 检查是否还存在 `not found`

### 5.1.1 建议把运行库检查到文件名级别

不要只在交付单里写“已附带 OpenVINO / ONNX Runtime 运行库”。
建议至少检查到下面这个粒度：

| 组件 | 至少要看到什么 |
|------|----------------|
| ONNX Runtime | `libonnxruntime.so` |
| FFmpeg | `libavcodec.so`、`libavformat.so`、`libavutil.so`、`libswscale.so`、`libswresample.so` |
| OpenVINO | `libopenvino.so`，以及对应 CPU / GPU plugin 库 |
| TBB | `libtbb.so` 或对应版本 `.so` |
| OpenCV | 由 `ldd Analyzer` 实际输出确认链接到哪些 `libopencv_*.so` |
| libcurl | `libcurl.so` |
| libevent | `libevent.so` |
| jsoncpp | `libjsoncpp.so` |

如果交付时没有核到这个粒度，现场只会知道“缺依赖”，但不知道到底缺哪一个 `.so`。

### 5.2 Compat 兼容动态库

这类动态库用于 `.rknn`、`.om` 等兼容后端。

配置方式：

```json
{
  "compatLibPath": "Analyzer/compat/libbeacon_compat.so"
}
```

或：

```text
BEACON_COMPAT_LIB_PATH=/opt/beacon/Analyzer/compat/libbeacon_compat.so
```

注意：

- `libbeacon_compat.so` 只是 Beacon 兼容入口
- 真正提供 RKNN / Ascend 推理能力的，是 `BEACON_COMPAT_BACKEND_PATH` 指向的后端插件

### 5.3 TensorRT Engine 插件动态库

仅在 `.engine` / `.plan` 模型场景需要。

配置方式：

```json
{
  "tensorrtEnginePluginPath": "Analyzer/plugins/libtrt_helper.so"
}
```

---

## 6. Linux 不同后端随包材料矩阵

| 后端场景 | 模型文件 | 必须随包携带 | 必须明确的配置项 | 常见漏项 |
|----------|----------|--------------|------------------|----------|
| ONNX Runtime | `.onnx` | 模型文件、`onnxruntime` 运行库 | `modelDir` | 只带模型，不带 `onnxruntime` |
| TensorRT Engine | `.engine` / `.plan` | 模型文件、TensorRT runtime、CUDA 相关库、Engine 插件 `.so` | `tensorrtEnginePluginPath` | 只带 engine，不带插件 `.so` |
| OpenVINO | `.xml` + `.bin` | `.xml`、`.bin`、OpenVINO runtime | `modelDir` | 只带 `.xml` 不带 `.bin` |
| RKNN Compat | `.rknn` | 模型文件、`libbeacon_compat.so`、RKNN 后端插件、RKNN SDK runtime | `compatLibPath`、`rknpuPreprocessMode` | 把 compat 入口当成完整后端 |
| Ascend Compat | `.om` | 模型文件、`libbeacon_compat.so`、Ascend 后端插件、Ascend runtime / CANN 依赖 | `compatLibPath` | 没带 Ascend runtime 或后端插件 |

补充说明：

- `libbeacon_compat.so` 只是 Beacon 兼容入口，不是 RKNN / Ascend 厂商 SDK 本体。
- 真正给 `.rknn` / `.om` 提供推理能力的，是实现了 `BeaconGetAlgorithmPluginV3` 的后端插件。
- Linux 打包时，建议把“编译期依赖目录”和“运行期 `.so` 文件”分别核对，不要混成一句“依赖已附带”。

---

## 7. Linux 标准交付目录

推荐交付目录如下：

```text
Beacon-linux-x64/
  config.json
  log/
  data/
    upload/
    models/
  runtime-libs/
  Admin/
  Analyzer/
    Analyzer
    compat/
      libbeacon_compat.so
    plugins/
      libtrt_helper.so
  MediaServer/
    bin/
      bin.x86.gcc9.4/
        MediaServer
        config.ini
```

不要求同时包含 Windows 产物。
Linux 包里应只放 Linux 可执行文件和 Linux `.so`。

### 7.1 建议把交付目录核到“实物文件名”级别

仅仅看到目录名还不够，建议至少能点名下面这些关键文件：

| 目录 | 至少应看到什么 |
|------|----------------|
| `Admin/` | `manage.py`、`requirements-linux.txt`、`app/`、`framework/` |
| `Admin/venv/` | `bin/python`、`bin/pip` |
| `Admin/static/app-shell/` | `index.html` |
| `Analyzer/` | `Analyzer` 主程序 |
| `Analyzer/compat/` | `libbeacon_compat.so`，仅兼容后端场景需要 |
| `Analyzer/plugins/` | `libtrt_helper.so` 或其他后端插件，仅特定场景需要 |
| `MediaServer/bin/bin.x86.gcc9.4/` | `MediaServer`、`config.ini` |
| `data/models/` | 实际模型文件，如 `.onnx`、`.xml` + `.bin`、`.engine`、`.rknn`、`.om` |
| `runtime-libs/` | `libonnxruntime.so`、`libopenvino.so`、`libtbb.so`、`libavcodec.so` 等，采用“运行库随包交付”方案时需要 |
| 根目录 | `config.json`、`log/` |

---

## 8. Linux 运行目录怎么组装

### 8.1 组装目录

```bash
mkdir -p dist/Beacon-linux-x64
mkdir -p dist/Beacon-linux-x64/Analyzer
mkdir -p dist/Beacon-linux-x64/Analyzer/compat
mkdir -p dist/Beacon-linux-x64/Analyzer/plugins
mkdir -p dist/Beacon-linux-x64/MediaServer/bin/bin.x86.gcc9.4
mkdir -p dist/Beacon-linux-x64/data/upload
mkdir -p dist/Beacon-linux-x64/data/models
mkdir -p dist/Beacon-linux-x64/log

cp config.json dist/Beacon-linux-x64/
cp -r Admin dist/Beacon-linux-x64/
cp Analyzer/build/Analyzer dist/Beacon-linux-x64/Analyzer/Analyzer
cp Analyzer/Compat/build/libbeacon_compat.so dist/Beacon-linux-x64/Analyzer/compat/ -f 2>/dev/null || true
cp MediaServer/source/release/linux/Release/MediaServer dist/Beacon-linux-x64/MediaServer/bin/bin.x86.gcc9.4/ -f
cp MediaServer/source/release/linux/Release/config.ini dist/Beacon-linux-x64/MediaServer/bin/bin.x86.gcc9.4/ -f
```

`Admin/venv/` 需要随包交付时，再补下面这一步：

```bash
cp -r Admin/venv dist/Beacon-linux-x64/Admin/
```

注意：

- Python `venv` 默认**不保证可移植**。实测 `Admin/venv/bin/python3` 和 `Admin/venv/bin/activate` 可能保留构建机绝对路径。
- 交付前至少建议核一遍：

```bash
ls -l dist/Beacon-linux-x64/Admin/venv/bin/python3
grep -n '^VIRTUAL_ENV=' dist/Beacon-linux-x64/Admin/venv/bin/activate || true
```

- 如果这里仍指向构建机路径，这份 `venv` 最多只适合同机自检；发到干净机器时，应在交付说明里明确目标机需按 [linux.md](linux.md) 重新创建 `venv`，或提供已单独验证的 Python 运行时。

选择“运行库随包交付”方案时，先创建目录：

```bash
mkdir -p dist/Beacon-linux-x64/runtime-libs
```

### 8.1.1 使用 `localdeps` 构建时，建议这样收集 `runtime-libs/`

当前仓库的 Linux 本机构建优先使用 `third_party/localdeps/`。
如果 `Analyzer` 是按这条路编出来的，**不要再按 `/usr/local/onnxruntime` / `/usr/local/openvino` 去拷**，而应直接从 `localdeps` 收集：

```bash
ORT_DIR="$(find third_party/localdeps/src -maxdepth 1 -type d -name 'onnxruntime-*' | head -n 1)"
OV_RUNTIME_DIR="$(find third_party/localdeps/src -maxdepth 2 -type d -path '*/l_openvino_toolkit_*/runtime' | head -n 1)"
OV_LIB_DIR=""
if [ -n "$OV_RUNTIME_DIR" ]; then
  OV_LIB_DIR="$(find "$OV_RUNTIME_DIR/lib" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
fi

if [ -n "$ORT_DIR" ]; then
  find "$ORT_DIR/lib" -maxdepth 1 \( -type f -o -type l \) -name 'libonnxruntime.so*' \
    -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \;
fi

if [ -n "$OV_LIB_DIR" ]; then
  find "$OV_LIB_DIR" -maxdepth 1 \( -type f -o -type l \) -name 'libopenvino*.so*' \
    -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \;
  test -f "$OV_LIB_DIR/cache.json" && cp -f "$OV_LIB_DIR/cache.json" dist/Beacon-linux-x64/runtime-libs/ || true
fi

if [ -n "$OV_RUNTIME_DIR" ]; then
  find "$OV_RUNTIME_DIR/3rdparty/tbb/lib" -maxdepth 1 \( -type f -o -type l \) -name 'libtbb*.so*' \
    -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \;
fi
```

### 8.1.2 使用 `/usr/local/...` 依赖布局时，可按系统目录收集

```bash
OV_LIB_DIR="$(find /usr/local/openvino/lib -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -n 1)"

find /usr/local/onnxruntime/lib -maxdepth 1 \( -type f -o -type l \) -name 'libonnxruntime.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true

if [ -n "$OV_LIB_DIR" ]; then
  find "$OV_LIB_DIR" -maxdepth 1 \( -type f -o -type l \) -name 'libopenvino*.so*' \
    -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
  test -f "$OV_LIB_DIR/cache.json" && cp -f "$OV_LIB_DIR/cache.json" dist/Beacon-linux-x64/runtime-libs/ || true
fi

find /usr/local/openvino/3rdparty/tbb/lib -maxdepth 1 \( -type f -o -type l \) -name 'libtbb*.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
find /usr/local/ffmpeg/lib -maxdepth 1 \( -type f -o -type l \) -name 'libavcodec.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
find /usr/local/ffmpeg/lib -maxdepth 1 \( -type f -o -type l \) -name 'libavformat.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
find /usr/local/ffmpeg/lib -maxdepth 1 \( -type f -o -type l \) -name 'libavutil.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
find /usr/local/ffmpeg/lib -maxdepth 1 \( -type f -o -type l \) -name 'libswscale.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
find /usr/local/ffmpeg/lib -maxdepth 1 \( -type f -o -type l \) -name 'libswresample.so*' \
  -exec cp -a {} dist/Beacon-linux-x64/runtime-libs/ \; 2>/dev/null || true
```

补充说明：

- Linux 动态加载器默认不会因为 `.so` 和可执行文件放在同目录就自动找到它
- 上面故意使用 `find ... -exec cp -a`，避免 `zsh` 下 `*.so*` 没匹配时直接报 `no matches found`
- OpenVINO 不要只拷 `libopenvino.so*`；至少应把同目录里的 `libopenvino*.so*` 一并带上，否则前端 / plugin 库可能缺失
- FFmpeg、OpenCV、`libcurl`、`libevent`、`jsoncpp` 等是否需要随包补齐，仍要以 `ldd Analyzer/Analyzer` 与 `ldd MediaServer/.../MediaServer` 的实际结果为准
- 当前仓库里的 `VideoAnalyzer.py` 在 Linux 下会自动把 `BEACON_ROOT_DIR/runtime-libs/` 注入到 `MediaServer` 与 `Analyzer` 子进程的 `LD_LIBRARY_PATH`
- 但 `ldd`、直接执行 `Analyzer/Analyzer` / `MediaServer`、以及 systemd / shell 自检，仍建议显式加入：

```bash
export LD_LIBRARY_PATH=/opt/beacon/runtime-libs:${LD_LIBRARY_PATH}
```

需要 TensorRT 插件时，再补：

```bash
cp /path/to/libtrt_helper.so dist/Beacon-linux-x64/Analyzer/plugins/ -f
```

### 8.2 压缩交付包

```bash
tar -czf Beacon-linux-x64.tar.gz -C dist Beacon-linux-x64
```

---

## 9. 交付前最少自检一遍

建议在构建机或干净 Linux 机器上至少验下面几件事：

1. `find dist/Beacon-linux-x64 -maxdepth 3 -type f | sort` 结果完整
2. 采用 `runtime-libs/` 方案时，`LD_LIBRARY_PATH="$PWD/runtime-libs:${LD_LIBRARY_PATH}" ldd Analyzer/Analyzer` 与 `LD_LIBRARY_PATH="$PWD/runtime-libs:${LD_LIBRARY_PATH}" ldd MediaServer/bin/bin.x86.gcc9.4/MediaServer` 不出现 `not found`
3. `python Admin/VideoAnalyzer.py` 能拉起三件套
4. `/login`、`/api/health`、`/open/license/usage` 至少能打通

示例：

```bash
cd dist/Beacon-linux-x64
LD_LIBRARY_PATH="$PWD/runtime-libs:${LD_LIBRARY_PATH}" ldd Analyzer/Analyzer | grep 'not found' || true
LD_LIBRARY_PATH="$PWD/runtime-libs:${LD_LIBRARY_PATH}" ldd MediaServer/bin/bin.x86.gcc9.4/MediaServer | grep 'not found' || true

# 如果随包复制的 venv 已通过上面的可移植性检查，可直接：
source Admin/venv/bin/activate
python Admin/VideoAnalyzer.py
```

另开终端：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9991/login
curl -sS -H "X-Beacon-Token: <token>" http://127.0.0.1:9993/api/health
curl -sS -H "X-Beacon-Token: <token>" http://127.0.0.1:9991/open/license/usage
```

### 9.1 缺 `.so` 时常见报错对照

| 报错表现 | 先怀疑什么 | 先查什么 |
|----------|------------|----------|
| `error while loading shared libraries: libonnxruntime.so: cannot open shared object file` | ONNX Runtime 没带上或 `LD_LIBRARY_PATH` 不可见 | `ldd Analyzer/Analyzer` |
| `error while loading shared libraries: libopenvino.so: cannot open shared object file` | OpenVINO runtime 不可见 | `ldd Analyzer/Analyzer` |
| `error while loading shared libraries: libtbb.so...` | TBB 没带上 | `ldd Analyzer/Analyzer` |
| `error while loading shared libraries: libavcodec.so...` | FFmpeg runtime 不可见 | `ldd Analyzer/Analyzer` 或 `ldd MediaServer/.../MediaServer` |
| `using stub backend` | `.rknn` / `.om` 只带了 compat 入口，没有真实后端插件 | `BEACON_COMPAT_BACKEND_PATH` 与插件文件 |

### 9.2 交付前最终核对表

建议在发包前，把下面这份清单逐项打勾：

- [ ] `dist/Beacon-linux-x64/config.json` 存在，且端口、目录、授权模式已按客户环境调整
- [ ] `dist/Beacon-linux-x64/Admin/manage.py` 存在
- [ ] `dist/Beacon-linux-x64/Admin/venv/bin/python` 存在，且 `bin/python3` / `bin/activate` 未指回构建机绝对路径；否则交付说明已明确要求客户机自行创建 `venv`
- [ ] `dist/Beacon-linux-x64/Admin/static/app-shell/index.html` 存在，前端改动已重新打包
- [ ] `dist/Beacon-linux-x64/Analyzer/Analyzer` 存在且有执行权限
- [ ] `dist/Beacon-linux-x64/MediaServer/bin/bin.x86.gcc9.4/MediaServer` 存在且有执行权限
- [ ] `dist/Beacon-linux-x64/data/models/` 下已有真实模型文件，不是空目录
- [ ] `LD_LIBRARY_PATH="$PWD/dist/Beacon-linux-x64/runtime-libs:${LD_LIBRARY_PATH}" ldd dist/Beacon-linux-x64/Analyzer/Analyzer` 不出现 `not found`
- [ ] `LD_LIBRARY_PATH="$PWD/dist/Beacon-linux-x64/runtime-libs:${LD_LIBRARY_PATH}" ldd dist/Beacon-linux-x64/MediaServer/bin/bin.x86.gcc9.4/MediaServer` 不出现 `not found`
- [ ] 正式环境需要的 `license.json`、公钥、`cluster_id` 说明已经随包或随交付文档提供
- [ ] `python Admin/VideoAnalyzer.py` 能在交付目录里实际拉起三件套
- [ ] `/login`、`/api/health`、`/open/license/usage` 已完成最少一次接口验收

---

## 10. 相关文档

- Linux 本机开发：参见 [local-linux.md](local-linux.md)
- Linux 用户部署：参见 [linux.md](linux.md)
- Windows 构建与打包：参见 [build-and-package-windows.md](build-and-package-windows.md)
- 交付目录规范：参见 [../deploy/delivery-layout.md](../deploy/delivery-layout.md)
- 配置字段：参见 [../configuration/config-json.md](../configuration/config-json.md)
