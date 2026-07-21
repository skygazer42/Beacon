---
title: Linux 用户部署
icon: fontawesome/brands/linux
---

# Linux 用户部署

本文适用于 **用户 / 实施 / 运维** 场景。
目标是完成 Beacon 在 Linux 机器上的安装、启动、授权导入、视频接入和最小业务验收。

源码开发场景请直接参见 [Linux 本机开发](local-linux.md)。

---

## 0. 先明确 Linux 交付形态

当前 Linux 标准交付形态通常不是 `.deb`、`.rpm` 或一键安装器，而是下面两种之一：

1. `Beacon-linux-x64.tar.gz`
2. 已解压好的运行目录

标准运行目录建议如下：

```text
/opt/beacon/
  config.json
  runtime-libs/
  Admin/
  Analyzer/
  MediaServer/
  data/
    models/
    upload/
  logs/
```

仅拿到源码、尚未拿到二进制运行包时，不应继续使用本文档。
此时应先完成源码构建：

- [Linux 本机开发](local-linux.md)
- [Linux 构建与打包](build-and-package-linux.md)

---

## 1. 开始前需要准备的材料

正式部署开始前，先确认交付方已经提供以下内容。

| 材料 | 是否必须 | 说明 |
|------|----------|------|
| `Beacon-linux-x64.tar.gz` 或完整运行目录 | 是 | Beacon 主运行包 |
| 模型文件 | 是 | 放入 `data/models/`，没有模型只能启动，不能正常推理 |
| `license.json` | 正式环境必须 | 授权池模式推荐交付物 |
| `cluster_id` | 正式环境必须 | 需与 `license.json` 一致 |
| 授权公钥 `BEACON_LICENSE_PUBLIC_KEY_B64` | 正式环境必须 | 用于校验 `license.json` |
| 管理员账号与密码 | 建议提供 | 便于首次登录验收 |
| 摄像头 RTSP 地址或测试视频文件 | 业务验收建议提供 | 用于验证流接入与告警闭环 |
| 离线 Python 依赖包或可联网安装条件 | 按交付包情况决定 | 交付包未附带 Python 运行环境时需要 |

### 1.1 Linux 机器类型不同，交付方应给的运行库也不同

Linux 用户部署最容易踩坑的点，是用户拿到了：

- `Analyzer`
- `MediaServer`
- `config.json`

但没有拿到和本机类型匹配的运行库目录。

建议要求交付方明确说明当前交付包对应哪一类机器，并至少核对到下面这个粒度：

| 机器类型 | 交付方至少应说明什么 | 交付包里建议至少看到什么 |
|----------|----------------------|--------------------------|
| Ubuntu 20.04 x86_64 | ONNX Runtime `x64`、OpenVINO `ubuntu20 x86_64` | `runtime-libs/libonnxruntime.so*`、`runtime-libs/libopenvino.so*`、`runtime-libs/libtbb.so*` |
| Ubuntu 22.04 x86_64 | ONNX Runtime `x64`、OpenVINO `ubuntu22 x86_64` | `runtime-libs/libonnxruntime.so*`、`runtime-libs/libopenvino.so*`、`runtime-libs/libtbb.so*` |
| Ubuntu 20 arm64 / aarch64 | ONNX Runtime `aarch64`、OpenVINO `ubuntu20 arm64` | `runtime-libs/libonnxruntime.so*`、`runtime-libs/libopenvino.so*`、`runtime-libs/libtbb.so*` |

如果现场机器类型和交付包说明对不上，不建议继续部署。
例如：

- `arm64` 机器拿到 `x64` 运行库
- Ubuntu 22 机器拿到只验证过 Ubuntu 20 的 OpenVINO 运行时
- 只给了模型文件，没有给对应后端 `.so`

### 1.2 建议直接要求交付方附这份“运行库清单”

正式交付时，建议让交付方把下面这类信息写进交付说明：

| 项目 | 示例 |
|------|------|
| 目标系统 | `Ubuntu 22.04 x86_64` |
| ONNX Runtime 包来源 | `onnxruntime-linux-x64-1.17.3.tgz` |
| OpenVINO 包来源 | `l_openvino_toolkit_ubuntu22_2024.6.0..._x86_64.tgz` |
| 运行库落位目录 | `/opt/beacon/runtime-libs/` |
| 是否要求配置 `LD_LIBRARY_PATH` | 是 |
| 是否已随包附带 `Admin/venv/` | 是 / 否 |
| 是否已随包附带模型文件 | 是 / 否 |

