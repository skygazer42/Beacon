---
title: 配置参考
description: Beacon 配置文件、环境变量、后台设置及其生效边界
icon: material/cog
---

# 配置概览

Beacon 使用 `config.json`、明确列出的环境变量和 Admin 后台设置。它们并不是一套可任意互相覆盖的通用配置框架；每个配置项支持哪些来源，以本页和[环境变量参考](env-vars.md)为准。

---

## 配置来源与优先级 {#priority}

| 配置来源 | 实际用途 | 生效规则 |
|----------|----------|----------|
| `config.json` | Admin、Analyzer 和 MediaServer 的共享运行参数 | 未被专用环境变量覆盖时使用 |
| `BEACON_*` 环境变量 | 密钥、部署模式、Django 安全项及部分运行参数 | 只有代码和文档明确支持的变量才生效 |
| Admin「系统设置」 | 品牌设置及页面列出的运行参数 | 保存到 `settings.json`、数据库或 `config.json`；不同进程的生效时机见下文 |
| 代码默认值 | 未配置字段的回退值 | 最低优先级 |

!!! warning "不存在自动命名映射"
    不能把任意 `config.json` 字段改成大写下划线后当作环境变量。例如，当前没有 `BEACON_ADMIN_PORT`；端口应写在 `config.json` 中。专用环境变量覆盖对应字段，其他变量会被忽略。

```mermaid
graph LR
    A["环境变量<br/><small>BEACON_*</small>"] -->|覆盖| B["config.json"]
    B -->|缺省回退| D["默认值<br/><small>代码内置</small>"]
    C["Admin 后台<br/><small>仅页面列出的设置</small>"] -->|持久化到对应存储| B
    style A fill:#c8e6c9,stroke:#388e3c
    style B fill:#bbdefb,stroke:#1565c0
    style C fill:#fff9c4,stroke:#f9a825
    style D fill:#f5f5f5,stroke:#9e9e9e
```

---

## 配置文件位置 {#file-locations}

### config.json

`config.json` 是 Beacon 的**主配置文件**，位于项目根目录（与 `Admin/`、`Analyzer/`、`MediaServer/` 同级）。Admin 管理服务和 Analyzer 分析引擎均从此文件读取配置。

```text
Beacon/
├── Admin/
│   ├── framework/
│   │   └── settings.py              # Django 框架设置
│   ├── app/
│   │   └── utils/
│   │       ├── Config.py            # config.json 解析器
│   │       ├── OpenApiGateway.py    # API 网关配置
│   │       ├── LdapAuth.py          # LDAP 认证配置
│   │       ├── OidcAuth.py          # OIDC SSO 配置
│   │       └── Otel.py              # OpenTelemetry 配置
│   └── Admin.sqlite3                # 默认 SQLite 数据库
├── Analyzer/
│   └── Analyzer/Core/
│       ├── Config.h                 # Analyzer 配置结构体
│       └── Config.cpp               # Analyzer 配置解析
├── MediaServer/
├── config.json                      ← 主配置文件
└── ...
```

!!! tip "最小可用配置"
    `config.json` 中未指定的参数会使用代码默认值。建议至少显式设置节点标识、端口和独立生成的流媒体密钥：

    ```json title="最简 config.json"
    {
      "code": "beacon-node-01",
      "name": "Beacon 智能分析平台",
      "host": "0.0.0.0",
      "adminPort": 9991,
      "mediaHttpPort": 9992,
      "analyzerPort": 9993,
      "mediaRtspPort": 9994,
      "mediaSecret": "your-media-secret"
    }
    ```

详细参数说明请参阅 **[config.json 参考手册](config-json.md)**。

### Django settings.py

`Admin/framework/settings.py` 是 Django 框架的标准配置文件，包含：

- 数据库连接设置（SQLite / PostgreSQL）
- Session 与 Cookie 安全配置
- CSRF / 安全中间件配置
- 日志系统配置
- 静态文件路径

