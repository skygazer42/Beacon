---
title: Linux 本机开发
icon: material/laptop
---

# Linux 本机开发

本文适用于 **开发者** 场景。
目标是在 Linux 机器上以源码方式完成后台、前端、分析器和流媒体链路的本机开发与联调。

交付部署场景请参见 [Linux 用户部署](linux.md)。

---

## 先确认当前开发场景

| 场景 | 建议起点 |
|------|------------|
| 后台页面、接口、权限逻辑开发 | 先只启动 `Admin` |
| React 前端页面开发 | 在 `Admin/frontend/` 里重新构建 |
| 视频流、布控、告警联调 | 启动 `Admin + Analyzer + MediaServer` |
| 完整业务闭环验收 | 在全栈跑通后再执行 RTSP / 摄像头 / 模型 / 布控验收 |

建议不要一开始就同时启动全部组件。
推荐先完成 `Admin` 联调，再逐步加入分析与流媒体组件。

---

## 第一步：准备源码目录

```bash
git clone https://github.com/skygazer42/Beacon.git
cd Beacon
```

后面的命令默认都在仓库根目录执行。

---

## 第二步：先把 `Admin` 单独跑起来

进入 `Admin`，建 Python 环境：

```bash
cd Admin
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt
python manage.py migrate --noinput
python manage.py createsuperuser
cd ..
```

新数据库没有预置账号；`createsuperuser` 只需在首次创建管理员时执行。仅进行页面或接口开发时，执行到此即可。

启动 `Admin`：

```bash
cd Admin
source venv/bin/activate
python manage.py runserver 0.0.0.0:9991
```

浏览器打开：

```text
http://127.0.0.1:9991/login
```

该步骤未通过前，不建议继续后续联调。

---

## 第三步：React 页面变更后的前端构建

未改动 `Admin/frontend/` 时，可跳过本步骤。
存在前端改动时，重新执行打包：

```bash
cd Admin/frontend
npm ci
npm run build
cd ../..
```

构建结果会进入：

```text
Admin/static/app-shell/
```

---

## 第四步：准备 `Analyzer` 的本地依赖

Linux 本机开发推荐优先使用项目里的本地依赖方案。

先看一下依赖环境：

```bash
bash tools/beacon_localdeps_env.sh
```

`third_party/localdeps/` 已准备完成时，可直接编译：

```bash
bash tools/build_analyzer_local.sh
```

正常情况下，产物会在：

```text
Analyzer/build/Analyzer
```

不使用 `localdeps` 时，也可以手动执行 CMake，但这里不是“只装几个包再试试”。
当前 `Analyzer/CMakeLists.txt` 为 ONNX Runtime、OpenVINO 和 FFmpeg 提供了明确的 CMake 缓存参数；手工构建时应传入实际路径，而不是修改源码或依赖固定目录。

### 不使用 `localdeps` 时，当前 CMake 默认会去哪里找

按仓库当前实现，`Analyzer/CMakeLists.txt` 主要按下面这些位置找依赖：

| 依赖 | 默认查找位置 | 说明 |
|------|--------------|------|
| OpenCV | `find_package(OpenCV REQUIRED)` | 依赖系统 CMake / pkg-config 环境 |
| FFmpeg | `BEACON_FFMPEG_ROOT`，默认 `/usr/local/ffmpeg` | 需要头文件和库都齐全 |
| jsoncpp 头文件 | `MediaServer/source/3rdpart/jsoncpp/include` | 仓库里自带一份头文件 |
| jsoncpp 动态库 | 系统链接库 `jsoncpp` | 仍然需要系统 `libjsoncpp.so` |
| ONNX Runtime | `BEACON_ONNXRUNTIME_DIR/include`、`BEACON_ONNXRUNTIME_DIR/lib` | 通过环境变量或 `-D` 参数指定包根目录 |
| OpenVINO | `BEACON_OPENVINO_RUNTIME_DIR/include`、`BEACON_OPENVINO_RUNTIME_DIR/lib/<arch>` | 通过环境变量或 `-D` 参数指定 runtime 根目录 |
| TBB | `BEACON_OPENVINO_RUNTIME_DIR/3rdparty/tbb` | 默认使用 OpenVINO runtime 自带 TBB |
| libevent / libcurl / FFmpeg / jsoncpp 系统库 | 由系统链接器解析 | 需要开发头文件和 `.so` 都已安装 |

### Ubuntu / Debian 最少先装哪些系统包

下面这组命令解决的是“系统级基础开发库”，不包含 ONNX Runtime 和 OpenVINO：

