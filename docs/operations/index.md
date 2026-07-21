---
title: 运维手册
icon: material/tools
---

# 运维手册

Beacon 当前既可单机运行，也提供 Cloud POC 和 Helm 参考，但没有自动的 MediaServer/Analyzer 故障迁移。运维目标和 SLO 必须由部署方按真实模型、视频与基础设施制定。

## 章节导航

| 章节 | 内容 |
|---|---|
| [运行监控](monitoring.md) | Admin 的 `/healthz`、`/readyz`、`/metrics` 及链路探测边界 |
| [安全加固](security.md) | 凭据、TLS、网络、OpenAPI、数据和审计 |
| [数据库与备份](../deploy/database-and-backup.md) | SQLite/PostgreSQL、配置和文件恢复 |
| [Failover 演练](failover.md) | 当前手工恢复能力与演练记录 |
| [故障排查](troubleshooting.md) | Admin、流媒体、Analyzer、告警和页面问题 |
| [性能调优](performance.md) | 可复现的容量基线与调优方法 |

## 组件检查面

| 对象 | 可直接检查的信号 | 仍需业务验收的内容 |
|---|---|---|
| Admin `:9991` | `/healthz`、`/readyz`、`/metrics`、登录和日志 | 页面/API 权限、数据库写入、后台任务 |
| Analyzer `:9993` | 端口、`/api/health`、启动/模型日志 | 真实流解码、模型推理、告警回调 |
| MediaServer `:9992/:9994/:9995` | 端口、MediaServer API 和日志 | 拉流稳定性、播放、录像、转推 |
| 数据库/文件 | 连接、容量、备份任务 | 恢复后的数据完整性与权限 |
| 告警出口 | Outbox pending/failed、接收端日志 | `event_id` 幂等和端到端时延 |

## 最小巡检节奏

| 频率 | 检查 |
|---|---|
| 持续 | Admin 探针、进程端口、磁盘水位、Outbox failed |
| 每日 | 三组件错误日志、备份任务结果、关键视频和布控状态 |
| 每周 | 随机恢复一份备份、检查账号/API Key、依赖和证书到期时间 |
| 发布前后 | 记录版本与模型哈希，执行端到端验收和回滚演练 |

不要只用 `/healthz` 代替业务监控。正式验收至少要覆盖一次“视频接入 → 布控 → Analyzer 推理 → Admin 告警入库 → Webhook/Cloud 投递”。

## 关键限制

- Admin 的计划、清理和 Outbox 等后台任务当前随 Django 进程启动。参考 Cloud 部署固定一个 Gunicorn worker 和一个副本。
- WebSocket 需要 ASGI；只用 WSGI/Gunicorn 启动时，常规 HTTP 页面仍可用但 `/ws/alarm/poll` 不可用。
- Cloud POC 不包含 Analyzer 和 MediaServer，不能用它证明真实检测链路可用。
- 外部告警是至少一次投递，下游必须按 `event_id` 幂等。
