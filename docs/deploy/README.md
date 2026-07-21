<div align="center">
  <img src="../assets/branding/readme-brand.png" alt="Beacon" width="720"/>
</div>

# Beacon 部署文档（从 0 开始）

本目录用于存放 Beacon 的部署/运行/验收文档，目标是让一个第一次拿到仓库的人，**从 0 到跑起来**，并且能做最小化验证。

如需最快进入功能测试，直接阅读下方 **「方案 A：Docker Compose（推荐）」**。

---

## 0. 先明确部署形态

Beacon 在仓库里主要有三块东西：

- `Admin/`：Django Web（管理后台 + API），浏览器中的主要 UI 由其提供。
- `Analyzer/`：C++ 分析引擎（二进制），负责“跑算法/布控”的核心计算。
- `MediaServer/`：流媒体服务（ZLMediaKit 体系）。

进入“运行阶段测试”通常分两类：

- 只测 Web/Cloud/权限/告警工作流等：跑 **Admin（Cloud POC）** 就够了。
- 要测真实 RTSP 拉流 + 算法 + 触发告警：需要把 **Admin + Analyzer + MediaServer** 一起跑起来（更偏交付/现场联调）。

本目录先把“最容易稳定复现的路径”写清楚：先跑 Cloud Docker POC。

---

## 1. 方案 A：Docker Compose 一键 Cloud POC（推荐）

这个 POC 会启动：

- `beacon-cloud`（Django Admin，`BEACON_DEPLOYMENT_MODE=cloud`）
- `postgres`（Cloud DB）
- `minio + minio-init`（S3 兼容对象存储 + 初始化 bucket）
- `edge-simulator`（模拟边缘节点上报 1 条带截图的告警）

### 1.1 前置要求

- 已安装 Docker（Windows 推荐 Docker Desktop）
- `docker compose` 可用

快速检查：

```bash
docker version
docker compose version
```

### 1.2 启动

在 Cloud POC 目录执行：

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

### 1.3 打开 Web

- 登录页：`http://localhost:9991/login`
- 账号：使用 `.env` 中的 bootstrap 管理员用户名和密码

Cloud 告警页（应当能看到 edge-simulator 上报的一条 demo 告警）：

- `http://localhost:9991/cloud/alarms`

### 1.4 运行 Saved Views 权限回归

容器内直接运行核心权限测试，验证无权限用户不能创建告警筛选预设：

```bash
docker compose exec -T beacon-cloud \
  python /app/Admin/manage.py test app.tests.test_user_permission_enforcement -v 2
```

预设的真实登录、创建、可见性与删除流程仍需在目标环境通过 `/alarms` 页面做一次人工验收，避免测试脚本向运行数据库写入临时用户和数据。

### 1.5 探针与 metrics（为什么会 401）

Cloud POC 从 `.env` 读取 `BEACON_OPEN_API_TOKEN`，并用它保护一些运维路径（比如 `/metrics`、`/healthz`、`/readyz` 等）。

`Admin/app/middleware.py` 支持两种 header：

- `Authorization: Bearer <token>`（推荐）
- `X-Beacon-Token: <token>`（legacy）

例子（在当前终端导出与 `.env` 相同的 token）：

```bash
curl -sS -H "Authorization: Bearer ${BEACON_OPEN_API_TOKEN}" \
  http://localhost:9991/metrics | head
```

### 1.6 停止/清理

停止但保留数据卷：

```bash
docker compose down
```

完全清理（连 Postgres/MinIO 数据卷一起删，适合“重跑验收”）：

```bash
docker compose down -v
```

---

## 2. 方案 B：本机直接跑 Admin（Edge/本地模式）

该路径适合本机开发调试，不依赖 Docker。

### 2.1 前置要求

- Python 3.10–3.12

### 2.2 安装依赖

Windows：

```powershell
cd Admin
python -m venv venv
venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
```

Linux：

```bash
cd Admin
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt
```

### 2.3 数据库与迁移

默认使用 SQLite：

- `Admin/Admin.sqlite3`（settings: `Admin/framework/settings.py`）

如需更换 SQLite 路径：

- 环境变量：`BEACON_SQLITE_DB_PATH=/abs/path/to/db.sqlite3`

首次运行建议执行迁移：

```bash
python manage.py migrate --noinput
```

如果是新库，需要创建管理员：

```bash
python manage.py createsuperuser
```

### 2.4 启动

```bash
python manage.py runserver 0.0.0.0:9991
```

浏览器访问：

- `http://127.0.0.1:9991/login`

---

## 3. 进一步阅读

- Cloud SaaS v1 集成说明（更详细的 Edge/Cloud 协议口径）：`docs/integration/cloud-saas-v1.md`
- Tracing（Jaeger + Tempo + OTel Collector）本地栈：`deploy/observability/tracing/README.md`
- 配置参考（`config.json` + env 覆盖规则）：`docs/deploy/config-reference.md`
- 运维手册（探针/metrics/诊断包/清理/离线升级）：`docs/deploy/ops-runbook.md`
- 端口与防火墙策略（端口矩阵/网络流向/巡检命令）：`docs/deploy/ports-and-firewall.md`
- 数据库与备份恢复（SQLite/Postgres/uploadDir/modelDir）：`docs/deploy/database-and-backup.md`
- 可观测性（Metrics/Logs/Tracing/诊断包）：`docs/deploy/observability.md`
- Edge 端到端验收（RTSP -> 拉流转发 -> 布控 -> 告警/模拟告警）：`docs/deploy/e2e-acceptance.md`
- 上线与运行阶段检查清单（交付/试运行）：`docs/deploy/go-live-checklist.md`
- 安全加固指南（Token/ApiKey/IP 策略/Rate Limit/WAF/登录安全/TOTP/SSO）：`docs/deploy/security-hardening.md`
- 密钥资产与轮换（Token/ApiKey/Pepper/Secret）：`docs/deploy/secrets-and-rotation.md`
- 反向代理部署（Nginx / HTTPS）：`docs/deploy/reverse-proxy-nginx.md`
- 进程托管与服务化（systemd / Windows Service）：`docs/deploy/service-management.md`
- 故障排除手册（常见 401/403/503/拉流失败/验收问题）：`docs/deploy/troubleshooting.md`
- 性能与稳定性调优（FramePool/外部推理/Rate Limit/告警链路）：`docs/deploy/performance-tuning.md`
- Edge 全栈（Admin + Analyzer + MediaServer）从 0 部署：`docs/deploy/edge-full-stack.md`
- Linux 本机源码运行：`docs/deployment/local-linux.md`
- Edge 交付包目录结构规范（让启动器能按约定找到二进制/配置）：`docs/deploy/delivery-layout.md`