```bash
sudo apt update
sudo apt install -y \
  build-essential cmake pkg-config \
  ffmpeg libopencv-dev \
  libavformat-dev libavcodec-dev libavutil-dev libswscale-dev libswresample-dev \
  libevent-dev libcurl4-openssl-dev libjsoncpp-dev
```

这些包分别解决：

- `build-essential cmake pkg-config`：编译器、链接器、CMake、pkg-config
- `libopencv-dev`：OpenCV 头文件和链接库
- `libavformat-dev libavcodec-dev libavutil-dev libswscale-dev libswresample-dev`：FFmpeg 开发头文件和链接库
- `libevent-dev`：`event` / `event2` 头文件和 `libevent.so`
- `libcurl4-openssl-dev`：`curl/curl.h` 和 `libcurl.so`
- `libjsoncpp-dev`：`libjsoncpp.so`

### ONNX Runtime、OpenVINO、TBB 不是 apt 这一条能解决的

这三类依赖和 `libcurl-dev`、`libevent-dev` 不是同一类问题。
当前项目不是简单依赖“系统里装过某个命令”或“Python 里 `pip install` 过某个包”。
当前 `Analyzer/CMakeLists.txt` 和 `tools/beacon_localdeps_env.sh` 实际期待的是：

- `ONNX Runtime`：有现成的 `include/` 和 `lib/`
- `OpenVINO`：有现成的 `runtime/include/` 和 `runtime/lib/<arch>/`
- `TBB`：默认直接取 `OpenVINO runtime/3rdparty/tbb/`

也就是说，必须先把上游产物准备到位，再谈 CMake。

需要集中查看机器类型矩阵、`runtime-libs` 目录约定、后端最低随包清单和 `LD_LIBRARY_PATH` 规则时，可直接参见 [Linux 运行库参考](linux-runtime-libs.md)。

#### 这三个依赖当前通常从哪里来

| 依赖 | 当前项目最省事的来源 | 当前项目是否推荐源码编译 |
|------|----------------------|--------------------------|
| ONNX Runtime | 官方 GitHub Releases 里的 Linux C/C++ 预编译包 | 不是首选，只有做自定义版本或特殊架构时再考虑 |
| OpenVINO | Intel 官方 Linux archive 包 | 当前项目更推荐 archive 包，不推荐先用 apt 再倒腾路径 |
| TBB | OpenVINO archive 包自带的 `runtime/3rdparty/tbb/` | 通常不需要单独编译 |

当前仓库里的 `third_party/localdeps/src/` 已经能看到一组实际示例目录：

```text
third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/
third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/
```

这说明本项目当前最贴合实际的准备方式，不是先 `git clone` 这两个大仓库自己全量编，而是：

1. 下载官方已经打好的运行时包
2. 解压到 `third_party/localdeps/src/`
3. 让 `tools/beacon_localdeps_env.sh` 自动拼出 `CPATH` / `LIBRARY_PATH` / `LD_LIBRARY_PATH`

#### 先按系统 / 架构决定该拿哪个包

当前仓库里已经存在的示例目录是：

```text
third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/
third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/
```

这只是“当前仓库示例”，不是唯一允许的组合。
`tools/beacon_localdeps_env.sh` 真正依赖的是目录命名模式和内部结构：

- `third_party/localdeps/src/onnxruntime-*`
- `third_party/localdeps/src/l_openvino_toolkit_*/runtime`

也就是说：

- Ubuntu 22 不需要伪装成 Ubuntu 20 的目录名
- `arm64` 不需要硬塞进 `x86_64` 目录
- 版本号不要求和仓库示例完全一致，但目录结构必须对

可按下面的矩阵选包：

| 开发机类型 | ONNX Runtime 建议包名 | OpenVINO 建议包名 | 说明 |
|------------|------------------------|-------------------|------|
| Ubuntu 20.04 x86_64 | `onnxruntime-linux-x64-<version>.tgz` | `l_openvino_toolkit_ubuntu20_<version>_x86_64.tgz` | 当前仓库现成示例就是这一类 |
| Ubuntu 22.04 x86_64 | `onnxruntime-linux-x64-<version>.tgz` | `l_openvino_toolkit_ubuntu22_<version>_x86_64.tgz` | `ONNX Runtime` 仍是 `x64` 包，`OpenVINO` 需切到 `ubuntu22` |
| Ubuntu 20 arm64 / aarch64 | `onnxruntime-linux-aarch64-<version>.tgz` | `l_openvino_toolkit_ubuntu20_<version>_arm64.tgz` | `OpenVINO` 官方 archive 当前对 Linux arm64 给的是 Ubuntu 20 arm64 这一类包 |

补充说明：