!!! warning "生产环境必设项"
    当 `BEACON_DJANGO_DEBUG=0`（生产模式）时，以下环境变量**必须**设置：

    - `BEACON_DJANGO_SECRET_KEY`：Django 密钥，必须为高强度随机值（不少于 32 位）
    - `BEACON_DJANGO_ALLOWED_HOSTS`：允许的主机名列表，**不可**包含 `*`

### 环境变量

环境变量以 `BEACON_` 为前缀，主要用于：

- **容器化部署** — 通过 Docker / Kubernetes 注入配置
- **云部署** — 区分 edge / cloud 部署模式
- **安全凭证** — API Token、数据库密码、LDAP/OIDC 与告警签名密钥等敏感信息
- **可观测性** — OpenTelemetry 追踪、日志级别、日志格式等

详细说明请参阅 **[环境变量参考](env-vars.md)**。

---

## 配置加载流程 {#loading}

Admin 启动时的主要配置流程如下。Analyzer 和 MediaServer 会独立读取自己的配置，不能依赖 Admin 进程中的内存修改。

```text
┌──────────────────────────────────────────────────────────┐
│ 1. 读取 config.json（UTF-8，兼容 GBK 回退）                  │
│    └→ 缺失字段使用对应代码默认值                             │
├──────────────────────────────────────────────────────────┤
│ 2. 读取代码明确支持的 BEACON_* 环境变量                      │
│    └→ 专用变量覆盖对应字段；不存在通用自动映射                │
├──────────────────────────────────────────────────────────┤
│ 3. 初始化 Django settings                                  │
│    └→ 校验生产密钥、主机名和数据库 URL                       │
├──────────────────────────────────────────────────────────┤
│ 4. 连接 SQLite 或 PostgreSQL，并启动 Admin 后台服务           │
├──────────────────────────────────────────────────────────┤
│ 5. Analyzer / MediaServer 由部署脚本分别启动                  │
│    └→ 进程启动时重新读取各自配置                              │
└──────────────────────────────────────────────────────────┘
```

!!! note "文件编码"
    系统优先使用 **UTF-8** 编码读取 `config.json`，如果 UTF-8 解析失败则自动回退到 GBK 编码。建议统一使用 UTF-8 编码保存。

---

## 配置校验 {#validation}

Beacon 会校验安全关键项和部分有明确取值范围的字段，但目前没有一个覆盖所有组件、端口和外部依赖的统一启动前校验器。

### 自动校验规则

| 校验项 | 规则 | 触发条件 |
|--------|------|----------|
| `config.json` | 必须能按 UTF-8 或 GBK 解码并解析为 JSON | Admin 初始化配置时 |
| `BEACON_DJANGO_SECRET_KEY` | 不少于 32 位、不以 `django-insecure-` 开头 | `BEACON_DJANGO_DEBUG=0` |
| `BEACON_DJANGO_ALLOWED_HOSTS` | 不得为空、不得包含 `*` | `BEACON_DJANGO_DEBUG=0` |
| `BEACON_CLOUD_DB_URL` | 只接受 PostgreSQL URL，并校验 URL 结构 | 设置该变量时 |
| Cloud 后台设置 | Cloud 地址必须是完整 HTTP(S) URL，启用时必须配置 Edge Token | 从系统设置保存时 |
| 部分数字字段 | 由对应模块限制最小值和最大值 | 加载或保存该字段时 |

端口占用、外部服务可达性、模型兼容性和摄像头连通性需要按部署环境单独检查。

### 手动校验

您也可以在不启动服务的情况下手动校验配置：

```bash
# 1. 校验 config.json JSON 语法
python -m json.tool config.json

# 2. 校验 Django 的生产安全配置
cd Admin && python manage.py check --deploy

# 3. 检查迁移状态和数据库访问
python manage.py migrate --check

# 4. 检查端口是否被占用
ss -tlnp | grep -E '9991|9992|9993|9994'
```

---

## 生效时机 {#hot-reload}

系统设置页面会持久化页面列出的字段，并更新当前 Admin 进程中的对应值。品牌和页面设置通常在刷新页面后可见。不要把它理解为跨进程通用热重载：Analyzer、MediaServer、Gunicorn 的其他 worker 以及后台线程是否重新读取配置，取决于具体调用链。