机器类型矩阵、后端最低随包清单、`runtime-libs` 目录约定、`LD_LIBRARY_PATH` 规则已集中整理在 [Linux 运行库参考](linux-runtime-libs.md)。

部署开始前，建议明确下面 4 个值：

| 项目 | 示例 |
|------|------|
| 安装目录 | `/opt/beacon` |
| 管理后台地址 | `http://<服务器IP>:9991` |
| OpenAPI Token | 一段随机长字符串 |
| `cluster_id` | `customer-a-edge-001` |

---

## 2. 第一步：准备 Linux 机器

推荐系统：

- Ubuntu 20.04 / 22.04
- Debian 11 / 12
- Rocky Linux 8 / 9

先安装基础依赖：

=== "Ubuntu / Debian"

    ```bash
    sudo apt update
    sudo apt install -y \
      python3 python3-pip python3-venv \
      ffmpeg curl wget unzip
    ```

=== "Rocky / CentOS"

    ```bash
    sudo yum install -y epel-release
    sudo yum install -y \
      python3 python3-pip \
      ffmpeg curl wget unzip
    ```

再创建固定目录：

```bash
sudo mkdir -p /opt/beacon
sudo mkdir -p /opt/beacon/runtime-libs
sudo mkdir -p /opt/beacon/data/models
sudo mkdir -p /opt/beacon/data/upload
sudo mkdir -p /opt/beacon/logs
sudo chown -R "$USER":"$USER" /opt/beacon
```

执行完成后，应满足：

- `/opt/beacon` 已存在
- 当前用户对 `/opt/beacon` 有写权限

可直接验证：

```bash
test -w /opt/beacon && echo "beacon_dir_writable=ok"
```

---

## 3. 第二步：把交付包放到固定目录

### 3.1 交付物为压缩包

```bash
cd /opt/beacon
tar -xzf /path/to/Beacon-linux-x64.tar.gz --strip-components=1
```

### 3.2 交付物为已解压目录

```bash
rsync -av /path/to/Beacon-linux-x64/ /opt/beacon/
```

### 3.3 解压后立刻检查目录

```bash
find /opt/beacon -maxdepth 2 -type f | sort | head -n 50
```

至少应能看到以下关键内容：

- `/opt/beacon/config.json`
- `/opt/beacon/runtime-libs/`，采用“运行库随包交付”方案时
- `/opt/beacon/Admin/manage.py`
- `/opt/beacon/Analyzer/`
- `/opt/beacon/MediaServer/`

推荐直接执行下面的存在性检查：

```bash
test -f /opt/beacon/config.json && echo "config_json=ok"
test -f /opt/beacon/Admin/manage.py && echo "admin_manage=ok"
find /opt/beacon/runtime-libs -maxdepth 1 -type f 2>/dev/null | sort | head
find /opt/beacon/Analyzer -maxdepth 3 -type f | head
find /opt/beacon/MediaServer -maxdepth 5 -type f | head
```

### 3.4 解压后立刻核对运行库目录

Linux 交付包采用“运行库随包交付”时，建议统一放在：

```text
/opt/beacon/runtime-libs/
```

至少先看目录里有没有关键 `.so`：

```bash
find /opt/beacon/runtime-libs -maxdepth 1 -type f | sort
```

按常见后端场景，至少应有下面这些文件中的对应项：

| 场景 | 至少应看到什么 |
|------|----------------|
| ONNX Runtime | `libonnxruntime.so` 或 `libonnxruntime.so.*` |
| OpenVINO | `libopenvino.so` 或 `libopenvino.so.*` |
| TBB | `libtbb.so` 或 `libtbb.so.*` |
| FFmpeg | `libavcodec.so*`、`libavformat.so*`、`libavutil.so*`、`libswscale.so*`、`libswresample.so*` |
| TensorRT Engine | 交付方声明的 TensorRT / CUDA 相关 `.so`，以及插件 `.so` |
| RKNN / Ascend Compat | `libbeacon_compat.so`、真实硬件后端插件 `.so`、厂商 SDK runtime |