- `ONNX Runtime` 这里关注的是 CPU 版 C/C++ 动态库包，不是 Python wheel
- `OpenVINO` 包名里的 `ubuntu20`、`ubuntu22`、`arm64` 需要和机器类型对应
- `OpenVINO` 官方文档当前给出的硬件支持矩阵里，`Ubuntu20 arm64` 是 CPU 可用，GPU/NPU 不适用；`Ubuntu20 x86_64` 和 `Ubuntu22 x86_64` 支持 CPU / GPU / NPU

#### 直接给三组可执行示例

下面三组命令分别对应最常见的三类机器。
执行前先进入仓库根目录。

##### Ubuntu 20.04 x86_64

```bash
ROOT_DIR="$(pwd)"
mkdir -p "$ROOT_DIR/third_party/localdeps/src"
cd "$ROOT_DIR/third_party/localdeps/src"

wget https://github.com/microsoft/onnxruntime/releases/download/v1.17.3/onnxruntime-linux-x64-1.17.3.tgz
tar -xzf onnxruntime-linux-x64-1.17.3.tgz

wget https://storage.openvinotoolkit.org/repositories/openvino/packages/2024.4/linux/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz
tar -xzf l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz
```

##### Ubuntu 22.04 x86_64

```bash
ROOT_DIR="$(pwd)"
mkdir -p "$ROOT_DIR/third_party/localdeps/src"
cd "$ROOT_DIR/third_party/localdeps/src"

wget https://github.com/microsoft/onnxruntime/releases/download/v1.17.3/onnxruntime-linux-x64-1.17.3.tgz
tar -xzf onnxruntime-linux-x64-1.17.3.tgz

curl -L https://storage.openvinotoolkit.org/repositories/openvino/packages/2024.6/linux/l_openvino_toolkit_ubuntu22_2024.6.0.17404.4c0f47d2335_x86_64.tgz --output openvino_2024.6.0.tgz
tar -xf openvino_2024.6.0.tgz
```

##### Ubuntu 20 arm64 / aarch64

```bash
ROOT_DIR="$(pwd)"
mkdir -p "$ROOT_DIR/third_party/localdeps/src"
cd "$ROOT_DIR/third_party/localdeps/src"

wget https://github.com/microsoft/onnxruntime/releases/download/v1.17.3/onnxruntime-linux-aarch64-1.17.3.tgz
tar -xzf onnxruntime-linux-aarch64-1.17.3.tgz

curl -L https://storage.openvinotoolkit.org/repositories/openvino/packages/2024.6/linux/l_openvino_toolkit_ubuntu20_2024.6.0.17404.4c0f47d2335_arm64.tgz --output openvino_2024.6.0.tgz
tar -xf openvino_2024.6.0.tgz
```

上面三组命令执行完后，`third_party/localdeps/src/` 下只要出现：

- 一个 `onnxruntime-*` 目录，里面有 `include/` 和 `lib/`
- 一个 `l_openvino_toolkit_*` 目录，里面的 `runtime/` 下有 `include/`、`lib/`、`3rdparty/tbb/`

就符合当前项目脚本的识别条件。

#### 三类机器的解压后目录实物示例

##### Ubuntu 20.04 x86_64 解压后应接近下面这样

```text
third_party/localdeps/src/
  onnxruntime-linux-x64-1.17.3/
    include/
      onnxruntime_cxx_api.h
    lib/
      libonnxruntime.so
      libonnxruntime.so.1.17.3
  l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/
    runtime/
      include/
        openvino/
          openvino.hpp
      lib/
        intel64/
          libopenvino.so.2024.4.0
          libopenvino_intel_cpu_plugin.so
      3rdparty/
        tbb/
          include/
            oneapi/
              tbb.h
          lib/
            libtbb.so.12.13
```

快速核对命令：

```bash
ROOT_DIR="$(pwd)"
find "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3" -maxdepth 2 -type f | sort | head
find "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime" -maxdepth 3 -type f | sort | head -n 20
```

##### Ubuntu 22.04 x86_64 解压后应接近下面这样

```text
third_party/localdeps/src/
  onnxruntime-linux-x64-1.17.3/
    include/
      onnxruntime_cxx_api.h
    lib/
      libonnxruntime.so
      libonnxruntime.so.1.17.3
  l_openvino_toolkit_ubuntu22_2024.6.0.17404.4c0f47d2335_x86_64/
    runtime/
      include/
        openvino/
          openvino.hpp
      lib/
        intel64/
          libopenvino.so
          libopenvino_intel_cpu_plugin.so
          libopenvino_intel_gpu_plugin.so
      3rdparty/
        tbb/
          include/
            oneapi/
              tbb.h
          lib/
            libtbb.so
```

快速核对命令：

