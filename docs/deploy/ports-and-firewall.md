# Beacon 端口矩阵与防火墙策略（工业交付）

本文档用于统一 Beacon 在单机交付与试运行阶段的端口口径、网络流向与防火墙建议，目标是：

- 明确默认端口与其用途（来自 `config.json`）
- 给出最小开放面（最小权限网络原则）的建议
- 形成可复用的现场网络巡检清单

适用范围：

- Edge 单机部署（Admin + Analyzer + MediaServer）
- 试运行阶段在同一局域网内的多机部署（组件拆分到不同主机）

相关文档：

- Edge 全栈部署：`docs/deploy/edge-full-stack.md`
- 安全加固基线：`docs/deploy/security-hardening.md`
- 上线检查清单：`docs/deploy/go-live-checklist.md`

---

## 1. 默认端口（来自 `config.json`）

Beacon 默认端口字段（可按交付环境调整）：

| 组件 | 字段 | 默认值 | 协议 | 用途 |
|---|---|---:|---|---|
| Admin | `adminPort` | 9991 | HTTP | 管理后台 UI + Admin API + OpenAPI/Ops |
| MediaServer | `mediaHttpPort` | 9992 | HTTP | ZLMediaKit HTTP API（Admin 调用） |
| Analyzer | `analyzerPort` | 9993 | HTTP | Analyzer API（Admin 调用） |
| MediaServer | `mediaRtspPort` | 9994 | RTSP | ZLMediaKit RTSP（播放器/拉流链路） |
| MediaServer | `mediaRtmpPort` | 9995 | RTMP | ZLMediaKit RTMP（可选） |

说明：

- 表中端口仅覆盖 Beacon 侧“固定会用到的端口字段”。MediaServer 的其他能力端口（例如 HLS/HTTP-FLV/WebRTC）以实际运行目录的 `config.ini` 为准。
- 工业交付建议将端口配置固化在 `config.json`，并与 MediaServer `config.ini` 对齐（至少对齐 HTTP/RTSP/RTMP 与 `secret`）。

---

## 2. 网络流向（谁访问谁）

### 2.1 最常见单机部署（建议默认）

单机部署的典型网络流向：

| 来源 | 目标 | 端口/协议 | 目的 |
|---|---|---|---|
| 浏览器/运维客户端 | Admin | `adminPort` / HTTP(S) | 登录、配置、查看告警、运维接口 |
| Admin | Analyzer | `analyzerPort` / HTTP | 下发布控、查询 controls、健康检查等 |
| Admin | MediaServer | `mediaHttpPort` / HTTP | `addStreamProxy` 等媒体侧控制 |
| MediaServer | 摄像头/RTSP 源 | 通常 554/RTSP（或自定义） | 从源端拉流（pull） |
| 播放器（网页/ffplay/VLC） | MediaServer | `mediaRtspPort` / RTSP（或其他协议端口） | 播放代理后的流 |

说明：

- 生产建议将 Admin 置于反向代理后（443 对外），并在网络层限制 Analyzer/MediaServer 仅内网可达。
- 若播放器统一通过 Admin 域名访问（例如 HLS/HTTP-FLV），需确保反向代理对 MediaServer 的相关路径做正确转发；具体端口以 `MediaServer/config.ini` 为准。

### 2.2 多机部署（同一局域网，组件拆分）

组件拆分时，至少保证以下连通：

| 来源 | 目标 | 端口/协议 | 说明 |
|---|---|---|---|
| Admin 主机 | Analyzer 主机 | `analyzerPort` / HTTP | Admin 需可访问 Analyzer API |
| Admin 主机 | MediaServer 主机 | `mediaHttpPort` / HTTP | Admin 需可访问 ZLM HTTP API |
| Analyzer 主机 | MediaServer 主机 | RTSP（通常 `mediaRtspPort`） | Analyzer 通常从本机/内网 MediaServer 拉流（以实际实现与配置为准） |
| MediaServer 主机 | 摄像头/RTSP 源 | 554/RTSP（或自定义） | MediaServer 从源端拉流 |

---

## 3. 防火墙开放建议（按最小暴露面）

### 3.1 场景 A：内网试运行（无公网）

建议策略：

- Admin 对试运行网段开放 `adminPort`（或由反向代理统一开放 443）。
- Analyzer 与 MediaServer 的管理端口（`analyzerPort` / `mediaHttpPort`）仅对 Admin 主机开放。
- MediaServer 的播放端口按需求开放给“播放客户端所在网段”（例如 `mediaRtspPort`）。

最小开放面示例（单机）：

- 入站开放：
  - Admin：`adminPort/tcp`
  - MediaServer：`mediaRtspPort/tcp`（如需要 RTSP 播放）
- 入站限制（建议）：
  - Analyzer：`analyzerPort/tcp` 仅允许来自 Admin 主机
  - MediaServer HTTP API：`mediaHttpPort/tcp` 仅允许来自 Admin 主机

### 3.2 场景 B：反向代理 + HTTPS（对外提供访问）

建议策略：

- 对外仅开放 443（以及按需求开放的媒体播放端口）。
- Admin 监听的 `adminPort` 仅对本机或反向代理主机开放。
- 强制开启 OpenAPI 鉴权（`BEACON_REQUIRE_OPEN_API_TOKEN=1` 或仅使用 DB ApiKey），避免“反代后 loopback 误放行”。

参考：

- `docs/deploy/reverse-proxy-nginx.md`
- `docs/deploy/security-hardening.md`

### 3.3 场景 C：Cloud POC（Docker Compose）

Cloud POC 端口以 `deploy/cloud-saas-v1/compose.yml` 为准，常见映射：

- Admin：宿主机 `9991` -> 容器内 `8000`
- MinIO：`9000/9001`（POC 对外暴露，生产通常不建议直接暴露）

说明：

- POC 仅用于快速功能测试；生产环境应按安全基线收敛端口暴露策略。

---

## 4. 网络巡检命令（现场可执行）

### 4.1 Windows（PowerShell）

检查端口监听：

```powershell
netstat -ano | Select-String -Pattern ":9991",":9992",":9993",":9994",":9995"
```

检查到目标端口的连通性（TCP）：

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 9991
Test-NetConnection -ComputerName 127.0.0.1 -Port 9993
```

### 4.2 Linux

检查监听：

```bash
ss -tlnp | grep -E "(:9991|:9992|:9993|:9994|:9995)"
```

检查连通：

```bash
nc -vz 127.0.0.1 9991
nc -vz 127.0.0.1 9993
```

---

## 5. 常见问题（端口/防火墙相关）

1. Admin 页面可打开，但播放/拉流相关操作失败  
优先排查：

- `mediaSecret` 是否对齐（`config.json.mediaSecret` 与 `MediaServer/config.ini [api].secret`）
- `mediaHttpPort` 是否对齐（`config.json.mediaHttpPort` 与 `config.ini [http].port`）
- `mediaHttpPort` 是否仅在本机监听或被防火墙拦截（Admin 无法访问）

2. Stream 代理失败（ZLM 无法拉到 RTSP 源）  
优先排查：

- MediaServer 主机到摄像头的网络连通性与防火墙
- RTSP 源地址是否可达（先用 `ffprobe/ffplay/VLC` 验证源端）

3. `/metrics` `/open/ops/*` 访问 401/403  
优先排查：

- OpenAPI Token/ApiKey 鉴权是否配置正确（`BEACON_REQUIRE_OPEN_API_TOKEN`、ApiKey scope）
- OpenAPI IP allowlist/denylist 是否误拦截（`BEACON_OPEN_API_IP_*`）

