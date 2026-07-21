---
title: 环境与依赖
description: 按目标组件准备可验证的运行环境
icon: material/clipboard-check
---

# 环境与依赖

Beacon 没有一个适用于所有模型和硬件的“最低生产配置”。先确定要运行 Admin、Cloud POC，还是完整 Edge，再准备对应依赖。

## 已验证与参考范围

| 组件 | 仓库自动验证 | 其他参考路径 |
|---|---|---|
| Admin | Ubuntu 24.04，Python 3.10 / 3.12 | Python 3.11、Windows 依赖文件 |
| React | Node.js 22 | `package.json` 允许 Node `^20.19` 或 `>=22.12` |
| Analyzer 核心测试 | Ubuntu 24.04、Clang/CMake/OpenCV | 完整引擎需 FFmpeg、libevent、curl、jsoncpp、ONNX Runtime、OpenVINO 等原生库 |
| MediaServer | Ubuntu 24.04、CMake/Ninja，裁剪的 CI 构建选项 | 完整 WebRTC/SRT/播放器能力需额外依赖 |
| Cloud POC | Docker Compose 配置和非 root 镜像构建 | Helm chart 语法与单副本配置 |

Windows、其他 Linux 发行版、ARM、GPU/NPU 和完整媒体特性需要在目标环境单独验收；文档路径不等于 CI 支持矩阵。

## 算力和容量

- CPU 可以做功能验证，但不能承诺固定视频路数。
- GPU/NPU 需要匹配的驱动、推理运行时、插件和模型格式。
- 容量同时受模型、输入分辨率/帧率、抽帧、解码、录像、回推和告警媒体影响。
- 磁盘按真实截图/视频平均大小、每日数量、留存天数、备份和高水位余量计算。

生产选型见 [性能调优](../operations/performance.md)。

## 默认端口

| 端口 | 组件 | 用途 |
|---:|---|---|
| 9991/TCP | Admin | 页面、Admin/OpenAPI/Ops |
| 9992/TCP | MediaServer | HTTP API 与 HTTP 播放 |
| 9993/TCP | Analyzer | Analyzer HTTP API |
| 9994/TCP/UDP | MediaServer | RTSP |
| 9995/TCP | MediaServer | RTMP |

这些值由根目录 `config.json` 协调。WebRTC/RTP 等附加端口由 MediaServer 构建和运行配置决定，必须查看最终生成的 MediaServer 配置，而不是照抄上表。

摄像头地址中的 `:554` 是常见设备 RTSP 端口；它不表示 Beacon 默认监听 `554`。

```bash
ss -tlnp | grep -E '9991|9992|9993|9994|9995'
```

生产通常只向用户网络暴露 TLS 反向代理；Admin、Analyzer、MediaServer、数据库和对象存储放在受限内网。具体策略见 [端口与防火墙](../deploy/ports-and-firewall.md)。

## 组件依赖入口

- Admin：`Admin/requirements-linux.txt`、`requirements-windows.txt`；LDAP/对象存储等可选能力使用 `requirements-optional.txt`。
- React：`Admin/frontend/package-lock.json`，使用 `npm ci`。
- Analyzer：以 `Analyzer/CMakeLists.txt` 和 [Linux 运行库](../deployment/linux-runtime-libs.md) 为准。
- MediaServer：以 `MediaServer/source/CMakeLists.txt`、构建开关和上游说明为准。
- 文档：`docs/requirements.txt`。

仓库不分发模型权重、CUDA/TensorRT/OpenVINO 厂商安装包或 NPU SDK。

## 安装前最小检查

```bash
python3 --version
cmake --version
ffmpeg -version | head -1
df -h .
```

只开发 Admin 时无需先安装完整 C++/GPU 依赖。要运行真实 Edge，继续阅读 [安装指南](installation.md) 和 [Edge 全栈](../deploy/edge-full-stack.md)。
