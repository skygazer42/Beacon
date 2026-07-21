---
title: 第一条视频流接入实战
description: 从浏览器登录到看见第一条告警的完整端到端 walkthrough
icon: material/play-network
---

# 第一条视频流接入实战

本页面把 [5 分钟快速体验](quickstart.md) 中的步骤展开成 **可逐步对照执行的实战 walkthrough**,适合第一次部署完成、需要把"通了"变成"用起来了"的运维或测试人员。

!!! info "前置条件"
    - 已经按照 [安装指南](installation.md) 启动了 Admin / MediaServer / Analyzer
    - 已经知道一台可访问的 IP 摄像头 RTSP 地址,或本地有一段 mp4 视频可作为模拟流
    - 浏览器可以访问 `http://<服务器 IP>:9991`

---

## 整体路径

```mermaid
flowchart LR
    A[① 浏览器登录] --> B[② 验证三服务健康]
    B --> C[③ 添加 RTSP/文件流]
    C --> D[④ 选内置算法新建布控]
    D --> E[⑤ 在画面上画 ROI]
    E --> F[⑥ 触发并查看告警]
    F --> G[⑦ 配置告警通知]
```

---

## ① 登录管理后台

打开 `http://<服务器 IP>:9991`,使用初始账号登录。

| 项目 | 值 |
|------|------|
| 默认地址 | `http://127.0.0.1:9991` |
| 默认用户名 | `admin` |
| 管理员密码 | 以 `createsuperuser` 或 Cloud bootstrap 时显式设置的值为准 |

!!! warning "首次登录立即改密"
    生产环境请在登录后立即修改密码,详见 [安全加固](../operations/security.md)。

---

## ② 验证三服务健康

打开终端执行,确保三个服务都返回正常:

```bash
curl -s -o /dev/null -w 'admin=%{http_code}\n' http://127.0.0.1:9991/login
curl -s http://127.0.0.1:9993/api/health
curl -s "http://127.0.0.1:9992/index/api/getServerConfig?secret=${BEACON_MEDIA_SECRET}" | head -c 200
```

期望:

- Admin `/login` 返回 `200`
- Analyzer `/api/health` 返回 `{"code":1000,...}`
- MediaServer `getServerConfig` 返回 `{"code":0,...}`

如果任何一项异常,先回到 [Linux 本机联调](../deployment/local-linux.md#common-troubleshooting) 中的排查清单。

---

## ③ 添加第一条视频流

进入「视频流管理」页,点击「添加」,选择最常见的 RTSP 协议。

=== "RTSP IP 摄像头"

    | 字段 | 示例值 |
    |------|--------|
    | 流编码 | `cam-test-01` |
    | 协议 | `rtsp` |
    | 地址 | `rtsp://admin:Pass123@192.168.1.100:554/Streaming/Channels/101` |
    | 描述 | 测试摄像头 |

=== "本地 mp4 文件回灌"

    | 字段 | 示例值 |
    |------|--------|
    | 流编码 | `file-test-01` |
    | 协议 | `file` |
    | 地址 | `/data/videos/sample.mp4` |
    | 是否循环 | `是` |

提交后,在「视频流管理」列表上点击 **预览** 按钮,几秒内应该能看到画面。看不到画面时常见原因:

- 摄像头网络不通 / 用户名密码错误 → 用 `ffplay` 或 `vlc` 直接拉流验证
- MediaServer 端口被占用 → 见 [本机联调常见故障](../deployment/local-linux.md#common-troubleshooting)

详见 [视频流管理指南](../guide/streams.md)。

---

## ④ 创建第一个布控任务

进入「布控管理」→「新建布控」,最关键的几项:

| 字段 | 推荐填法 |
|------|----------|
| 关联视频流 | 选刚才创建的 `cam-test-01` |
| 算法 | 选内置「人员入侵检测」(`ov_yolov8n_80` 或类似) |
| 检测类别 | `person` |
| 置信度阈值 | `0.5` 起步 |
| 调度计划 | `7×24` |
| 告警冷却时间 | `30s` |

布控保存后,进入下一步绘制 ROI。

---

## ⑤ 在画面上画 ROI

点击布控行的「绘制区域」按钮,在视频画面上:

1. 鼠标依次点击形成多边形(至少 3 个点)
2. 双击闭合
3. 保存

ROI 决定 **"目标进入此区域才告警"**,常见误区:

- 把整个画面框成 ROI → 任何运动都会告警,容易告警风暴
- ROI 范围过小 → 目标在框内但部分越界,导致漏报

---

## ⑥ 触发并查看告警

让一个真实人员经过摄像头画面 / 让回灌视频中包含人员片段。等待 5–15 秒,在「告警管理」页面应该能看到新告警:

- 缩略图带有红色检测框
- 点开告警可以播放 5–10 秒告警视频片段
- 字段中包含 `controlCode`、`streamCode`、`algorithmCode`、置信度

如果迟迟没有告警,按以下顺序排查:

1. 「布控管理」中布控状态是否为 **运行中**
2. 「视频流管理」中流是否在线
3. Analyzer 日志(`log/`)中搜索 `controlCode`,确认是否在推理
4. 详见 [算法故障排查](../algorithms/troubleshooting.md)

---

## ⑦ 把告警推送到外部系统

仅在 Beacon 内查看告警是不够的,生产环境通常需要把告警推送到运维平台:

- 推 HTTP 接口: [Webhook 集成](../integration/webhook.md)
- 推送到 Beacon Cloud: [Cloud SaaS v1](../integration/cloud-saas-v1.md)
- 协议字段: [告警事件载荷规范](../integration/alarm-event-bus.md)

最小验证:

```bash
# 启动一个本地 webhook 接收器
cd examples/alarm_webhook_receiver
python receiver.py
```

然后在 Admin 「系统设置 → 告警通知」中配置 webhook URL 指向本地接收器,再触发一条告警即可看到回调。

---

## 你已经走完最小闭环

| 阶段 | 关注点 |
|------|--------|
| **流接入** | 流编码、协议、URL、ROI |
| **检测** | 算法选型、阈值、调度计划 |
| **告警** | 冷却时间、截图与视频、推送渠道 |

继续深入:

- [视频流管理](../guide/streams.md) — 多流批量、ONVIF 发现、健康监控
- [布控管理](../guide/controls.md) — 复杂行为(越线、徘徊、跌倒)
- [算法管理](../guide/algorithms.md) — 自定义模型、Pipeline
- [API 文档](../api/index.md) — 用脚本批量管理流和布控
