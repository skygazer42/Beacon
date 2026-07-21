# Beacon 可观测性（Metrics / Logs / Tracing）

本文档用于将 Beacon 的可观测性能力固化为“可部署、可采集、可排障”的企业级口径，覆盖：

- Metrics（Prometheus）
- Logs（结构化日志、落盘、集中采集）
- Tracing（OpenTelemetry / Zipkin）
- 诊断包（配置 + DB 摘要 + 日志 tail）

相关文档：

- 运维手册（接口与命令）：`docs/deploy/ops-runbook.md`
- 安全加固（鉴权/IP 策略/网关保护）：`docs/deploy/security-hardening.md`
- Tracing 本地栈（OTel Collector + Jaeger/Tempo）：`deploy/observability/tracing/README.md`

---

## 1. Metrics（Prometheus）

### 1.1 指标入口

Admin 指标入口：

- `GET /metrics`（标准）
- `GET /open/ops/metrics`（推荐：统一走 OpenAPI/Ops 鉴权）

鉴权约束：

- 建议使用 ApiKey(scope=ops) 或 OpenAPI Token 保护指标入口，避免在弱信任网络中泄露运行态信息。

缓存与性能：

- 计数类指标可配置缓存 TTL：`BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS`（默认 10；范围 0..300）。

### 1.2 Prometheus 抓取建议（示例）

以下为示例片段，具体语法需按现场 Prometheus 版本与运维规范调整。

示例 A：使用 Bearer Token（推荐通过文件注入，避免在配置中落明文）

```yaml
scrape_configs:
  - job_name: "beacon-admin"
    metrics_path: /open/ops/metrics
    scheme: http
    static_configs:
      - targets: ["beacon-admin.internal:9991"]
    bearer_token_file: /etc/prometheus/secrets/beacon_ops_token
```

示例 B：使用反向代理统一出口（https）

```yaml
scrape_configs:
  - job_name: "beacon-admin"
    metrics_path: /open/ops/metrics
    scheme: https
    static_configs:
      - targets: ["beacon.example.com"]
    bearer_token_file: /etc/prometheus/secrets/beacon_ops_token
```

说明：

- 建议将 `ops` scope 的 ApiKey 专门用于探针与指标抓取。
- 运行阶段测试可先用 `curl` 验证指标可抓取，再进入 Prometheus 配置。

---

## 2. Logs（日志）

### 2.1 Admin（Django）日志策略

Beacon Admin 支持结构化日志与落盘轮转（见 `Admin/framework/settings.py`）：

- `BEACON_LOG_LEVEL`：`INFO`（生产建议）/ `WARNING`（更保守）
- `BEACON_LOG_FORMAT`：`json`（推荐集中采集）或 `text`
- `BEACON_LOG_TO_FILE=1`：启用本地落盘
- `BEACON_LOG_DIR`：日志目录（建议与交付根目录一致）
- `BEACON_LOG_FILE_RETENTION_DAYS`：按天保留（>0 时启用）
- 或按大小轮转：`BEACON_LOG_FILE_MAX_MB` + `BEACON_LOG_FILE_BACKUP_COUNT`

落盘文件（启用落盘时）：

- `<BEACON_LOG_DIR>/admin.log`

运行期提级：

- `/open/ops/logging/level` 可在不中断服务的情况下临时提级（排障后建议恢复 `INFO`）。

### 2.2 Analyzer / MediaServer 日志采集建议

Analyzer 与 MediaServer 常见运行方式：

- 由服务管理器托管（systemd/Windows Service）
- 由容器编排托管（Docker/k8s）
- 由 Beacon 启动器 `Admin/VideoAnalyzer.py` 拉起并在 `<root>/log` 目录落盘

建议：

- 生产推荐将 stderr/stdout 纳入统一日志采集（journald / fluent-bit / vector / filebeat 等）。
- 现场离线排障建议保留本地落盘副本，并控制留存天数与磁盘占用。

---

## 3. Tracing（链路追踪）

### 3.1 Admin（OpenTelemetry OTLP/HTTP）

启用开关：

- `BEACON_OTEL_ENABLED=1`

常用参数：

- `BEACON_OTEL_OTLP_ENDPOINT=http://otel-collector:4318`（或完整 `/v1/traces`）
- `BEACON_OTEL_SAMPLE_RATIO=0.1`
- `BEACON_OTEL_SERVICE_NAME=beacon-admin`（可选）

说明：

- Admin 为 best-effort 初始化：依赖缺失或 exporter 初始化失败不会阻断启动。
- 追踪上下文提取与传递与请求头相关（见下节）。

### 3.2 Analyzer（OTLP/HTTP 或 Zipkin 兼容）

Analyzer 侧 tracing 能力与构建方式相关：

- 构建期：`-DBEACON_ENABLE_OTEL=ON` 时可启用 opentelemetry-cpp（OTLP/HTTP exporter）
- 未启用 OTel 构建时：存在 Zipkin v2 JSON 的轻量 fallback（依赖 collector 的 Zipkin receiver）

运行期开关通常仍由 `BEACON_OTEL_ENABLED` 控制。

### 3.3 MediaServer（Zipkin 兼容）

MediaServer（ZLMediaKit）在 tracing 场景下通常以 Zipkin receiver 方式接入（具体以交付包配置为准）。

建议：

- 统一接入 OpenTelemetry Collector，同时开启 OTLP receiver（4317/4318）与 Zipkin receiver（9411），再转发至 Jaeger/Tempo 等后端。

参考：

- `deploy/observability/tracing/README.md`

---

## 4. 请求关联（Request ID / Correlation ID / Trace Context）

Beacon Admin 中间件会 best-effort 读取并生成请求关联字段，常见来源包括：

- `X-Request-Id`
- `X-Beacon-Request-Id`
- `traceparent`（W3C）
- `X-Amzn-Trace-Id`
- `X-Cloud-Trace-Context`
- `X-B3-TraceId` / `b3`

建议（网关/反向代理口径）：

- 在网关层统一写入 `X-Request-Id`
- 在 tracing 场景下透传 `traceparent`，并保证跨服务调用链路一致

---

## 5. 诊断包（离线排障标准动作）

诊断包导出接口（scope=ops）：

- `GET /open/ops/diagnostics/export`

建议：

- 在关键事件点（上线、重大变更、故障）导出并留档（注意敏感信息与传输控制）。
- 如需包含媒体日志：使用 `include_media_logs=1`。

参考：

- `docs/deploy/ops-runbook.md`

