---
title: Docker 部署
icon: fontawesome/brands/docker
---

# Docker 部署

当前仓库提供并验证的容器路线是 **Cloud POC**：Django Cloud
控制台、PostgreSQL、MinIO 和一个边缘上报模拟器。它适合界面预览、云端
接入联调和 API 验收。

!!! warning "能力边界"

    这个镜像不包含 Analyzer、GPU 推理运行时或完整 MediaServer 进程，
    因此不是“摄像头 + 算法检测”的 Edge 全栈容器交付。需要真实视频
    分析链路时，使用 [Edge 全栈部署](../deploy/edge-full-stack.md)。

## 前置条件

- Docker Engine 24+
- Docker Compose v2
- 至少 4 GB 可用内存

```bash
docker version
docker compose version
```

## 启动 Cloud POC

```bash
git clone https://github.com/skygazer42/Beacon.git
cd Beacon/deploy/cloud-saas-v1
cp .env.example .env
```

编辑 `.env`，替换每一个 `CHANGE_ME` 值。数据库密码如果包含 URL 保留
字符，还要对 `BEACON_CLOUD_DB_URL` 中的用户名和密码做 URL 编码。

```bash
docker compose config -q
docker compose up -d --build
docker compose ps
```

打开 `http://localhost:9991/login`，使用 `.env` 中的
`BEACON_BOOTSTRAP_ADMIN_USERNAME` 和 `BEACON_BOOTSTRAP_ADMIN_PASSWORD`。
边缘模拟器会上报一条带截图的演示告警，可在 `/cloud/alarms` 查看。

```bash
docker compose logs -f beacon-cloud
docker compose logs -f edge-simulator
```

## 启用监控组件

Prometheus 和 Grafana 是可选叠加层。先在 `.env` 中设置
`GF_SECURITY_ADMIN_PASSWORD`，然后执行：

```bash
docker compose -f compose.yml -f compose.monitoring.yml up -d
```

- Prometheus：`http://localhost:9090`
- Grafana：`http://localhost:3000`

Prometheus 使用同一个 `BEACON_OPEN_API_TOKEN` 访问 `/metrics`，不带凭据的
直接请求返回 401 是预期行为。

## 停止与清理

```bash
# 保留 PostgreSQL / MinIO 数据卷
docker compose down

# 删除数据卷，仅用于重置演示环境
docker compose down -v
```

## 生产前必做

- 所有密钥改用 Secret 管理，不随镜像或 Compose 文件分发。
- 在 HTTPS 反向代理后启用 Secure Cookie 和受信任的代理协议头。
- 限制 PostgreSQL、MinIO 和运维端口的网络边界。
- 使用固定镜像 digest、持久化数据卷、备份和外部可观测系统。
- 执行 [上线检查清单](../deploy/go-live-checklist.md) 和
  [安全加固](../deploy/security-hardening.md)。