为获得确定、可重复的部署结果，以下配置修改后应重启对应服务：

- 端口变更（`adminPort`、`mediaHttpPort`、`analyzerPort`、`mediaRtspPort`、`mediaRtmpPort`）
- `host` 绑定地址变更
- 数据库类型切换（SQLite ↔ PostgreSQL）
- `mediaSecret` 流媒体鉴权密钥变更
- 硬件编解码器配置（`hardwareDecoderType`、`hardwareEncoderType` 等）
- WebRTC STUN/TURN 配置
- LDAP / OIDC 认证配置
- `BEACON_DJANGO_SECRET_KEY`

日志级别也是启动时读取；当前没有受支持的 `SIGHUP` 日志热重载接口。

!!! tip "最佳实践"
    对于需要重启的配置变更，建议在维护窗口进行。使用 Docker 或 Kubernetes 部署时，可通过**滚动更新**最大限度减少服务中断时间。

---

## 数据库配置 {#database}

Beacon 默认使用 **SQLite** 作为数据存储后端，适合开发环境和小规模部署。生产环境或云部署推荐使用 PostgreSQL。

=== "SQLite（默认）"

    ```bash
    # 默认路径：Admin/Admin.sqlite3
    # 可通过环境变量覆盖路径
    export BEACON_SQLITE_DB_PATH="/data/beacon/admin.sqlite3"
    export BEACON_SQLITE_TIMEOUT_SECONDS=30
    ```

    !!! note
        SQLite 适合单机部署和开发测试环境。在高并发写入场景下可能遇到锁等待，建议此时切换为 PostgreSQL。

=== "PostgreSQL（云部署推荐）"

    ```bash
    # 使用 DATABASE_URL 格式
    export BEACON_CLOUD_DB_URL="postgres://user:pass@host:5432/beacon"
    ```

当前 `BEACON_CLOUD_DB_URL` 解析器只接受 `postgres://` 和
`postgresql://`。MySQL URL 会被明确拒绝。

---

## 快速参考 {#quick-ref}

| 需求 | 配置方式 | 参考文档 |
|------|---------|---------|
| 修改端口号 | `config.json` 中的 `adminPort` / `mediaHttpPort` 等 | [config.json 参考](config-json.md#server) |
| 设置 API Token | 环境变量 `BEACON_OPEN_API_TOKEN` 或 `config.json` | [环境变量参考](env-vars.md#open-api) |
| 配置告警推送 | `config.json` 中的 `alarm*` 系列参数 | [config.json 参考](config-json.md#alarm) |
| 启用 LDAP 认证 | 环境变量 `BEACON_LDAP_*` 系列 | [环境变量参考](env-vars.md#ldap) |
| 启用 OIDC SSO | 环境变量 `BEACON_OIDC_*` 系列 | [环境变量参考](env-vars.md#oidc) |
| 云部署数据库 | 环境变量 `BEACON_CLOUD_DB_URL` | [环境变量参考](env-vars.md#database) |
| 启用 OpenTelemetry | 环境变量 `BEACON_OTEL_*` 系列 | [环境变量参考](env-vars.md#otel) |
| 配置 API 限流/WAF | `config.json` 或环境变量 `BEACON_OPEN_API_*` | [config.json 参考](config-json.md#api-gateway) |
| 配置 WebRTC | `config.json` 或环境变量 `BEACON_WEBRTC_*` | [config.json 参考](config-json.md#webrtc) |
| 配置 GPU 硬件加速 | `config.json` 中的 `hardware*` 系列参数 | [config.json 参考](config-json.md#hardware) |

---

## 章节导航

| 文档 | 说明 |
|------|------|
| :material-file-document: [config.json 参考手册](config-json.md) | 所有 `config.json` 字段的完整文档，含类型、默认值、示例 |
| :material-console: [环境变量参考](env-vars.md) | 所有 `BEACON_*` 环境变量列表及 Docker / Kubernetes 映射 |
