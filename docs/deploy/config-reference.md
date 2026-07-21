# Beacon 配置参考（`config.json` + 环境变量）

本文档用于汇总 Beacon 在交付与运行阶段的主要配置项、加载顺序与常见对齐关系，目标是：

- 明确 `config.json` 的定位与路径解析规则
- 明确环境变量覆盖规则（生产推荐优先使用 env 注入敏感项）
- 提供“最小可用配置”与“常见问题对照表”

适用范围：

- Edge 单机部署（Admin + Analyzer + MediaServer）
- Cloud POC（部分字段不同，但配置原则一致）

相关文档：

- 端口与防火墙策略：`docs/deploy/ports-and-firewall.md`
- 安全加固指南：`docs/deploy/security-hardening.md`

---

## 1. 配置来源与优先级

Beacon 在运行期常见配置来源：

- `config.json`：运行参数（端口、目录、密钥、告警外发、WebRTC 等）
- 环境变量：覆盖 `config.json`（敏感字段与路径类字段推荐使用 env）
- `settings.json`：品牌与部分 UI 展示类配置（与运行参数分离）
- 数据库（SystemConfig / ApiKey 等）：动态配置与密钥管理（按功能模块生效）

环境变量模板（仓库内，逐行注释）：

- `.env.example`：开发/本机
- `.env.production.example`：生产/反代/公网

### 1.1 `config.json` 文件路径

源码运行时（默认）：

- `config.json` 位于仓库根目录

交付包运行时（推荐）：

- 以 `BEACON_ROOT_DIR` 作为产品根目录
- `config.json` 位于 `${BEACON_ROOT_DIR}/config.json`

根目录解析顺序（Admin 侧 `Admin/runtime_paths.py`）：

1. 环境变量 `BEACON_ROOT_DIR`
2. Frozen build（PyInstaller）时使用 `sys.executable` 所在目录
3. 源码模式时根据 `Admin/runtime_paths.py` 推导仓库根目录

### 1.2 路径字段解析规则（重要）

下列路径字段支持 env 注入，并支持 `config.json` 相对路径：

- `uploadDir`：告警图片/视频等落盘目录
- `modelDir`：模型目录
- `fileServiceRootDir`：文件服务根目录（OpenAPI）

规则：

- 环境变量优先（例如 `BEACON_UPLOAD_DIR` 优先于 `config.json.uploadDir`）
- `config.json` 内的相对路径统一按 **`config.json` 所在目录** 解析
- 非 Windows 系统下，如果 `config.json` 填入了类似 `C:\...` 的 Windows 盘符路径，会被识别为异常并回退到默认相对路径（避免误建目录）

---

## 2. 网络端口与地址（Admin/Analyzer/MediaServer 对齐）

### 2.1 核心字段（`config.json`）

- `host`：展示用/兼容字段；如设置为 `0.0.0.0` 表示绑定全部网卡
- `adminPort`：Admin 端口（默认 `9991`）
- `analyzerPort`：Analyzer 端口（默认 `9993`）
- `mediaHttpPort`：MediaServer HTTP 端口（默认 `9992`）
- `mediaRtspPort`：MediaServer RTSP 端口（默认 `9994`）
- `mediaRtmpPort`：MediaServer RTMP 端口（默认 `9995`）

### 2.2 Admin 内部互调地址（`internalHost` 行为）

Admin 配置加载时存在兼容逻辑：

- 当 `host` 为 `0.0.0.0` 或 `::` 时，Admin 内部互调（Admin -> Analyzer/MediaServer）会使用 `127.0.0.1`
- 当 `host` 为具体 IP/域名时，内部互调使用该值

该行为用于避免出现 `http://0.0.0.0:<port>` 这类无法作为客户端访问地址的配置。

### 2.3 USB 摄像头桥接（可选，本机采集 -> 标准流）

Beacon 本身仍按 RTSP / RTMP / HTTP-FLV 等标准网络流工作，不直接把 `/dev/video*` 当成一类独立流模型。

正式环境如需接 USB 摄像头，推荐做法是：

- 由本机 `ffmpeg` 从 USB 设备采集
- 推送到本机 MediaServer 的 RTMP 地址
- Beacon 再按普通网络流 `live/<streamName>` 使用

可选启动配置：

