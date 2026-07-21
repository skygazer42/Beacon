# Beacon 版本更新日志

!!! info "本页记录 Beacon 版本变更。"
    发布前的工作先记录在 `Unreleased`，打标签时再归入对应版本。

---

所有重要变更都将记录在此文件中。

---

## [Unreleased]

### 开源发布准备

- 清理生成文档、旧前端依赖、运行时上传、构建产物和内部过程资料。
- 移除需要单独商业授权的播放器运行时，补齐第三方来源与许可证说明。
- 生产密钥改为显式配置，清除示例默认密码，并加入当前源码密钥扫描。
- 新增后端、前端、原生模块、SDK、文档、Compose、Helm 与依赖审计 CI。
- Cloud 镜像改用 Gunicorn、WhiteNoise 和非 root 用户，补齐部署安全边界。
- Admin 升级到 Django 5.2 LTS，依赖与 CI 覆盖 Python 3.10–3.12。
- 前端构建生成确定性的第三方许可证清单，并加入 Gitleaks 与 Semgrep 扫描。

## [4.753] - 2026-07-15

- 精简控制台导航与重复页面入口。
- 整理 Cloud 接入与云边管理流程。

## [4.752] - 2026-03-31

- 重建并同步 React 管理端生产包。

## [4.751] - 2026-03-25

### 品牌与体验焕新（Admin / Docs）

#### 新增 / 变更

- Admin 登录页完成品牌化重构：
  - 采用更统一的 Beacon 视觉语言，重做品牌徽标、标题层级、左侧能力说明与右侧登录卡片布局。
  - 保留并兼容本地账号登录、OIDC 单点登录、TOTP 二次验证、验证码等现有认证能力。
- Admin 后台视觉体系升级：
  - `modern-theme.css` 升级为多主题变量体系，统一深色 / 浅色 / 跟随系统的颜色令牌、状态色与面板样式。
  - 侧边栏、顶部导航、首页仪表盘、审计页、API Key 页、用户页、设备发现页、流媒体页等页面同步对齐新的品牌样式。
- Beacon 品牌资源统一：
  - 更新站点 Logo、favicon、默认头像及一组横版 / 图标品牌素材。
  - README 与文档首页统一使用新的品牌头图，提升对外展示一致性。
- 退出路径兼容性修复：
  - 新增 `/logout/` 路由别名，解决导航退出入口在部分场景下访问 `404` 的问题。

#### 文档更新

- 仓库主 README、`Admin/README.md`、`Analyzer/README.md`、`MediaServer/README.md` 统一为 Beacon 品牌表述。
- 重构“快速开始 / 安装指南 / 部署文档”内容组织，补齐新用户从环境准备、安装部署到首次体验的阅读路径。
- 架构文档增强：
  - 扩充 Admin 架构说明，补充模块结构、数据模型、安全网关、后台服务、模板与静态资源说明。
  - 新增 Analyzer 与 MediaServer 架构文档。
  - 完善部署总览与 Docker / Linux / Windows / Kubernetes / 集群部署文档。

#### 工程质量

- 新增登录页 UI 回归测试：
  - 覆盖品牌文案、TOTP / CAPTCHA / OIDC 入口与关键版式钩子。
- 新增退出别名回归测试：
  - 覆盖 `/logout/` 的普通退出与 OIDC end-session 跳转场景。
- 补充系统设置测试，继续覆盖品牌配置与运行时配置保存链路。

### 2026-03 Security Hardening (Admin)

> 详细发布说明：已合并到本 CHANGELOG（历史 plans 文档已移除）。

#### 新增 / 加固

- OIDC：`id_token` 验签强制开启，回调必须通过 JWKS 签名与基础声明校验（fail-closed）。
- OpenAPI/Admin IP 策略：CIDR 配置含非法条目时改为拒绝访问（fail-closed），并输出告警日志。
- Token 比对：legacy OpenAPI token 改为常量时间比较（`hmac.compare_digest`）。
- 命令执行：License dongle 检测、Windows `wmic` 探测改为参数化子进程调用，去除 `shell=True`。
- ONVIF 截图：不再返回 `full_path`；新增截图文件名净化，阻断路径注入/非法字符风险。

#### 变更影响（升级注意）

