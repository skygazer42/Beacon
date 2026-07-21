---
title: Linux 运行库参考
icon: material/library-shelves
---

# Linux 运行库参考

本文集中说明 Linux 交付和部署里最容易反复出现的几件事：

1. 目标机器属于哪一类
2. 应拿哪套 ONNX Runtime / OpenVINO / TBB 运行库
3. 运行库建议放到哪里
4. `LD_LIBRARY_PATH` 应如何配置
5. 现场应执行哪些核对命令

本页不替代完整部署步骤。
完整流程请参见：

- [Linux 本机开发](local-linux.md)
- [Linux 构建与打包](build-and-package-linux.md)
- [Linux 用户部署](linux.md)

---

## 1. 先判断机器类型

部署前先确认当前 Linux 机器的系统和架构：

```bash
uname -m
cat /etc/os-release
```

最常见的三类机器如下：

| 机器类型 | `uname -m` 典型输出 | 运行库选择重点 |
|----------|---------------------|----------------|
| Ubuntu 20.04 x86_64 | `x86_64` | ONNX Runtime 选 `x64`，OpenVINO 选 `ubuntu20 x86_64` |
| Ubuntu 22.04 x86_64 | `x86_64` | ONNX Runtime 选 `x64`，OpenVINO 选 `ubuntu22 x86_64` |
| Ubuntu 20 arm64 / aarch64 | `aarch64` | ONNX Runtime 选 `aarch64`，OpenVINO 选 `ubuntu20 arm64` |

只要机器类型和交付说明对不上，就不要继续部署。
典型错误包括：

- `aarch64` 机器拿到 `x64` 运行库
- Ubuntu 22 机器拿到只验证过 Ubuntu 20 的 OpenVINO 运行时
- 只拿到模型文件，没拿到实际后端 `.so`

---

## 2. 运行库来源矩阵

| 组件 | 推荐来源 | 典型包名模式 | 说明 |
|------|----------|--------------|------|
| ONNX Runtime | 官方 GitHub Releases | `onnxruntime-linux-x64-<version>.tgz` / `onnxruntime-linux-aarch64-<version>.tgz` | 这里关注的是 C/C++ 运行时，不是 Python wheel |
| OpenVINO | 官方 Linux archive 包 | `l_openvino_toolkit_ubuntu20_<version>_x86_64.tgz` / `l_openvino_toolkit_ubuntu22_<version>_x86_64.tgz` / `l_openvino_toolkit_ubuntu20_<version>_arm64.tgz` | 当前项目更推荐 archive 包，而不是先 `apt install` 再整理路径 |
| TBB | OpenVINO archive 包自带 | `runtime/3rdparty/tbb/` | 当前项目通常不需要单独下载 TBB |

当前项目里，最稳定的交付策略是：

1. 使用官方预编译运行时包
2. 把运行期 `.so` 收集到统一目录
3. 用 `LD_LIBRARY_PATH` 暴露给 `Analyzer` 和 `MediaServer`

---

## 3. 建议交付目录

Linux 正式交付建议把运行库集中到：

```text
/opt/beacon/runtime-libs/
```

推荐目录示意：

```text
/opt/beacon/
  config.json
  runtime-libs/
    libonnxruntime.so*
    libopenvino.so*
    libtbb.so*
    libavcodec.so*
    libavformat.so*
    libavutil.so*
    libswscale.so*
    libswresample.so*
  Admin/
  Analyzer/
    build/
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
  data/
    models/
    upload/
  logs/
```

补充说明：

- `runtime-libs/` 主要解决运行期动态库搜索
- `Analyzer/compat/` 主要放兼容层入口和硬件兼容后端插件
- `Analyzer/plugins/` 主要放 TensorRT Engine 插件等额外插件

---

## 4. 按后端场景的最低随包清单

| 后端场景 | 模型文件 | 最低随包要求 |
|----------|----------|--------------|
| ONNX Runtime | `.onnx` | `libonnxruntime.so*` |
| OpenVINO | `.xml` + `.bin` | `libopenvino.so*`、对应 CPU / GPU plugin `.so`、`libtbb.so*` |
| TensorRT Engine | `.engine` / `.plan` | TensorRT / CUDA 相关 `.so`、Engine 插件 `.so` |
| RKNN Compat | `.rknn` | `libbeacon_compat.so`、RKNN 后端插件 `.so`、RKNN SDK runtime |
| Ascend Compat | `.om` | `libbeacon_compat.so`、Ascend 后端插件 `.so`、CANN / Ascend runtime |
| FFmpeg 视频链路 | 任意视频场景 | `libavcodec.so*`、`libavformat.so*`、`libavutil.so*`、`libswscale.so*`、`libswresample.so*` |

