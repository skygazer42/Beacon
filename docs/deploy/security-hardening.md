# Beacon 安全加固指南（工业交付）

本文档用于汇总 Beacon 在工业交付/试运行阶段的常见安全加固项，覆盖：

- 安全边界与端口暴露策略
- OpenAPI/Ops 鉴权与密钥资产治理（Token / ApiKey / Pepper）
- IP allowlist/denylist、速率限制（Rate Limit）、WAF 轻量防护
- 登录安全（验证码、登录锁定、反代场景的真实源 IP）
- TOTP 敏感操作二次确认（re-auth）
- 允许 iframe 嵌入的安全策略
- SSO（OIDC）与 LDAP/AD 接入基线
- 日志/诊断包的敏感信息处理建议

说明：

- 本文档以“可落地”为目标：以 Beacon 现有配置/实现为准，不引入未落地能力。
- 生产环境建议将 Admin 暴露在受控网络与反向代理之后，并仅对外开放必要端口。

相关文档：

- 端口与防火墙策略：`docs/deploy/ports-and-firewall.md`
- 反向代理部署（Nginx / HTTPS）：`docs/deploy/reverse-proxy-nginx.md`
- 上线与运行阶段检查清单：`docs/deploy/go-live-checklist.md`

---

## 1. 安全边界与威胁面

Beacon 常见组件与接口边界：

