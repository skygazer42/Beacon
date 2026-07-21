# Beacon 运维手册（运行期检查/诊断/清理/升级）

本文档用于 Beacon 在“运行阶段测试”与“工业交付”场景下的运维操作，覆盖：

- 健康检查与就绪探针（用于 k8s 探针、监控系统、现场巡检）
- Prometheus 指标采集
- 诊断包导出（配置 + DB 快照 + 日志 tail）
- 运行期日志级别切换
- 运维清理（缓存/日志/临时文件）
- Outbox 失败事件重放（DLQ / failed replay）
- 离线升级包接口（上传/校验/应用/回滚）

相关文档：

- 上线与运行阶段检查清单：`docs/deploy/go-live-checklist.md`
- 安全加固指南（Token/ApiKey/IP 策略/Rate Limit/WAF/登录安全/TOTP/SSO）：`docs/deploy/security-hardening.md`
- 可观测性（Metrics/Logs/Tracing）：`docs/deploy/observability.md`

说明：

- 运维接口默认受 OpenAPI Token 或 ApiKey(scope=ops) 保护
- 文档示例统一使用 `Authorization: Bearer <token>`，兼容场景可替换为 `X-Beacon-Token: <token>`
- Windows PowerShell 场景建议使用 `curl.exe`（避免与 `Invoke-WebRequest` 别名冲突）

---

## 1. 运维前置：统一变量

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

---

## 2. 健康检查与就绪探针

### 2.1 Admin（Django）

接口：

- `GET /healthz`：健康探针（返回 200，表示进程存活）
- `GET /readyz`：就绪探针（返回 200 表示可对外服务；失败返回 503）
- `GET /metrics`：Prometheus 文本指标（建议受 ops scope 保护）

OpenAPI 别名（同功能，统一走 OpenAPI 鉴权）：

- `GET /open/ops/health`
- `GET /open/ops/ready`
- `GET /open/ops/metrics`

示例：

```bash
curl -sS "${ADMIN}/open/ops/health" -H "Authorization: Bearer ${TOKEN}"
curl -sS "${ADMIN}/open/ops/ready"  -H "Authorization: Bearer ${TOKEN}"
curl -sS "${ADMIN}/open/ops/metrics" -H "Authorization: Bearer ${TOKEN}" | head
```

返回约定：

- JSON 类接口：成功 `code=1000`，失败 `code=0`，就绪失败通常返回 HTTP 503
- Prometheus 指标：`text/plain; version=0.0.4`

常见就绪失败原因（`/readyz`）：

- 数据库不可用（SQLite 锁、云端 Postgres 连接失败等）
- Cloud 模式缺少必需环境变量（例如 S3 bucket、edge token pepper 等）

### 2.2 Analyzer（C++）

接口（常用）：

- `GET /api/health`：健康检查
- `GET /api/scheduler/info`：调度统计（Admin 运维卡片可能使用）
- `POST /api/controls`：当前运行布控列表（用于核对 control 是否已下发）

示例：

```bash
curl -sS "${ANALYZER}/api/health" -H "Authorization: Bearer ${TOKEN}"
curl -sS "${ANALYZER}/api/scheduler/info" -H "Authorization: Bearer ${TOKEN}"
curl -sS -X POST "${ANALYZER}/api/controls" -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d '{}'
```

### 2.3 MediaServer（ZLMediaKit）

接口（ZLM 约定 `code=0` 为成功）：

- `GET /index/api/getServerConfig?secret=<mediaSecret>`
- `GET /index/api/getMediaList?secret=<mediaSecret>`

示例：

```bash
curl -sS "${MEDIA_HTTP}/index/api/getServerConfig?secret=${MEDIA_SECRET}" | head
curl -sS "${MEDIA_HTTP}/index/api/getMediaList?secret=${MEDIA_SECRET}" | head
```

---

## 3. Prometheus 指标采集（Admin）

指标入口：