- 若未正确配置 OIDC 验签参数（如 `JWKS/issuer/client_id`），登录回调可能返回 `400 oidc invalid id_token`。
- 若 IP allowlist/denylist 中存在错误 CIDR，相关入口将返回 `403`（需先修正配置）。

#### 验证（已执行）

- 定向与关联回归已通过：`4/4 + 32/32 + 5/5 + 29/29 PASS`。
- 关键验证命令见发布说明文档（同上）。

### 2026-03 Security Hardening (Admin, Wave11 Addendum)

#### 新增 / 加固

- 登录锁定（Lockout）：
  - 新增过期锁定记录回收与保留期控制：`BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS`（默认 30 天，范围 1 小时到 365 天）。
  - 代理来源 IP 仅在合法 IP 格式下参与锁定计算（`X-Forwarded-For` / `X-Real-IP` 非法值将回退）。
  - 登录标识符标准化增强：增加 Unicode NFKC 归一化，减少全角/兼容字符别名绕过风险。
- OIDC：
  - `provider` 参数增加严格净化（仅允许 `[A-Za-z0-9_.-]`，最长 64），非法值返回 `400 oidc provider invalid`。
  - 权限同步模式下，若映射结果为空会清理历史本地权限，避免陈旧授权残留。
- 审计与可观测性：
  - 安全拒绝事件补充标准化字段 `security_reason`（如 `ip_policy`、`token_missing_or_invalid`、`rate_limited` 等）。
  - 指标新增登录锁定态暴露：`beacon_admin_login_lockout_active`、`beacon_admin_login_lockout_principals`。

#### 验证（已执行）

- 已通过 Wave11 组合验证：
  - `python Admin/manage.py test app.tests.test_login_lockout app.tests.test_ops_audit_log_autotrace app.tests.test_ops_observability app.tests.test_oidc_sso.OidcSsoLoginTest.test_oidc_start_rejects_invalid_provider_id app.tests.test_oidc_sso.OidcSsoLoginTest.test_oidc_callback_rejects_invalid_provider_id app.tests.test_oidc_sso.OidcSsoLoginTest.test_oidc_permission_sync_drops_unknown_permission_keys app.tests.test_oidc_sso.OidcSsoLoginTest.test_oidc_permission_sync_can_clear_stale_permissions_when_mapped_empty app.tests.test_permission_coerce`

### 2026-03 Alarm Filter Presets (Admin)

#### 新增 / 变更

- 告警列表（`/alarms`）与 Review Center（`/alarm/review`）支持筛选预设（Saved Views）：可保存个人预设，或按权限角色（permission key）定向共享。
- 预设可见性在 DB 查询侧提前过滤（owner + permission share keys），避免加载无关私有预设后再在 Python 侧丢弃，降低列表页开销。


### 2026-02 工业交付增强（可交付 / 可售卖）

> 说明：本段用于“交付验收 / 售前演示 / 工业排障”的统一口径汇总。  
> 对应的详细设计与实施过程已从仓库移除（可通过 Git 历史追溯）。

#### 交付清单（对应计划）

- Alarm Event Bus M1（DB Outbox + Webhook/MQTT）
- Alarm Email Notification + Audit（邮件通知 + 已处理审核）
- 安全加固（反代/公网安全默认值）
- License Manager v1（浮动池授权/可卖 SKU）
- Integration Kit v1（对接包 + Receiver 示例）
- Cloud SaaS v1（告警聚合 + 截图上云）
- Docker Compose POC（Cloud 一键验收）
- Ops 可观测性（health/ready/metrics/logs/audit）

#### 验收命令（最小可信）

- Python 回归（核心）：`python3 Admin/manage.py test app -v 2`
- Integration Receiver 示例可运行：`python3 examples/alarm_webhook_receiver/receiver.py --help`
- Cloud Docker POC（一键起）：`docker compose -f deploy/cloud-saas-v1/compose.yml up -d --build`
- Cloud Docker POC（清理，方便重跑）：`docker compose -f deploy/cloud-saas-v1/compose.yml down -v`

#### 验收截图建议（交付/售前材料）