如果 `runtime-libs/` 是空目录，或者缺少当前模型场景必须的 `.so`，先不要继续启动。

---

## 4. 第三步：确认 Analyzer 和 MediaServer 可执行文件位置

`Admin/VideoAnalyzer.py` 会按约定路径去找二进制。
Linux 交付包至少应满足下面之一：

### 4.1 Analyzer 推荐位置

- `/opt/beacon/Analyzer/build/Analyzer`
- `/opt/beacon/Analyzer/Analyzer`

### 4.2 MediaServer 推荐位置

- `/opt/beacon/MediaServer/bin/bin.x86.gcc9.4/MediaServer`
- 同目录下存在 `config.ini`

执行检查：

```bash
find /opt/beacon/Analyzer -maxdepth 3 -type f \( -name 'Analyzer' -o -name 'Analyzer.bin' \) -print
find /opt/beacon/MediaServer -maxdepth 5 -type f \( -name 'MediaServer' -o -name 'config.ini' \) -print
```

二进制存在但无法启动时，先看动态库依赖：

```bash
ldd /opt/beacon/Analyzer/build/Analyzer 2>/dev/null || true
ldd /opt/beacon/MediaServer/bin/bin.x86.gcc9.4/MediaServer 2>/dev/null || true
```

`not found` 表示交付包缺少 `.so`，或 `LD_LIBRARY_PATH` 尚未配置。

### 4.3 按机器类型快速核对 `.so` 是否匹配

建议至少执行下面一组检查：

```bash
uname -m
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libonnxruntime.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libopenvino.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libtbb.so*' | head -n 3
```

判断原则：

- `uname -m` 输出 `x86_64` 时，应使用 `x64 / x86_64` 交付包
- `uname -m` 输出 `aarch64` 时，应使用 `aarch64 / arm64` 交付包
- 输出架构和交付说明不一致时，不建议继续往下启动

如果交付方给的是“完整运行时目录”而不是纯 `runtime-libs/`，也至少要确认：

```bash
find /opt/beacon -type f -name 'onnxruntime_cxx_api.h' | head -n 1
find /opt/beacon -type f -path '*/openvino/openvino.hpp' | head -n 1
```

---

## 5. 第四步：准备 Admin 的 Python 运行环境

有些交付包已包含可直接使用的 `venv`；有些只包含 `Admin/` 源码。
标准处理方式如下。

### 5.1 创建虚拟环境

```bash
cd /opt/beacon/Admin
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt
python manage.py migrate --noinput
cd /opt/beacon
```

### 5.2 交付环境无法联网时的处理原则

无法访问 PyPI 时，不应在现场临时解决依赖下载问题。
应由交付方提供以下内容之一：

1. 已构建完成的 `venv/`
2. 离线 wheel 包目录
3. 能直接运行的 PyInstaller / 可执行交付方案

### 5.3 首次管理员账号

交付方已提供管理员账号时，直接使用提供的账号。
未提供时，手动创建：

```bash
cd /opt/beacon/Admin
source venv/bin/activate
python manage.py createsuperuser
cd /opt/beacon
```

执行完成后，应满足：

- `Admin/venv/` 已存在
- `python manage.py migrate --noinput` 无报错
- 存在可登录后台的管理员账号

---

## 6. 第五步：修改 `config.json`

先备份：

```bash
cd /opt/beacon
cp config.json "config.json.bak.$(date +%Y%m%d%H%M%S)"
```

再编辑：

```bash
vi /opt/beacon/config.json
```

至少检查这些字段：

```json
{
  "host": "0.0.0.0",
  "adminPort": 9991,
  "mediaHttpPort": 9992,
  "analyzerPort": 9993,
  "mediaRtspPort": 9994,
  "mediaRtmpPort": 9995,
  "mediaSecret": "CHANGE_ME_LONG_RANDOM_SECRET",
  "openApiToken": "CHANGE_ME_LONG_RANDOM_TOKEN",
  "uploadDir": "data/upload",
  "modelDir": "data/models",
  "licenseType": "pool"
}
```

重点说明：

