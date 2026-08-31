# Beacon 版本更新日志

本页只记录公开发布版本。当前版本以仓库根目录的 `PROJECT_VERSION` 和
[GitHub Releases](https://github.com/skygazer42/Beacon/releases) 为准。

## [1.0.1-rc.1] - 2026-08-31

这是 `v1.0.1` 的候选预发布版本，重点收紧生产安全默认值并验证兼容范围内的依赖升级。

### 安全与部署

- Admin 在 `DEBUG=0` 时默认启用 HTTPS 跳转、安全 Cookie 和一年 HSTS，并要求显式信任代理协议头；配置缺失或回退到不安全值时拒绝启动。
- 为仅绑定回环地址的本地 POC 保留显式 `BEACON_DJANGO_ALLOW_INSECURE_HTTP=1` 逃生开关，生产模板默认关闭。
- 更新环境变量、安全运维说明和回归测试，覆盖生产默认值、不安全配置拒绝以及 POC 例外路径。

### 依赖与可观测性

- 在 Python 3.10–3.12、Django 5.2 和 NumPy 1.x 兼容边界内更新 Admin、前端、文档和发布 Action 依赖。
- 更新 OpenTelemetry Collector、Jaeger、Tempo 和 Grafana；迁移 Tempo 3 配置，并为非 root Tempo 容器增加最小权限的数据卷初始化步骤。
- Dependabot 默认只分组次版本和补丁版本；不再把运行时、框架和前端主版本混入同一个自动更新 PR。

### 发布边界

- 本版本是候选预发布，不替代 `v1.0.0` 的稳定版本地位。
- 正式 `v1.0.1` 仍需通过受保护分支、发布环境审批以及生产级 L2 验收证据门禁。

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
