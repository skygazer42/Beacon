# 运行监控

Beacon Admin 在自身 HTTP 端口（默认 `9991`）提供健康检查、就绪检查和 Prometheus 文本指标。仓库没有单独的 `9100` 指标服务，也不需要在 `config.json` 中启用 Prometheus。

## 运维端点

| 路径 | 用途 | 成功响应 |
|---|---|---|
| `/healthz` | Admin 进程、版本、运行时长及后台服务状态 | HTTP 200 JSON |
| `/readyz` | 数据库及 Cloud 必需配置检查 | 就绪时 HTTP 200，否则 HTTP 503 |
| `/metrics` | Admin 的 Prometheus 文本指标 | HTTP 200 text/plain |

`/open/ops/health`、`/open/ops/ready` 和 `/open/ops/metrics` 是同一组端点的兼容别名。

这些端点受 OpenAPI/Ops 鉴权保护。生产环境设置 `BEACON_REQUIRE_OPEN_API_TOKEN=1`，再使用具有 `ops` scope 的数据库 API Key，或配置共享的 `BEACON_OPEN_API_TOKEN`：

```bash
curl http://127.0.0.1:9991/healthz \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}"

curl http://127.0.0.1:9991/metrics \
  -H "Authorization: Bearer ${BEACON_OPEN_API_TOKEN}"
```

登录 Admin 页面不会自动获得 Ops 端点权限。完整鉴权边界见 [认证鉴权](../api/authentication.md)。

## 当前指标

| 指标 | 说明 |
|---|---|
| `beacon_admin_build_info` | Admin 版本和构建标识 |
| `beacon_admin_uptime_seconds` | Admin 进程运行时间 |
| `beacon_admin_db_up` | 数据库连通状态 |
| `beacon_admin_db_latency_ms` | 数据库探测延迟 |
| `beacon_admin_system_cpu_used_ratio` | 主机 CPU 使用比例 |
| `beacon_admin_system_mem_used_ratio` | 主机内存使用比例 |
| `beacon_admin_system_disk_used_ratio` | 主机磁盘使用比例 |
| `beacon_admin_alarm_outbox_pending` | 待投递 Outbox 数量 |
| `beacon_admin_alarm_outbox_failed` | 失败 Outbox 数量 |
| `beacon_admin_login_lockout_active` | 当前生效的登录锁定数量 |
| `beacon_admin_login_lockout_principals` | 有锁定记录的账号数量 |
| `beacon_admin_license_active_leases` | 活跃授权租约数量 |
| `beacon_admin_license_active_nodes` | 活跃授权节点数量 |
| `beacon_admin_cloud_alarm_events_total` | Cloud 模式下已接收的告警总数 |

系统资源指标在采集失败时可能缺席；Cloud 指标只在 `BEACON_DEPLOYMENT_MODE=cloud` 时出现。当前端点不提供 Analyzer 的 GPU、帧率、推理延迟或队列指标，不能据此判断推理服务健康。

## Prometheus 抓取示例

```yaml
scrape_configs:
  - job_name: beacon-admin
    scrape_interval: 15s
    authorization:
      type: Bearer
      credentials: CHANGE_ME
    static_configs:
      - targets: ["beacon.example.internal:9991"]
    metrics_path: /metrics
```

不要把真实 Token 提交到仓库；优先通过 Prometheus 的 secret/file 机制注入。告警规则应只引用上表中真实存在的指标，例如：

```yaml
groups:
  - name: beacon-admin
    rules:
      - alert: BeaconAdminDatabaseDown
        expr: beacon_admin_db_up == 0
        for: 2m
        labels:
          severity: critical
      - alert: BeaconAlarmOutboxFailed
        expr: beacon_admin_alarm_outbox_failed > 0
        for: 5m
        labels:
          severity: warning
```

## 日志与链路监控

日志位置由启动方式、工作目录和服务管理器共同决定，不保证固定为某个仓库内文件。生产环境建议让 systemd、容器运行时或进程管理器收集标准输出，并配置轮转和留存。

`/healthz` 只说明 Admin 自身存活；完整 Edge 验收还应分别探测 MediaServer、Analyzer，并执行一次“拉流 → 布控 → 告警 → Webhook/Cloud”的业务链路测试。