- `mediaSecret`：必须与 MediaServer 的 `config.ini` 中 API `secret` 完全一致
- `openApiToken`：OpenAPI、诊断接口、运维验收会使用
- `uploadDir`：截图和告警视频落盘目录
- `modelDir`：模型目录
- `licenseType`：正式交付推荐 `pool`

`uploadDir` 和 `modelDir` 推荐保持为：

- `data/upload`
- `data/models`

这样部署目录更稳定，迁移机器时不必反复改路径。

---

## 7. 第六步：对齐 MediaServer 的 `config.ini`

打开实际运行目录下的 `config.ini`：

```bash
vi /opt/beacon/MediaServer/bin/bin.x86.gcc9.4/config.ini
```

至少确认以下内容与 `config.json` 对齐：

- `[api] secret`
- `[http] port`
- `[rtsp] port`
- `[rtmp] port`

建议直接检查：

```bash
grep -nE '^\[api\]|^\[http\]|^\[rtsp\]|^\[rtmp\]|^secret=|^port=' \
  /opt/beacon/MediaServer/bin/bin.x86.gcc9.4/config.ini
```

对齐原则如下：

| 配置项 | 应与谁一致 |
|--------|------------|
| MediaServer `[api] secret` | `config.json.mediaSecret` |
| MediaServer `[http] port` | `config.json.mediaHttpPort` |
| MediaServer `[rtsp] port` | `config.json.mediaRtspPort` |
| MediaServer `[rtmp] port` | `config.json.mediaRtmpPort` |

`mediaSecret` 不一致时，常见表现是：

- 登录页面正常
- 视频流、播放器、拉流代理、截图等媒体相关功能失败

---

## 8. 第七步：把模型文件放到模型目录

模型文件统一放到：

```text
/opt/beacon/data/models/
```

建议执行：

```bash
find /opt/beacon/data/models -maxdepth 2 -type f | sort
```

该目录为空时，系统可能可以启动，但布控运行时无法正常推理。

### 8.1 先明确：C++ 侧参数写在 `config.json` 顶层

当前实现里，下面这些 Analyzer C++ 运行时字段都直接写在 `config.json` 顶层，不写在 `"Analyzer": {}` 节点下：

- `modelDir`
- `modelConcurrency`
- `tensorrtEnginePluginPath`
- `compatLibPath`
- `rknpuPreprocessMode`
- `hardwareDecoderType`
- `hardwareEncoderType`
- `forceHardwareCodec`
- `hardwareCodecDeviceId`
- `maxHardwareDecodeChannels`
- `maxHardwareEncodeChannels`
- `ffmpegDecodeThreadCount`
- `ffmpegEncodeThreadCount`

部署时先把“模型后缀对应什么后端”看清楚，再决定要不要随包附带对应运行库。

### 8.2 推理后端 / 运行库 / 参数对照表

| 后端场景 | 模型文件 | 还要随包携带什么 | `config.json` 关键项 | 环境变量 | 什么时候必须配置 | 常见失败表现 |
|----------|----------|------------------|----------------------|----------|------------------|--------------|
| ONNX Runtime | `.onnx` | `onnxruntime` 运行库（交付包未内置时） | `modelDir`、`modelConcurrency` | `BEACON_ONNXRUNTIME_DIR` | 使用 ONNX 模型，且运行库不在系统默认搜索路径时 | `libonnxruntime.so` 缺失，或日志显示 provider 降级到 CPU |
| TensorRT Engine | `.engine` / `.plan` | TensorRT runtime、CUDA 相关库、Engine 插件动态库 | `tensorrtEnginePluginPath`、`modelDir`、`modelConcurrency` | 主要看 `LD_LIBRARY_PATH` | 使用 NVIDIA Engine 模型时必须配 | 启动时报 `TensorRT engine model requires 'tensorrtEnginePluginPath'`，或 engine 与 GPU / TensorRT 版本不匹配 |
| OpenVINO | `.xml` + `.bin` | `.xml` 和同目录 `.bin`、OpenVINO runtime | `modelDir`、`modelConcurrency` | `BEACON_OPENVINO_RUNTIME_DIR` | 使用 OpenVINO IR 模型时 | `.bin` 缺失、OpenVINO runtime 未找到、设备查询失败 |
| RKNN Compat | `.rknn` | `libbeacon_compat.so`、实现 `BeaconGetAlgorithmPluginV3` 的 RKNN 后端插件、RKNN SDK runtime | `compatLibPath`、`rknpuPreprocessMode`、`modelDir` | `BEACON_COMPAT_LIB_PATH`、`BEACON_COMPAT_BACKEND_PATH`、`BEACON_RKNPU_PREPROCESS_MODE` | 使用 RK3568 / RK3576 / RK3588 等 NPU 时 | 日志出现 `using stub backend`、后端缺少 `BeaconGetAlgorithmPluginV3` 符号、模型无法真正跑在 NPU 上 |
| Ascend Compat | `.om` | `libbeacon_compat.so`、实现 `BeaconGetAlgorithmPluginV3` 的 Ascend 后端插件、Ascend runtime / CANN 依赖 | `compatLibPath`、`modelDir` | `BEACON_COMPAT_LIB_PATH`、`BEACON_COMPAT_BACKEND_PATH` | 使用 Ascend `.om` 模型时 | 日志出现 `using stub backend`、后端动态库加载失败、推理未真正落到昇腾设备 |