```bash
ROOT_DIR="$(pwd)"
find "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3" -maxdepth 2 -type f | sort | head
find "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu22_2024.6.0.17404.4c0f47d2335_x86_64/runtime" -maxdepth 3 -type f | sort | head -n 20
```

##### Ubuntu 20 arm64 / aarch64 解压后应接近下面这样

```text
third_party/localdeps/src/
  onnxruntime-linux-aarch64-1.17.3/
    include/
      onnxruntime_cxx_api.h
    lib/
      libonnxruntime.so
      libonnxruntime.so.1.17.3
  l_openvino_toolkit_ubuntu20_2024.6.0.17404.4c0f47d2335_arm64/
    runtime/
      include/
        openvino/
          openvino.hpp
      lib/
        aarch64/
          libopenvino.so
          libopenvino_intel_cpu_plugin.so
      3rdparty/
        tbb/
          include/
            oneapi/
              tbb.h
          lib/
            libtbb.so
```

快速核对命令：

```bash
ROOT_DIR="$(pwd)"
find "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-aarch64-1.17.3" -maxdepth 2 -type f | sort | head
find "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.6.0.17404.4c0f47d2335_arm64/runtime" -maxdepth 3 -type f | sort | head -n 20
```

##### 三类机器共用的最低通过标准

无论选哪一组包，只要下面几件事同时成立，就说明目录形态对当前项目是可用的：

```bash
ROOT_DIR="$(pwd)"
find "$ROOT_DIR/third_party/localdeps/src" -maxdepth 1 -type d -name 'onnxruntime-*'
find "$ROOT_DIR/third_party/localdeps/src" -maxdepth 1 -type d -name 'l_openvino_toolkit_*'
find "$ROOT_DIR/third_party/localdeps/src" -type f -name 'onnxruntime_cxx_api.h' | head -n 1
find "$ROOT_DIR/third_party/localdeps/src" -type f -path '*/runtime/include/openvino/openvino.hpp' | head -n 1
find "$ROOT_DIR/third_party/localdeps/src" -type f -name 'libonnxruntime.so*' | head -n 3
find "$ROOT_DIR/third_party/localdeps/src" -type f -name 'libopenvino.so*' | head -n 3
find "$ROOT_DIR/third_party/localdeps/src" -type f -path '*/runtime/3rdparty/tbb/lib/libtbb.so*' | head -n 3
```

如果上面找不到结果，不要继续执行 `build_analyzer_local.sh`，先回到下载和解压步骤把目录纠正好。

#### 路线 A：直接使用官方预编译包，按当前项目目录放置

这是当前项目最推荐的路线。
原因很简单：仓库当前 `localdeps` 的目录名、`beacon_localdeps_env.sh` 的查找逻辑、`Admin/VideoAnalyzer.py` 的运行时注入，都是围绕“已解压的运行时目录”在工作。

##### A.1 准备 ONNX Runtime

在仓库根目录执行：

```bash
ROOT_DIR="$(pwd)"
mkdir -p "$ROOT_DIR/third_party/localdeps/src"
cd "$ROOT_DIR/third_party/localdeps/src"
wget https://github.com/microsoft/onnxruntime/releases/download/v1.17.3/onnxruntime-linux-x64-1.17.3.tgz
tar -xzf onnxruntime-linux-x64-1.17.3.tgz
```

解压完成后，应至少满足：

```bash
ROOT_DIR="$(pwd)"
test -f "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/include/onnxruntime_cxx_api.h" && echo "ort_header=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/lib/libonnxruntime.so.1.17.3" && echo "ort_lib=ok"
```

当前项目真正需要的是这个目录结构：

```text
third_party/localdeps/src/onnxruntime-linux-x64-1.17.3/
  include/
    onnxruntime_cxx_api.h
  lib/
    libonnxruntime.so
    libonnxruntime.so.1.17.3
```

##### A.2 准备 OpenVINO

当前仓库示例目录对应的是 Ubuntu 20 x86_64 的 archive 包。
在相同位置执行：

```bash
ROOT_DIR="$(pwd)"
cd "$ROOT_DIR/third_party/localdeps/src"
wget https://storage.openvinotoolkit.org/repositories/openvino/packages/2024.4/linux/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz
tar -xzf l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64.tgz
```

解压完成后，应至少满足：

```bash
ROOT_DIR="$(pwd)"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/include/openvino/openvino.hpp" && echo "openvino_header=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/lib/intel64/libopenvino.so.2024.4.0" && echo "openvino_lib=ok"
```

当前项目真正需要的是 `runtime/` 这一层，而不是整套文档、示例、Python 工具都必须参与编译。

##### A.3 准备 TBB

