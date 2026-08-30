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

Compose 会先用一次性 `minio-volume-init` 容器收紧对象存储卷权限，然后以 UID
`10001` 启动 MinIO。`beacon-init` 串行执行 Bucket 初始化、数据库 migration 和幂等
bootstrap；成功后才启动 `beacon-cloud` Web 与 `beacon-background-worker`。各角色在依赖
失败时关闭式退出。Beacon、MinIO、PostgreSQL、边缘模拟器及可选监控组件均使用只读根文件系统、
最小 capabilities 与显式可写卷；第三方基础镜像固定到 digest。Beacon healthcheck
调用带 Token 的 `/readyz`；后台 Worker 使用带新鲜度和状态校验的 heartbeat healthcheck，
因此数据库、对象存储 Bucket 或单例后台服务未就绪时不会被误判为健康。

不可变静态资源在镜像构建阶段完成 `collectstatic`。运行时上传写入共享
`cloud_runtime:/app/data` 卷，并通过登录会话保护的 `/static/upload/*` 兼容路由读取；
不会向只读镜像内的 `/app/Admin/static` 写文件。

Cloud 镜像从 `Admin/requirements-cloud.lock` 安装完整且带 SHA-256 的依赖闭包，
`uv pip` 使用 `--require-hashes` 和 binary-only 模式。构建时临时挂载 digest 固定的
`uv 0.12.7`，安装器不会进入最终镜像；基础层使用 digest 固定的 Python 3.12 / Alpine 3.23，
构建时应用可用的 Alpine 安全更新，并在依赖校验后移除 `pip`。本地 PyInstaller 产物、
虚拟环境和 `collectstatic` 输出不会进入构建上下文。修改 `requirements-cloud.txt` 后必须执行
lock 文件头部记录的 `uv pip compile` 命令，并运行：

```bash
python deploy/cloud-saas-v1/scripts/verify_requirements_lock.py \
  Admin/requirements-cloud.txt Admin/requirements-cloud.lock
```

打开 `http://localhost:9991/login`，使用 `.env` 中的
`BEACON_BOOTSTRAP_ADMIN_USERNAME` 和 `BEACON_BOOTSTRAP_ADMIN_PASSWORD`。
边缘模拟器会上报一条带截图的演示告警，可在 `/cloud/alarms` 查看。

Compose 默认把 Admin、MinIO API、MinIO Console、Prometheus 和 Grafana 只发布到宿主机
`127.0.0.1`。需要调整本机端口时设置 `BEACON_ADMIN_PORT`、
`BEACON_MINIO_API_PORT`、`BEACON_MINIO_CONSOLE_PORT`、`BEACON_PROMETHEUS_PORT`
和 `BEACON_GRAFANA_PORT`；只有在已经配置受审查的
防火墙或反向代理时，才把 `BEACON_BIND_ADDRESS` 改成明确的私网地址。不要在生产环境
使用 `0.0.0.0` 直接暴露 MinIO Console。

本 Compose 文件通过 `BEACON_CLOUD_ALLOW_INSECURE_HTTP=1` 明确声明本机 HTTP POC
例外。Cloud 容器在没有该声明时会拒绝关闭 Session/CSRF Secure Cookie；生产部署必须
删除例外并通过 TLS 提供服务。

```bash
docker compose logs -f beacon-cloud
docker compose logs -f beacon-background-worker
docker compose logs beacon-init
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
