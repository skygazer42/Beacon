---
title: 集群部署边界
icon: material/server-network
---

# 集群部署边界

当前仓库提供的是“一个 Cloud 控制面连接多个独立 Edge 节点”的云边协同能力，
不是已经完成自动故障转移的高可用 VMS 集群。请先根据目标选择部署入口：

| 目标 | 当前可用入口 | 支持状态 |
|---|---|---|
| 单机 Edge 全栈 | [Edge 全栈部署](../deploy/edge-full-stack.md) | 支持 |
| Cloud POC | [Docker 部署](docker.md) | 支持 |
| Kubernetes Cloud 控制面 | [Kubernetes 部署](kubernetes.md) | 支持参考部署 |
| 多个 Edge 接入一个 Cloud | [Cloud SaaS v1](../integration/cloud-saas-v1.md) | 支持云边接入流程 |
| Cloud 多副本、数据库自动切换 | 无现成方案 | 尚未交付 |
| MediaServer / Analyzer 自动故障转移 | 无现成方案 | 尚未交付 |

## 当前 Helm Chart 实际包含什么

`deploy/cloud-saas-v1/chart/` 默认渲染：

- 1 个 Beacon Cloud Web 副本；
- 1 个 PostgreSQL StatefulSet；
- 1 个 MinIO StatefulSet 和初始化 Job；
- 可选 Edge Simulator Job；
- Service、可选 Ingress、PVC、Secret 和健康探针。

该 Chart 用于验证 Cloud 控制面和云边接口。默认 PostgreSQL、MinIO 都是
单实例，`beaconCloud.replicaCount` 也默认为 `1`。仅把副本数调大并不会自动
获得数据库高可用、共享限流、防重放、会话粘性或媒体任务接管能力。

## 多 Edge 接入流程

1. 按 Kubernetes 或 Docker 文档部署 Cloud，并完成管理员初始化。
2. 在 Cloud 的边缘集群页面创建集群并生成接入凭据。
3. 在每个 Edge 上配置 Cloud 地址和独立的 Edge token。
4. 分别验证节点心跳、远程资源读取、告警上报和截图访问。
5. 撤销或轮换单个节点 token，确认不会影响其他 Edge。

Edge token 属于生产凭据，不要写入镜像、Chart values、Git 或截图。具体字段与
接口见 [Cloud SaaS v1](../integration/cloud-saas-v1.md) 和
[环境变量参考](../configuration/env-vars.md)。

## 发布前验证

```bash
docker compose \
  --env-file deploy/cloud-saas-v1/.env.example \
  -f deploy/cloud-saas-v1/compose.yml config --quiet

python deploy/cloud-saas-v1/tests/test_helm_chart.py
```

正式部署还应在目标集群执行 `helm template` / `helm upgrade --install`，并验证
Ingress TLS、PVC、备份恢复、NetworkPolicy、资源限制和 Pod 重建后的数据完整性。

## 若项目要求真正高可用

在对外承诺 HA 前，至少需要单独设计并验收：

- PostgreSQL 与对象存储的高可用、备份和恢复；
- 多副本会话、限流和防重放共享状态；
- Admin 后台任务的唯一执行或分布式锁；
- Analyzer 任务重调度与模型预热；
- MediaServer 录像、流代理和播放地址的故障转移；
- 明确的 RTO、RPO、容量上限和故障演练结果。

当前仓库没有为这些能力提供可验证实现，因此不应把本页或 Helm Chart 当作 HA
交付承诺。