- Cloud Console：
  - 登录页：`/login`（能登录）
  - 集群管理：`/cloud/edge-clusters`（能创建集群/生成 token）
  - 告警列表：`/cloud/alarms`（能看到告警）
  - 告警详情：`/cloud/alarm/detail?id=...`（能看到截图预览）
- License Manager：
  - 管理页：`/license/manager`（能导入 license / 显示状态）
  - 使用量：`GET /open/license/usage`（建议用 Postman/浏览器保存返回 JSON 作为验收附件）
- Docker POC：
  - `docker compose ps`（服务健康）
  - `docker compose logs -f beacon-cloud`（启动完成、bootstrap 成功）
  - `docker compose logs -f edge-simulator`（成功输出 `event_id`）

#### 关键配置项（交付必看）

> 完整变量说明见：`.env.example` 与 `.env.production.example`（逐行中文注释）。

- 通用安全（建议生产必配）：
  - `BEACON_OPEN_API_TOKEN`（open/api 共享 Token）
  - `BEACON_REQUIRE_OPEN_API_TOKEN=1`（反代/公网强制 Token，避免 localhost 误放行）
  - `BEACON_DJANGO_SECRET_KEY` / `BEACON_DJANGO_ALLOWED_HOSTS` / `BEACON_DJANGO_CSRF_TRUSTED_ORIGINS`
- Alarm Event Bus（对接/集成）：
  - `BEACON_ALARM_WEBHOOK_URLS` / `BEACON_ALARM_WEBHOOK_SECRET` / `BEACON_ALARM_WEBHOOK_TIMEOUT_SECONDS`
  - Cloud 出口：`BEACON_CLOUD_ENABLED=1`，并配置 `BEACON_CLOUD_BASE_URL` / `BEACON_CLOUD_EDGE_TOKEN`
  - Webhook 与 Cloud 共用 DB Outbox；当前不再内置 MQTT、邮件等告警出口
- License Manager（浮动池授权）：
  - `BEACON_LICENSE_PUBLIC_KEY_B64` / `BEACON_CLUSTER_ID`
  - `BEACON_NODE_ID` / `BEACON_LICENSE_LEASE_TTL_SECONDS` / `BEACON_LICENSE_GRACE_SECONDS`
- Cloud SaaS v1（云端模式）：
  - `BEACON_DEPLOYMENT_MODE=cloud`
  - `BEACON_CLOUD_DB_URL`（推荐 Postgres；不设则回退 SQLite）
  - `BEACON_CLOUD_S3_*`（bucket/endpoint/ak/sk/region）
  - `BEACON_CLOUD_EDGE_TOKEN_PEPPER`（必须保密）
  - `BEACON_CLOUD_IMAGE_PREVIEW_PROXY=1`（Docker/MinIO 场景推荐开启：截图预览走 Cloud 代理）
- Docker Compose POC：
  - 入口：`deploy/cloud-saas-v1/compose.yml`
  - 用户名默认 `admin`；密码必须通过 `.env` 的 `BEACON_BOOTSTRAP_ADMIN_PASSWORD` 显式设置，没有内置默认密码

### 新增
- 完整的项目 README 文档
- 详细的部署文档 (DEPLOYMENT.md)
- 快速参考手册 (QUICK_REFERENCE.md)
- 新的小鹿 Logo 设计

### 改进
- 优化侧边栏显示，添加 Logo
- 更新浏览器标签页图标

---

## [4.22.0] - 2026-02-27

### 新增
- Admin：摄像头管理支持自定义编号（`code`），并默认保持视频流 `name=code` 对齐
- Admin：摄像头管理新增“全部删除”危险操作（需二次确认）
- Admin：系统设置新增“布控异常自动恢复”开关，支持 Admin 启动后 best-effort 恢复 `state=1` 的布控任务

---

## [4.21.1] - 2026-02-27

### 新增
- Analyzer：`POST /api/algorithm/testInfer` 返回的 `detects` 支持 `hasPose/keypoints`（姿态关键点，兼容旧字段）
- Admin：报警数据新增多区域编号 `region_index` 字段（0-based；-1=未知/不适用）
- Analyzer：内置离岗（`absence`）/无人值守（`unattended`）多区域触发时写入 `region_index`（openAdd、open/alarm/upload、本地 `result.json`）

