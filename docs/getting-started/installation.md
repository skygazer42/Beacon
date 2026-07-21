---
title: 安装指南
icon: material/download
---

# 安装指南

先根据验证目标选一条路线。三条路线的产物和能力不同，不要混用启动命令。

| 目标 | 推荐路线 | 包含内容 |
|---|---|---|
| 快速查看云端 UI 和上报流程 | Cloud POC | Admin + PostgreSQL + MinIO + Edge Simulator |
| 开发后台、API 和 React 页面 | Admin 源码 | Django + SQLite + React 已构建产物 |
| 真实 RTSP/摄像头检测 | Edge 全栈 | Admin + Analyzer + MediaServer + 模型/推理运行时 |

## Cloud POC

```bash
git clone https://github.com/skygazer42/Beacon.git
cd Beacon/deploy/cloud-saas-v1
cp .env.example .env
# 编辑 .env，替换所有 CHANGE_ME
docker compose config -q
docker compose up -d --build
```

访问 `http://localhost:9991/login`，账号与密码以 `.env` 中的 bootstrap
变量为准。详见 [Docker 部署](../deployment/docker.md)。

## Admin 本地开发

支持 Python 3.10、3.11 和 3.12。

```bash
cd Beacon/Admin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt
python manage.py migrate --noinput
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:9991
```

Windows 把激活命令换成 `.venv\Scripts\activate`，依赖文件换成
`requirements-windows.txt`。新数据库没有预置登录账号，必须执行
`createsuperuser` 或使用明确配置的 bootstrap 命令。

React 源码在 `Admin/frontend/`：

```bash
cd Admin/frontend
npm ci
npm test
npm run build
```

## Edge 全栈

Edge 路线需要 FFmpeg、OpenCV 4、ONNX Runtime，以及与目标硬件匹配的
OpenVINO 或 CUDA/TensorRT。仓库不分发模型权重和这些大型运行库。

按下列文档顺序操作：

1. [环境要求](requirements.md)
2. [Edge 全栈部署](../deploy/edge-full-stack.md)
3. [Linux 本机构建](../deployment/local-linux.md) 或
   [Windows 本机构建](../deployment/local-windows.md)
4. [端到端验收](../deploy/e2e-acceptance.md)

## 安装后检查

```bash
curl -fsS http://127.0.0.1:9991/healthz
curl -fsS http://127.0.0.1:9991/readyz
```

MediaServer 和 Analyzer 只有在 Edge 全栈中启动后才会监听 `9992` 和
`9993`。请不要把 Cloud POC 没有这两个进程误判为安装失败。