说明：

- `tensorrtEnginePluginPath` 指向的是“负责加载 `.engine/.plan` 的 Beacon 插件动态库”，不是 TensorRT 安装目录。
- `compatLibPath` 通常指向 `libbeacon_compat.so`，它只是兼容层入口，不等于 RKNN 或 Ascend 厂商 SDK 本体。
- `BEACON_COMPAT_BACKEND_PATH` 指向的是“实现了 `BeaconGetAlgorithmPluginV3` 接口的硬件后端插件”，不能直接填一个普通厂商基础运行库。
- 按仓库当前实现，`VideoAnalyzer.py` 在 `third_party/localdeps/` 目录结构存在时，会自动补 `BEACON_ONNXRUNTIME_DIR` 和 `BEACON_OPENVINO_RUNTIME_DIR`。

### 8.3 RKNN 预处理参数说明

`rknpuPreprocessMode` 只对 `.rknn` 兼容后端有意义，当前代码里的取值范围是 `0` 到 `3`：

| 值 | 当前实现名 | 说明 |
|----|------------|------|
| `0` | `disabled` | 不额外声明 RK NPU 预处理模式 |
| `1` | `adaptive` | 适合需要保比例适配的场景 |
| `2` | `stretch` | 直接拉伸到输入尺寸 |
| `3` | `rga_stretch` | 需要后端支持 RGA 拉伸路径 |

现场无法确认时，先用 `1`，确认画面比例与精度后再微调。

### 8.4 硬件编解码参数对照

`hardwareDecoderType` 和 `hardwareEncoderType` 也是 C++ 侧常用字段，含义如下：

| 值 | 用在哪个字段 | 适用平台 | 说明 |
|----|--------------|----------|------|
| `auto` | 解码 / 编码 | 通用 | 让系统自动选择可用实现，交付初次验收可先用这个 |
| `nvdec` | 仅 `hardwareDecoderType` | NVIDIA | FFmpeg 走 NVIDIA 硬解 |
| `nvenc` | 仅 `hardwareEncoderType` | NVIDIA | 告警视频、转码等走 NVIDIA 硬编 |
| `qsv` | 解码 / 编码 | Intel | Intel Quick Sync 路径 |
| `vaapi` | 解码 / 编码 | Linux | Linux 下常见的 `/dev/dri` 路径 |
| `videotoolbox` | 解码 / 编码 | macOS | Apple 平台使用，Linux 不应配置成这个值 |
| `none` | 解码 / 编码 | 通用 | 强制关闭硬编解码，只走软件编解码 |

Linux 现场最常见的组合如下：

- NVIDIA：`hardwareDecoderType=nvdec`，`hardwareEncoderType=nvenc`
- Intel：优先尝试 `qsv`，设备驱动路径按现场环境再决定是否改 `vaapi`
- 无可用 GPU 或排障阶段：`hardwareDecoderType=none`，`hardwareEncoderType=none`

### 8.5 C++ 侧参数全集示意

下面是“当前实现里可能用到的 C++ 侧参数全集示意”，不是要求同时全部启用：

