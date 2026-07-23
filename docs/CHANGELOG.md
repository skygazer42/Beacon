# Beacon 版本更新日志

本页只记录公开发布版本。当前版本以仓库根目录的 `PROJECT_VERSION` 和
[GitHub Releases](https://github.com/skygazer42/Beacon/releases) 为准。

## [1.0.0] - 2026-07-23

Beacon 的首个公开版本，统一 Admin、前端、Analyzer、部署资源和文档版本号为
`v1.0.0`。

### 已包含

- Django 5.2 与 React 管理端：视频流、算法、布控、告警、权限和运维入口。
- C++17 Analyzer：ONNX Runtime、OpenVINO 及算法插件接入路径。
- ZLMediaKit 体系的 MediaServer：视频接入、播放、录像与协议分发。
- Edge 与 Beacon Cloud 的节点注册、告警上报和远程资源管理能力。
- Python、JavaScript 和 Go SDK，以及 OpenAPI、Webhook 集成文档。
- Docker Compose、Helm、Linux 和 Windows 部署说明。
- 后端、前端、Analyzer、SDK、文档与安全扫描的 CI 校验。

### 发布边界

- 仓库不分发模型权重、客户数据、录像、厂商 SDK 或商业授权运行时。
- Cloud POC 用于验证云端流程，不包含真实 MediaServer 和 Analyzer 推理链路。
- GPU、TensorRT 和 NPU 能力需要部署者提供匹配的硬件、驱动、运行时或插件。

公开版本从 `v1.0.0` 开始；此前内部迭代编号不再作为公开 Git 标签或兼容性承诺。
