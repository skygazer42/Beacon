# Beacon 上线与运行阶段检查清单（交付/试运行）

本文档提供一个“可执行”的上线与运行阶段检查清单，用于将 Beacon 从“可启动”推进到“可稳定运行并可验收/可排障”。  
端到端业务验收步骤见：

- `docs/deploy/e2e-acceptance.md`

运行期运维接口与诊断能力见：

- `docs/deploy/ops-runbook.md`

安全加固基线见：

- `docs/deploy/security-hardening.md`
- 端口与防火墙口径：`docs/deploy/ports-and-firewall.md`
- 数据库与备份恢复：`docs/deploy/database-and-backup.md`
- 可观测性（Metrics/Logs/Tracing）：`docs/deploy/observability.md`
- 密钥资产与轮换：`docs/deploy/secrets-and-rotation.md`

---

## 1. 交付包完整性与目录结构

交付物应至少包含：

- `config.json`（端口/目录/密钥/外发等运行参数）
- `settings.json`（品牌/展示类参数，若使用）
- Admin：
  - 源码运行：`Admin/` + Python 依赖
  - 交付运行：Admin 可执行/服务脚本（若使用 PyInstaller）
- Analyzer：
  - `Analyzer` 二进制（或 `Analyzer.exe`）与其运行依赖（OpenCV/FFmpeg/onnxruntime/openvino 等按交付清单）
  - 模型目录（`modelDir`）与模型文件（若需跑真实算法）
- MediaServer：
  - ZLMediaKit 二进制与 `config.ini`
  - FFmpeg（如需截图/转码能力）
- 数据目录（建议）：
  - `${BEACON_ROOT_DIR}/data/upload/`（告警图片/视频/录制落盘）
  - `${BEACON_ROOT_DIR}/data/models/`（模型）
  - `${BEACON_ROOT_DIR}/logs/`（日志归档与采集落点）

交付目录结构规范见：

- `docs/deploy/delivery-layout.md`

---

## 2. 配置冻结与变更管理

建议在试运行阶段建立“配置冻结”与“变更留痕”：

- `config.json` 与 `.env`（或等效配置注入）纳入变更流程与审批。
- Token/Secret/Pepper 等密钥资产不落明文配置文件时，需建立“密钥版本与生效窗口”记录（便于回滚与追溯）。
- 建议为每次验收导出一份诊断包（含配置与状态快照），作为留档（见 `docs/deploy/ops-runbook.md` 的诊断导出）。

---

## 3. 启动顺序与健康检查（最低可用标准）

推荐启动顺序：

1. MediaServer（ZLMediaKit）
2. Analyzer
3. Admin

最低可用的健康标准（建议在监控/巡检中固化）：

Admin：

- `GET /open/ops/health`：HTTP 200 + `code=1000`
- `GET /open/ops/ready`：HTTP 200 + `code=1000`
- `GET /open/ops/metrics`：可被抓取（Prometheus 文本）

Analyzer：

- `GET /api/health`：HTTP 200 + `code=1000`（带 token 视配置而定）

MediaServer（ZLM）：

- `GET /index/api/getServerConfig?secret=<mediaSecret>`：返回 `code=0`

建议将“健康探针失败的常见原因”固化到现场排障 SOP：

- OpenAPI/Ops 鉴权缺失（Token/ApiKey、IP 策略、强制 token 开关）
- `mediaSecret` 与 ZLM `config.ini [api].secret` 不一致
- SQLite 被锁导致 `/readyz` 失败（写并发高时更常见）
- Cloud 模式缺少必需 env（S3、edge token pepper 等）

---

## 4. 端到端验收（从 RTSP 到布控到告警）

端到端验收建议至少覆盖两条路径：

- 路径 A：真实 RTSP 拉流 -> 媒体代理 -> 播放验证
- 路径 B：布控下发 -> Analyzer 控制启动 -> 告警（真实或模拟）-> Admin 页面可见

具体步骤与命令见：

- `docs/deploy/e2e-acceptance.md`

验收输出建议固化为“可回放证据”：

- 关键接口响应（stream add/proxy、control start、controls list、alarm add）
- 诊断包（`/open/ops/diagnostics/export`）
- 运维审计导出（`/open/ops/audit/export`，可选）

