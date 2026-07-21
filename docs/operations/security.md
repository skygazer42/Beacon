# 安全加固

本页列出当前实现能直接配置的安全边界，以及仍需部署方补齐的控制。上线前也应执行 Django `check --deploy`、依赖审计、源码泄密扫描和针对目标网络的安全测试。

## 上线前必须完成

1. 设置随机的 `BEACON_DJANGO_SECRET_KEY`、管理员密码、`BEACON_OPEN_API_TOKEN`、`mediaSecret` 及所有 Cloud/数字人/对象存储凭据。
2. 设置 `BEACON_REQUIRE_OPEN_API_TOKEN=1`；为不同调用方创建独立 API Key，只分配 `openapi` 或 `ops` 所需 scope。
3. 设置明确的 `BEACON_DJANGO_ALLOWED_HOSTS`，关闭 Debug，并通过可信反向代理提供 HTTPS。
4. 让 Admin、Analyzer、MediaServer、数据库和对象存储只在所需网段可达；公网仅暴露反向代理。
5. 关闭不需要的 USB bridge、文件服务、iframe 嵌入、WAF 例外和调试入口。
6. 轮换任何曾写入 Git、日志、Issue、镜像层或演示脚本的凭据；从当前文件删除并不能使历史凭据失效。

生产环境变量模板见根目录 `.env.production.example`。

## HTTPS 与 Django

反向代理至少应传递真实 Host、客户端地址和外部协议：

```nginx
location / {
    proxy_pass http://127.0.0.1:9991;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /ws/ {
    proxy_pass http://127.0.0.1:9991;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

同时配置：

```bash
BEACON_DJANGO_DEBUG=0
BEACON_DJANGO_ALLOWED_HOSTS=beacon.example.com
BEACON_DJANGO_SESSION_COOKIE_SECURE=1
BEACON_DJANGO_CSRF_COOKIE_SECURE=1
BEACON_DJANGO_TRUST_X_FORWARDED_PROTO=1
BEACON_DJANGO_CSRF_TRUSTED_ORIGINS=https://beacon.example.com
```

确认域名已稳定使用 HTTPS 后再开启 HSTS。不要在本地 HTTP、临时域名或尚未覆盖的子域上盲目启用 preload/includeSubDomains。

## OpenAPI 与 Ops

- 共享 Token 兼容旧部署，但独立数据库 API Key 更利于吊销和审计。
- 当前 scope 只有 `openapi`、`ops` 和兼容的 `*`，不是资源级 RBAC。
- 未配置 Token 且未强制鉴权时，只对 loopback 保留开发兼容行为；反向代理可能让远端请求看起来来自 loopback，因此生产必须设置 `BEACON_REQUIRE_OPEN_API_TOKEN=1`。
- 可使用 `BEACON_OPEN_API_IP_ALLOWLIST`/`DENYLIST` 和 Admin 对应 IP 列表进一步收窄来源，但必须正确处理可信代理地址。
- 速率限制依赖 Django cache；多进程/多副本若使用进程内 cache，不会形成全局配额。

内置 OpenAPI WAF 只检查请求体大小及 URL/query 中少量可疑模式，不解析完整请求体，也不能替代反向代理 WAF、参数校验或安全测试。

## 页面、WebSocket 与 iframe

- 页面使用 Django Session + CSRF；机器 API 不应依赖已登录页面会话。
- `/ws/alarm/poll` 只接受已登录 Session Cookie，并需要 ASGI。
- 默认响应禁止跨站 iframe。只有明确需要嵌入时才设置 `BEACON_IFRAME_EMBED_ENABLED=1`，并填写精确的 `BEACON_IFRAME_EMBED_ALLOWED_ORIGINS`；空白白名单仍只允许同源。
- OIDC、LDAP、数字人运行时和 Cloud Edge 各有独立认证边界，不能混用 Token。

## 文件与数据

- `BEACON_FILE_SERVICE_ENABLED` 默认关闭。启用时将根目录限制到专用只读目录，并强制 OpenAPI Token 和网络来源限制。
- 上传、告警截图、录像、人脸数据和模型可能包含个人信息或客户资产；部署方负责合法依据、最小留存、访问审计、备份加密和删除流程。
- 当前部分第三方凭据、TOTP Secret、数字人/Cloud 配置等以明文应用字段存入数据库。生产至少使用加密磁盘/数据库、严格数据库账号和备份加密；更高要求场景应先实现应用层字段加密或外部密钥管理。
- 进程使用专用非 root 账号；配置、数据库、模型、授权和上传目录按最小权限分开授权。

## 审计与导出

审计页面为 `/ops/audit`。机器导出接口是：

```bash
curl 'http://127.0.0.1:9991/open/ops/audit/export?format=csv&limit=1000' \
  -H "Authorization: Bearer ${OPS_API_KEY}" \
  -o beacon-audit.csv
```

该接口需要 `ops` scope，最多导出接口允许的记录数；长期合规留存应将日志和审计事件送到独立、不可由应用管理员随意修改的存储。

## 发布安全检查

```bash
cd Admin
BEACON_DISABLE_BACKGROUND=1 python manage.py check --deploy
```

再确认：源码候选无密钥、依赖无已知高危漏洞、镜像以非 root 运行、生产 Secret 不在 Compose/Helm values 中、备份可以恢复、Webhook 接收方校验签名并按 `event_id` 幂等。