- `usbCameraEnabled`：是否启用本机 USB 摄像头 bridge
- `usbCameraFfmpegBin`：`ffmpeg` 可执行文件路径
- `usbCameraInputDriver`：采集驱动，Linux 常用 `v4l2`
- `usbCameraInputFormat`：输入像素/压缩格式，如 `mjpeg`
- `usbCameraVideoSize`：采集分辨率，如 `1280x720`
- `usbCameraFramerate`：采集帧率
- `usbCameraDevice`：设备路径，如 `/dev/video0`
- `usbCameraApp` / `usbCameraStreamName`：未显式设置推流 URL 时，用于拼接 `rtmp://127.0.0.1:<mediaRtmpPort>/<app>/<name>`
- `usbCameraPublishUrl`：可直接覆盖为完整推流地址

环境变量模板见 `.env.production.example` 中的 `BEACON_USB_CAMERA_*` 段落。

---

## 3. OpenAPI / Ops 鉴权配置（Token 与 ApiKey）

### 3.1 共享 Token（legacy，兼容模式）

OpenAPI Token 读取顺序（Admin/Analyzer）：

1. 环境变量 `BEACON_OPEN_API_TOKEN`
2. `config.json.openApiToken`

支持的请求头（Admin 与 Analyzer 均兼容）：

- `Authorization: Bearer <token>`（推荐）
- `X-Beacon-Token: <token>`（兼容历史）

强制要求 token（Admin 中间件）：

- `BEACON_REQUIRE_OPEN_API_TOKEN=1`：即使来自 loopback 也要求 token
- 未开启强制要求时：当未配置 token 且未配置 DB ApiKey 时，部分路径允许 loopback 访问（用于本机开发/自测）
- `BEACON_OPEN_API_TOKEN_MAX_LENGTH`：限制请求头中 token 最大长度（默认 2048；范围 64..16384），用于降低异常超长 Header 风险

反向代理/公网场景建议：

- 建议开启 `BEACON_REQUIRE_OPEN_API_TOKEN=1`，避免反代后 `REMOTE_ADDR` 变为 loopback 导致的误放行

### 3.2 DB 管理的 ApiKey（推荐工业交付）

Admin 支持在数据库中管理多组 ApiKey（支持多 Key、轮换、吊销、过期、scope）。

常用 scope 约定：

- `ops`：运维探针与运维接口（`/healthz` `/readyz` `/metrics` 与 `/open/ops/*`）
- `openapi`：业务 OpenAPI（`/open/*`、`/stream/open*`、`/control/open*`、`/alarm/open*` 等）

可通过 Admin 的运维页面管理 ApiKey：

- `/ops/apikeys`

### 3.3 ApiKey Pepper（重要）

ApiKey 在 DB 中仅保存 hash（不可逆），hash 计算会混入一个 server-side Pepper：

- `BEACON_API_KEY_PEPPER`

约束：

- Pepper 需要在同一部署环境内保持一致（多实例必须一致）。
- 若在运行期变更 Pepper，历史 ApiKey 将无法通过校验（等价于全部失效），需按轮换流程重新下发新 key。

### 3.4 IP allowlist/denylist（OpenAPI/Ops 与 Admin 入口）

Beacon 提供两组 CIDR 策略（逗号分隔）用于收敛访问面：

OpenAPI/Ops：

- `BEACON_OPEN_API_IP_ALLOWLIST`
- `BEACON_OPEN_API_IP_DENYLIST`

Admin 入口（仅作用于登录页与验证码接口）：

- `BEACON_ADMIN_IP_ALLOWLIST`
- `BEACON_ADMIN_IP_DENYLIST`

行为要点：

- 未配置 allow/deny 时：策略关闭（默认放行）。
- denylist 优先：命中 denylist 直接拒绝。
- 配置 allowlist 时：仅 allowlist 命中放行。
- allow/deny 中如存在无法解析的 CIDR token：按 fail-closed 拒绝（避免误配导致暴露）。

### 3.5 OpenAPI 网关防护（Rate Limit / WAF）

Beacon 提供轻量 OpenAPI 网关能力（可用于运行阶段测试与工业交付的“兜底保护”），可通过 `config.json` 或 env 配置：

Rate Limit：