### 修复
- 推理引擎：修复 ONNX Runtime 资源释放导致的轻微内存泄漏（模型实例释放后仍残留引用）
- 扩展参数：修复 `algorithmInstanceKey` 解析失败时覆盖默认参数的问题（避免实例复用 key 异常）
- 协议兼容：行为 API 返回的 `detects.keypoints` 支持多种格式（对象数组/二维数组/扁平数组）

### 改进
- Linux：图片检测接口减少 `imdecode()` 前的多余拷贝，提升编解码性能

---

## [4.21.0] - 2026-02-27

### 新增
- Admin：录像数据/报警数据支持按“存储空间上限”自动覆盖（按最旧优先删除；后台守护任务定时清理）
- Admin：新增录像计划 RecordingPlan（支持自定义编号、录音、按时间段/星期自动开始/停止）
- OpenAPI：新增 8 个平台接口（基本信息/存储信息/重启软件/重启系统/录像计划增删改查）
- Analyzer：本地报警目录新增写入 `result.json`（描述报警结果与关键字段，便于离线解析/对接）
- 行为算法：新增 APIv2（混合模式）支持：调用行为 API 获得 detects 后，Analyzer 本地内置规则判定 happen（intrusion/crowd/crossing/loitering/absence/unattended）
- 算法管理：新增“业务算法”类型，与基础算法/行为算法并列

### 改进
- Admin：SQLite 多线程/并发稳定性增强（WAL/busy_timeout + timeout）
- Admin：日志记录优化：支持可选写入本地轮转日志文件（env：`BEACON_LOG_TO_FILE/BEACON_LOG_DIR/...`）
- 模型加密：升级加密算法（支持写入试用时长与自定义编号，并兼容旧算法）；上传 TensorRT/OpenVINO 时可自动识别并避免重复加密
- OSD：新增支持配置“算法名/FPS 显示”的起点坐标（x/y）

### 修复
- 录像计划：勾选“录音”时无法正常录制的问题（FFmpeg 显式 map + mp4 音频兼容）
- OpenAPI：修复添加布控接口绘制区域参数兼容性问题（多矩形/多多边形区域）

---

## [4.20.1] - 2026-02-26

### 新增
- Admin：布控区域绘制支持多区域（多个矩形/多边形），并兼容旧版单区域数据
- Analyzer：识别区域解析升级为多区域（`;` 分隔），任一区域命中即视为命中，并在画面叠加中绘制所有区域
- Analyzer：内置行为离岗（`absence`）与无人值守（`unattended`）新增“持续时长阈值”后处理（默认 3 秒，可用 `behaviorConfig` 覆盖）
- OpenAPI：新增图片检测接口 `POST /open/algorithm/imageDetect`（支持 `image` 文件或 `image_base64`，并支持基础算法 API 转发或本地模型推理）

### 改进
- Admin：系统设置新增/完善启动配置在线修改（GB28181 参数、硬编解码配额、摄像头自启动转发、报警数据自动清理）
- Admin：新增报警数据自动清理任务（按保留天数清理 DB 与文件，安全路径校验，默认关闭）
- Analyzer：支持布控级“是否占用硬解/硬编配额”开关（不改 FFmpeg pipeline，仅调度与配额控制）

---

## [4.20.0] - 2026-02-25

### 新增
- Analyzer：新增可构建的国产硬件 compat 动态库 stub：`libbeacon_compat.*`（用于 `.rknn/.om`，可替换为带硬件 SDK 的实现）
- Admin：报警管理新增筛选项：视频流（`stream_code/app/name`）+ 画框类型（`draw_type`），并支持 openAdd 落库 `draw_type`

### 改进
- Analyzer：推流回帧修复：PTS 单调化 + fps 对齐最小步长（弱机/抖动场景更稳定）
- Analyzer：API 行为算法（模式5）payload 构建优化：避免大 base64 在 JSON 构建过程中多份拷贝
- Analyzer：动态库插件算法性能优化：复用每个 instance 的输出缓冲区，减少每帧分配

### 修复
- Admin：系统设置“部分字段保存”不再覆盖未提交的品牌/UI 字段（避免生产误覆盖）
- Admin：ONVIF 截图 open API 路径不再误重定向到登录页（302→200）