当前项目默认不需要单独下载 TBB。
OpenVINO archive 包已经带了 `runtime/3rdparty/tbb/`，当前 `Analyzer/CMakeLists.txt` 就是按这条路径找。

直接验证：

```bash
ROOT_DIR="$(pwd)"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/3rdparty/tbb/include/oneapi/tbb.h" && echo "tbb_header=ok"
test -f "$ROOT_DIR/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime/3rdparty/tbb/lib/libtbb.so.12.13" && echo "tbb_lib=ok"
```

也就是说，对当前项目来说：

- `OpenVINO` 和 `TBB` 不是两次独立准备
- 通常是一份 OpenVINO archive 包同时解决 `OpenVINO runtime + TBB`

##### A.4 准备好以后怎么让项目识别

准备完上面两包后，直接执行：

```bash
bash tools/beacon_localdeps_env.sh
```

正常输出里应能看到：

- `BEACON_ONNXRUNTIME_DIR=.../third_party/localdeps/src/onnxruntime-linux-x64-1.17.3`
- `BEACON_OPENVINO_RUNTIME_DIR=.../third_party/localdeps/src/l_openvino_toolkit_.../runtime`
- `CPATH=...`
- `LIBRARY_PATH=...`
- `LD_LIBRARY_PATH=...`

然后再构建：

```bash
bash tools/build_analyzer_local.sh
```

#### 路线 B：不使用 `localdeps`，直接把官方包路径交给 CMake

这条路线不需要创建 `/usr/local` 符号链接。先解压官方运行时包，再把包根目录传给当前 CMake 已提供的参数：

```bash
ORT_DIR="$PWD/third_party/localdeps/src/onnxruntime-linux-x64-1.17.3"
OPENVINO_RUNTIME_DIR="$PWD/third_party/localdeps/src/l_openvino_toolkit_ubuntu20_2024.4.0.16579.c3152d32c9c_x86_64/runtime"

test -f "$ORT_DIR/include/onnxruntime_cxx_api.h" && echo "ort_header=ok"
test -f "$ORT_DIR/lib/libonnxruntime.so" && echo "ort_lib=ok"
test -f "$OPENVINO_RUNTIME_DIR/include/openvino/openvino.hpp" && echo "openvino_header=ok"
find "$OPENVINO_RUNTIME_DIR/lib" -maxdepth 2 -type f -name 'libopenvino.so*' | head
find "$OPENVINO_RUNTIME_DIR/3rdparty/tbb/lib" -maxdepth 1 -type f -name 'libtbb.so*' | head

cmake -S Analyzer -B Analyzer/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DBEACON_ONNXRUNTIME_DIR="$ORT_DIR" \
  -DBEACON_OPENVINO_RUNTIME_DIR="$OPENVINO_RUNTIME_DIR"
cmake --build Analyzer/build -j
```

两个目录分别需要包含 `include/`、`lib/`，OpenVINO runtime 还需要 `3rdparty/tbb/`。

#### 路线 C：确实要自己源码编译时，分别怎么来

这条路线不是当前项目的首选。
只有在下面几种情况才建议这样做：

- 官方预编译包没有覆盖当前架构
- 必须固定到某个自编译版本
- 必须开启上游特定编译选项

##### C.1 ONNX Runtime 源码编译

官方文档给出的 Linux 基本构建方式是：

```bash
git clone --recursive https://github.com/Microsoft/onnxruntime.git
cd onnxruntime
git checkout v1.17.3
./build.sh --config RelWithDebInfo --build_shared_lib --parallel --compile_no_warning_as_error --skip_submodule_sync
```

需要特别注意两件事：

1. 上面命令只是把 ONNX Runtime 编出来，不会自动形成可直接传给 `BEACON_ONNXRUNTIME_DIR` 的包目录
2. 编译完成后，仍然需要人工整理出至少下面这套目录：

```text
<ORT_DIR>/
  include/
    onnxruntime_cxx_api.h
  lib/
    libonnxruntime.so
```

也就是说，源码编译不是当前项目更简单的路，而是“额外多了一步整理安装目录”。

##### C.2 OpenVINO 源码编译

对当前项目来说，不推荐把 OpenVINO 作为“先 `git clone` 再本地全量编译”的日常路径。
原因不是不能编，而是当前项目真正消耗的是：

- `runtime/include/`
- `runtime/lib/<arch>/`
- `runtime/3rdparty/tbb/`

这正是 OpenVINO 官方 archive 包已经直接给出的结构。
因此当前项目更建议直接使用官方 archive 包，而不是先做一遍 OpenVINO 源码构建再人工整理 runtime 子树。

##### C.3 oneTBB 单独源码编译