- `${ADMIN}/metrics`
- `${ADMIN}/open/ops/metrics`（建议统一使用此路径）

计数类指标缓存：

- 环境变量 `BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS`
- 默认 `10` 秒
- 最小 `0`（不缓存），最大 `300`

建议：

- 运行阶段测试：保持默认即可
- 大规模部署：按 Prometheus 抓取频率调整 TTL，避免 DB count 过于频繁

---

## 4. 诊断包导出（推荐运维标准动作）

诊断包导出用于“离线排障/工单流转/验收留档”：

- 配置：`config.json`、`settings.json`（可能包含敏感字段）
- DB 快照：streams、controls、api_keys、login_lockout、ops_audit（best-effort，按条数上限截断）
- 日志：按目录打包 tail bytes，避免超大包
- `manifest.json`：导出清单与参数（包括 tail 截断信息）

OpenAPI 导出接口（scope=ops）：

- `GET /open/ops/diagnostics/export`

参数：

- `include_media_logs=1`：包含 `MediaServer/log`（默认不包含）
- `max_tail_bytes=<int>`：单文件 tail 字节数（默认 2MB，范围 64KB 到 20MB）
- `max_files=<int>`：每个目录最多打包文件数（默认 200，范围 0 到 2000；0 表示不限制）

示例（bash）：

```bash
curl -fSL "${ADMIN}/open/ops/diagnostics/export?include_media_logs=1&max_tail_bytes=2097152&max_files=200" \
  -H "Authorization: Bearer ${TOKEN}" \
  -o beacon_diagnostics.zip
```

示例（PowerShell）：

```powershell
curl.exe -fSL "$ADMIN/open/ops/diagnostics/export?include_media_logs=1&max_tail_bytes=2097152&max_files=200" `
  -H "Authorization: Bearer $TOKEN" `
  -o beacon_diagnostics.zip
```

安全注意：

- 诊断包可能包含 token、密钥、连接串等敏感字段
- 建议按密钥资产管理要求保存与传输（加密存储、受控分发、到期销毁）

Web 诊断中心（需登录 session）：

- `GET /ops/diagnostics`

---

## 5. 运维审计导出（Ops Audit）

OpenAPI 导出接口（scope=ops）：

- `GET /open/ops/audit/export`

通用参数：

- `format=json|csv`（默认 json）
- `limit=<int>`（默认 1000，范围 1 到 2000）

过滤参数：

- `event_type=<string>`
- `action=<string>`：按 `event_type` 尾部 action 过滤（如 `.create`、`.delete`）
- `actor=<string>`：operator 模糊匹配
- `object=<string>`：在 node/control/algorithm/lease/detail_json 中模糊匹配
- `keyword=<string>`：全字段模糊匹配
- `ok=1|0`
- `since=<ISO8601>`：起始时间
- `until=<ISO8601>`：结束时间

示例：

```bash
curl -sS "${ADMIN}/open/ops/audit/export?format=csv&limit=2000&ok=0" \
  -H "Authorization: Bearer ${TOKEN}" \
  -o beacon_audit.csv
```

---

## 6. 运行期日志级别切换（无需重启）

接口：

- `POST /open/ops/logging/level`

请求体（JSON 或表单）：

- `level`：`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`
- `logger`：单个 logger 名称（可选，空字符串表示 root logger）
- `loggers`：logger 数组（可选，优先于 `logger`）

示例：

```bash
curl -sS -X POST "${ADMIN}/open/ops/logging/level" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"level":"DEBUG","loggers":["app.middleware",""]}'
```

说明：

- best-effort，仅修改当前进程内 Python logging level
- 适用于现场排障临时提级，排障结束后建议恢复为 `INFO`

---

## 7. 运维清理（缓存/日志/临时文件）

接口：

- `POST /open/ops/cleanup`

请求体（JSON 或表单）：

- `dry_run`：是否演练（默认 `true`）
- `targets`：清理目标列表；字符串时按 `,` 分割；缺省为 `["all"]`