- `openApiRateLimitEnabled` / `BEACON_OPEN_API_RATE_LIMIT_ENABLED`
- `openApiRateLimitPerMinute` / `BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE`（默认 60）
- `openApiRateLimitBurst` / `BEACON_OPEN_API_RATE_LIMIT_BURST`（默认 10）

WAF（轻量）：

- `openApiWafEnabled` / `BEACON_OPEN_API_WAF_ENABLED`
- `openApiWafMaxBodyBytes` / `BEACON_OPEN_API_WAF_MAX_BODY_BYTES`（默认 1048576 = 1MB）

说明：

- 速率限制计数依赖 Django cache；多实例部署建议使用共享 cache（例如 Redis），否则每个实例独立计数，整体限流效果不准确。
- WAF 属于 best-effort：拦截超大 body 与明显可疑 pattern；公网生产建议仍由反向代理/WAF 产品承担主要防护。

### 3.6 TOTP 敏感操作二次确认（re-auth）

用于对高风险管理操作要求“近期二次确认”（仅对已启用 TOTP 的账号生效）：

- `BEACON_TOTP_SENSITIVE_REAUTH_ENABLED`
- `BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS`（默认 300）
- `BEACON_TOTP_SENSITIVE_REAUTH_PREFIXES`（逗号分隔路径前缀列表）

### 3.7 允许 iframe 嵌入（可选）

默认策略为拒绝 iframe 嵌入（`X-Frame-Options=DENY`）。如需允许嵌入（例如大屏系统），需显式配置：

- `BEACON_IFRAME_EMBED_ENABLED=1`
- `BEACON_IFRAME_EMBED_ALLOWED_ORIGINS=https://a.example.com,https://b.example.com`（可选；未配置时仅允许同源）

更完整的安全基线与建议见：

- `docs/deploy/security-hardening.md`

---

## 4. 目录与存储（上传目录/模型目录）

### 4.1 上传目录（告警图片/视频落盘）

字段：

- `config.json.uploadDir`
- env 覆盖：`BEACON_UPLOAD_DIR`

说明：

- Admin 与 Analyzer 都会使用 `uploadDir` 相关配置（用于告警素材落盘、文件服务、诊断导出等）
- 交付包建议将可变数据统一落在 `${BEACON_ROOT_DIR}/data/upload/`

### 4.2 模型目录（Analyzer 模型/插件）

字段：

- `config.json.modelDir`
- env 覆盖：`BEACON_MODEL_DIR`

说明：

- 仓库默认不包含模型文件；全栈可启动不代表算法可立即运行
- 交付包建议将模型放入 `${BEACON_ROOT_DIR}/data/models/`

---

## 5. MediaServer 管理密钥（`mediaSecret`）

字段：

- `config.json.mediaSecret`

对齐要求：

- 必须与 ZLMediaKit `config.ini` 中 `[api].secret` 一致
- 不一致时表现为：UI 可打开，但所有媒体相关动作（拉流代理、媒体列表等）失败
- 使用 `Admin/VideoAnalyzer.py` 统一启动且未配置密钥时，启动器会生成一个随机值，同时注入 Admin、Analyzer 和 MediaServer 运行配置
- 分别手工启动组件时，仍应显式设置同一个 `BEACON_MEDIA_SECRET`，或把同一个随机值分别写入两侧配置

---

## 6. WebRTC NAT / ICE（播放器/对讲相关）

字段（`config.json` / env）：

- `webrtcStunUrls` / `BEACON_WEBRTC_STUN_URLS`（CSV 或 JSON 数组）
- `webrtcTurnUrl` / `BEACON_WEBRTC_TURN_URL`
- `webrtcTurnUsername` / `BEACON_WEBRTC_TURN_USERNAME`
- `webrtcTurnPassword` / `BEACON_WEBRTC_TURN_PASSWORD`
- `webrtcSelfCheckTimeoutSeconds` / `BEACON_WEBRTC_SELFCHECK_TIMEOUT_SECONDS`

说明：

- 局域网内播放通常不需要 TURN
- 跨网段/NAT 环境建议配置 STUN/TURN，并使用自检接口辅助定位

---

## 7. 告警外发与预检

Beacon 保留 Webhook 与 Cloud 两种告警外发方式：