只有在明确不想使用 OpenVINO 自带 TBB 时，才需要单独处理 oneTBB。
官方仓库给出的一个最直接示例是：

```bash
cd /tmp
git clone https://github.com/uxlfoundation/oneTBB.git
cd oneTBB
mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=/tmp/my_installed_onetbb -DTBB_TEST=OFF ..
cmake --build .
cmake --install .
```

编译完成后，还不能直接结束。
因为当前项目会在 `BEACON_OPENVINO_RUNTIME_DIR` 指向的 runtime 下查找：

```text
<OPENVINO_RUNTIME_DIR>/3rdparty/tbb/include
<OPENVINO_RUNTIME_DIR>/3rdparty/tbb/lib
```

所以单独编好的 oneTBB 还需要二选一：

1. 把安装结果整理进 `<OPENVINO_RUNTIME_DIR>/3rdparty/tbb/`
2. 在配置 CMake 前通过 `CPATH`、`LIBRARY_PATH` 和 `LD_LIBRARY_PATH` 暴露自定义 TBB

如果没有这一步，单独编好 oneTBB 对当前项目也没有意义。

如果不走 `localdeps`，这三类依赖至少要满足下面的目录结构：

```text
<ORT_DIR>/
  include/
  lib/

<OPENVINO_RUNTIME_DIR>/
  include/
  lib/intel64/        # x86_64
  lib/aarch64/        # aarch64
  3rdparty/tbb/include/
  3rdparty/tbb/lib/
```

也就是说：

- `ONNX Runtime` 不是“系统里有个 Python 包”就算准备好了，必须有 C++ 头文件和 `libonnxruntime.so`
- `OpenVINO` 不是“命令能跑 `ovc`”就算准备好了，必须有 C++ 头文件、`libopenvino.so` 和对应插件库
- `TBB` 在当前 CMake 里按 OpenVINO runtime 自带目录找，不是随便装个 `libtbb-dev` 就一定能被识别

### 建议直接整理成这个目录样板

如果决定不用 `localdeps`，所选目录至少应具备下面的结构；目录本身不要求位于 `/usr/local`：

```text
<FFMPEG_ROOT>/
  include/
    libavcodec/
    libavformat/
    libavutil/
    libswscale/
    libswresample/
  lib/
    libavcodec.so
    libavformat.so
    libavutil.so
    libswscale.so
    libswresample.so

<ORT_DIR>/
  include/
    onnxruntime_cxx_api.h
  lib/
    libonnxruntime.so

<OPENVINO_RUNTIME_DIR>/
  include/
    openvino/
  lib/intel64/        # x86_64
  lib/aarch64/        # aarch64
  3rdparty/tbb/include/
  3rdparty/tbb/lib/
```

配置 CMake 时分别将这三个根目录传给 `BEACON_FFMPEG_ROOT`、`BEACON_ONNXRUNTIME_DIR` 和 `BEACON_OPENVINO_RUNTIME_DIR`。

### 每个依赖至少要验证什么

手动 CMake 前，建议直接逐项检查：

```bash
ORT_DIR=/path/to/onnxruntime
OPENVINO_RUNTIME_DIR=/path/to/openvino/runtime

pkg-config --modversion opencv4
test -f /usr/include/curl/curl.h && echo "curl_header=ok"
test -f /usr/include/event2/event.h && echo "event_header=ok"
ldconfig -p | grep jsoncpp || true
test -f "$ORT_DIR/include/onnxruntime_cxx_api.h" && echo "onnxruntime_header=ok"
test -f "$ORT_DIR/lib/libonnxruntime.so" && echo "onnxruntime_lib=ok"
test -f "$OPENVINO_RUNTIME_DIR/include/openvino/openvino.hpp" && echo "openvino_header=ok"
find "$OPENVINO_RUNTIME_DIR/lib" -maxdepth 2 -type f | grep -E 'libopenvino|plugin' | head
find "$OPENVINO_RUNTIME_DIR/3rdparty/tbb/lib" -maxdepth 1 -type f -name 'libtbb.so*' | head
```

以上任一项缺失时，不应继续执行 CMake。

### 路径不一致时怎么处理

依赖路径不固定时，优先使用项目已经提供的参数：

1. 配置 CMake 时传入 `BEACON_ONNXRUNTIME_DIR`、`BEACON_OPENVINO_RUNTIME_DIR` 和 `BEACON_FFMPEG_ROOT`
2. 特殊布局再在运行 CMake 前补充 `CPATH`、`LIBRARY_PATH` 和 `LD_LIBRARY_PATH`

也就是说，不能只说“我装过了 OpenVINO / ONNX Runtime”，还必须确认：

