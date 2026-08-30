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
| Kubernetes Cloud 控制面 | [Kubernetes 部署](kubernetes.md) | 支持应用层多副本基线 |
| 多个 Edge 接入一个 Cloud | [Cloud SaaS v1](../integration/cloud-saas-v1.md) | 支持云边接入流程 |
| Cloud Web/后台 Worker 多副本 | Helm Chart | 已提供 Web 冗余与 Worker 自动接管 |
| PostgreSQL/对象存储自动切换 | 需托管服务或平台方案 | Chart 内置实例不支持 |
| MediaServer / Analyzer 自动故障转移 | 无现成方案 | 尚未交付 |

## 当前 Helm Chart 实际包含什么

`deploy/cloud-saas-v1/chart/` 默认渲染：

- 2 个 Beacon Cloud Web 副本；
- 2 个后台 Worker 副本，其中 1 个 advisory-lock leader、其余 standby；
- 1 个按 Release revision 命名的迁移/bootstrap 初始化 Job；
- 1 个 PostgreSQL StatefulSet；
- 1 个 MinIO StatefulSet；
- 1 个 Web/Worker 共享的 runtime RWX PVC；
- 可选 Edge Simulator Job；
- Service、可选 Ingress、PVC、Secret 和健康探针。

该 Chart 用于 Cloud 控制面和云边接口。应用 Web 与单例后台调度已经解耦，并有
PDB、滚动更新、跨节点偏好和 Worker 自动接管；生产 values 少于两个 Web/Worker
副本或缺少共享 runtime 持久卷会被拒绝。默认 PostgreSQL、MinIO 仍是单实例，
因此它不是数据库、对象存储或完整媒体链路的 HA 承诺。

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

## 若项目要求端到端高可用

在对外承诺 HA 前，至少需要单独设计并验收：

- PostgreSQL 与对象存储的高可用、备份和恢复；
- 多副本会话、限流和防重放共享状态；
- PostgreSQL advisory-lock leader 的故障接管、数据库会话中断和任务幂等；
- Analyzer 任务重调度与模型预热；
- MediaServer 录像、流代理和播放地址的故障转移；
- 明确的 RTO、RPO、容量上限和故障演练结果。

当前仓库已经实现 Cloud Web/Worker 的应用层冗余，但没有为其余能力提供完整可验证
实现，因此不应把本页或 Helm Chart 直接当作端到端 HA 交付承诺。