```jsonc
{
  // 模型公共参数
  "modelDir": "data/models",
  "modelConcurrency": 2,

  // TensorRT Engine 专用
  "tensorrtEnginePluginPath": "Analyzer/plugins/libtrt_helper.so",

  // RKNN / Ascend Compat 专用
  "compatLibPath": "Analyzer/compat/libbeacon_compat.so",
  "rknpuPreprocessMode": 1,

  // 硬件编解码
  "hardwareDecoderType": "nvdec",
  "hardwareEncoderType": "nvenc",
  "forceHardwareCodec": false,
  "hardwareCodecDeviceId": 0,
  "maxHardwareDecodeChannels": 16,
  "maxHardwareEncodeChannels": 8,
  "ffmpegDecodeThreadCount": 1,
  "ffmpegEncodeThreadCount": 1
}
```

---

## 9. 第八步：写环境变量文件

正式部署不建议只在当前 shell 手工 `export`。
建议先写成固定文件：

```bash
cat >/opt/beacon/beacon.env <<'EOF'
BEACON_ROOT_DIR=/opt/beacon
BEACON_OPEN_API_TOKEN=change-me-long-random-token
BEACON_LICENSE_TYPE=pool
BEACON_CLUSTER_ID=customer-a-edge-001
BEACON_LICENSE_PUBLIC_KEY_B64=your-ed25519-public-key-base64
BEACON_UPLOAD_DIR=/opt/beacon/data/upload
BEACON_MODEL_DIR=/opt/beacon/data/models
LD_LIBRARY_PATH=/opt/beacon/runtime-libs
EOF
```

采用“完整运行时目录随包交付”时，再按需额外补：

```text
BEACON_ONNXRUNTIME_DIR=/opt/beacon/onnxruntime
BEACON_OPENVINO_RUNTIME_DIR=/opt/beacon/openvino/runtime
```

但对正式交付而言，更推荐优先保证 `/opt/beacon/runtime-libs/` 能覆盖运行期 `.so` 搜索，而不是要求现场再自己拼装一套开发目录。

先在当前终端加载一次：

```bash
set -a
source /opt/beacon/beacon.env
set +a
```

再检查关键变量：

```bash
printf 'BEACON_ROOT_DIR=%s\n' "$BEACON_ROOT_DIR"
printf 'BEACON_LICENSE_TYPE=%s\n' "$BEACON_LICENSE_TYPE"
printf 'BEACON_CLUSTER_ID=%s\n' "$BEACON_CLUSTER_ID"
printf 'BEACON_UPLOAD_DIR=%s\n' "$BEACON_UPLOAD_DIR"
printf 'BEACON_MODEL_DIR=%s\n' "$BEACON_MODEL_DIR"
printf 'LD_LIBRARY_PATH=%s\n' "$LD_LIBRARY_PATH"
```

---

## 10. 第九步：先手动启动一次

在配置 systemd 前，应先手动启动，确认三件套本身可运行。

```bash
cd /opt/beacon
set -a
source /opt/beacon/beacon.env
set +a
source /opt/beacon/Admin/venv/bin/activate
python /opt/beacon/Admin/VideoAnalyzer.py
```

这条命令会尝试拉起：

- `Admin`
- `MediaServer`
- `Analyzer`

手动启动阶段的目标不是“长期运行”，而是确认：

1. 进程能起来
2. 端口能监听
3. 健康检查能通过

另开一个终端执行：

```bash
ss -lntp | grep -E ':(9991|9992|9993|9994|9995)\b' || true
```

正常情况下，至少应看到：

- `9991`：Admin
- `9992`：MediaServer HTTP
- `9993`：Analyzer

---

## 11. 第十步：验收服务是否真的可用

不要只看“命令没退出”或“日志没报错”。
必须实际验收。

