# 认证鉴权

Beacon 的认证方式按接口边界区分。不存在一个可访问全部接口的通用 JWT。

## Django 登录会话

浏览器和需要调用开发者会话接口的 SDK 使用 `/login`：

```bash
curl -c cookies.txt -X POST http://localhost:9991/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=admin' \
  --data-urlencode 'password=<password>'
```

登录成功后服务端设置 `v3_sessionid` Cookie。React 的 `/api/app-shell/*`、个人资料和管理页面依赖此会话；写请求还受 Django CSRF 保护。`/login` 不返回通用访问 JWT。

本地账号、LDAP 和 OIDC 最终都会建立相同的 Django 登录会话。OIDC `id_token` 只在回调阶段验证身份，不是 Beacon OpenAPI Token。

## Machine OpenAPI Token

生产建议：

```dotenv
BEACON_REQUIRE_OPEN_API_TOKEN=1
BEACON_OPEN_API_TOKEN=<random-secret-at-least-32-characters>
```

调用时使用：

```http
X-Beacon-Token: <token>
```

兼容请求头包括 `X-API-Key` 和 `Authorization: Bearer <token>`，但新集成建议统一使用 `X-Beacon-Token`。共享 Token 拥有完整 `openapi`/`ops` 权限，适合单机兼容部署；需要吊销、过期、审计和限流时应使用数据库 API Key。

如果未配置 Token 且 `BEACON_REQUIRE_OPEN_API_TOKEN` 未开启，只有回环地址请求会被兼容放行。反向代理可能让远端请求看起来来自回环地址，因此生产必须显式开启强制 Token。

## 数据库 API Key

管理员在“系统管理 → API 安全”（`/ops/apikeys`）中创建、轮换和吊销 API Key。完整 Token 只在创建或轮换时返回一次；数据库保存加 `BEACON_API_KEY_PEPPER` 的 SHA-256 哈希。

| scope | 可访问范围 |
|---|---|
| `openapi` | 机器 OpenAPI |
| `ops` | 健康、指标和 `/open/ops/*` |
| `*` | 两类范围；仅兼容已有记录，UI 默认不创建 |

每个 Key 可配置过期时间、每分钟限制和 burst。当前不支持资源级 scope。

## Cloud Edge Token

`/open/cloud/v1/*` 使用 Edge Cluster 的 Bearer Token：

```http
Authorization: Bearer <edge-token>
```

Cloud 端只保存 pepper 后的哈希。它与 `BEACON_OPEN_API_TOKEN`、数据库 API Key 不是同一种凭据。

## 数字人运行时认证

数字人 `/open/agent/*` 使用自身的账户换取与设备上报协议；`/open/human/report` 使用配置的 machineCode/SM4 兼容认证。详见 [数字人运行时接入](../deployment/digital-human-runtime.md)。不要将其 Token 用于其他 Admin API。

## WebSocket 认证

`/ws/alarm/poll` 只检查 `v3_sessionid` 登录会话，不接受查询参数 Token、API Key 或通用 JWT。

## 生产检查

- 设置强随机 `BEACON_DJANGO_SECRET_KEY`、`BEACON_API_KEY_PEPPER` 和 OpenAPI/Cloud Token。
- 启用 HTTPS、安全 Cookie、明确的 `ALLOWED_HOSTS` 和可信反代设置。
- 不把 Token 写入 URL、日志、仓库或前端 bundle。
- 为不同调用方创建独立 API Key，并定期轮换和审查 `last_used_at`。
- 配置 OpenAPI IP allowlist/denylist 和限流时，先用测试环境验证反向代理传递的真实来源地址。