targets 取值：

- `metrics_cache`：清理 Admin 指标计数缓存
- `alarm_compose_cache`：清理告警合成缓存（支持 dry_run）
- `transcode_cache`：清理转码缓存（依赖后台转码管理器）
- `logs`：清理日志文件（按 mtime + retention_days；支持 dry_run）
- `tmp_files`：清理临时文件（按 mtime + max_age_hours；支持 dry_run）

`logs` 附加参数：

- `log_retention_days`：保留天数（默认 7，范围 1 到 3650）

`tmp_files` 附加参数：

- `tmp_max_age_hours`：最大保留小时（默认 24，范围 1 到 8760）

演练示例（推荐先演练再执行）：

```bash
curl -sS -X POST "${ADMIN}/open/ops/cleanup" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true,"targets":["logs","tmp_files"],"log_retention_days":14,"tmp_max_age_hours":48}'
```

执行示例（实际删除）：

```bash
curl -sS -X POST "${ADMIN}/open/ops/cleanup" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"dry_run":false,"targets":["logs","tmp_files"],"log_retention_days":14,"tmp_max_age_hours":48}'
```

---

## 8. Outbox 失败事件重放（failed -> pending）

用途：

- 告警外发（Webhook/Cloud）失败后进入 failed 状态
- 支持将 failed 重置回 pending 并立即重试

接口：

- `POST /open/ops/outbox/replay`

请求体（JSON 或表单）：

- `outbox_id=<int>` 或 `event_id=<string>`（二选一）
- `sink_type=<string>`（可选，用于 event_id 场景进一步过滤）
- `reset_attempts=true|false`（可选，默认 false）

示例：

```bash
curl -sS -X POST "${ADMIN}/open/ops/outbox/replay" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"outbox_id":123,"reset_attempts":true}'
```

---

## 9. 离线升级包（上传/校验/应用/回滚）

升级包接口用于断网环境下的升级包管理，重点是“可审计、可回滚、可验证”的磁盘工作流。

升级目录结构（位于产品根目录）：

- `<root>/upgrade/packages/<package_id>/package.zip`
- `<root>/upgrade/packages/<package_id>/meta.json`
- `<root>/upgrade/staging/<package_id>/...`（apply 后解压产物）
- `<root>/upgrade/state.json`（记录 applied/previous 等状态）

### 9.1 列出已上传升级包

接口：

- `GET /open/ops/upgrade/list`

参数：

- `only_compatible=1`：仅返回与当前版本兼容的包

示例：

```bash
curl -sS "${ADMIN}/open/ops/upgrade/list?only_compatible=1" \
  -H "Authorization: Bearer ${TOKEN}"
```

### 9.2 上传升级包

接口：

- `POST /open/ops/upgrade/upload`

请求：

- `multipart/form-data`
- 文件字段名：`file`（或兼容 `package`）
- zip 内必须包含 `manifest.json`
- `manifest.json` 必须包含 `compatible` 元数据（避免误用不兼容包）

示例：

```bash
curl -sS -X POST "${ADMIN}/open/ops/upgrade/upload" \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@upgrade.zip;type=application/zip"
```

成功返回：

- `data.package_id`：升级包 ID（用于后续 validate/apply）

### 9.3 校验兼容性

接口：

- `GET /open/ops/upgrade/validate?package_id=...`

示例：

```bash
curl -sS "${ADMIN}/open/ops/upgrade/validate?package_id=pkg-001" \
  -H "Authorization: Bearer ${TOKEN}"
```

返回字段：

- `data.ok`：是否兼容当前运行版本
- `data.errors`：不兼容原因列表（如 min/max/from_versions 不匹配）
- `data.current_version`：当前版本（Admin 侧 `PROJECT_VERSION`）
- `data.target_version`：升级包目标版本（manifest 字段）

### 9.4 应用升级包（解压到 staging 并更新 state）

