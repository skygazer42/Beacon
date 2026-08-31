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
- 发布证据与供应链验证：`docs/deploy/release-evidence.md`
- 可观测性（Metrics/Logs/Tracing）：`docs/deploy/observability.md`
- 密钥资产与轮换：`docs/deploy/secrets-and-rotation.md`

---

## 0. 企业发布判定（GO / NO-GO）

本清单中的“建议”不能替代正式发布判定。企业交付应把下表标记为**强制门禁**：任一项没有可复核证据，结论即为 `NO-GO`，不得用“服务能启动”代替业务、可靠性或安全验收。

| 门禁 | 最低通过标准 | 必须留存的证据 |
|------|--------------|----------------|
| 源码与构建 | 对应模块的单元测试、前端生产构建、文档严格检查、静态安全扫描全部通过 | commit、命令、退出码、测试数量、构建日志 |
| 供应链 | Python、npm 与容器 OS/library 审计无未豁免的高危/严重漏洞；每个实际交付包均有 SBOM、校验和与可验证签名/证明 | 审计报告、豁免审批、SBOM、`SHA256SUMS`、签名/证明及验证记录 |
| 生产配置 | Admin 使用生产 WSGI 服务；DEBUG 关闭；域名、TLS、Cookie、CSRF、鉴权、密钥与端口边界符合基线 | 脱敏配置快照、`check --deploy`、反代与防火墙验证 |
| 真实业务闭环 | E2E 的 L0、L1、L2 均通过；每个拟交付算法 SKU 使用真实授权模型和代表性视频验证 | 模型哈希/授权、视频样本编号、接口响应、截图/告警记录 |
| 容量与稳定性 | 在目标硬件上完成容量边界测试和持续运行；P95/P99、错误率、丢帧、队列、资源峰值满足已批准 SLO | 压测配置与原始报告、监控图、SLO 签字记录 |
| 数据可靠性 | 数据库与媒体文件备份成功，并在隔离环境完成恢复；RPO/RTO 来自实测 | 备份清单、恢复日志、数据核对、计时记录 |
| 故障与回滚 | 服务、网络、数据库、磁盘和下游故障演练通过；升级包可验证且能回滚 | 演练时间线、审计日志、回滚后 E2E 结果 |
| 运维与合规 | 告警、日志、指标、审计留存、隐私/数据保留、第三方许可证和现场 SOP 已确认 | 看板/告警截图、留存策略、许可证清单、交接记录 |

发布证据必须绑定同一组 Beacon commit、模型哈希、依赖锁文件和目标环境；任一项变化后，应重跑受影响门禁。HSTS `includeSubDomains`/`preload` 等不可安全通用开启的选项可以保留明确的风险接受记录，但 `DEBUG`、安全 Cookie、HTTPS、强鉴权和生产 WSGI 不属于可默认豁免项。

仓库的 `Release` 编排工作流会先创建草稿，再调用 `Release evidence` 为**源码归档**
生成 SPDX SBOM、SLSA provenance、SBOM attestation、离线验证记录和校验清单，并调用
`Release container` 为 GHCR `linux/amd64` Cloud 镜像生成、复验同类证据。只有两组
证据完整且二次验证通过，草稿才会发布为不可变 Release。具体触发和验签命令见
[发布证据与供应链验证](release-evidence.md)。这些证据不能覆盖另行组装的 Linux、
Windows、其他架构容器、模型或 GPU 专用产物；这些交付件必须在各自构建流水线中单独
生成并验证证据，缺一项仍为 `NO-GO`。

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

Cloud Helm/Compose 形态使用另一套受控顺序：PostgreSQL/对象存储 → `init`（migration、
bootstrap）→ `web` + `worker`。不得让每个 Web 副本自行迁移。生产至少保留两个 Web
和两个 Worker，并验证一个 Worker 为 `leader/running`、其余为 `standby`。

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
- Cloud Worker heartbeat 过期、leader 后台状态 degraded，或初始化 Job 未完成

---

## 4. 端到端验收（从 RTSP 到布控到告警）

端到端验收建议至少覆盖两条路径：

- 路径 A：真实 RTSP 拉流 -> 媒体代理 -> 播放验证
- 路径 B：布控下发 -> Analyzer 控制启动 -> 告警（真实或模拟）-> Admin 页面可见

具体步骤与命令见：

- `docs/deploy/e2e-acceptance.md`
- 可复跑基线：`python tools/edge_e2e_acceptance.py --synthetic-l1 --alarm-workflow`；
  保存其脱敏 JSON 输出与退出码。正式 L1/L2 改用 `--external-l1` 和正式算法编号。

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
  - `BEACON_DJANGO_TRUST_X_FORWARDED_PROTO=1`，且只有受信反向代理可以直连 Admin
  - HTTPS 跳转、Session/CSRF 安全 Cookie 和 HSTS 已启用；`BEACON_DJANGO_ALLOW_INSECURE_HTTP` 未开启
  - Edge Admin 使用默认 `waitress`（或经评审的其他生产 WSGI 服务），进程参数中不得出现 `runserver`
  - 若信任反向代理头，`BEACON_ADMIN_TRUSTED_PROXY` 必须是实际直连代理 IP，不得使用通配符
- Cloud 外置 PostgreSQL URL 使用 `sslmode=verify-full`（最低不低于 `require`），外置 S3 endpoint 使用 HTTPS
- Cloud `/app/data` 使用经验证的共享 RWX PVC；运行时上传不写入镜像内 `Admin/static`
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
  - Cloud runtime RWX PVC（即 `/app/data`；不得只备份对象存储而漏掉兼容上传）
- 配置：
  - `config.json`、`settings.json`
  - `.env`（或等效配置注入清单）

建议至少完成一次恢复演练：

- 将 DB 与 `uploadDir` 恢复到隔离环境
- SQLite 场景运行 `tools/beacon_backup.py create/verify/restore`，保留命令 JSON、归档 SHA-256 与恢复目录核对结果
- 验证 Admin/Analyzer/MediaServer 可启动
- 按 `docs/deploy/e2e-acceptance.md` 完成最小验收

---

## 8. 升级与回滚策略（离线环境）

离线升级建议具备：

- 可审计：升级包上传/应用/回滚过程可追溯
- 可回滚：保留 previous 状态，出现问题可快速回退
- 可验证：升级后执行健康检查与端到端验收
- Cloud 发布使用版本化 initialize Job，并以 `--wait --wait-for-jobs` 等待成功；迁移采用 expand/contract，Helm 回滚不等于 schema 回滚
- 演练停止当前 Worker leader，确认 standby 在目标 RTO 内接管且任务不重复

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
