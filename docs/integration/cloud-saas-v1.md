# Beacon Cloud SaaS v1（告警聚合 + 截图上云）集成指南

本指南描述如何用同一套 Django Admin 代码，通过 `BEACON_DEPLOYMENT_MODE=edge|cloud` 实现 Cloud SaaS v1：

- 云端（Cloud）：聚合告警事件 + 生成 S3 presigned PUT/GET + 控制台查看截图
- 边缘（Edge）：告警事件通过 DB Outbox 可靠投递；截图使用 presigned PUT 直传对象存储，再上报告警事件到云端

> 说明：v1 不包含"云端控制面"(对边缘下发配置/启停布控等),那是 v2 的范围。

!!! tip "Cloud SaaS 三件套"
    1. **告警聚合 / 截图上云** —— 本页(v1)
    2. **远程控制面**(查看远程视频流、录像、算法流) —— [云远程控制面](cloud-remote-control-plane.md)
    3. **告警事件载荷规范** —— [告警事件总线](alarm-event-bus.md)

---

## 1) 关键概念

### 1.1 Edge Token（每个边缘集群一个）

- Edge -> Cloud Open API 使用：`Authorization: Bearer <edge_token>`
- Cloud 侧只保存 `edge_token_hash`（`sha256(pepper + token)`），不保存明文 token
- token 可轮换、可吊销（禁用集群）

### 1.2 幂等（工业交付必备）

云端对告警事件按 `(edge_cluster_id, event_id)` 唯一约束去重：

- 边缘允许 at-least-once 重试（网络抖动/进程重启都不会丢）
- 云端重复 ingest 仍返回成功（不会重复入库）

### 1.3 S3 对象 Key 规范（确定性）

云端生成（边缘不可自定义）：

`tenant_<tenant_id>/project_<project_id>/cluster_<cluster_id>/alarms/YYYY/MM/DD/<event_id>/image.<ext>`

收益：

- 多租户隔离（按前缀清理/生命周期策略最稳）
- 重试覆盖同 key（可控）
- 易于做成本与留存策略

---

## 2) Cloud 侧部署（`BEACON_DEPLOYMENT_MODE=cloud`）

### 2.0 Docker Compose 一键 POC（推荐，开箱即验收）

> 适用场景：售前演示 / 交付验收 / 开发自测  
> 内容：Cloud Admin + Postgres + MinIO + Edge Simulator（自动造 1 条带截图的告警）

启动：

```bash
cd deploy/cloud-saas-v1
cp .env.example .env
# 编辑 .env，替换所有 CHANGE_ME
docker compose config -q
docker compose up -d --build
docker compose ps
```

看日志（建议开两个终端）：

```bash
docker compose logs -f beacon-cloud
docker compose logs -f edge-simulator
```

验收（浏览器）：

- 登录页：`http://localhost:9991/login`
- 账号：使用 `.env` 中的 `BEACON_BOOTSTRAP_ADMIN_USERNAME` 和 `BEACON_BOOTSTRAP_ADMIN_PASSWORD`
- 告警列表：`/cloud/alarms`（应看到 1 条 demo 告警）
- 告警详情：点击进入后应能看到截图预览  

> POC 默认开启 `BEACON_CLOUD_IMAGE_PREVIEW_PROXY=1`：截图预览走 Cloud 代理，避免 presigned GET 在 Docker 场景下指向 `minio` 域名导致浏览器不可达。

清理（删数据卷，方便重跑）：

```bash
docker compose down -v
```

### 2.0.1 可选：叠加监控（Prometheus + Grafana）

> 适用场景：售前演示 / 工业交付验收 / 运维看板  
> 内容：Prometheus 抓取 Beacon `/metrics`，Grafana 预置 Dashboard。

启动（在 POC 基础上追加一个 compose 文件）：

```bash
docker compose -f compose.yml -f compose.monitoring.yml up -d
```

访问：

- Prometheus：`http://localhost:9090`
- Grafana：`http://localhost:3000`（用户名 `admin`，密码来自 `.env`）

注意：

- `BEACON_OPEN_API_TOKEN` 由 `.env` 显式提供，用于保护 `/metrics` 与 `/open/*`。
- Prometheus 通过 `Authorization: Bearer <token>` 抓取（见 `deploy/cloud-saas-v1/monitoring/prometheus.yml`）。

可选：MinIO Console（排障用）

- `http://localhost:9001`
- 用户名/密码：来自 `.env` 中的 `MINIO_ROOT_USER` 和 `MINIO_ROOT_PASSWORD`

### 2.0.2 Helm Chart（Kubernetes）

> 适用场景：K8s 演示环境 / 交付模板 / 后续二次定制
> Chart 路径：`deploy/cloud-saas-v1/chart`

基础检查：

```bash
helm lint deploy/cloud-saas-v1/chart
helm template beacon-cloud deploy/cloud-saas-v1/chart --set beaconCloud.replicaCount=2 > /tmp/beacon-cloud-rendered.yaml
```

安装示例：

```bash
# 先准备镜像（示例标签）
docker build -t beacon-cloud-saas-v1:latest -f deploy/cloud-saas-v1/Dockerfile .

# kind/minikube 场景需先把镜像导入集群

helm upgrade --install beacon-cloud deploy/cloud-saas-v1/chart \
  --namespace beacon-cloud \
  --create-namespace \
  --set beaconCloud.image.repository=beacon-cloud-saas-v1 \
  --set beaconCloud.image.tag=latest
```

说明：

- Chart 默认部署 `beacon-cloud + postgres + minio + minio-init`，并保留 `edge-simulator` 为可选 Job。
- `beaconCloud.replicaCount` 支持横向扩容 Cloud Admin Deployment。
- 生产交付建议把 `beaconCloud.secrets.*`、`postgres.auth.password`、`minio.rootPassword` 改为 Secret 管理流程，不要继续使用 demo 默认值。