接口：

- `POST /open/ops/upgrade/apply`

请求体（JSON 或表单）：

- `package_id`（必填）
- `dry_run`（可选）：仅返回 staging 目录位置，不执行解压与状态写入

示例（dry-run）：

```bash
curl -sS -X POST "${ADMIN}/open/ops/upgrade/apply" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"package_id":"pkg-001","dry_run":true}'
```

示例（实际 apply）：

```bash
curl -sS -X POST "${ADMIN}/open/ops/upgrade/apply" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"package_id":"pkg-001"}'
```

注意：

- 当前实现的 apply 侧重“安全、可测试的磁盘工作流”
- apply 会解压到 staging 并更新 `upgrade/state.json`
- 二进制切换与进程重启属于交付侧编排工作（需结合现场部署方式制定 SOP）

### 9.5 回滚

接口：

- `POST /open/ops/upgrade/rollback`

说明：

- best-effort：将 `state.json` 中 `applied_package_id` 回退为 `previous_package_id`

示例：

```bash
curl -sS -X POST "${ADMIN}/open/ops/upgrade/rollback" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## 10. 日志导出（Web UI，管理员权限）

接口（需登录，并要求管理员权限）：

- `GET /config/api/logs/export`

参数：

- `include_stream_logs=1`：包含 stream/media 相关日志目录（按实现为别名）
- `max_tail_bytes=<int>`：单文件 tail 字节数（默认 2MB，范围 64KB 到 20MB）

说明：

- 运维场景优先使用 `/open/ops/diagnostics/export`（无需登录，scope=ops）
- `/config/api/logs/export` 适用于现场登录排障

---

## 11. 日志落盘与位置（建议固化）

本节用于统一说明“日志在哪里、如何落盘、如何轮转与清理”，便于在运行阶段测试与现场交付中形成一致口径。

### 11.1 Admin（Django）

日志输出：

- 默认输出到标准输出（console），由服务管理器（systemd / Docker / k8s）接管采集
- 可选落盘文件（推荐工业交付启用）

建议配置（环境变量，见 `Admin/framework/settings.py`）：

- `BEACON_LOG_LEVEL=INFO`（或按需 `WARNING`）
- `BEACON_LOG_FORMAT=json`（便于集中采集与检索）
- `BEACON_LOG_TO_FILE=1`
- `BEACON_LOG_DIR=<root>/logs`（建议使用绝对路径或与交付根目录一致的相对路径）
- `BEACON_LOG_FILE_MAX_MB=50`
- `BEACON_LOG_FILE_BACKUP_COUNT=10`
- `BEACON_LOG_FILE_RETENTION_DAYS=30`（>0 时按天轮转并保留 N 天；否则按大小轮转）

落盘文件：

- `<BEACON_LOG_DIR>/admin.log`

说明：

- 运行期可通过 `/open/ops/logging/level` 临时提级（排障结束后建议恢复 `INFO`）。
- 清理策略可通过 `/open/ops/cleanup` 的 `targets=["logs"]` 执行（建议先 `dry_run=true` 演练）。

### 11.2 Analyzer（C++）

日志输出：

- 默认输出到标准错误（stderr），由服务管理器采集/落盘更为稳妥
- 工业交付建议提供 systemd unit 或容器日志采集配置，将 stderr/stdout 统一汇聚

建议：

- 若需要离线排障留档，建议在服务编排层将 Analyzer 输出重定向到文件，并配合轮转策略。

### 11.3 MediaServer（ZLMediaKit）

日志输出位置取决于 ZLMediaKit 启动目录与其 `config.ini` 日志配置（不同版本略有差异）。

建议：

- 固化 MediaServer 的运行目录（交付包内），并将其 `log/` 目录纳入日志采集与诊断包导出。
- 如启用诊断包导出并需要包含媒体日志，可使用 `/open/ops/diagnostics/export?include_media_logs=1`。
