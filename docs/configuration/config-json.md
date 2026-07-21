---
title: config.json 参考手册
description: Beacon 主配置文件 config.json 的完整字段参考，包含类型、默认值、说明与示例
icon: material/code-json
---

# config.json 参考手册

`config.json` 是 Beacon 系统的核心配置文件，位于项目根目录（与 `Admin/`、`Analyzer/`、`MediaServer/` 同级目录）。Admin 管理服务和 Analyzer 分析引擎均从此文件读取配置。

!!! info "文件编码"
    系统优先使用 UTF-8 编码读取配置文件，如果 UTF-8 解析失败则自动回退到 GBK 编码。建议统一使用 **UTF-8** 编码保存。

!!! tip "阅读提示"
    - 表中的默认值是当前代码回退值或仓库示例值；不同组件只读取自己使用的字段
    - 当前没有覆盖全部字段的统一“必填项”启动校验，生产要求会在说明中单独标出
    - 带有 :material-swap-horizontal: 标记的参数可被旁边明确写出的环境变量覆盖

---

## 服务与网络 {#server}

节点标识、网络绑定与端口配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 必填 | 说明 |
    |--------|------|--------|:----:|------|
    | `code` | string | — | :material-check: | 节点编号，用于多节点部署时的唯一标识 |
    | `name` | string | — | :material-check: | 节点名称，显示在管理界面标题栏 |
    | `describe` | string | `""` | | 节点描述信息 |
    | `host` | string | `"127.0.0.1"` | :material-check: | 服务监听地址。`0.0.0.0` 监听所有网卡，`127.0.0.1` 仅本地 |
    | `adminPort` | int | `9991` | :material-check: | Admin 管理后台端口 |
    | `analyzerPort` | int | `9993` | :material-check: | Analyzer 分析引擎 API 端口 |
    | `mediaHttpPort` | int | `9992` | :material-check: | 流媒体 HTTP/API 端口（ZLMediaKit） |
    | `mediaRtspPort` | int | `9994` | :material-check: | 流媒体 RTSP 端口 |
    | `mediaRtmpPort` | int | `9995` | | 流媒体 RTMP 端口 |
    | `mediaSecret` | string | `""` | | 流媒体服务鉴权密钥。生产环境必须设置独立随机值，可用 `BEACON_MEDIA_SECRET` 注入 |

!!! example "服务配置示例"
    ```json
    {
      "code": "beacon-prod-01",
      "name": "Beacon 智能分析平台",
      "describe": "总部机房主节点",
      "host": "0.0.0.0",
      "adminPort": 9991,
      "analyzerPort": 9993,
      "mediaHttpPort": 9992,
      "mediaRtspPort": 9994,
      "mediaRtmpPort": 9995,
      "mediaSecret": "CHANGE_ME_MEDIA_SECRET"
    }
    ```

---

## 站点外观 {#site}

页面展示相关的品牌定制参数。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `siteName` | string | 同 `name` 或 `"Beacon"` | 站点名称，显示在页面导航栏 |
    | `siteTitle` | string | `"Beacon 新一代 AI 视频分析系统"` | 浏览器标签页标题 |
    | `siteLogo` | string | `"/static/images/logo.png"` | 站点 Logo 图片路径（支持相对路径和绝对 URL） |
    | `authorName` | string | `""` | 作者/公司名称，显示在页面底部 |
    | `authorLink` | string | `""` | 作者/公司链接 |
    | `siteIcp` | string | `""` | ICP 备案号（中国大陆部署时填写） |
    | `customCss` | string | `""` | 自定义 CSS 代码，注入到页面 `<head>` 中 |
    | `customScript` | string | `""` | 自定义 JavaScript 代码，注入到页面中 |
    | `loginBg` | string | `""` | 登录页背景图片 URL |
    | `loginCaptchaEnabled` | bool | `false` | 是否启用登录验证码 :material-swap-horizontal: `BEACON_LOGIN_CAPTCHA_ENABLED` |

---

## 数据库 {#database}