### 2.1 安装依赖

不使用 Docker Compose、改为手工部署 Cloud 时：

- Cloud 最小依赖（推荐）：`pip install -r Admin/requirements-cloud.txt`

> Edge/本地交付仍可继续使用：`Admin/requirements-linux.txt` / `Admin/requirements-windows.txt`。

### 2.2 Cloud 侧环境变量（必须）

最小必填：

- `BEACON_DEPLOYMENT_MODE=cloud`
- `BEACON_CLOUD_EDGE_TOKEN_PEPPER`（必须保密）
- `BEACON_CLOUD_S3_BUCKET`
- `BEACON_CLOUD_S3_REGION`（MinIO 可用 `us-east-1`）
- `BEACON_CLOUD_S3_ENDPOINT_URL`（MinIO/私有云必填）
- `BEACON_CLOUD_S3_ACCESS_KEY_ID`
- `BEACON_CLOUD_S3_SECRET_ACCESS_KEY`
- `BEACON_CLOUD_DB_URL`（推荐：Postgres；SQLite 仅适合本机验证）

可选（有默认值）：

- `BEACON_CLOUD_PRESIGN_PUT_EXPIRES_SECONDS=900`
- `BEACON_CLOUD_PRESIGN_GET_EXPIRES_SECONDS=60`
- `BEACON_CLOUD_IMAGE_PREVIEW_PROXY=1`（Docker/MinIO 场景推荐开启：截图预览走 Cloud 代理）

> 建议把 S3 SecretKey 与 pepper 用 Secret 注入，不要写到文件里。

### 2.3 数据库与迁移

Cloud 推荐使用 PostgreSQL（SQLite 仅用于本机验证）。当前数据库 URL 解析器不支持 MySQL。

在 Cloud 侧启动前请执行 Django migrations（含 cloud_saas_v1 相关新表）。

### 2.4 启动 Cloud

```bash
BEACON_DEPLOYMENT_MODE=cloud python3 Admin/manage.py runserver 0.0.0.0:9991
```

### 2.5 生成边缘集群 token

1. 浏览器打开 Cloud 控制台：
   - `/cloud/edge-clusters`
2. 点击“创建 + 生成 Token”
3. 复制页面提示的 `edge token`（**仅显示一次**）

---

## 3) Edge 侧部署（`BEACON_DEPLOYMENT_MODE=edge`）

### 3.1 前置要求：必须启用 DB Outbox

Edge -> Cloud sink 依赖 Alarm Event Bus（DB Outbox）：

- `alarmOutboxEnabled=true`（默认）
- Edge 的告警必须落库/可重试投递

> 已知限制：部署使用 `saveAlarmType=2`（仅 HTTP，不落库/outbox）时，Cloud sink 无法可靠同步（没有 outbox 记录）。工业交付建议使用能落库的模式。

### 3.2 Edge 侧环境变量（必须）

最小必填：

- `BEACON_DEPLOYMENT_MODE=edge`
- `BEACON_CLOUD_ENABLED=1`
- `BEACON_CLOUD_BASE_URL=https://cloud.example.com`
- `BEACON_CLOUD_EDGE_TOKEN=<从 Cloud 控制台复制>`

可选（有默认值）：

- `BEACON_CLOUD_UPLOAD_TIMEOUT_SECONDS=10`
- `BEACON_CLOUD_INGEST_TIMEOUT_SECONDS=5`

### 3.3 Edge 侧数据流（发生报警时）

1. 产生 alarm.created 事件（带 `event_id`）
2. Cloud sink 请求 Cloud presign：
   - `POST /open/cloud/v1/presign/image`
3. Edge 使用 presigned PUT 把截图直传对象存储
4. Edge 调用 Cloud ingest：
   - `POST /open/cloud/v1/events/alarm-created`
5. Cloud 控制台 `/cloud/alarms` 可查看并预览截图（presigned GET）

---

## 4) 对象存储（MinIO）示例

MinIO 推荐先跑通链路再换云厂商（S3 兼容，业务代码不变）。

Cloud 侧关键配置：

- `BEACON_CLOUD_S3_ENDPOINT_URL=http://<minio-host>:9000`
- `BEACON_CLOUD_S3_REGION=us-east-1`
- `BEACON_CLOUD_S3_ACCESS_KEY_ID=<minio-access-key>`
- `BEACON_CLOUD_S3_SECRET_ACCESS_KEY=<minio-secret-key>`

---

## 5) 常见问题排查（工业交付口径）

### 5.1 Edge 调用 Cloud 返回 401

原因：

- `Authorization: Bearer` 缺失
- `BEACON_CLOUD_EDGE_TOKEN` 配错
- Cloud 未正确配置 `BEACON_CLOUD_EDGE_TOKEN_PEPPER`

处理：

- Cloud 控制台轮换 token，并同步更新 Edge 侧环境变量

### 5.2 Edge 调用 Cloud 返回 403

原因：

- Cloud 上该 EdgeCluster 被禁用

处理：

- Cloud 控制台启用集群或重新创建集群

### 5.3 presign 正常但 PUT 失败

原因：

- S3 endpoint/ak/sk 配置错误
- PUT 超时/网络抖动
- 对象存储策略阻止写入（bucket policy）

处理：

- 检查 Cloud 侧 S3 env
- 先用 MinIO 本地验证链路

### 5.4 ingest 重复上报是否会重复入库？

不会。云端用 `(edge_cluster_id, event_id)` 唯一约束幂等去重，重复 ingest 返回成功但只落 1 条记录。