---

## [4.19.0] - 2026-02-24

### 新增
- Admin：新增 `settings.json`（UI/品牌/外链配置），支持在系统设置页配置：
  - 系统名称/标题/Logo、作者链接
  - 文档地址（`docsUrl`）、下载地址（`downloadUrl`）

### 改进
- Launcher（`Admin/VideoAnalyzer.py`）：修复 PyInstaller（frozen）场景下 root/log/lock 路径不稳定导致的多开风险
- Admin：branding 读取优先级调整为 `settings.json > DB(SystemConfig) > config.json`
- Admin：报警筛选 `end=YYYY-MM-DD` 时包含当日（避免漏掉当晚告警）

### 修复
- Admin：报警详情弹窗去掉 inline onclick，修复 desc 含引号/换行导致弹窗打不开的问题
- Analyzer：当 `alarmVideoType=none` 时显著降低报警帧队列上限，减少“无报警视频”场景的内存占用

---

## [4.18.6] - 2026-02-24

### 改进
- Analyzer：pipeline mode=2（检测→追踪→行为）支持 ReID embedding 限流策略（默认不变），可通过 `trackingConfig` 配置：
  - `reidEmbedEveryNFrames`：每 N 帧执行 embedding
  - `reidMaxRoiPerFrame`：单帧最多 embedding 的 ROI 数量
  - `reidEmbedTargetOnly`：仅对布控目标类别做 embedding（其它目标 IOU-only）

---

## [4.18.5] - 2026-02-24

### 新增
- Admin：补齐 ONVIF 设备发现页 UI（`/onvif/discover`），支持发现设备、获取 profiles/RTSP、按 profile 截图
- Admin：新增 ONVIF 批量导入摄像头 API（`POST /onvif/api/importStreams`），支持勾选 profiles 批量生成 Stream，并可选自动开启转发
- Admin：补齐录像/截图管理页（`/recording/manager`），可手动开始/停止录像、查询状态、查看活跃列表与手动截图

---

## [4.18.4] - 2026-02-24

### 新增
- Admin：算法管理支持配置 `algorithm_subtype`（detection/classification/tracking/behavior），追踪(Tracking)模型允许无 `object_str`
- Admin：算法管理支持 OpenVINO IR `.xml + .bin` 配对文件上传（`paired_file`）
- Admin：布控页面流程模式2支持选择 tracking 算法（来自算法管理），并支持独立选择追踪推理设备（CPU/GPU/TRT/AUTO + deviceId）

### 改进
- Admin：追踪(Tracking)算法强制“本地模型”方式，限制格式为 `.onnx` 或 `.xml + .bin`，降低误配置导致的启动失败
- Admin：运维预热加载接口支持 tracking subtype 无 `classNames`（与 Analyzer v4.18.3 行为一致）

### 修复
- Admin：行为算法新增/编辑时正确提交 `api_url_behavior`（修复行为 API 地址未保存的问题）

---

## [4.18.3] - 2026-02-23

### 新增
- Analyzer：`/api/algorithm/load` 支持 `algorithmSubtype=tracking`（追踪模型允许 `classNames` 为空）
- Analyzer：新增 ReID 推理引擎（ONNXRuntime / OpenVINO），用于“模型型追踪”能力补齐
- Analyzer：pipeline mode=2 支持 ReID 跟踪器（将 `track_id` / `track_len` 写回 attributes，可选 debugDrawTrackId 叠加显示）

### 改进
- Analyzer：报警视频编码链路增强：处理 `avcodec_send_frame` 的 `EAGAIN` 回压，并在队列满时优先丢弃非证据帧，降低丢帧与延迟

### 修复
- Admin：ONVIF 截图 API 统一对齐 `storageRootPath`，修复落盘路径不一致导致的图片找不到问题

---

## [4.18] - 2026-02-23

### 新增
- Analyzer：API 类型基础算法增加“稳定性保护”（超时/重试/熔断/最小调用间隔），避免外部推理服务异常时队列堆积导致崩溃
- Analyzer：新增 `POST /api/algorithm/testInfer` 一次性推理测试接口（用于验收/调试）
- Analyzer：插件 SDK v2（稳定 C ABI）：支持按 `modelConcurrency` 并发实例化，并提供示例插件与协议文档
- Admin：算法管理新增“算法测试（一次推理）”入口，支持本地模型/插件与 API 算法两条路径
- Admin：布控启动自动预热加载算法（本地模型/插件），降低首次布控失败率

