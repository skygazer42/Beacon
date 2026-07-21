# 常见问题

## 项目与许可

??? question "Beacon 由哪些组件组成？"

    - **Admin**：Django 5.2 + React 管理端，负责配置、编排、告警和外部接口。
    - **Analyzer**：C++17 分析进程，负责解码、推理、追踪和告警生成。
    - **MediaServer**：基于 ZLMediaKit 的媒体接入、分发、播放和录像服务。

    三者是可分别启动但共享配置和文件目录的进程，不是可任意横向扩容的无状态微服务。

??? question "整个仓库都只有 MIT 许可证吗？"

    Beacon 自研代码使用根目录 MIT 许可证；`MediaServer/source/`、前端依赖及其他引入代码继续适用各自的上游许可证和附加条款。分发前必须同时阅读 `THIRD_PARTY_NOTICES.md`、`MediaServer/UPSTREAM.md` 和各源码目录中的许可证。

??? question "仓库是否包含可直接演示的模型？"

    不包含。模型权重、TensorRT Engine、厂商 SDK 和需要单独授权的运行时必须由部署者合法取得。页面中的算法定义或设备后缀不等于模型已经可用。

## 部署与算力

??? question "必须安装 GPU 吗？"

    不必须。ONNX Runtime CPU 可以用于功能验证，但任何“能跑几路”的结论都必须用目标模型、视频分辨率、抽帧、编码和真实硬件压测。不能用固定的 1–3 路承诺替代容量测试。

??? question "GPU、OpenVINO 和 NPU 是开箱即用吗？"

    不是。NVIDIA 加速依赖版本匹配的 ONNX Runtime Provider、CUDA/TensorRT；OpenVINO 依赖对应平台运行时；RKNN、Ascend 等 NPU 依赖 Compat Plugin 和厂商 SDK。以 Analyzer 启动日志和实际推理测试为准。

??? question "支持哪些操作系统？"

    仓库提供 Linux、Windows、本地 Cloud POC 和 Kubernetes 参考路径，但支持范围取决于原生依赖与硬件运行时。先按 [部署总览](deployment/index.md) 选择与交付物匹配的路线，不把文档示例当作所有发行版的兼容承诺。

??? question "Docker Compose 或 Helm 会启动完整视频分析链路吗？"

    `deploy/cloud-saas-v1/` 默认启动的是 Admin + PostgreSQL + MinIO，用来验证 Cloud 登录、边缘接入和告警聚合；不包含真实 Analyzer、MediaServer、模型或 GPU/NPU 运行时。当前 Helm 参考是单副本 Cloud 部署。

## 视频与算法

??? question "拉流、推流和播放协议怎么区分？"

    RTSP/RTMP 地址可作为摄像头、NVR 或主动推流端的来源；MediaServer 再按配置提供 RTSP、RTMP、HLS、HTTP-FLV 或 WebRTC 等播放/分发形式。不是每个播放协议都能直接作为 Analyzer 输入。接入步骤见 [视频流管理](guide/streams.md)。

??? question "GB28181 和 ONVIF 是否自动可用？"

    ONVIF 用于发现和读取设备信息，最终仍需得到可访问的媒体地址。GB28181 通过已配置的 Provider 适配，仓库不自带完整 SIP 平台。两者都需要在目标网络和设备上联调。

??? question "上传 ONNX 后是否立即可检测？"

    上传只完成模型文件和算法定义的一部分。还需确认模型输入输出布局、类别、前后处理、阈值、模型路径和运行 Provider 与 Analyzer 实现匹配，并完成单图测试后再创建布控。

??? question "可以接入自定义算法吗？"

    可以使用 Analyzer 已支持的模型路径、外部 HTTP 推理算法，或 `examples/algorithm_plugin_cpp/` 展示的 C ABI 插件接口。插件 ABI、依赖和许可证需要由集成方自行验证。

??? question "为什么配置了算法却没有告警？"

    依次确认：视频流能实际解码、Analyzer 可达、模型测试通过、布控处于运行状态、当前时间命中计划、ROI/类别/阈值正确，并查看分析日志。仅看到数据库中存在算法或布控记录不能证明推理链路已启动。

## API 与告警

??? question "Beacon 是否提供完整 REST v1 或 Swagger？"

    当前没有统一的 `/api/v1/resources` 或自动生成 Swagger。外部稳定面是既有 `/open/*`、`/stream/open*`、`/control/open*`、Cloud 和 Ops 路径；React 使用的 `/api/app-shell/*` 是内部 UI 契约。使用 [API 概览](api/index.md) 和仓库内 SDK，不要根据资源名猜 URL。

??? question "有哪些鉴权方式？"

    浏览器页面使用 Django Session + CSRF；机器 OpenAPI 使用共享 Token 或带 `openapi`/`ops` scope 的 API Key；Cloud Edge 和数字人运行时各有独立协议。仓库不存在一个能访问全部 Admin API 的通用 JWT。

??? question "如何接收告警？"

    外部系统使用 Webhook 或 Beacon Cloud；两者可通过数据库 Outbox 做至少一次投递，接收方必须按 `event_id` 幂等。`/ws/alarm/poll` 只用于已登录管理端的增量显示，不接受 API Key/JWT，React 告警页当前仍以 HTTP 轮询为主。

## 运维

??? question "如何判断服务可用？"

    Admin 使用受保护的 `/healthz`、`/readyz` 和 `/metrics`；MediaServer 与 Analyzer 需分别探测。正式验收还应跑通一次真实的“拉流 → 布控 → 告警 → 外部投递”链路。

??? question "日志在哪里？"

    路径取决于工作目录和启动方式，不保证固定文件名。生产建议由 systemd、容器运行时或进程管理器收集标准输出并做轮转；排障时同时检查 Admin、Analyzer、MediaServer 和反向代理日志。

??? question "可以直接增加 Gunicorn worker 或 Kubernetes 副本吗？"

    当前不可以直接这样扩容。Admin 的计划、清理和 Outbox 等后台任务在 Django 进程内启动；参考 Cloud 部署固定一个 Gunicorn worker 和一个副本。先拆出独立 worker 或加分布式互斥，再扩容 Web 进程。