Beacon 的数据库通过**环境变量**配置（详见 [环境变量参考](env-vars.md#database)），`config.json` 中不直接包含数据库连接参数。

| 数据库类型 | 配置方式 | 适用场景 |
|-----------|---------|---------|
| SQLite（默认） | 环境变量 `BEACON_SQLITE_DB_PATH` | 开发环境、小规模部署 |
| PostgreSQL | 环境变量 `BEACON_CLOUD_DB_URL` | 云部署、高并发生产环境 |

---

## 存储路径 {#storage}

文件上传、模型存放和告警存储相关的路径配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `uploadDir` | string | `"Admin/static/upload"` | 文件上传目录。支持相对路径（相对 config.json 所在目录）和绝对路径 :material-swap-horizontal: `BEACON_UPLOAD_DIR` |
    | `modelDir` | string | `"Analyzer/models"` | 算法模型文件目录 :material-swap-horizontal: `BEACON_MODEL_DIR` |
    | `storageRootPath` | string | 同 `uploadDir` | 运行时存储根目录，告警视频/录像/快照等存储在此目录下的子目录中 |
    | `saveAlarmType` | int | `1` | 告警文件存储方式。`1` = 本地存储 |
    | `saveAlarmUrl` | string | `""` | 远程告警存储地址（当 `saveAlarmType` 不为 `1` 时使用） |

!!! tip "路径建议"
    生产环境建议使用**绝对路径**，并将存储目录放在独立的数据盘上，避免与系统盘共享空间：

    ```json
    {
      "uploadDir": "/data/beacon/upload",
      "modelDir": "/data/beacon/models",
      "storageRootPath": "/data/beacon/storage"
    }
    ```

---

## 分析引擎 {#analyzer}

Analyzer 引擎的模型加载、推理并发与缓存配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `modelConcurrency` | int | `1` | 基础算法模型并发实例数（>=1）。多实例可提升推理吞吐量，但占用更多内存/显存 |
    | `modelCacheSeconds` | int | `300` | 模型空闲缓存时长（秒）。`0` = 引用计数归零时立即卸载非内置模型。最大值 30 天 :material-swap-horizontal: `BEACON_MODEL_CACHE_SECONDS` |
    | `modelEncrypt` | bool | `false` | 是否启用模型加密 :material-swap-horizontal: `BEACON_MODEL_ENCRYPT` |
    | `modelEncryptKey` | string | `""` | 模型解密密钥（XOR 方式） :material-swap-horizontal: `BEACON_MODEL_ENCRYPT_KEY` |
    | `modelEncryptSuffix` | string | `".enc"` | 加密模型文件后缀名 :material-swap-horizontal: `BEACON_MODEL_ENCRYPT_SUFFIX` |
    | `modelDecryptDir` | string | `""` | 模型解密缓存目录。为空则使用默认临时目录 :material-swap-horizontal: `BEACON_MODEL_DECRYPT_DIR` |
    | `tensorrtEnginePluginPath` | string | `""` | TensorRT Engine 插件动态库路径。仅 `.engine` / `.plan` 模型需要；这里填的是 Beacon 插件动态库路径，不是 TensorRT 安装目录 |
    | `compatLibPath` | string | `""` | Compat 兼容动态库路径。仅 `.rknn` / `.om` 模型需要；通常指向 `libbeacon_compat.dll/.so` :material-swap-horizontal: `BEACON_COMPAT_LIB_PATH` |
    | `rknpuPreprocessMode` | int | `0` | RK NPU 预处理模式。`0=disabled`、`1=adaptive`、`2=stretch`、`3=rga_stretch` :material-swap-horizontal: `BEACON_RKNPU_PREPROCESS_MODE` |

!!! note "C++ 运行时字段放置位置"
    当前实现中，`modelDir`、`modelConcurrency`、`tensorrtEnginePluginPath`、`compatLibPath`、`rknpuPreprocessMode` 都直接写在 `config.json` 顶层，不写在 `Analyzer` 节点下。

!!! warning "Compat 后端路径的真实含义"
    `compatLibPath` 指向的是 Beacon 兼容入口库 `libbeacon_compat.*`。
    真正通过 `BEACON_COMPAT_BACKEND_PATH` 指定的，应是实现了 `BeaconGetAlgorithmPluginV3` 接口的硬件后端插件，而不是普通厂商基础 SDK 动态库。

!!! tip "并发调优建议"
    - **CPU 推理**：`modelConcurrency` 建议设为 CPU 核心数的 1/4 ~ 1/2
    - **GPU 推理**：根据显存大小调整，每个实例约占用 200-500MB 显存（视模型而定）
    - 多实例适合高并发布控场景，但单机总实例数不宜超过 GPU 显存 / 单实例显存

---

## 硬件编解码 {#hardware}

GPU 硬件加速编解码相关配置，由 Analyzer 引擎读取。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `hardwareDecoderType` | string | `"auto"` | 硬件解码器类型。可选：`auto`、`nvdec`、`qsv`、`videotoolbox`、`vaapi`、`none` |
    | `hardwareEncoderType` | string | `"auto"` | 硬件编码器类型。可选：`auto`、`nvenc`、`qsv`、`videotoolbox`、`vaapi`、`none` |
    | `forceHardwareCodec` | bool | `false` | 是否强制使用硬件编解码（失败时不回退到软件编解码） |
    | `hardwareCodecDeviceId` | int | `0` | 硬件设备 ID（多 GPU 环境使用，默认为第一块设备） |
    | `maxHardwareDecodeChannels` | int | `0` | 最大硬件解码路数。`0` = 不限制 |
    | `maxHardwareEncodeChannels` | int | `0` | 最大硬件编码路数。`0` = 不限制 |
    | `ffmpegDecodeThreadCount` | int | `1` | FFmpeg 解码线程数。`0` = FFmpeg 默认值 |
    | `ffmpegEncodeThreadCount` | int | `1` | FFmpeg 编码线程数。`0` = FFmpeg 默认值 |

!!! tip "GPU 配置建议"

    | GPU 类型 | `hardwareDecoderType` | `hardwareEncoderType` | 备注 |
    |----------|----------------------|----------------------|------|
    | NVIDIA | `nvdec` | `nvenc` | 需安装 CUDA 和 NVIDIA 驱动 |
    | Intel 集成显卡 | `qsv` | `qsv` | 需安装 Intel Media SDK |
    | macOS (Apple Silicon) | `videotoolbox` | `videotoolbox` | macOS 原生支持 |
    | 无 GPU | `none` | `none` | 使用 CPU 软件编解码 |

    建议根据 GPU 显存设置 `maxHardwareDecodeChannels` 和 `maxHardwareEncodeChannels`，避免超负荷导致解码失败。

---

## 告警参数 {#alarm}

告警视频生成与队列的核心配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `alarmVideoSeconds` | int | `6` | 告警视频时长（秒）。`0` = 使用帧数配置 |
    | `alarmPrefixFrames` | int | `30` | 告警视频前缀帧数（触发前保留的帧数，用于回溯） |
    | `alarmTotalFrames` | int | `60` | 告警视频总帧数 |
    | `alarmMergeWindowSeconds` | int | `10` | 连续触发合并窗口（秒）。在此时间窗口内的连续告警将合并为一条 |
    | `alarmSegmentMaxSeconds` | int | `60` | 单段告警视频最大时长（秒） |
    | `alarmPushDelaySeconds` | int | `1` | 告警推送延迟秒数。`0` = 立即推送 |
    | `alarmQueueMaxSize` | int | `5` | 告警队列最大长度。超出时丢弃最早的告警，防止内存溢出 |
    | `alarmEncodeProfile` | string | `"balanced"` | 告警视频编码质量档位。可选值见下表 |
    | `alarmUploadIncludeBase64` | bool | `false` | 告警上传/推送时是否包含图片 Base64 数据 :material-swap-horizontal: `BEACON_ALARM_UPLOAD_INCLUDE_BASE64` |

    **告警编码档位说明：**

    | 档位 | 说明 |
    |------|------|
    | `balanced` | 均衡模式，兼顾画质与 CPU 占用（推荐） |
    | `high_quality` | 高质量模式，更高码率和更清晰的画质 |
    | `low_cpu` | 低 CPU 模式，降低编码开销，适用于资源受限设备 |

---

## 告警通道 - Webhook {#alarm-webhook}

通过 HTTP Webhook 推送告警事件。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `alarmWebhookEnabled` | bool | `false` | 是否启用 Webhook 推送 |
    | `alarmWebhookUrls` | list\<string\> | `[]` | Webhook 接收地址列表，支持多个 URL :material-swap-horizontal: `BEACON_ALARM_WEBHOOK_URLS`（逗号分隔） |
    | `alarmWebhookTimeoutSeconds` | int | `5` | 请求超时时间（1~30 秒） :material-swap-horizontal: `BEACON_ALARM_WEBHOOK_TIMEOUT_SECONDS` |
    | `alarmWebhookSecret` | string | `""` | HMAC 签名密钥。设置后请求头中携带 `X-Beacon-Signature` :material-swap-horizontal: `BEACON_ALARM_WEBHOOK_SECRET` |

!!! example "Webhook 配置示例"
    ```json
    {
      "alarmWebhookEnabled": true,
      "alarmWebhookUrls": [
        "https://your-server.com/api/alarm/receive",
        "https://backup-server.com/api/alarm/receive"
      ],
      "alarmWebhookTimeoutSeconds": 10,
      "alarmWebhookSecret": "your-hmac-secret"
    }
    ```

---


## 告警发件箱（Outbox） {#alarm-outbox}

Outbox 模式确保告警消息的**可靠投递**，先写入数据库再异步分发到各个通道。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `alarmOutboxEnabled` | bool | `true` | 是否启用 Outbox 模式 |
    | `alarmOutboxPollSeconds` | int | `2` | 轮询间隔秒数（1~10） |
    | `alarmOutboxMaxBatch` | int | `50` | 每次轮询最大处理批量（1~200） |
    | `alarmOutboxRetentionHours` | int | `72` | 已投递消息保留时长（小时），超时后清理 |
    | `alarmComposeCacheRetentionHours` | int | `72` | 告警合成缓存保留时长（小时） |

---

## 告警前置检查 {#alarm-precheck}

告警推送前的可选外部校验接口，允许通过外部系统过滤或确认告警。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `alarmPrecheckEnabled` | bool | `false` | 是否启用前置检查 :material-swap-horizontal: `BEACON_ALARM_PRECHECK_ENABLED` |
    | `alarmPrecheckUrl` | string | `""` | 前置检查接口 URL :material-swap-horizontal: `BEACON_ALARM_PRECHECK_URL` |
    | `alarmPrecheckTimeoutSeconds` | int | `5` | 接口超时时间（1~60 秒） :material-swap-horizontal: `BEACON_ALARM_PRECHECK_TIMEOUT_SECONDS` |
    | `alarmPrecheckFailOpen` | bool | `true` | 调用失败时是否放行告警。`true` = 放行（fail-open），`false` = 丢弃（fail-close） :material-swap-horizontal: `BEACON_ALARM_PRECHECK_FAIL_OPEN` |

---

## API 网关 {#api-gateway}

Open API 认证、限流和 WAF（Web 应用防火墙）相关配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `openApiToken` | string | `""` | Open API 认证 Token。设置后 `/open/` 接口须携带 `X-Beacon-Token` 请求头 :material-swap-horizontal: `BEACON_OPEN_API_TOKEN` |
    | `openApiRateLimitEnabled` | bool | `false` | 是否启用速率限制 :material-swap-horizontal: `BEACON_OPEN_API_RATE_LIMIT_ENABLED` |
    | `openApiRateLimitPerMinute` | int | `60` | 每分钟最大请求数（1~100000） :material-swap-horizontal: `BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE` |
    | `openApiRateLimitBurst` | int | `10` | 突发请求允许数（0~100000） :material-swap-horizontal: `BEACON_OPEN_API_RATE_LIMIT_BURST` |
    | `openApiWafEnabled` | bool | `false` | 是否启用 WAF :material-swap-horizontal: `BEACON_OPEN_API_WAF_ENABLED` |
    | `openApiWafMaxBodyBytes` | int | `1048576` | WAF 允许的最大请求体大小（字节），默认 1MB :material-swap-horizontal: `BEACON_OPEN_API_WAF_MAX_BODY_BYTES` |

!!! warning "安全建议"
    - 生产环境**必须**设置 `openApiToken`，否则 Open API 接口将仅允许本地访问
    - 建议启用 `openApiRateLimitEnabled` 以防止接口被恶意刷取
    - 建议启用 `openApiWafEnabled` 以拦截常见的 XSS、SQL 注入等攻击

---

## 认证安全 {#auth}

登录安全与认证相关配置。LDAP/AD 和 OIDC 的详细配置通过环境变量设置，请参阅 [环境变量参考](env-vars.md#ldap)。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `loginCaptchaEnabled` | bool | `false` | 是否启用登录验证码 :material-swap-horizontal: `BEACON_LOGIN_CAPTCHA_ENABLED` |

    **通过环境变量配置的认证功能：**

    | 功能 | 环境变量前缀 | 参考 |
    |------|-------------|------|
    | Django Session | `BEACON_DJANGO_SECRET_KEY`、`BEACON_SESSION_COOKIE_AGE_SECONDS` | [环境变量 - Django](env-vars.md#django) |
    | LDAP/AD 认证 | `BEACON_LDAP_*` | [环境变量 - LDAP](env-vars.md#ldap) |
    | OIDC SSO | `BEACON_OIDC_*` | [环境变量 - OIDC](env-vars.md#oidc) |
    | TOTP 两步验证 | `BEACON_TOTP_*` | [环境变量 - TOTP](env-vars.md#totp) |
    | 登录锁定 | `BEACON_LOGIN_LOCKOUT_*` | [环境变量 - 登录安全](env-vars.md#login-security) |

---

## 流媒体服务 {#mediaserver}

ZLMediaKit 流媒体服务相关配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `mediaSecret` | string | `""` | 流媒体服务鉴权密钥；生产环境必须设置独立随机值 |
    | `mediaHttpPort` | int | `9992` | 流媒体 HTTP/API 端口 |
    | `mediaRtspPort` | int | `9994` | 流媒体 RTSP 端口 |
    | `mediaRtmpPort` | int | `9995` | 流媒体 RTMP 端口 |
    | `transcodeIdleSeconds` | int | `300` | 转码会话空闲超时（秒，最小 30）。超时后自动停止转码 |
    | `transcodeStartCooldownSeconds` | int | `5` | 转码启动冷却时间（秒，最小 1）。防止频繁启停 |

---

## WebRTC {#webrtc}

WebRTC 实时视频播放相关的 ICE 配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `webrtcStunUrls` | list\<string\> | `[]` | STUN 服务器地址列表 :material-swap-horizontal: `BEACON_WEBRTC_STUN_URLS`（逗号分隔） |
    | `webrtcTurnUrl` | string | `""` | TURN 服务器地址 :material-swap-horizontal: `BEACON_WEBRTC_TURN_URL` |
    | `webrtcTurnUsername` | string | `""` | TURN 服务器用户名 :material-swap-horizontal: `BEACON_WEBRTC_TURN_USERNAME` |
    | `webrtcTurnPassword` | string | `""` | TURN 服务器密码 :material-swap-horizontal: `BEACON_WEBRTC_TURN_PASSWORD` |
    | `webrtcSelfCheckTimeoutSeconds` | int | `3` | WebRTC 自检超时时间（1~30 秒） :material-swap-horizontal: `BEACON_WEBRTC_SELFCHECK_TIMEOUT_SECONDS` |

!!! example "WebRTC 配置示例"
    ```json
    {
      "webrtcStunUrls": [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302"
      ],
      "webrtcTurnUrl": "turn:turn.example.com:3478",
      "webrtcTurnUsername": "beacon",
      "webrtcTurnPassword": "turn-password"
    }
    ```

---

## GB28181 国标接入 {#gb28181}

GB/T 28181 国标视频流接入相关配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `gb28181Provider` | string | `"wvp"` | GB28181 接入提供商。可选：`wvp`（WVP-PRO）、`custom` :material-swap-horizontal: `BEACON_GB28181_PROVIDER` |
    | `gb28181WvpBaseUrl` | string | `""` | WVP-PRO 服务基地址 :material-swap-horizontal: `BEACON_GB28181_WVP_BASE_URL` |
    | `gb28181TransportMode` | string | `""` | 传输模式 :material-swap-horizontal: `BEACON_GB28181_TRANSPORT_MODE` |
    | `gb28181HttpTimeoutSeconds` | int | `8` | HTTP 请求超时（1~60 秒） :material-swap-horizontal: `BEACON_GB28181_HTTP_TIMEOUT_SECONDS` |

---

## 资源限制 {#limits}

系统资源使用上限配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `maxControls` | int | `20` | 布控（分析任务）总数上限 |
    | `maxPendingControls` | int | `2` | 并发启动布控数量上限。防止批量启动时资源尖峰 |
    | `transcodeIdleSeconds` | int | `300` | 转码会话空闲超时（秒，最小 30）。超时后自动停止 |
    | `transcodeStartCooldownSeconds` | int | `5` | 转码启动冷却时间（秒，最小 1） |

---

## 日志 {#logging}

日志配置通过**环境变量**控制，详见 [环境变量参考](env-vars.md#logging)。

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `BEACON_LOG_LEVEL` | `"INFO"` | 日志级别：`DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `BEACON_LOG_FORMAT` | `"text"` | 日志格式：`text`（文本）或 `json`（结构化） |
| `BEACON_LOG_TO_FILE` | `false` | 是否将日志写入文件 |
| `BEACON_LOG_DIR` | `"Admin/logs"` | 日志文件目录 |
| `BEACON_LOG_FILE_MAX_MB` | `50` | 单个日志文件最大大小（MB） |
| `BEACON_LOG_FILE_BACKUP_COUNT` | `10` | 日志文件保留数量 |
| `BEACON_LOG_FILE_RETENTION_DAYS` | `0` | 日志保留天数。`0` = 按文件大小轮转 |

---

## 授权许可 {#license}

软件授权相关配置。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `licenseType` | string | `"community"` | 授权类型。可选：`community`（无运行授权门禁）、`machine`（机器码绑定）、`dongle`（加密锁）、`pool`（License Manager 池） |
    | `licenseKey` | string | `""` | 本地机器授权密钥（`licenseType=machine` 时使用） |
    | `licenseDongleCmd` | string | `""` | 加密锁探测命令（`licenseType=dongle` 时使用） |
    | `licenseDongleFile` | string | `""` | 加密锁哨兵文件路径（`licenseType=dongle` 时使用） |

---

## 系统杂项 {#system}

版本检查及其他系统级参数。

??? abstract "展开查看全部字段"

    | 参数名 | 类型 | 默认值 | 说明 |
    |--------|------|--------|------|
    | `versionCheckUrl` | string | `""` | 版本更新检查地址。为空则禁用自动检查 |

---

## 完整配置示例 {#full-example}

以下是一个包含常用配置项的**生产环境推荐配置**示例：

```json title="config.json — 生产环境示例"
{
  "code": "beacon-prod-01",
  "name": "Beacon 新一代 AI 视频分析系统",
  "describe": "生产环境主节点",
  "siteName": "智能安防平台",
  "siteTitle": "智能安防 - Beacon",

  "host": "0.0.0.0",
  "adminPort": 9991,
  "mediaHttpPort": 9992,
  "analyzerPort": 9993,
  "mediaRtspPort": 9994,
  "mediaRtmpPort": 9995,
  "mediaSecret": "CHANGE_ME_MEDIA_SECRET",

  "uploadDir": "/data/beacon/upload",
  "modelDir": "/data/beacon/models",
  "storageRootPath": "/data/beacon/storage",

  "modelConcurrency": 2,
  "modelCacheSeconds": 600,

  "maxControls": 50,
  "maxPendingControls": 4,
  "maxHardwareDecodeChannels": 16,
  "maxHardwareEncodeChannels": 8,
  "hardwareDecoderType": "nvdec",
  "hardwareEncoderType": "nvenc",

  "alarmVideoSeconds": 10,
  "alarmMergeWindowSeconds": 15,
  "alarmEncodeProfile": "balanced",
  "alarmOutboxEnabled": true,

  "alarmWebhookEnabled": true,
  "alarmWebhookUrls": [
    "https://your-server.com/api/alarm/receive"
  ],
  "alarmWebhookSecret": "webhook-hmac-secret",


  "openApiRateLimitEnabled": true,
  "openApiRateLimitPerMinute": 120,
  "openApiRateLimitBurst": 20,
  "openApiWafEnabled": true,

  "webrtcStunUrls": ["stun:stun.l.google.com:19302"],

  "licenseType": "community",
  "licenseKey": ""
}
```

!!! warning "安全提醒"
    上述示例中的密钥、密码均为**占位值**。生产环境部署时，敏感信息（如 `mediaSecret`、Webhook 签名密钥、Cloud Edge Token 等）建议通过**环境变量**注入，而非写入 `config.json` 文件。详见 [环境变量参考](env-vars.md)。

---

## 常用场景的最小化配置片段

下面给出三类典型部署的 **最小可用配置切片**,在已有 `config.json` 基础上替换/合并相应键即可。

### 场景一: 单机最小可用(开发 / 演示)

```jsonc
{
  "code": "beacon-dev-01",
  "name": "Beacon Dev",
  "host": "0.0.0.0",
  "adminPort": 9991,
  "analyzerPort": 9993,
  "mediaHttpPort": 9992,
  "mediaRtspPort": 9994,
  "mediaRtmpPort": 9995,
  "mediaSecret": "dev-only-please-change",
  "modelDir": "./models",
  "modelConcurrency": 1,
  "hardwareDecoderType": "none",
  "hardwareEncoderType": "none",
  "alarmOutboxEnabled": false,
  "saveAlarmType": 1
}
```

特点:CPU 推理、单实例、不启用外发,部署起来最快,**不要用于生产**。

### 场景二: NVIDIA GPU + TensorRT 节点

```jsonc
{
  "code": "beacon-edge-prod-07",
  "name": "Beacon Prod Edge 07",
  "host": "0.0.0.0",
  "modelDir": "/data/beacon/models",
  "modelConcurrency": 4,
  "tensorrtEnginePluginPath": "/data/beacon/plugins/libtrt_helper.so",
  "hardwareDecoderType": "nvdec",
  "hardwareEncoderType": "nvenc",
  "hardwareCodecDeviceId": 0,
  "maxHardwareDecodeChannels": 32,
  "maxHardwareEncodeChannels": 16,
  "alarmOutboxEnabled": true,
  "alarmWebhookEnabled": true,
  "alarmWebhookUrls": ["https://siem.example.com/webhook/beacon"],
  "alarmWebhookSecret": "${BEACON_ALARM_WEBHOOK_SECRET}",

  "openApiRateLimitEnabled": true,
  "openApiRateLimitPerMinute": 600,
  "openApiWafEnabled": true
}
```

要点:启用 GPU、TensorRT Engine 插件、Outbox + Webhook、网关限流;敏感字段全部走环境变量(详见 [环境变量](env-vars.md))。

### 场景三: 边缘低算力(RKNN / Ascend 兼容层)

```jsonc
{
  "code": "beacon-edge-rk3588-12",
  "name": "Beacon Edge RK3588",
  "host": "0.0.0.0",
  "modelDir": "/data/beacon/models",
  "modelConcurrency": 1,
  "compatLibPath": "/usr/local/lib/libbeacon_compat.so",
  "rknpuPreprocessMode": 1,
  "hardwareDecoderType": "none",
  "hardwareEncoderType": "none",
  "saveAlarmType": 2,
  "alarmOutboxEnabled": false,
  "alarmWebhookEnabled": false,
  "alarmHttpReportUrl": "https://cloud.example.com/ingest/alarm"
}
```

要点:

- 关掉 GPU 推理,改用 Compat Plugin(RKNN / Ascend OM)兼容层,详见 [模型格式](../algorithms/models.md)
- `saveAlarmType=2` 表示**只 HTTP 上报、不本地落库**,带宽与磁盘双重节省,但要保证云端接收稳定(云端配合见 [Cloud SaaS v1](../integration/cloud-saas-v1.md))
- 仅发起单实例推理,把算力让给设备本身的服务

!!! note "关于 `gpuId` / `decoder`"
    旧示例里常见的 `gpuId`、`decoder` 并不是当前 `config.json` 全局字段。
    以当前实现为准，系统级部署时应优先关注 `tensorrtEnginePluginPath`、`compatLibPath`、`rknpuPreprocessMode`、`hardwareDecoderType`、`hardwareEncoderType` 这些真实会被 `Analyzer/Core/Config.cpp` 读取的键。

---

## 进一步阅读

- [环境变量](env-vars.md) — 用环境变量覆盖 config.json 字段
- [部署总览](../deployment/index.md) — 不同部署形态的端到端流程
- [安全加固](../operations/security.md) — 凭据管理与轮换