### 改进
- Analyzer：Scheduler 增加 API 推理观测指标，并在 `/metrics` 暴露（allowed/skip/success/fail/retry/latency 等）
- 文档：补充对接协议与二开文档（`docs/integration/`）及示例（`examples/`）

### 修复
- Analyzer：插件动态库卸载流程修正，避免错误清理指针导致潜在崩溃

---

## [4.17] - 2026-02-22

### 新增
- Analyzer：`/api/control/add` 支持 `drawType=line`（越线）与 OSD 贴图参数（PNG alpha）
- Analyzer：`--verify-model` 新增 `--device` 参数，并输出 provider 选择（AUTO/TRT/CUDA/CPU 等）
- Admin：布控页面支持“绘制类型（区域/越线）”、越线方向配置，并支持 OSD 贴图参数配置与下发
- Admin：开放接口 `POST /open/alarm/upload` 支持更多上报字段（algorithm/stream/threshold/metadata/extra_images）

### 改进
- Analyzer：OSD 渲染支持“贴图 + 文字”组合；贴图读盘做线程内 cache，降低每帧 IO
- Admin：开放接口参数校验更严格，防止 `extra_images` 路径逃逸

### 修复
- Analyzer：基础算法检测 `mode=2` 间隔单位修正为“秒”（避免误当毫秒导致检测节奏异常）
- Analyzer：多卡/多设备 suffix 解析增强（`_gpu1/_trt0`），修复算法实例复用 key 设备冲突
- Admin：`/alarm/openAdd` 支持 JSON body，修复“二次开发报警接口测试”提交 JSON 失败

---

## [4.16] - 2026-02-22

### 新增
- 布控轮巡增强：新增“下一组”接口，轮巡预览支持 1/4/9/16 分屏与“跟随后端/前端独立”模式
- 告警外发 sinks：新增 Kafka/Redis/MongoDB 配置项，并提供 `/api/alarm/sinks/testSend` 运维测试接口
- OpenVINO 推理增强：支持分类模型（ResNet 等）输出（自动识别输出 shape，按 top-1 返回结果）
- 流程模式补齐：支持下发分类/行为字段，便于“检测 → 分类 → 行为”链路编排

### 修复
- 告警视频合成缓存清理：避免误删仍被告警记录引用的目录
- 转码拉起稳定性：`/stream/getPlayUrl` 在转码启动失败时返回可重试（code=1001），避免前端卡死
- 系统设置保存支持“部分字段更新”：参数缺失时保留现有值，避免误清空导致校验失败

---

## [4.15] - 2026-02-22

### 新增
- 系统设置新增 `modelCacheSeconds`（秒）：可配置模型引用归零后的缓存 TTL（写入 `config.json`，重启 Analyzer 生效）
- 布控轮巡新增 `control_patrol_concurrency`（默认 1）：支持按并发数分组轮转，可选“跳过离线流/自动管理转发”

### 修复
- 模型加密鲁棒性增强：suffix 兼容 `enc`/`.ENC`，`modelDecryptDir` 相对路径按 `config.json` 目录解析，并避免 `std::filesystem` 异常导致崩溃

---

## [3.52] - 2024-09-25

### 新增
- 新增集群管理平台支持
- 支持多节点协同工作
- 新增告警回调接口
- 新增系统发现 API

### 改进
- 优化视频流管理界面
- 改进告警视频生成逻辑
- 提升系统稳定性
- 优化内存使用

### 修复
- 修复长时间运行内存泄漏问题
- 修复多线程竞争条件
- 修复部分 RTSP 流无法连接问题

---

## [3.48] - 2024-03-26

### 新增
- 接入 Qwen2.5 VL 多模态大模型
- 接入 Qwen2.0 VL 视觉语言模型
- 接入 MiniCPM-o 2.6 多模态模型
- 新增 LLM 视频分析算法

### 改进
- 优化 Llama.cpp 推理性能
- 改进大模型响应速度

---

## [3.47] - 2024-03-05

