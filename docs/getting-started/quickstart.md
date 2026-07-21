---
title: 5 分钟体验
description: 启动可重复的 Cloud POC 并查看一条边缘模拟告警
icon: material/timer-sand
---

# 5 分钟体验

这条快速路径验证登录、Cloud API、对象存储和告警展示。它使用边缘模拟器，
不启动 Analyzer 或真实摄像头检测。

## 1. 准备配置

```bash
git clone https://github.com/skygazer42/Beacon.git
cd Beacon/deploy/cloud-saas-v1
cp .env.example .env
```

编辑 `.env`，把所有 `CHANGE_ME` 替换成独立的随机值。记住你设置的
`BEACON_BOOTSTRAP_ADMIN_PASSWORD`。

## 2. 启动

```bash
docker compose config -q
docker compose up -d --build
docker compose ps
```

等 `postgres`、`minio` 和 `beacon-cloud` 显示为运行或健康状态。

## 3. 验收

1. 打开 `http://localhost:9991/login`。
2. 用 `.env` 中的 bootstrap 管理员账号登录。
3. 进入 `http://localhost:9991/cloud/alarms`。
4. 确认边缘模拟器上报的告警可见，并且详情页能读取截图。

如果告警未出现：

```bash
docker compose logs --tail=200 beacon-cloud
docker compose logs --tail=200 edge-simulator
```

## 4. 清理

```bash
docker compose down
```

只有在确定要删除演示数据时才执行 `docker compose down -v`。

## 继续做真实检测

要验证 RTSP/摄像头、GPU 算法和告警闭环，继续阅读：

- [第一条视频流接入](first-stream.md)
- [Edge 全栈部署](../deploy/edge-full-stack.md)
- [端到端验收](../deploy/e2e-acceptance.md)
