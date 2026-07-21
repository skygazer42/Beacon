# Beacon 故障排除手册（运行阶段测试）

本文档用于运行阶段测试与现场联调的快速排障，目标是将常见问题固化为“症状 -> 证据 -> 定位 -> 处置”的可执行步骤，覆盖：

- 401/403（鉴权、IP 策略、ApiKey scope、WAF/限流）
- /readyz 503（就绪失败）
- MediaServer（ZLMediaKit）secret/端口对齐与拉流失败
- Analyzer 健康检查与控制任务下发失败
- 播放失败、告警不落库/不展示等常见现象

相关文档：

- 端到端验收：`docs/deploy/e2e-acceptance.md`
- 运维手册：`docs/deploy/ops-runbook.md`
- 配置参考：`docs/deploy/config-reference.md`
- 安全加固：`docs/deploy/security-hardening.md`
- 端口与防火墙：`docs/deploy/ports-and-firewall.md`

---

## 0. 排障最小集（建议先执行）

建议先完成“三大组件连通性”检查，再进入细分问题定位。

### 0.1 统一变量（示例）

Linux/macOS（bash）：

```bash
export ADMIN="http://127.0.0.1:9991"
export MEDIA_HTTP="http://127.0.0.1:9992"
export ANALYZER="http://127.0.0.1:9993"
export TOKEN="CHANGE_ME"
export MEDIA_SECRET="CHANGE_ME"
```

Windows PowerShell：

```powershell
$ADMIN = "http://127.0.0.1:9991"
$MEDIA_HTTP = "http://127.0.0.1:9992"
$ANALYZER = "http://127.0.0.1:9993"
$TOKEN = "CHANGE_ME"
$MEDIA_SECRET = "CHANGE_ME"
```

### 0.2 Admin 健康/就绪/指标

```bash
curl -sS "${ADMIN}/open/ops/health"  -H "Authorization: Bearer ${TOKEN}"
curl -sS "${ADMIN}/open/ops/ready"  -H "Authorization: Bearer ${TOKEN}"
curl -sS "${ADMIN}/open/ops/metrics" -H "Authorization: Bearer ${TOKEN}" | head
```

### 0.3 Analyzer 健康

```bash
curl -sS "${ANALYZER}/api/health" -H "Authorization: Bearer ${TOKEN}"
```

### 0.4 MediaServer（ZLM）连通（code=0）

```bash
curl -sS "${MEDIA_HTTP}/index/api/getServerConfig?secret=${MEDIA_SECRET}" | head
```

如上述任一项失败，优先按本手册对应章节处理（401/403、端口、secret、进程状态）。

---

## 1. 401 Unauthorized（OpenAPI/Ops/Analyzer）

### 1.1 典型症状

- `/open/ops/health`、`/metrics`、`/open/*` 返回 401
- `/api/health`（Analyzer）返回 401

### 1.2 优先证据

1. 确认请求是否携带 Token：

- 推荐：`Authorization: Bearer <token>`
- 兼容：`X-Beacon-Token: <token>`

2. 确认 token 的“实际来源”：

- 环境变量 `BEACON_OPEN_API_TOKEN`
- 或 `config.json.openApiToken`

3. 如使用 DB ApiKey：

- ApiKey 是否启用、是否过期/吊销
- ApiKey scope 是否包含 `ops` 或 `openapi`

### 1.3 常见原因与处置

1. Token 不一致（最常见）  
处置：统一以环境变量注入为准，并避免多处同时配置导致混淆。

2. 强制 token 开启但未携带（`BEACON_REQUIRE_OPEN_API_TOKEN=1`）  
处置：对所有 OpenAPI/Ops/Analyzer 请求统一携带 token；验收脚本与监控探针均需一致配置。

3. ApiKey scope 不匹配  
处置：为运维探针使用 scope=ops，为业务 OpenAPI 使用 scope=openapi；如需混用可在同一 key 上授权多个 scope。

---

## 2. 403 Forbidden（IP 策略 / WAF / 权限）

### 2.1 典型症状

- OpenAPI/Ops 返回 403（JSON `{"code":403,"msg":"forbidden"}` 或类似）
- `/login` 或 `/getVerifyCode` 返回 403（文本 forbidden）

### 2.2 优先证据

1. 检查 IP allowlist/denylist 配置：

- OpenAPI/Ops：`BEACON_OPEN_API_IP_ALLOWLIST` / `BEACON_OPEN_API_IP_DENYLIST`
- Admin 登录入口：`BEACON_ADMIN_IP_ALLOWLIST` / `BEACON_ADMIN_IP_DENYLIST`

2. 反向代理部署时确认 `REMOTE_ADDR` 与真实源 IP 的关系  
说明：应用层 IP 策略使用 `REMOTE_ADDR`；若反代链路导致 `REMOTE_ADDR` 异常，可能产生误拦截。

3. 如开启 OpenAPI WAF：

- `BEACON_OPEN_API_WAF_ENABLED=1`
- `BEACON_OPEN_API_WAF_MAX_BODY_BYTES` 是否过小导致 413/403