### 11.1 Admin 登录页

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9991/login
```

期望：返回 `200`

### 11.2 MediaServer API

```bash
python3 - <<'PY'
import json
cfg = json.load(open('/opt/beacon/config.json', 'r', encoding='utf-8'))
print(cfg.get('mediaSecret') or '')
PY
```

将输出的 `mediaSecret` 带入下面命令：

```bash
curl -sS "http://127.0.0.1:9992/index/api/getServerConfig?secret=<mediaSecret>" | head
```

期望：返回 JSON，通常包含 `code`

### 11.3 Analyzer 健康检查

```bash
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9993/api/health
```

期望：返回 `{"code":1000,...}`

### 11.4 Admin 侧授权状态

```bash
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/usage
```

期望：

- 已导入授权时，可看到当前授权状态
- 尚未导入授权时，通常会看到 `license_not_installed` 或类似错误信息

---

## 12. 第十一步：导入授权文件

浏览器打开：

```text
http://<服务器IP>:9991/login
```

登录管理员账号后，进入：

```text
/license/manager
```

操作步骤：

1. 上传交付方提供的 `license.json`
2. 页面显示“导入成功”
3. 失败时查看页面上的错误信息

最常见错误如下：

| 错误码 | 说明 |
|--------|------|
| `missing_public_key` | 没有配置 `BEACON_LICENSE_PUBLIC_KEY_B64` |
| `cluster_mismatch` | `license.json.cluster_id` 与 `BEACON_CLUSTER_ID` 不一致 |
| `license_expired` | 授权已过期 |

导入后重新执行：

```bash
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/info
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/usage
```

---

## 13. 第十二步：完成最小业务验收

服务启动并完成授权导入后，建议继续完成最小业务闭环：

1. 登录后台
2. 添加第一条 RTSP 或文件流
3. 确认视频流在线并可预览
4. 新建一个布控任务
5. 触发告警并检查截图 / 告警列表

完整操作步骤参见：

- [第一条视频流接入实战](../getting-started/first-stream.md)
- [视频流管理](../guide/streams.md)
- [布控管理](../guide/controls.md)

仅完成服务启动而未完成这一步时，只能证明“部署起来了”，不能证明“业务能用”。

---

## 14. 第十三步：配置 systemd 长期运行

手动启动验收通过后，再配置 systemd。

### 14.1 写服务文件

```bash
sudo tee /etc/systemd/system/beacon.service >/dev/null <<'EOF'
[Unit]
Description=Beacon Edge Stack
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/beacon
EnvironmentFile=/opt/beacon/beacon.env
ExecStart=/opt/beacon/Admin/venv/bin/python /opt/beacon/Admin/VideoAnalyzer.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### 14.2 启用与启动

```bash
sudo systemctl daemon-reload
grep -n 'LD_LIBRARY_PATH' /opt/beacon/beacon.env
systemctl show beacon --property=Environment | tr ' ' '\n' | grep LD_LIBRARY_PATH || true
sudo systemctl enable beacon
sudo systemctl start beacon
sudo systemctl status beacon --no-pager
```

### 14.3 常用运维命令

```bash
sudo systemctl restart beacon
sudo systemctl stop beacon
sudo journalctl -u beacon -f
```

---

## 15. 常见问题

| 现象 | 先看什么 |
|------|----------|
| 登录页打不开 | 看 `9991` 是否监听，再看 `journalctl -u beacon -f` |
| `VideoAnalyzer.py` 启动时报找不到二进制 | 看 `Analyzer` 和 `MediaServer` 是否放在约定路径 |
| Analyzer / MediaServer 启动时报 `.so` 缺失 | 对对应可执行文件执行 `ldd` |
| 媒体相关功能失败 | 看 `mediaSecret` 是否与 `config.ini` 一致 |
| `Analyzer` 健康检查 401 | 请求头中是否带了 `X-Beacon-Token` |
| 授权导入失败 | 看 `/license/manager` 的错误码和 `cluster_id` / 公钥配置 |
| 布控启动时报 `license_invalid` | 看授权是否已导入、`licenseType` 是否正确 |
| 视频流在线但没有告警 | 看模型目录、布控状态、检测目标是否实际出现 |

---

## 下一步文档

- Linux 源码联调：参见 [local-linux.md](local-linux.md)
- 构建交付包：参见 [build-and-package-linux.md](build-and-package-linux.md)
- 交付目录规范：参见 [../deploy/delivery-layout.md](../deploy/delivery-layout.md)
- 服务托管说明：参见 [../deploy/service-management.md](../deploy/service-management.md)
- 完整业务验收：参见 [../deploy/e2e-acceptance.md](../deploy/e2e-acceptance.md)