---

## 5. 安全基线（上线前检查）

上线前建议至少检查：

- OpenAPI 强制鉴权：`BEACON_REQUIRE_OPEN_API_TOKEN=1`（或仅使用 DB ApiKey 且禁用 loopback 放行）
- Token/ApiKey/Pepper：
  - `BEACON_OPEN_API_TOKEN` 已设置（若采用 legacy token）
  - `BEACON_API_KEY_PEPPER` 已设置且已纳入密钥资产管理（多实例需一致）
- Django 生产安全项：
  - `BEACON_DJANGO_DEBUG=0`
  - `BEACON_DJANGO_SECRET_KEY` 非默认占位
  - `BEACON_DJANGO_ALLOWED_HOSTS` 已显式配置且不含 `*`
- 端口暴露策略：Analyzer/MediaServer 管理端口不对公网暴露（或已网关隔离）
- IP 策略：对 OpenAPI/Ops 配置 allowlist/denylist（应用层兜底）
- 速率限制与 WAF：公网或弱信任网络建议开启（OpenAPI）

更完整的加固项见：

- `docs/deploy/security-hardening.md`

---

## 6. 观测与留存（Metrics/Logs/Tracing）

建议至少建立以下可观测性基线：

- 指标：Prometheus 抓取 `/open/ops/metrics`
- 日志：
  - Admin：建议开启 `BEACON_LOG_TO_FILE=1` 并配置轮转（`BEACON_LOG_FILE_*`）
  - Analyzer/MediaServer：如以服务方式运行，建议由 systemd/journald 或容器日志系统统一收集，并为现场离线排障保留落盘副本
- 诊断包：在关键事件（上线、变更、故障）后导出并留档

可选项（链路追踪）：

- OpenTelemetry：按需启用 `BEACON_OTEL_ENABLED=1`，并指向 collector（OTLP/Zipkin）

参考：

- `docs/deploy/ops-runbook.md`
- `.env.production.example`（包含可观测性相关 env 示例）

---

## 7. 数据备份、恢复与演练

建议备份范围：

- 数据库：
  - SQLite：`Admin/Admin.sqlite3`（需在服务停止或一致性窗口内备份）
  - Postgres：按标准 pg_dump/快照策略执行
- 文件数据：
  - `uploadDir`（告警截图/视频、录制数据等）
  - `modelDir`（模型文件与插件）
- 配置：
  - `config.json`、`settings.json`
  - `.env`（或等效配置注入清单）

建议至少完成一次恢复演练：

- 将 DB 与 `uploadDir` 恢复到隔离环境
- 验证 Admin/Analyzer/MediaServer 可启动
- 按 `docs/deploy/e2e-acceptance.md` 完成最小验收

---

## 8. 升级与回滚策略（离线环境）

离线升级建议具备：

- 可审计：升级包上传/应用/回滚过程可追溯
- 可回滚：保留 previous 状态，出现问题可快速回退
- 可验证：升级后执行健康检查与端到端验收

Beacon 运维接口支持离线升级包管理（上传/校验/应用/回滚）：

- 见 `docs/deploy/ops-runbook.md` 的“离线升级包”章节

---

## 9. 容量与性能（试运行前的基准测试）

建议在试运行前做一次基准验证：

- 多路 RTSP 拉流稳定性（代理/断线重连/转发）
- 布控并发与 CPU/内存占用
- 告警吞吐与外发稳定性（Webhook/Cloud/Outbox 重试）

可调参数示例（按场景选取）：

- `BEACON_FRAMEPOOL_MAX_FRAMES` / `BEACON_FRAMEPOOL_BUDGET_MB`（Analyzer 内存上限保护）
- OpenAPI 速率限制与 WAF（避免外部请求导致系统不稳定）
- SQLite 超时与数据库选型（高并发建议迁移到 Postgres）

---

## 10. 运行期 SOP（建议固化）

建议固化为现场 SOP 的操作集：

- 健康/就绪/指标探针
- 诊断包导出与工单留档
- 临时日志提级（排障后恢复）
- 缓存/日志/临时文件清理（先 dry-run 再执行）
- Outbox 失败事件重放

参考：

- `docs/deploy/ops-runbook.md`