### 新增
- 完整支持 ARM/x86 Linux 编译
- 完整支持 Windows 编译
- 支持 RK3588 硬件加速
- 支持昇腾 NPU
- 支持算能 TPU
- 支持树莓派部署
- 支持英特尔/AMD/海光 CPU

### 改进
- 统一编译流程
- 优化跨平台兼容性
- 改进硬件检测逻辑

---

## [3.46] - 2025-02-06

### 新增
- 集成 llama.cpp 推理引擎
- 支持 MiniCPM 视觉大模型
- 零门槛体验视觉大模型
- 新增算法 API 调用方式

### 改进
- 优化模型加载速度
- 改进推理性能

---

## [3.45] - 2024-12-26

### 新增
- C++ 版 TensorRT 推理 YOLO
- C++ 版 OpenVINO 推理 YOLO
- C++ 版 ONNX Runtime 推理 YOLO
- 支持多推理引擎切换

### 改进
- 统一算法接口
- 优化推理性能
- 改进模型加载逻辑

---

## [3.44] - 2024-11-26

### 新增
- C++ 版 RKNPU 推理 YOLO
- RGA 预处理加速
- 支持 RK3588 芯片
- 支持 RK3576 芯片

### 改进
- 针对 Rockchip 芯片优化
- 提升边缘设备性能

---

## [3.43] - 2024-10-09

### 新增
- 人员管理模块
- 人脸检测算法
- 人脸特征提取
- 人脸识别功能
- 无感考勤系统

### 改进
- 优化人脸识别精度
- 改进特征匹配速度

---

## [3.42] - 2024-10-02

### 新增
- CNN+LSTM 时序视频分析
- 视频分类算法
- 行为序列识别

### 改进
- 优化时序模型性能
- 改进分类准确率

---

## [3.41] - 2024-10-02

### 新增
- C++ 版 ONNX Runtime 推理 YOLO
- 支持 Rockchip 平台
- 支持树莓派
- 支持香橙派
- 支持英特尔平台
- 支持 NVIDIA 平台
- 支持 AMD 平台

### 改进
- 跨平台兼容性
- 优化 ONNX 推理性能

---

## [3.40] - 2024-10-02

### 新增
- 人脸检测算法
- YOLO v9 支持
- YOLO v8 优化
- 400 种动作检测
- 动作识别报警

### 改进
- 扩展检测类别
- 提升检测精度

---

## [3.3] - 2024-10-02

### 新增
- 优化播放器功能
- 改进摄像头对接
- 优化算法性能
- 改进存储逻辑

### 改进
- 提升播放流畅度
- 优化存储效率

---

## [3.2] - 2024-10-02

### 新增
- 完整支持 Linux 系统
- Linux 编译教程
- 优化报警视频帧计算
- 升级 FFmpeg 依赖库

### 改进
- 提升系统性能
- 改进跨平台支持

---

## [3.1] - 2024-10-02

### 新增
- 支持 NVIDIA 显卡推理
- C++ 版 TensorRT 推理引擎
- Windows 完整依赖库
- 可直接运行版本

### 改进
- 大幅提升推理速度
- 优化 GPU 利用率

---

## [3.0] - 2024-10-02

### 新增
- 算法模型升级至 YOLO v8
- C++ 版 OpenVINO 推理加速
- 完善周界入侵算法
- 支持绘制检测区域
- 完善后台管理模块

### 改进
- 提升检测精度
- 优化推理性能
- 改进用户界面

---

## [2.0] - 之前版本

### 新增
- 兼容 Linux 系统
- 优化推流功能
- 改进系统架构

---

## [1.0] - 初始版本

### 新增
- 实时分析视频流
- 实时产生报警视频
- 实时推流功能
- 基础算法支持
- Web 管理界面

---

## 版本号说明

版本号格式: `主版本.次版本.修订号`

- **主版本**: 重大架构变更或不兼容更新
- **次版本**: 新功能添加或重要改进
- **修订号**: Bug 修复和小改进

## 贡献指南

如果您想为 Beacon 项目贡献代码或提交问题，请参考：
- [贡献指南](developer/contributing.md)
- [GitHub Issues](https://github.com/skygazer42/Beacon/issues)