- Webhook：`alarmWebhookEnabled` / `BEACON_ALARM_WEBHOOK_URLS` / `BEACON_ALARM_WEBHOOK_SECRET`
- Cloud：`BEACON_CLOUD_ENABLED` / `BEACON_CLOUD_BASE_URL` / `BEACON_CLOUD_EDGE_TOKEN`

大模型预检（可选，落库前过滤误报）：

- `alarmPrecheckEnabled` / `BEACON_ALARM_PRECHECK_ENABLED`
- `alarmPrecheckUrl` / `BEACON_ALARM_PRECHECK_URL`
- `alarmPrecheckTimeoutSeconds` / `BEACON_ALARM_PRECHECK_TIMEOUT_SECONDS`
- `alarmPrecheckFailOpen` / `BEACON_ALARM_PRECHECK_FAIL_OPEN`

---

## 8. GB28181（可选）

GB28181 相关参数主要通过环境变量或 `config.json` 注入，字段前缀：

- `BEACON_GB28181_*`

典型用途：

- 对接 WVP 平台或自定义平台
- 由 provider 负责 `start_play` / `stop_play` / `ptz_control` 等动作

---

## 9. License（Analyzer）

Analyzer 支持从 `config.json` 与环境变量读取授权信息，常用 env：

- `BEACON_LICENSE_TYPE`
- `BEACON_LICENSE_KEY`
- `BEACON_LICENSE_DONGLE_CMD`
- `BEACON_LICENSE_DONGLE_FILE`
- `BEACON_LICENSE_LEASE_TTL_SECONDS`
- `BEACON_LICENSE_GRACE_SECONDS`

说明：

- 开源源码默认 `BEACON_LICENSE_TYPE=community`，不启用运行授权门禁
- `licenseKey` 属于敏感字段，推荐使用 env 注入
- 诊断包/日志导出可能包含配置文件，需按密钥资产管理要求保存与传输

---

## 10. Admin（Django）运行与日志（常用 env）

### 10.1 Django 基础安全项

- `BEACON_DJANGO_DEBUG`：生产建议为 `0`
- `BEACON_DJANGO_SECRET_KEY`：生产必须设置，且不得使用默认值
- `BEACON_DJANGO_ALLOWED_HOSTS`：生产必须显式配置，不允许 `*`

### 10.2 日志输出与落盘

日志相关 env（`Admin/framework/settings.py`）：

- `BEACON_LOG_LEVEL`：默认 `INFO`
- `BEACON_LOG_FORMAT`：`text` / `json`
- `BEACON_LOG_TO_FILE`：是否落盘（默认 `0`）
- `BEACON_LOG_DIR`：日志目录（默认 `Admin/logs`）
- `BEACON_LOG_FILE_MAX_MB`：轮转大小（默认 50MB）
- `BEACON_LOG_FILE_BACKUP_COUNT`：轮转保留份数（默认 10）
- `BEACON_LOG_FILE_RETENTION_DAYS`：按天保留（启用后使用 TimedRotatingFileHandler）

### 10.3 SQLite（默认 DB）相关

- `BEACON_SQLITE_DB_PATH`：覆盖 SQLite 路径
- `BEACON_SQLITE_TIMEOUT_SECONDS`：写锁等待超时（默认 30 秒）
- `BEACON_SESSION_COOKIE_AGE_SECONDS`：Session Cookie 生命周期

Cloud 部署（Postgres）：

- `BEACON_CLOUD_DB_URL`：覆盖数据库连接（`postgres://...`）

---

## 11. 最小可用配置示例（Edge 全栈）

以下为示例，仅用于说明字段形态（实际值需按部署环境调整）：

```json
{
  "host": "127.0.0.1",
  "adminPort": 9991,
  "mediaHttpPort": 9992,
  "analyzerPort": 9993,
  "mediaRtspPort": 9994,
  "mediaRtmpPort": 9995,
  "mediaSecret": "CHANGE_ME",
  "openApiToken": "CHANGE_ME",
  "uploadDir": "Admin/static/upload",
  "modelDir": "Analyzer/models"
}
```

生产交付建议：

- `openApiToken`、Webhook/Cloud 密钥等敏感项通过 env 注入
- `uploadDir`、`modelDir` 固化到 `${BEACON_ROOT_DIR}/data/`，便于备份与迁移