注意：

- `libbeacon_compat.so` 只是 Beacon 兼容层入口，不等于 RKNN / Ascend 厂商 SDK 本体
- `BEACON_COMPAT_BACKEND_PATH` 指向的才是真正实现 `BeaconGetAlgorithmPluginV3` 的硬件后端插件
- `tensorrtEnginePluginPath` 指向的是 Beacon 插件动态库，不是 TensorRT 安装目录

---

## 5. 环境变量约定

Linux 交付建议把关键环境变量写进：

```text
/opt/beacon/beacon.env
```

最低建议内容：

```bash
BEACON_ROOT_DIR=/opt/beacon
BEACON_UPLOAD_DIR=/opt/beacon/data/upload
BEACON_MODEL_DIR=/opt/beacon/data/models
BEACON_OPEN_API_TOKEN=change-me-long-random-token
LD_LIBRARY_PATH=/opt/beacon/runtime-libs:${LD_LIBRARY_PATH}
```

如果交付采用“完整运行时目录随包附带”，再按需增加：

```bash
BEACON_ONNXRUNTIME_DIR=/opt/beacon/onnxruntime
BEACON_OPENVINO_RUNTIME_DIR=/opt/beacon/openvino/runtime
```

当前项目正式交付更推荐优先保证 `runtime-libs/` 可直接满足运行期搜索，而不是要求现场再自己拼装开发目录。

---

## 6. 快速核对命令

### 6.1 看运行库目录是否齐全

```bash
find /opt/beacon/runtime-libs -maxdepth 1 -type f | sort
```

### 6.2 看关键 `.so` 是否存在

```bash
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libonnxruntime.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libopenvino.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libtbb.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libavcodec.so*' | head -n 3
```

### 6.3 看 systemd 是否真的拿到了 `LD_LIBRARY_PATH`

```bash
grep -n 'LD_LIBRARY_PATH' /opt/beacon/beacon.env
systemctl show beacon --property=Environment | tr ' ' '\n' | grep LD_LIBRARY_PATH || true
```

### 6.4 看二进制是否还缺库

```bash
ldd /opt/beacon/Analyzer/build/Analyzer 2>/dev/null || true
ldd /opt/beacon/MediaServer/bin/bin.x86.gcc9.4/MediaServer 2>/dev/null || true
```

如果输出里出现 `not found`，优先检查：

1. `runtime-libs/` 是否缺文件
2. `LD_LIBRARY_PATH` 是否没注入
3. 交付包架构是否和机器类型不匹配

---

## 7. 常见报错对照

| 报错表现 | 先怀疑什么 | 先查什么 |
|----------|------------|----------|
| `libonnxruntime.so: cannot open shared object file` | ONNX Runtime 没跟包或 `LD_LIBRARY_PATH` 不可见 | `find runtime-libs -name 'libonnxruntime.so*'`、`ldd Analyzer` |
| `libopenvino.so: cannot open shared object file` | OpenVINO runtime 不可见 | `find runtime-libs -name 'libopenvino.so*'`、`ldd Analyzer` |
| `libtbb.so: cannot open shared object file` | TBB 没跟包 | `find runtime-libs -name 'libtbb.so*'` |
| `libavcodec.so...` 缺失 | FFmpeg 运行库没带上 | `find runtime-libs -name 'libavcodec.so*'` |
| `using stub backend` | 兼容层只带了入口，没带真实后端插件 | `compatLibPath`、`BEACON_COMPAT_BACKEND_PATH` |
| `TensorRT engine model requires 'tensorrtEnginePluginPath'` | 缺 Engine 插件库 | `tensorrtEnginePluginPath` 指向的文件 |

---

## 8. 相关文档

- Linux 本机开发：参见 [local-linux.md](local-linux.md)
- Linux 构建与打包：参见 [build-and-package-linux.md](build-and-package-linux.md)
- Linux 用户部署：参见 [linux.md](linux.md)
- 交付目录规范：参见 [../deploy/delivery-layout.md](../deploy/delivery-layout.md)
- 服务托管说明：参见 [../deploy/service-management.md](../deploy/service-management.md)