- 头文件在哪里
- `.so` 在哪里
- CMake 和链接器是否真的能看到它们

### 手动 CMake 命令

依赖和路径都确认无误后，再执行：

```bash
cmake -S Analyzer -B Analyzer/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DBEACON_ONNXRUNTIME_DIR="$ORT_DIR" \
  -DBEACON_OPENVINO_RUNTIME_DIR="$OPENVINO_RUNTIME_DIR" \
  -DBEACON_FFMPEG_ROOT=/usr/local/ffmpeg
cmake --build Analyzer/build -j
```

只有在下面这两件事都能明确回答时，才建议走这条路：

1. 每个依赖的头文件和 `.so` 分别放在哪里
2. 当前 CMakeLists 为什么能找到这些路径

否则直接使用 `third_party/localdeps/` 更稳。

### 手工编译阶段常见报错对照

| 报错表现 | 先怀疑什么 | 先查什么 |
|----------|------------|----------|
| `fatal error: opencv2/...: No such file or directory` | OpenCV 头文件没装或 CMake 没找到 | `pkg-config --modversion opencv4` |
| `fatal error: curl/curl.h: No such file or directory` | libcurl 开发头文件缺失 | `test -f /usr/include/curl/curl.h` |
| `fatal error: event2/event.h: No such file or directory` | libevent 开发头文件缺失 | `test -f /usr/include/event2/event.h` |
| `fatal error: onnxruntime_cxx_api.h: No such file or directory` | ONNX Runtime 头文件路径不对 | `test -f "$ORT_DIR/include/onnxruntime_cxx_api.h"` |
| `fatal error: openvino/openvino.hpp: No such file or directory` | OpenVINO 头文件路径不对 | `test -f "$OPENVINO_RUNTIME_DIR/include/openvino/openvino.hpp"` |
| `ld: cannot find -lonnxruntime` | `libonnxruntime.so` 不在链接器可见路径 | `test -f "$ORT_DIR/lib/libonnxruntime.so"` |
| `ld: cannot find -lopenvino` / `-ltbb` | OpenVINO / TBB 库路径不对 | `find "$OPENVINO_RUNTIME_DIR/lib" -type f | head` |
| `undefined reference to av_*` | FFmpeg 头文件和库版本不一致，或某个 `libav*` 库没装全 | `ls /usr/local/ffmpeg/lib` 与 `libav*dev` 安装情况 |
| `./Analyzer: error while loading shared libraries: ... not found` | 运行阶段找不到 `.so` | `ldd Analyzer/build/Analyzer` |

这里最重要的一条原则是：

- 编译报错先查头文件和 `.so` 是否存在
- 运行报错先查 `ldd`

---

## 第五步：准备 `MediaServer`

后台或接口开发场景可暂不启动 `MediaServer`。
视频流与播放器联调场景需要启动 `MediaServer`。

Linux 下最直接的编译方式：

```bash
cd MediaServer/source
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j
cd ../../..
```

如果 `cmake` 阶段出现：

```text
srtp 未找到, WebRTC 相关功能打开失败
```

说明本次 `MediaServer` 构建仍可完成，但 `WebRTC` 能力会被关闭。
做 `RTSP / RTMP / HLS / HTTP-FLV` 本机联调时可继续；若要验证 `WebRTC`，先安装 `libsrtp` 的开发包（例如 Ubuntu / Debian 下的 `libsrtp2-dev`）后再重新执行 `cmake ..` 和 `cmake --build . -j`。

编完后，通常产物在：

```text
MediaServer/source/release/linux/Release/MediaServer
MediaServer/source/release/linux/Release/config.ini
```

---

## 第六步：检查根目录 `config.json`

开发联调最少要看这些字段：

```json
{
  "adminPort": 9991,
  "mediaHttpPort": 9992,
  "analyzerPort": 9993,
  "mediaRtspPort": 9994,
  "mediaRtmpPort": 9995,
  "mediaSecret": "CHANGE_ME",
  "uploadDir": "data/upload",
  "modelDir": "data/models",
  "openApiToken": "CHANGE_ME",
  "licenseType": "pool"
}
```

开发时常见建议：

- `uploadDir` 用本地可写目录
- `modelDir` 指到你本机真实存在的模型目录
- `openApiToken` 可以写进 `config.json`，也可以改用环境变量 `BEACON_OPEN_API_TOKEN`
- 两者同时存在时，以 `BEACON_OPEN_API_TOKEN` 为准
- 若两者都留空，`Analyzer` 的 open API 默认只允许本机调用
- `mediaSecret` 要和 `MediaServer` 的 `config.ini` 对齐
- 分别手工启动组件时，根目录 `config.json` 和新生成的 MediaServer `config.ini` 不会自动同步；使用后文统一启动器时，空密钥会自动生成并注入三个子进程

