# 故障恢复与演练

Beacon 当前提供健康检查、备份说明、Outbox 重试和服务托管样例，但不包含自动主备选举、Analyzer 任务迁移或 MediaServer 跨节点接管。本页描述的是手工恢复基线，不是高可用承诺。

## 先定义目标

部署方应分别为 Admin、Analyzer、MediaServer、数据库/文件和告警出口定义 RTO/RPO。数值必须来自实际演练；仓库不预设“30 分钟恢复”或“5 分钟数据点”等服务等级。

## 恢复顺序

1. 确认数据库、`config.json`、模型、授权和上传/录像目录可用。
2. 恢复 Admin，并使用带 `ops` 权限的 Token 检查 `/healthz` 与 `/readyz`。
3. 恢复 MediaServer，验证配置中的 HTTP、RTSP、RTMP 端口和至少一条关键流。
4. 恢复 Analyzer，检查 `/api/health`、模型加载和真实推理日志。
5. 检查布控实际状态、Outbox 积压和下游幂等结果。

## 演练前记录

```bash
git rev-parse --short HEAD
ss -tlnp | grep -E '9991|9992|9993|9994|9995'
curl -fsS http://127.0.0.1:9991/readyz \
  -H "Authorization: Bearer ${BEACON_OPEN_API_TOKEN}"
curl -fsS http://127.0.0.1:9993/api/health
```

如果 Analyzer 配置了 Token，应按其部署协议增加 `Authorization: Bearer` 或 `X-Beacon-Token`。同时记录最新备份、关键流/布控、Outbox 指标以及各组件日志采集位置。

## 故障矩阵

| 注入场景 | 预期影响 | 观察 | 恢复与验收 |
|---|---|---|---|
| 停止 Admin | 页面、OpenAPI、告警入库不可用 | `:9991`、反代、数据库和 Admin 日志 | 重启后 `/readyz` 成功，登录、写入和后台任务正常 |
| 停止 Analyzer | 实时推理和新告警中断 | `:9993`、布控状态、模型日志 | 重启并重新核对布控，真实测试流产生预期结果 |
| 停止 MediaServer | 拉流、播放、录像/转推中断 | `:9992/:9994/:9995`、媒体 API 和日志 | 重启代理，关键流可播放且 Analyzer 恢复解码 |
| 数据库不可写 | 配置、告警、审计和 Outbox 写入失败 | `/readyz`、数据库日志和磁盘 | 恢复数据库，验证迁移和业务写入，不只检查连接 |
| 磁盘耗尽 | 截图、录像、日志或数据库失败 | 磁盘比例、写入错误 | 先止写/扩容，再按留存策略清理并验证文件权限 |
| Webhook/Cloud 不可达 | 下游暂时收不到事件 | Outbox pending/failed、接收端日志 | 恢复后确认队列消化；按 `event_id` 去重 |

## 演练记录

| 日期 | 版本/模型 | 场景 | 发现时间 | 恢复时间 | 数据损失/重复 | 结论与改进 |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | commit + model hash | Analyzer 停止 |  |  |  |  |

每次演练都应保留命令、日志、时间线和验收证据。自动切换、多副本 Admin 或跨节点调度属于后续架构改造，不能通过增加 Gunicorn worker 或 Kubernetes replica 直接获得。