- Admin（Django Web）：管理后台 UI + 业务 API + OpenAPI/Ops 入口。
- Analyzer（C++）：算法运行与布控执行；提供 HTTP API（/api/*）。
- MediaServer（ZLMediaKit）：RTSP/HTTP-FLV/HLS/WebRTC 等媒体能力；提供 HTTP API（/index/api/*）。

接口类型（按安全策略区分）：

- Web UI：依赖登录 Session（浏览器访问）。
- OpenAPI/Ops：面向机器调用（无需 Web Session），由 Token/ApiKey(scope) 鉴权（见下文）。
- 内部互调：Admin -> Analyzer/MediaServer（通常应限制为同机或内网访问）。

---

## 2. 端口暴露与网络隔离策略

推荐的对外暴露策略（通用工业交付）：

- 仅对外暴露 Admin（默认 `adminPort=9991`），并置于反向代理（Nginx/Ingress）后统一做 TLS、访问控制与审计。
- Analyzer（默认 `analyzerPort=9993`）与 MediaServer HTTP（默认 `mediaHttpPort=9992`）优先仅对内网或本机开放。
- MediaServer 的 RTSP/RTMP/WebRTC 端口按场景开放；若仅在内网播放，优先限制为内网可达。

常见风险：

- 在公网暴露 `9992/9993` 会显著扩大攻击面；若确需暴露，至少启用强鉴权、IP 策略与速率限制，并配合网关/WAF。
- 反向代理场景下，如果 `REMOTE_ADDR` 被变为 loopback（例如 127.0.0.1），必须开启强制 Token（`BEACON_REQUIRE_OPEN_API_TOKEN=1`），避免“误放行 loopback”。

---

## 3. 鉴权与密钥资产（Token / ApiKey / Pepper）

### 3.1 OpenAPI legacy Token（共享 Token，兼容模式）

Token 读取顺序（Admin/Analyzer）：

1. 环境变量 `BEACON_OPEN_API_TOKEN`
2. `config.json.openApiToken`

支持的请求头：

- 推荐：`Authorization: Bearer <token>`
- 兼容：`X-Beacon-Token: <token>`

关键开关：

- `BEACON_REQUIRE_OPEN_API_TOKEN=1`：强制所有 OpenAPI/Ops 均必须携带 token（即使来自 loopback）。
- `BEACON_OPEN_API_TOKEN_MAX_LENGTH`：限制 Header 中 token 最大长度（默认 2048；范围 64..16384），用于防御异常超长 header。

建议：

- 工业交付/试运行阶段建议开启 `BEACON_REQUIRE_OPEN_API_TOKEN=1`。
- Token 建议使用高强度随机字符串，并通过 env 注入，不在 `config.json` 落明文（避免诊断包导出与交付包泄漏）。

### 3.2 DB 管理的 ApiKey（推荐工业交付）

能力概述：

- 支持多 Key、轮换、吊销、过期、scope（最小权限）。
- Token 仅保存 hash（不可逆），明文仅在创建时返回。
- 作用域（scope）示例：
  - `ops`：运维探针与 `/open/ops/*`
  - `openapi`：业务 OpenAPI（`/open/*`、`/stream/open*`、`/control/open*`、`/alarm/open*` 等）

管理入口（Admin UI）：

- `/ops/apikeys`

与 Pepper 的关系（重要）：

- `BEACON_API_KEY_PEPPER` 用于对 ApiKey token 进行二次混入后再 hash 存储（SHA-256）。
- Pepper 必须在同一环境内保持一致；若在运行期变更，已有 ApiKey 将无法再被验证（等价于全部失效）。

建议：

- 生产环境应设置 `BEACON_API_KEY_PEPPER`，并纳入密钥资产管理（与 Token 同级）。
- 多实例部署应确保所有实例使用相同 Pepper。

### 3.3 MediaServer 密钥（ZLMediaKit API secret）

- `config.json.mediaSecret` 必须与 ZLMediaKit `config.ini [api].secret` 一致。
- 建议仅在内网/本机可访问 MediaServer HTTP API 端口；同时避免将 `secret` 暴露到外部系统日志与工单中。

### 3.4 Django 安全基础项

生产建议（Admin/Django）：

- `BEACON_DJANGO_DEBUG=0`
- `BEACON_DJANGO_SECRET_KEY` 必须设置为随机值，且不得使用默认占位（`django-insecure-*`）。
- `BEACON_DJANGO_ALLOWED_HOSTS` 必须显式设置且不得包含 `*`。

TLS/反代相关（可选，建议在反代启用 HTTPS 时配置）：

- `BEACON_DJANGO_TRUST_X_FORWARDED_PROTO=1`
- `BEACON_DJANGO_SECURE_SSL_REDIRECT=1`
- `BEACON_DJANGO_SESSION_COOKIE_SECURE=1`
- `BEACON_DJANGO_CSRF_COOKIE_SECURE=1`
- `BEACON_DJANGO_CSRF_TRUSTED_ORIGINS=https://beacon.example.com`
- `BEACON_DJANGO_HSTS_SECONDS=31536000`（确认全站 HTTPS 稳定后再开启）

---

## 4. IP 访问控制（allowlist/denylist）

Beacon 提供两组 IP 策略（CIDR allowlist/denylist，逗号分隔），用于快速收敛攻击面：

OpenAPI/Ops：

- `BEACON_OPEN_API_IP_ALLOWLIST`
- `BEACON_OPEN_API_IP_DENYLIST`

Admin 入口（仅作用于登录页与验证码接口）：

- `BEACON_ADMIN_IP_ALLOWLIST`
- `BEACON_ADMIN_IP_DENYLIST`

格式示例：

- 单 IP：`203.0.113.10/32`
- 网段：`10.0.0.0/8,192.168.0.0/16`
- IPv6：`2001:db8::/32`

行为约定：

- 未配置 allowlist/denylist 时：策略关闭（默认放行）。
- denylist 优先生效：命中 denylist 直接拒绝。
- 配置 allowlist 时：仅 allowlist 命中的地址放行。
- 若配置字符串中包含无法解析的 CIDR token：视为策略异常并拒绝（fail-closed）。

适用路径（Admin 中间件）：

- OpenAPI/Ops：`/open/*`、`/api/*`、`/stream/open*`、`/control/open*`、`/alarm/open*`，以及标准探针 `/healthz` `/readyz` `/metrics`
- Admin IP 策略：`/login*` 与 `/getVerifyCode*`

建议：

- 反向代理部署时，应优先在网关/安全组层面做 IP 收敛；本策略作为“应用层兜底”使用。
- 反代场景真实源 IP 识别需由代理层保证（例如通过安全组固定代理出口），避免伪造 header 造成绕过。

---

## 5. OpenAPI 网关防护：Rate Limit 与 WAF

### 5.1 速率限制（Rate Limit）

开关与参数（支持 `config.json` 与 env 覆盖）：

- `openApiRateLimitEnabled` / `BEACON_OPEN_API_RATE_LIMIT_ENABLED`
- `openApiRateLimitPerMinute` / `BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE`（默认 60）
- `openApiRateLimitBurst` / `BEACON_OPEN_API_RATE_LIMIT_BURST`（默认 10）

叠加逻辑：

- 以“每分钟窗口”进行计数：`limit = per_minute + burst`
- 支持通过 ApiKey 行级字段为单个 key 设置 `rate_limit_per_minute` 与 `burst_limit`
  - 若 ApiKey 配置了行级限制，则优先生效；否则回退到全局配置

实现注意事项：

- 计数使用 Django cache；多实例部署建议使用共享 cache（例如 Redis），否则每个实例独立计数，导致整体限流失真。
- 限流拒绝返回 HTTP 429，并携带 `Retry-After`、`X-RateLimit-*` 响应头。

### 5.2 轻量 WAF（请求体与路径/查询检测）

开关与参数（支持 `config.json` 与 env 覆盖）：

- `openApiWafEnabled` / `BEACON_OPEN_API_WAF_ENABLED`
- `openApiWafMaxBodyBytes` / `BEACON_OPEN_API_WAF_MAX_BODY_BYTES`（默认 1048576 = 1MB）

能力边界：

- 该 WAF 属于轻量 best-effort：拦截超大 body 与明显可疑 pattern（例如 `<script`、`../`、`union select` 等）。
- 工业交付建议仍由反向代理/WAF 产品承担主要防护，本能力作为应用层补充。

---

## 6. 登录安全（验证码与登录锁定）

### 6.1 登录验证码

- `BEACON_LOGIN_CAPTCHA_ENABLED=1`：启用登录验证码（SVG 图形验证码）。

建议：

- 公网或弱信任网络建议启用；内网部署可按风险评估决定。

### 6.2 登录失败锁定（Login Lockout）

功能：对同一“账号标识 + 源 IP”组合的连续失败进行锁定，降低撞库与暴力破解风险。

开关与参数：

- `BEACON_LOGIN_LOCKOUT_ENABLED=1`
- `BEACON_LOGIN_LOCKOUT_MAX_ATTEMPTS`：阈值（默认 5）
- `BEACON_LOGIN_LOCKOUT_WINDOW_SECONDS`：统计窗口（默认 300）
- `BEACON_LOGIN_LOCKOUT_SECONDS`：锁定时长（默认 900）
- `BEACON_LOGIN_LOCKOUT_CLEAR_ALL_IPS_ON_SUCCESS`：成功登录后清理策略（默认仅清理本 IP；开启后可清理所有 IP）
- `BEACON_LOGIN_LOCKOUT_RETENTION_SECONDS`：锁定表 GC 保留（默认 30 天）

反代真实源 IP（谨慎启用）：

- 默认使用 `REMOTE_ADDR`。
- 可显式启用读取代理头部：
  - `BEACON_LOGIN_LOCKOUT_TRUST_X_REAL_IP=1`：读取 `X-Real-Ip`
  - `BEACON_LOGIN_LOCKOUT_TRUST_FORWARDED=1`：读取 RFC7239 `Forwarded: for=...`
  - `BEACON_LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR=1`：读取 `X-Forwarded-For`
  - `BEACON_LOGIN_LOCKOUT_FORWARDED_MAX_HOPS` / `BEACON_LOGIN_LOCKOUT_XFF_MAX_HOPS`：最大 hop 数（默认 8）

建议：

- 仅在反向代理层确保 header 不可被外部伪造时启用 trust 开关。
- 若反代链路复杂，建议在网关层做统一真实源 IP 写入，并在应用侧仅信任该单一来源。

---

## 7. TOTP 敏感操作二次确认（re-auth）

用途：对高风险管理操作要求“近期二次确认”，降低长 Session 持有的风险。

开关与参数：

- `BEACON_TOTP_SENSITIVE_REAUTH_ENABLED=1`
- `BEACON_TOTP_SENSITIVE_REAUTH_WINDOW_SECONDS`：有效期窗口（默认 300；范围 30..3600）
- `BEACON_TOTP_SENSITIVE_REAUTH_PREFIXES`：需要 re-auth 的路径前缀列表（逗号分隔）

行为约定：

- 仅对已启用 TOTP 的账号生效（存在有效的 TOTP 凭据）。
- 仅对 Web UI 路径生效（非 OpenAPI 路径）。
- 二次确认入口位于个人信息页（/profile），完成后在 Session 内写入有效期。

配置示例（按前缀）：

- `ops/apikeys/api/`
- `user/api/`
- `config/api/system/save`

---

## 8. 允许 iframe 嵌入（CSP frame-ancestors）

默认策略：

- Django 默认返回 `X-Frame-Options=DENY`，拒绝被 iframe 嵌入。

如需嵌入（例如大屏系统嵌入管理页面），需显式开启：

- `BEACON_IFRAME_EMBED_ENABLED=1`
- `BEACON_IFRAME_EMBED_ALLOWED_ORIGINS=https://a.example.com,https://b.example.com`（可选）

行为约定：

- 开启后会移除 `X-Frame-Options`，并在 `Content-Security-Policy` 中写入 `frame-ancestors`。
- 若未配置 allowlist，则使用 `frame-ancestors 'self'`，只允许同源嵌入。

建议：

- 工业交付优先配置 allowlist（仅允许可信大屏域名）。
- 反向代理层建议补充 CSP 与同源策略，避免跨域嵌入扩大攻击面。

---

## 9. SSO 与目录服务接入基线（OIDC / LDAP）

### 9.1 OIDC（OAuth2 / OpenID Connect）

启用开关：

- `BEACON_OIDC_ENABLED=1`

最小必需参数：

- `BEACON_OIDC_CLIENT_ID`
- `BEACON_OIDC_CLIENT_SECRET`
- `BEACON_OIDC_AUTHORIZATION_ENDPOINT`
- `BEACON_OIDC_TOKEN_ENDPOINT`
- `BEACON_OIDC_SCOPE`（默认 `openid email profile`）

生产建议开启严格校验：

- `BEACON_OIDC_JWKS_URI`
- `BEACON_OIDC_ISSUER`
- `BEACON_OIDC_REQUIRE_NONCE=1`

账号绑定策略（建议显式设定）：

- `BEACON_OIDC_ACCOUNT_LINK_MODE=create|deny|auto`
  - 工业交付通常建议 `create` 或 `deny`，避免自动绑定造成账号串号风险。

组与权限治理（企业交付常用）：

- `BEACON_OIDC_REQUIRED_GROUPS`：强制要求至少命中 1 个组
- `BEACON_OIDC_STAFF_GROUPS` / `BEACON_OIDC_SUPERUSER_GROUPS`
- `BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON` + `BEACON_OIDC_SYNC_USER_PERMISSIONS`

### 9.2 LDAP/AD（本地认证失败时的回退）

启用开关：

- `BEACON_LDAP_ENABLED=1`

最小参数：

- `BEACON_LDAP_URL`（ldap:// 或 ldaps://）

两种接入模式：

1. 直连 bind：`BEACON_LDAP_USER_DN_TEMPLATE`
2. service account 搜索 DN 再 bind：`BEACON_LDAP_BIND_DN`/`BEACON_LDAP_BIND_PASSWORD`/`BEACON_LDAP_BASE_DN`/`BEACON_LDAP_USER_FILTER`

TLS 建议：

- `BEACON_LDAP_TLS_VERIFY=1`（生产建议保持校验并配置证书链）
- `BEACON_LDAP_STARTTLS=1`（如目录服务要求）

---

## 10. 日志与诊断包的敏感信息处理

敏感信息常见来源：

- `config.json` 中的 token/secret/password 类字段（即使已在运行日志中做 masking，文件本身仍可能含明文）。
- `.env` 与运行期环境变量（通常含 Token、Pepper、密钥）。
- 诊断包导出（`/open/ops/diagnostics/export`）会打包配置与 DB 摘要，需按密级管理。

建议：

- 生产环境以 env 注入敏感项，减少落盘明文。
- 将诊断包视为“可能包含敏感信息”的工单附件，使用受控传输与受控存储。
- 如需对外提供诊断包，建议先做脱敏处理（移除 token/secret/password/key 等字段）。

---

## 11. 最小安全基线（建议值）

工业交付/试运行阶段建议至少满足：

- OpenAPI：设置强 Token，并开启 `BEACON_REQUIRE_OPEN_API_TOKEN=1`。
- ApiKey：启用 DB 管理 ApiKey 并设置 `BEACON_API_KEY_PEPPER`（便于轮换与最小权限）。
- Django：`BEACON_DJANGO_DEBUG=0`，配置 `BEACON_DJANGO_SECRET_KEY` 与 `BEACON_DJANGO_ALLOWED_HOSTS`。
- 网络：仅暴露必要端口；Analyzer/MediaServer 优先不对公网开放。
- IP 策略：对 OpenAPI/Ops 配置 allowlist/denylist（作为应用层兜底）。
- 网关防护：按场景启用 Rate Limit 与 WAF；公网建议启用。
- 登录安全：公网建议启用验证码与登录锁定；反代场景谨慎启用信任 header。
