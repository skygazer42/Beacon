---
title: 环境变量参考
description: Beacon 支持的所有环境变量列表，包括 Docker 和 Kubernetes 部署映射
icon: material/console
---

# 环境变量参考

Beacon 通过明确实现的环境变量覆盖部分 `config.json` 字段，并提供额外的系统级配置。变量通常以 `BEACON_` 开头，但不存在把任意 JSON 字段自动映射为环境变量的机制。

!!! info "优先级"
    本页列出的专用环境变量优先于其“对应 config.json”字段；未列出的变量不会自动生效。详见[配置来源说明](index.md#priority)。

---

## 命名规则 {#naming}

环境变量命名遵循以下规则：

```
BEACON_{SECTION}_{KEY}
```

| 组成部分 | 说明 | 示例 |
|---------|------|------|
| `BEACON_` | 固定前缀 | — |
| `{SECTION}` | 功能分区 | `DJANGO`、`LDAP`、`OIDC`、`ALARM`、`LOG` 等 |
| `{KEY}` | 配置键名（大写下划线风格） | `SECRET_KEY`、`ENABLED`、`HOST` |

**示例：**

| 环境变量 | 对应功能 |
|---------|---------|
| `BEACON_DJANGO_SECRET_KEY` | Django 框架密钥 |
| `BEACON_LDAP_ENABLED` | 启用 LDAP 认证 |
| `BEACON_ALARM_WEBHOOK_URLS` | 告警 Webhook 接收地址列表 |
| `BEACON_LOG_LEVEL` | 日志级别 |

---

## 布尔值解析规则 {#bool-parsing}

所有 `BEACON_*` 布尔类型环境变量支持以下值（**不区分大小写**）：

| 真值 | 假值 |
|------|------|
| `1`、`true`、`yes`、`y`、`on` | 其他任意值或未设置 |

---

## 部署模式 {#deployment-mode}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_DEPLOYMENT_MODE` | string | `"edge"` | 部署模式。`edge` = 边缘/单机部署，`cloud` = 云端 SaaS 部署 |

!!! note "edge 与 cloud 模式的差异"
    - **edge 模式**（默认）：适用于单机或本地网络部署。所有功能在本地运行。
    - **cloud 模式**：启用云端 SaaS 特性，包括多租户、远程管理、云端 RBAC 等。部分仅 edge 模式可用的功能会被隐藏。

---

## Open API 认证与网关 {#open-api}

| 变量名 | 类型 | 默认值 | 对应 config.json | 说明 |
|--------|------|--------|-----------------|------|
| `BEACON_OPEN_API_TOKEN` | string | `""` | `openApiToken` | Open API 认证 Token |
| `BEACON_REQUIRE_OPEN_API_TOKEN` | bool | `false` | — | 是否强制要求所有 Open API 请求携带 Token |
| `BEACON_OPEN_API_RATE_LIMIT_ENABLED` | bool | `false` | `openApiRateLimitEnabled` | 是否启用速率限制 |
| `BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE` | int | `60` | `openApiRateLimitPerMinute` | 每分钟最大请求数 |
| `BEACON_OPEN_API_RATE_LIMIT_BURST` | int | `10` | `openApiRateLimitBurst` | 突发请求允许数 |
| `BEACON_OPEN_API_WAF_ENABLED` | bool | `false` | `openApiWafEnabled` | 是否启用 WAF |
| `BEACON_OPEN_API_WAF_MAX_BODY_BYTES` | int | `1048576` | `openApiWafMaxBodyBytes` | WAF 允许的最大请求体大小（字节） |

---

## 系统路径 {#paths}

| 变量名 | 类型 | 默认值 | 对应 config.json | 说明 |
|--------|------|--------|-----------------|------|
| `BEACON_ROOT_DIR` | string | — | — | Beacon 项目根目录路径 |
| `BEACON_UPLOAD_DIR` | string | — | `uploadDir` | 上传文件目录 |
| `BEACON_MODEL_DIR` | string | — | `modelDir` | 模型文件目录 |

---

## 数据库 {#database}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_SQLITE_DB_PATH` | string | `""` | 自定义 SQLite 数据库文件路径（覆盖默认的 `Admin/Admin.sqlite3`） |
| `BEACON_SQLITE_TIMEOUT_SECONDS` | int | `30` | SQLite 写锁等待超时（秒，1~300） |
| `BEACON_CLOUD_DB_URL` | string | `""` | 云部署数据库连接 URL |

!!! tip "数据库 URL 格式"

    === "PostgreSQL"
        ```
        postgres://user:password@host:5432/dbname
        ```

    当前只支持 `postgres://` 与 `postgresql://` URL；其他 scheme 会被拒绝。

---

## Django 框架 {#django}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_DJANGO_DEBUG` | bool | `true` | 是否启用 Django 调试模式。**生产环境必须设为 `false`** |
| `BEACON_DJANGO_SECRET_KEY` | string | — | Django 密钥。生产模式下**必须**设置为高强度随机值（>=32 字符） |
| `BEACON_DJANGO_ALLOWED_HOSTS` | string | `"*"`(调试) / `""`(生产) | 允许的主机名列表（逗号分隔）。生产模式下不可包含 `*` |
| `BEACON_SESSION_COOKIE_AGE_SECONDS` | int | `604800` | Session 过期时间（秒），默认 7 天 |
| `BEACON_DJANGO_SESSION_COOKIE_SECURE` | bool | 非调试默认 `true` | Session Cookie 是否仅通过 HTTPS 传输 |
| `BEACON_DJANGO_CSRF_COOKIE_SECURE` | bool | 非调试默认 `true` | CSRF Cookie 是否仅通过 HTTPS 传输 |
| `BEACON_DJANGO_SECURE_SSL_REDIRECT` | bool | `false` | 是否将 HTTP 请求自动重定向到 HTTPS |
| `BEACON_DJANGO_TRUST_X_FORWARDED_PROTO` | bool | `false` | 是否信任反向代理的 `X-Forwarded-Proto` 头（Nginx 反代时启用） |
| `BEACON_DJANGO_HSTS_SECONDS` | int | `0` | HSTS 有效秒数；确认正式域名全站 HTTPS 后再设为 `31536000` |
| `BEACON_DJANGO_HSTS_INCLUDE_SUBDOMAINS` | bool | `false` | HSTS 是否覆盖所有子域名 |
| `BEACON_DJANGO_HSTS_PRELOAD` | bool | `false` | 是否声明 HSTS preload；提交预加载列表前需单独评估 |
| `BEACON_DJANGO_CSRF_TRUSTED_ORIGINS` | string | `""` | CSRF 可信源列表（逗号分隔），如 `https://beacon.example.com` |

!!! danger "生产环境必设项"
    当 `BEACON_DJANGO_DEBUG=0` 时，以下变量**必须**正确设置，否则服务将拒绝启动：

    ```bash
    # 生成高强度随机密钥
    export BEACON_DJANGO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"

    # 设置允许的主机名（不可为 *）
    export BEACON_DJANGO_ALLOWED_HOSTS="beacon.example.com,192.168.1.100"
    ```

---

## 日志配置 {#logging}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_LOG_LEVEL` | string | `"INFO"` | 日志级别。可选：`DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `BEACON_LOG_FORMAT` | string | `"text"` | 日志格式。`text` = 文本格式，`json` = JSON 结构化格式 |
| `BEACON_LOG_TO_FILE` | bool | `false` | 是否将日志写入文件 |
| `BEACON_LOG_DIR` | string | `"Admin/logs"` | 日志文件目录 |
| `BEACON_LOG_FILE_MAX_MB` | int | `50` | 单个日志文件最大大小（MB，1~1024） |
| `BEACON_LOG_FILE_BACKUP_COUNT` | int | `10` | 日志文件保留数量（1~100） |
| `BEACON_LOG_FILE_RETENTION_DAYS` | int | `0` | 日志保留天数。`0` = 按文件大小轮转，`>0` = 按天轮转 |

!!! tip "生产环境日志建议"
    ```bash
    # 使用 JSON 格式便于日志采集系统（ELK/Loki）解析
    export BEACON_LOG_FORMAT=json
    export BEACON_LOG_LEVEL=INFO

    # 启用文件日志并设置轮转策略
    export BEACON_LOG_TO_FILE=true
    export BEACON_LOG_DIR=/var/log/beacon
    export BEACON_LOG_FILE_MAX_MB=100
    export BEACON_LOG_FILE_BACKUP_COUNT=20
    export BEACON_LOG_FILE_RETENTION_DAYS=30
    ```

---

## LDAP/AD 认证 {#ldap}

通过 LDAP/Active Directory 进行用户认证，实现与企业目录服务的集成。

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_LDAP_ENABLED` | bool | `false` | 是否启用 LDAP 认证 |
| `BEACON_LDAP_URL` | string | `""` | LDAP 服务器地址（如 `ldap://host:389` 或 `ldaps://host:636`） |
| `BEACON_LDAP_USE_SSL` | bool | `false` | 是否使用 SSL 连接。`ldaps://` 时自动启用 |
| `BEACON_LDAP_STARTTLS` | bool | `false` | 是否使用 STARTTLS 升级连接 |
| `BEACON_LDAP_TLS_VERIFY` | bool | `true` | 是否验证 TLS 证书 |
| `BEACON_LDAP_BIND_DN` | string | `""` | 绑定 DN，用于搜索用户 |
| `BEACON_LDAP_BIND_PASSWORD` | string | `""` | 绑定密码 |
| `BEACON_LDAP_BASE_DN` | string | `""` | 搜索绑定模式的基础 DN |
| `BEACON_LDAP_USER_FILTER` | string | `"(uid={username})"` | 搜索绑定模式的用户过滤器 |
| `BEACON_LDAP_USER_DN_TEMPLATE` | string | `""` | 直接绑定模式的用户 DN 模板；设置后不使用服务账号搜索 |
| `BEACON_LDAP_EMAIL_ATTR` | string | `"mail"` | 邮箱 LDAP 属性名 |
| `BEACON_LDAP_CONNECT_TIMEOUT_SECONDS` | float | — | 连接超时时间（秒，1~60） |

!!! example "LDAP 配置示例"

    === "OpenLDAP"
        ```bash
        export BEACON_LDAP_ENABLED=true
        export BEACON_LDAP_URL="ldap://ldap.example.com:389"
        export BEACON_LDAP_STARTTLS=true
        export BEACON_LDAP_BIND_DN="cn=readonly,dc=example,dc=com"
        export BEACON_LDAP_BIND_PASSWORD="readonly-password"
        export BEACON_LDAP_BASE_DN="ou=people,dc=example,dc=com"
        export BEACON_LDAP_USER_FILTER="(uid={username})"
        ```

    === "Active Directory"
        ```bash
        export BEACON_LDAP_ENABLED=true
        export BEACON_LDAP_URL="ldaps://ad.example.com:636"
        export BEACON_LDAP_BIND_DN="cn=svc-beacon,cn=Users,dc=corp,dc=example,dc=com"
        export BEACON_LDAP_BIND_PASSWORD="service-password"
        export BEACON_LDAP_BASE_DN="dc=corp,dc=example,dc=com"
        export BEACON_LDAP_USER_FILTER="(sAMAccountName={username})"
        ```

---

## OIDC 单点登录 {#oidc}

通过 OpenID Connect (OIDC) 协议实现单点登录（SSO），兼容多种身份提供商（Keycloak、Azure AD、Okta 等）。

### 基础配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_OIDC_ENABLED` | bool | `false` | 是否启用 OIDC SSO |
| `BEACON_OIDC_CLIENT_ID` | string | `""` | 默认 Provider 的 Client ID |
| `BEACON_OIDC_CLIENT_SECRET` | string | `""` | 默认 Provider 的 Client Secret |
| `BEACON_OIDC_AUTHORIZATION_ENDPOINT` | string | `""` | 授权端点 URL |
| `BEACON_OIDC_TOKEN_ENDPOINT` | string | `""` | Token 端点 URL |
| `BEACON_OIDC_USERINFO_ENDPOINT` | string | `""` | UserInfo 端点 URL |
| `BEACON_OIDC_SCOPE` | string | `"openid profile email"` | 请求的 OAuth Scope |
| `BEACON_OIDC_END_SESSION_ENDPOINT` | string | `""` | Provider 的退出端点 |

### 多 Provider 配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_OIDC_PROVIDERS_JSON` | string (JSON) | `""` | 多 Provider 配置（顶层为 Provider ID 到配置对象的映射） |

??? example "多 Provider JSON 配置示例"
    ```bash
    export BEACON_OIDC_PROVIDERS_JSON='{
        "keycloak": {
          "client_id": "beacon-app",
          "client_secret": "secret",
          "authorization_endpoint": "https://keycloak.example.com/auth/realms/beacon/protocol/openid-connect/auth",
          "token_endpoint": "https://keycloak.example.com/auth/realms/beacon/protocol/openid-connect/token",
          "userinfo_endpoint": "https://keycloak.example.com/auth/realms/beacon/protocol/openid-connect/userinfo",
          "display_name": "Keycloak SSO"
        },
        "azure_ad": {
          "client_id": "azure-client-id",
          "client_secret": "azure-secret",
          "authorization_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
          "token_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
          "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
          "display_name": "Azure AD"
        }
    }'
    ```

!!! info "Provider ID 命名规则"
    Provider ID 仅允许包含字母、数字、下划线、连字符和点号（`[A-Za-z0-9_.-]+`），最大长度 64 个字符。

---

## TOTP 两步验证 {#totp}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_TOTP_SENSITIVE_REAUTH_ENABLED` | bool | `false` | 敏感操作是否要求 TOTP 重新认证 |
| `BEACON_TOTP_SENSITIVE_REAUTH_PREFIXES` | string | `""` | 需要 TOTP 重认证的 URL 前缀（逗号分隔） |
| `BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS` | int | `300` | TOTP 重认证有效窗口（秒，30~3600） |

---

## 登录安全 {#login-security}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_LOGIN_LOCKOUT_ENABLED` | bool | `false` | 是否启用登录失败锁定 |
| `BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS` | int | `5` | 锁定前允许的最大失败次数 |
| `BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS` | int | `300` | 失败计数时间窗口（秒） |
| `BEACON_LOGIN_LOCKOUT_SECONDS` | int | `900` | 锁定持续时间（秒） |
| `BEACON_LOGIN_CAPTCHA_ENABLED` | bool | `false` | 是否启用登录验证码 |

---

## OpenTelemetry 可观测性 {#otel}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_OTEL_ENABLED` | bool | `false` | 是否启用 OpenTelemetry 分布式追踪 |
| `BEACON_OTEL_OTLP_ENDPOINT` | string | `""` | OTLP/HTTP 导出端点（如 `http://otel-collector:4318`） |
| `BEACON_OTEL_SAMPLE_RATIO` | float | `1.0` | 采样率（0.0~1.0）。`1.0` = 全量，`0.1` = 10% |

!!! example "接入 Jaeger 示例"
    ```bash
    export BEACON_OTEL_ENABLED=true
    export BEACON_OTEL_OTLP_ENDPOINT="http://jaeger:4318"
    export BEACON_OTEL_SAMPLE_RATIO=0.5
    ```

---

## 云端功能 {#cloud}

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_CLOUD_ENABLED` | bool | `false` | 是否启用云端平台功能 |
| `BEACON_CLOUD_BASE_URL` | string | `""` | 云端平台基地址 |
| `BEACON_CLOUD_EDGE_TOKEN` | string | `""` | 边缘节点接入云端的认证 Token |
| `BEACON_CLOUD_UPLOAD_TIMEOUT_SECONDS` | int | `10` | 告警数据上传超时（秒，1~60） |
| `BEACON_CLOUD_INGEST_TIMEOUT_SECONDS` | int | `5` | 数据摄入超时（秒，1~60） |

---

## 数字人监管运行时 {#digital-human-runtime}

以下变量用于 Beacon 本地承接数字人终端注册、上报、防重放、截图存储与 AI/钉钉运行时链路。

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET` | string | `""` | 采集端 `machineCode` 生成/校验密钥；启用对应接口前必须设置 |
| `BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY` | string | `""` | 采集端上报 `Authorization` 密文使用的 SM4 密钥；启用对应接口前必须设置 |
| `BEACON_DIGITAL_HUMAN_REPORT_DEFAULT_INTERVAL_SEC` | int | `30` | Beacon 返回给采集端的默认下一次上报间隔 |
| `BEACON_DIGITAL_HUMAN_REPORT_IMAGE_MAX_BYTES` | int | `524288` | 设备截图 Base64 解码后的大小上限（字节） |
| `BEACON_DIGITAL_HUMAN_REPLAY_REDIS_URL` | string | `""` | 数字人防重放专用 Redis 连接串；生产推荐优先设置 |
| `BEACON_DIGITAL_HUMAN_REDIS_URL` | string | `""` | 数字人防重放 Redis 的兼容别名 |
| `BEACON_DIGITAL_HUMAN_REPLAY_CACHE_PREFIX` | string | `"beacon:digital-human:replay"` | Redis 防重放 key 前缀 |
| `BEACON_DIGITAL_HUMAN_S3_BUCKET` | string | `""` | 数字人截图对象存储 bucket；优先于 `BEACON_CLOUD_S3_BUCKET` |

### 相关共享配置

数字人截图对象存储还会复用以下通用 S3 变量：

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `BEACON_CLOUD_S3_BUCKET` | string | `""` | 当未设置 `BEACON_DIGITAL_HUMAN_S3_BUCKET` 时，作为截图 bucket 回退值 |
| `BEACON_CLOUD_S3_REGION` | string | `"us-east-1"` | S3/MinIO region |
| `BEACON_CLOUD_S3_ENDPOINT_URL` | string | `""` | MinIO 或私有 S3 endpoint |
| `BEACON_CLOUD_S3_ACCESS_KEY_ID` | string | `""` | S3 Access Key |
| `BEACON_CLOUD_S3_SECRET_ACCESS_KEY` | string | `""` | S3 Secret Key |

### 运行时优先级

- 防重放：`Redis -> Django cache -> 进程内内存`
- 截图存储：`数字人专用 bucket -> 通用 cloud bucket -> 本地 uploadDir -> 行内 base64 兜底`

!!! warning "依赖前置"
    若要启用截图对象存储，请安装 `Admin/requirements-optional.txt` 中的 `boto3`。
    数字人共享防重放默认使用 Django cache；只有多实例部署明确需要 Redis 时再单独安装 Redis 客户端。

---

## 告警通道覆盖 {#alarm-sinks}

以下环境变量可覆盖 `config.json` 中的同名告警通道配置：

### Webhook

| 变量名 | 对应 config.json | 说明 |
|--------|-----------------|------|
| `BEACON_ALARM_WEBHOOK_URLS` | `alarmWebhookUrls` | 多个 URL 用逗号分隔 |
| `BEACON_ALARM_WEBHOOK_SECRET` | `alarmWebhookSecret` | HMAC 签名密钥 |
| `BEACON_ALARM_WEBHOOK_TIMEOUT_SECONDS` | `alarmWebhookTimeoutSeconds` | 请求超时（秒） |

### 其他

| 变量名 | 对应 config.json | 说明 |
|--------|-----------------|------|
| `BEACON_ALARM_UPLOAD_INCLUDE_BASE64` | `alarmUploadIncludeBase64` | 是否包含 Base64 图片 |
| `BEACON_ALARM_PRECHECK_ENABLED` | `alarmPrecheckEnabled` | 是否启用前置检查 |
| `BEACON_ALARM_PRECHECK_URL` | `alarmPrecheckUrl` | 前置检查接口 URL |
| `BEACON_ALARM_PRECHECK_TIMEOUT_SECONDS` | `alarmPrecheckTimeoutSeconds` | 前置检查超时 |
| `BEACON_ALARM_PRECHECK_FAIL_OPEN` | `alarmPrecheckFailOpen` | 失败时是否放行 |

---

## 模型相关 {#model-env}

| 变量名 | 对应 config.json | 说明 |
|--------|-----------------|------|
| `BEACON_MODEL_ENCRYPT` | `modelEncrypt` | 是否启用模型加密 |
| `BEACON_MODEL_ENCRYPT_KEY` | `modelEncryptKey` | 解密密钥 |
| `BEACON_MODEL_ENCRYPT_SUFFIX` | `modelEncryptSuffix` | 加密文件后缀 |
| `BEACON_MODEL_DECRYPT_DIR` | `modelDecryptDir` | 解密缓存目录 |
| `BEACON_MODEL_CACHE_SECONDS` | `modelCacheSeconds` | 模型空闲缓存时长 |

---

## WebRTC 相关 {#webrtc-env}

| 变量名 | 对应 config.json | 说明 |
|--------|-----------------|------|
| `BEACON_WEBRTC_STUN_URLS` | `webrtcStunUrls` | STUN 地址列表（逗号分隔） |
| `BEACON_WEBRTC_TURN_URL` | `webrtcTurnUrl` | TURN 地址 |
| `BEACON_WEBRTC_TURN_USERNAME` | `webrtcTurnUsername` | TURN 用户名 |
| `BEACON_WEBRTC_TURN_PASSWORD` | `webrtcTurnPassword` | TURN 密码 |
| `BEACON_WEBRTC_SELFCHECK_TIMEOUT_SECONDS` | `webrtcSelfCheckTimeoutSeconds` | 自检超时 |

---

## GB28181 相关 {#gb28181-env}

| 变量名 | 对应 config.json | 说明 |
|--------|-----------------|------|
| `BEACON_GB28181_PROVIDER` | `gb28181Provider` | 接入提供商 |
| `BEACON_GB28181_WVP_BASE_URL` | `gb28181WvpBaseUrl` | WVP-PRO 基地址 |
| `BEACON_GB28181_TRANSPORT_MODE` | `gb28181TransportMode` | 传输模式 |
| `BEACON_GB28181_HTTP_TIMEOUT_SECONDS` | `gb28181HttpTimeoutSeconds` | HTTP 超时 |

---

## Docker 部署 {#docker}

### Docker Compose 示例

```yaml title="docker-compose.yml"
services:
  beacon-admin:
    image: beacon/admin:latest
    ports:
      - "9991:9991"
    environment:
      # --- 部署模式 ---
      - BEACON_DEPLOYMENT_MODE=edge

      # --- Django 安全（生产必填） ---
      - BEACON_DJANGO_DEBUG=0
      - BEACON_DJANGO_SECRET_KEY=${BEACON_SECRET_KEY}
      - BEACON_DJANGO_ALLOWED_HOSTS=beacon.example.com
      - BEACON_DJANGO_CSRF_TRUSTED_ORIGINS=https://beacon.example.com

      # --- 数据库 ---
      - BEACON_CLOUD_DB_URL=postgres://beacon:${DB_PASSWORD}@db:5432/beacon

      # --- API 认证 ---
      - BEACON_OPEN_API_TOKEN=${BEACON_API_TOKEN}
      - BEACON_OPEN_API_RATE_LIMIT_ENABLED=true
      - BEACON_OPEN_API_WAF_ENABLED=true

      # --- 日志 ---
      - BEACON_LOG_LEVEL=INFO
      - BEACON_LOG_FORMAT=json

      # --- 告警通道 ---
      - BEACON_ALARM_WEBHOOK_URLS=https://your-server.com/api/alarm
      - BEACON_ALARM_WEBHOOK_SECRET=${WEBHOOK_SECRET}

      # --- 可选：LDAP ---
      - BEACON_LDAP_ENABLED=${LDAP_ENABLED:-false}
      - BEACON_LDAP_URL=${LDAP_URL:-}
      - BEACON_LDAP_BIND_DN=${LDAP_BIND_DN:-}
      - BEACON_LDAP_BIND_PASSWORD=${LDAP_BIND_PASSWORD:-}
      - BEACON_LDAP_BASE_DN=${LDAP_SEARCH_BASE:-}
      - BEACON_LDAP_USER_FILTER=${LDAP_SEARCH_FILTER:-}
    volumes:
      - beacon-data:/data/beacon
      - ./config.json:/app/config.json:ro

  beacon-analyzer:
    image: beacon/analyzer:latest
    ports:
      - "9993:9993"
    volumes:
      - ./config.json:/app/config.json:ro
      - beacon-models:/data/beacon/models

  beacon-media:
    image: beacon/mediaserver:latest
    ports:
      - "9992:9992"
      - "9994:9994"
      - "9995:9995"
    volumes:
      - ./config.json:/app/config.json:ro

volumes:
  beacon-data:
  beacon-models:
```

### Docker 环境变量文件

建议使用 `.env` 文件管理敏感信息：

```bash title=".env"
# 数据库
DB_PASSWORD=your-db-password

# Django 安全
BEACON_SECRET_KEY=your-random-secret-key-at-least-32-chars

# API 认证
BEACON_API_TOKEN=your-api-token

# Webhook
WEBHOOK_SECRET=your-webhook-hmac-secret

# LDAP（可选）
LDAP_ENABLED=false
LDAP_URL=
LDAP_BIND_DN=
LDAP_BIND_PASSWORD=
LDAP_SEARCH_BASE=
LDAP_SEARCH_FILTER=
```

!!! danger "安全警告"
    `.env` 文件包含敏感信息，**绝不**应提交到版本控制系统中。请确保 `.gitignore` 中包含 `.env`。

---

## Kubernetes 部署 {#kubernetes}

### ConfigMap — 非敏感配置

```yaml title="beacon-configmap.yaml"
apiVersion: v1
kind: ConfigMap
metadata:
  name: beacon-config
  namespace: beacon
data:
  # 部署模式
  BEACON_DEPLOYMENT_MODE: "edge"

  # Django
  BEACON_DJANGO_DEBUG: "0"
  BEACON_DJANGO_ALLOWED_HOSTS: "beacon.example.com"
  BEACON_DJANGO_CSRF_TRUSTED_ORIGINS: "https://beacon.example.com"
  BEACON_DJANGO_TRUST_X_FORWARDED_PROTO: "true"

  # API 网关
  BEACON_OPEN_API_RATE_LIMIT_ENABLED: "true"
  BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE: "120"
  BEACON_OPEN_API_WAF_ENABLED: "true"

  # 日志
  BEACON_LOG_LEVEL: "INFO"
  BEACON_LOG_FORMAT: "json"

  # 路径
  BEACON_UPLOAD_DIR: "/data/beacon/upload"
  BEACON_MODEL_DIR: "/data/beacon/models"
  BEACON_LOG_DIR: "/var/log/beacon"

  # OpenTelemetry
  BEACON_OTEL_ENABLED: "true"
  BEACON_OTEL_OTLP_ENDPOINT: "http://otel-collector.monitoring:4318"
  BEACON_OTEL_SAMPLE_RATIO: "0.5"
```

### Secret — 敏感配置

```yaml title="beacon-secret.yaml"
apiVersion: v1
kind: Secret
metadata:
  name: beacon-secrets
  namespace: beacon
type: Opaque
stringData:
  BEACON_DJANGO_SECRET_KEY: "your-random-secret-key"
  BEACON_OPEN_API_TOKEN: "your-api-token"
  BEACON_CLOUD_DB_URL: "postgres://beacon:password@pg-service:5432/beacon"
  BEACON_ALARM_WEBHOOK_SECRET: "your-webhook-secret"
  BEACON_CLOUD_EDGE_TOKEN: "your-cloud-edge-token"
  BEACON_LDAP_BIND_PASSWORD: "ldap-password"
  BEACON_OIDC_CLIENT_SECRET: "oidc-client-secret"
```

!!! tip "建议使用 External Secrets Operator"
    生产环境建议使用 [External Secrets Operator](https://external-secrets.io/) 从 Vault、AWS Secrets Manager、Azure Key Vault 等外部密钥管理系统同步 Secret，避免在 YAML 中明文存储敏感信息。

### Deployment 引用示例

```yaml title="beacon-deployment.yaml (片段)"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: beacon-admin
  namespace: beacon
spec:
  template:
    spec:
      containers:
        - name: admin
          image: beacon/admin:latest
          envFrom:
            - configMapRef:
                name: beacon-config
            - secretRef:
                name: beacon-secrets
          volumeMounts:
            - name: config-volume
              mountPath: /app/config.json
              subPath: config.json
              readOnly: true
            - name: data-volume
              mountPath: /data/beacon
      volumes:
        - name: config-volume
          configMap:
            name: beacon-config-file
        - name: data-volume
          persistentVolumeClaim:
            claimName: beacon-data-pvc
```

---

## 优先级规则详解 {#precedence}

配置值的最终生效遵循以下优先级（从高到低）：

```text
专用环境变量  >  对应的 config.json 字段  >  代码默认值
```

### 具体规则

1. **只有专用变量参与覆盖** — 例如 `BEACON_OPEN_API_TOKEN` 会覆盖 `openApiToken`；当前没有 `BEACON_ADMIN_PORT`，端口仍由 `config.json` 配置
2. **config.json 覆盖默认值** — `config.json` 中显式设置的值覆盖代码内置默认值
3. **仅部分参数支持环境变量覆盖** — 并非所有 `config.json` 参数都有对应的环境变量，本文档中未列出的参数只能通过 `config.json` 配置
4. **列表类型的转换** — 环境变量中的列表值使用**逗号分隔**，例如 `BEACON_ALARM_WEBHOOK_URLS="url1,url2"` 等价于 `config.json` 中的 `["url1", "url2"]`
5. **JSON 类型的传递** — 复杂对象（如 `BEACON_OIDC_PROVIDERS_JSON`）直接传递 JSON 字符串

### 调试配置生效情况

启动 Admin 后可在「系统设置」查看该页面管理的配置。页面不会展示所有环境变量，也不应作为密钥回读接口；确认容器注入值时请使用部署平台的配置视图，并避免把密钥打印到日志。