可以先准备目录：

```bash
mkdir -p data/upload data/models logs
```

---

## 第七步：你有三种启动方式

### 方式一：只启动 `Admin`

适合做页面、接口、权限、表单、配置类开发。

```bash
cd Admin
source venv/bin/activate
python manage.py runserver 0.0.0.0:9991
```

### 方式二：启动全栈

适合做 RTSP、布控、告警、分析链路联调。

最稳妥的顺序是：

1. 先启动 `MediaServer`
2. 再启动 `Analyzer`
3. 最后启动 `Admin`

示例：

```bash
# 终端1
cd MediaServer/source/release/linux/Release
./MediaServer -c ./config.ini
```

```bash
# 终端2
cd /path/to/Beacon
eval "$(./tools/beacon_localdeps_env.sh --print)"
export BEACON_OPEN_API_TOKEN='change-me-long-random-token'
./Analyzer/build/Analyzer -f config.json
```

```bash
# 终端3
cd /path/to/Beacon/Admin
source venv/bin/activate
python manage.py runserver 0.0.0.0:9991
```

如果 `Analyzer` 是按第四步的 `localdeps` 方式编出来的，上面的 `eval "$(./tools/beacon_localdeps_env.sh --print)"` 不能省。
否则启动时通常会报 `libonnxruntime.so`、`libopenvino.so` 或 `libtbb.so` 找不到。

### 方式三：用统一启动器

`Analyzer` 和 `MediaServer` 已放置在启动器可识别路径时，也可直接执行：

```bash
cd /path/to/Beacon
source Admin/venv/bin/activate
python Admin/VideoAnalyzer.py
```

它会按约定路径去找：

- `Analyzer/build/Analyzer`
- `Analyzer/Analyzer`
- `MediaServer/bin/bin.x86.gcc9.4/MediaServer`

它不会自动改用第四步刚编出来的 `MediaServer/source/release/linux/Release/MediaServer`。
如果你要直接验证源码构建产物，优先使用上面的“方式二：启动全栈”。

---

## 第八步：开发者验活

启动后，不要只看终端没报错，要实际检查。

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9991/login
curl -sS "http://127.0.0.1:9992/index/api/getServerConfig?secret=<你的mediaSecret>" | head
curl -sS -H "X-Beacon-Token: <你的生效openApiToken>" http://127.0.0.1:9993/api/health
```

期望结果：

- `Admin` 登录页返回 `200`
- `MediaServer` 返回配置
- `Analyzer` 返回健康检查成功

如果你明确保持 `openApiToken` 为空，并且当前请求来自本机，也可以先不带 `X-Beacon-Token` 验证 `Analyzer` 健康检查。

---

## 第九步：真实业务闭环验收前的补充检查

完整闭环不是“服务起来了”就算完。

还要再做：

1. 添加一条视频流
2. 确认视频流在线
3. 配置或导入算法
4. 创建并启动布控
5. 让画面里出现检测目标
6. 去 `/alarms` 看有没有新告警

需按完整手册逐项验收时，参见：

- [../deploy/e2e-acceptance.md](../deploy/e2e-acceptance.md)
- [Edge 全栈部署](../deploy/edge-full-stack.md)
- [build-and-package-linux.md](build-and-package-linux.md)

---

## 常见联调故障 { #common-troubleshooting }

| 现象 | 先看什么 |
|------|----------|
| `Admin` 起不来 | Python 依赖是否装好，数据库迁移是否执行 |
| React 页面没变化 | 有没有重新执行 `npm run build` |
| `Analyzer` 找不到依赖库 | `third_party/localdeps/` 是否准备好，环境是否注入 |
| `MediaServer` 功能失败 | `mediaSecret` 是否和 `config.ini` 对齐 |
| `Analyzer` 健康检查 401 | 请求是否带了 `X-Beacon-Token` |
| 服务都起来了但没有告警 | 视频流、模型、布控、目标出现，这四件事缺一不可 |

---

## 常见开发问题

- 页面、接口、联调这几个开发阶段，可以共用上面的排查表
- 如果是“启动器找不到二进制”，先看 `Analyzer/` 和 `MediaServer/` 是否放在文档约定路径

---

## 开发者建议

- 做页面开发时，先只跑 `Admin`
- 做接口联调时，先确保 `openApiToken` 固定
- 做视频分析联调时，再把 `Analyzer` 和 `MediaServer` 加进来
- 不要一开始就在一台新机器上同时解决 Python、Node、C++、模型、视频流、授权五件事

按顺序拆开，效率会高很多。