### 2.3 常见原因与处置

1. allowlist/denylist 填入了无法解析的 CIDR token  
行为：策略按 fail-closed 拒绝。  
处置：修正 CIDR 字符串（逗号分隔；如 `10.0.0.0/8,192.168.0.0/16`）。

2. WAF 拦截（路径/查询包含可疑 pattern）  
处置：排查请求路径与 query；必要时关闭 WAF 或增加网关层更完善的 WAF 规则。

3. Web UI 权限不足（管理员页面）  
处置：确认登录账号角色（staff/superuser）与模块权限；如为运维页面（ApiKey 管理等）需管理员权限。

---

## 3. 429 Too Many Requests（OpenAPI 速率限制）

### 3.1 典型症状

- OpenAPI/Ops 返回 HTTP 429，并携带 `Retry-After`、`X-RateLimit-*`

### 3.2 定位要点

1. 检查全局速率限制配置（`config.json` 或 env 覆盖）：

- `BEACON_OPEN_API_RATE_LIMIT_ENABLED`
- `BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE`
- `BEACON_OPEN_API_RATE_LIMIT_BURST`

2. 如使用 DB ApiKey：

- ApiKey 行级 `rate_limit_per_minute` / `burst_limit` 是否配置过小（行级优先）

### 3.3 处置建议

- 运行阶段测试可临时关闭限流或提高阈值；上线后建议按监控数据回收至合理值。
- 多实例部署建议使用共享 cache（例如 Redis），避免每实例独立计数导致整体限流失真。

---

## 4. `/readyz` 返回 503（Admin 就绪失败）

### 4.1 典型症状

- `/healthz` 正常，但 `/readyz` 返回 503
- OpenAPI 别名 `/open/ops/ready` 返回 503

### 4.2 常见原因

1. 数据库不可用

- SQLite：写锁导致就绪失败（并发写入、磁盘问题）
- Postgres：连接串错误或网络不可达

2. Cloud 模式缺少必需 env（如 S3、edge token pepper 等）

### 4.3 处置建议

- 优先查看 Admin 日志（console 或 `BEACON_LOG_DIR/admin.log`）定位具体错误。
- SQLite 场景可提高 `BEACON_SQLITE_TIMEOUT_SECONDS`，并评估迁移到 Postgres（见 `docs/deploy/database-and-backup.md`）。

---

## 5. MediaServer（ZLMediaKit）相关问题

### 5.1 Admin 里媒体相关动作全部失败

典型表现：

- Stream 代理失败（`openAddStreamProxy` 返回错误）
- 获取媒体列表失败

优先排查：

- `config.json.mediaSecret` 是否等于 ZLM `config.ini [api].secret`
- `config.json.mediaHttpPort` 是否对齐 ZLM `config.ini [http].port`
- 防火墙是否拦截 `mediaHttpPort`（Admin -> MediaServer 的 HTTP API 调用）

### 5.2 Stream 代理成功但播放失败

优先排查：

- 播放协议端口是否开放（如 RTSP 播放需开放 `mediaRtspPort/tcp`）
- RTSP 源是否稳定（先用 `ffprobe/ffplay/VLC` 验证源端）
- MediaServer 日志是否存在拉流失败信息（建议导出诊断包包含媒体日志：`include_media_logs=1`）

---

## 6. Analyzer 相关问题

### 6.1 `/api/health` 不通或返回异常

优先排查：

- 进程是否启动、端口是否监听（见 `docs/deploy/ports-and-firewall.md`）
- 是否启用 token，且请求是否携带正确 token

### 6.2 Control 创建成功但启动失败

常见原因：

- Analyzer 不可达（网络/鉴权）
- 算法/模型未准备导致运行失败（L2 不可达但不影响 L1 验收）

建议处置：

- 按 `docs/deploy/e2e-acceptance.md` 走 L1 验收路径：先证明“流媒体链路 + 布控下发 + controls 可见”成立，再处理算法侧依赖。

---

## 7. 告警相关问题

### 7.1 告警列表一直为空

常见原因：

- 未配置/未运行真实算法（模型缺失，算法条目未启用）
- 外部告警外发/模拟未执行

建议：

- 在缺少模型阶段，优先使用 `e2e-acceptance.md` 的“模拟外部告警”步骤验证告警工作流。

### 7.2 告警记录存在但图片/视频打不开

优先排查：

- `uploadDir` 是否一致（组件对齐同一 `uploadDir`，且目录存在、权限正常）
- 文件是否被清理（清理策略/手动清理）
- 文件服务/对象存储模式是否配置正确（Cloud 场景下由 S3/MinIO 管理）

---

## 8. 诊断包：将排障“可移交”

当现场需要将问题移交到研发/交付二线，建议导出诊断包：

- `GET /open/ops/diagnostics/export`
- 如需包含 MediaServer 日志：`include_media_logs=1`

参考：

- `docs/deploy/ops-runbook.md`

