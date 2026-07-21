# Beacon 性能与稳定性调优指南（试运行/工业交付）

本文档用于运行阶段测试与工业交付场景下的性能/稳定性调优，覆盖：

- 资源基线与容量规划要点
- 视频链路与算法侧内存保护（FramePool）
- 外部推理（HTTP API）稳定性保护（超时/重试/熔断/限流）
- OpenAPI 网关保护（Rate Limit / WAF）
- 告警链路（带宽/CPU/Outbox）
- 指标与日志对性能的影响

相关文档：

- 端到端验收：`docs/deploy/e2e-acceptance.md`
- 运维手册：`docs/deploy/ops-runbook.md`
- 配置参考：`docs/deploy/config-reference.md`

---

## 1. 调优原则（建议固化为试运行策略）

建议优先级：

1. 稳定性优先：避免 OOM、队列堆积、外部依赖雪崩导致整体不可用
2. 限制输入：对外部请求与外部推理调用进行速率限制与超时保护
3. 观测先行：先建立 metrics/logs 的可观测性基线，再做参数迭代
4. 分层验收：先跑通 L1（流媒体链路 + 布控调度），再推进 L2（真实算法告警）

---

## 2. 视频链路与内存保护（Analyzer FramePool）

Analyzer 提供 FramePool 上限保护，用于防止“生产 > 消费”导致内存持续增长：

- `BEACON_FRAMEPOOL_MAX_FRAMES`：总帧数硬上限（设置为正整数）
- `BEACON_FRAMEPOOL_BUDGET_MB`：未设置 MAX_FRAMES 时按内存预算估算上限（默认 128MB）

建议：

- 多路并发、弱机或外部推理较慢时，优先设置更保守的预算（例如 64/32）。
- 若需要更稳定的上限控制，优先显式配置 `BEACON_FRAMEPOOL_MAX_FRAMES`。

说明：

- 该参数用于“保命”，并不等价于吞吐提升；吞吐提升通常依赖算法优化、硬件加速与 IO/网络优化。

---

## 3. 外部推理（HTTP API）稳定性保护

当基础算法的 `basic_source=api` 依赖外部 HTTP 推理服务时，必须避免“失败重试放大”与“慢调用堆积”：

常用 env（覆盖 `config.json`）：

- `BEACON_API_INFER_CONNECT_TIMEOUT_SECONDS`：连接超时（默认 2；范围 1..60）
- `BEACON_API_INFER_TIMEOUT_SECONDS`：请求总超时（默认 5；范围 1..300）
- `BEACON_API_INFER_RETRY_MAX`：失败重试次数（默认 0；范围 0..10）
- `BEACON_API_INFER_CIRCUIT_BREAKER_FAILS`：熔断阈值（默认 5；0=禁用）
- `BEACON_API_INFER_CIRCUIT_BREAKER_OPEN_SECONDS`：熔断打开时长（默认 10）
- `BEACON_API_INFER_MIN_INTERVAL_MS`：最小调用间隔（毫秒；默认 0=禁用）

建议（试运行常用组合）：

- 超时：从 `connect=2s`、`total=5s` 起步，根据现场推理耗时迭代
- 重试：默认保持 0，避免雪崩重试；如需重试，建议仅 1 次且配合熔断
- 熔断：建议开启（fails=5, open=10s 起步），避免外部服务抖动拖垮系统
- 最小间隔：在外部服务承压或弱机场景下可启用，用于主动限流

---

## 4. OpenAPI 网关保护（Rate Limit / WAF）

OpenAPI/Ops 面向机器调用，试运行阶段常见风险包括“误配置导致高频轮询”和“异常请求体导致资源耗尽”。

建议按场景启用：

Rate Limit（`config.json` 或 env 覆盖）：

- `BEACON_OPEN_API_RATE_LIMIT_ENABLED=1`
- `BEACON_OPEN_API_RATE_LIMIT_PER_MINUTE=60`（按实际调用频率调整）
- `BEACON_OPEN_API_RATE_LIMIT_BURST=10`

WAF（轻量）：

- `BEACON_OPEN_API_WAF_ENABLED=1`
- `BEACON_OPEN_API_WAF_MAX_BODY_BYTES=1048576`（按导入/上传接口调整）

说明：

- 速率限制依赖 Django cache；多实例部署建议使用共享 cache（例如 Redis）。
- WAF 属于 best-effort；生产仍建议由反向代理/WAF 产品承担主要防护。

---

## 5. 告警链路：带宽/CPU/Outbox

### 5.1 降低告警上传负载（Base64 字段）

告警外发与上报场景中，图片 base64 会显著增加带宽与 CPU：

- `BEACON_ALARM_UPLOAD_INCLUDE_BASE64=0` 可关闭 base64 字段，仅上传 URL（适用于对象存储/文件服务可达的场景）

### 5.2 Outbox 与外发稳定性

Beacon 支持告警外发 Outbox（落库后异步投递），相关字段在 `config.json` 中存在：

- `alarmOutboxEnabled`
- `alarmOutboxPollSeconds`
- `alarmOutboxMaxBatch`
- `alarmOutboxRetentionHours`

建议：

- 试运行阶段保持 Outbox 启用，降低外部系统抖动对主流程的影响
- 外发失败通过运维接口进行重放（见 `docs/deploy/ops-runbook.md` 的 Outbox replay）

---

## 6. 指标与日志对性能的影响

### 6.1 Metrics 采集频率与 DB 压力

Admin 的计数类指标可配置缓存 TTL：

- `BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS`（默认 10；范围 0..300）

建议：

- Prometheus 抓取周期较短时（例如 5s），建议设置 TTL >= 抓取周期，避免频繁 DB count。

### 6.2 日志格式与落盘策略

建议生产使用：

- `BEACON_LOG_FORMAT=json`（便于集中采集）
- `BEACON_LOG_TO_FILE=1`（保留离线排障能力）
- 按天或按大小轮转（`BEACON_LOG_FILE_RETENTION_DAYS` 或 `BEACON_LOG_FILE_MAX_MB`）

说明：

- 过高日志级别（DEBUG）会显著放大 IO 与 CPU；现场排障建议临时提级，排障完成后恢复。
- 运行期日志提级可通过 `/open/ops/logging/level` 执行（见 `docs/deploy/ops-runbook.md`）。

---

## 7. 数据库对性能的影响（SQLite vs Postgres）

SQLite：

- 优点：部署简单、单机可用
- 风险：并发写入与长事务会导致锁争用，影响就绪探针与整体可用性

Postgres：

- 优点：并发能力更好、稳定性更强、便于备份恢复与审计
- 建议：试运行或工业交付优先采用 Postgres（见 `docs/deploy/database-and-backup.md`）

---

## 8. 调优闭环（建议固化）

建议形成固定闭环：

1. 建立基线：跑通 L1 验收 + 固化探针/指标/日志
2. 压测与观测：多路拉流 + 布控并发 + 告警吞吐
3. 调参：FramePool、外部推理超时/熔断、OpenAPI 限流、指标缓存 TTL
4. 留档：诊断包与运维审计导出作为试运行证据

