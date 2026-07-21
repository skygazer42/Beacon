# 告警接口

Analyzer 或第三方系统可以向 Admin 上报告警。Admin 负责预检、媒体落盘、告警入库、事件构造和可选的 Webhook/Cloud Outbox 投递。

## 上报告警

推荐使用 `POST /open/alarm/upload`。它支持 JSON、表单和 multipart：

```bash
curl -X POST http://localhost:9991/open/alarm/upload \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}" \
  -F 'control_code=ctrl-01' \
  -F 'desc=发现人员' \
  -F 'image_file=@snapshot.jpg'
```

核心字段包括：

| 字段 | 说明 |
|---|---|
| `control_code` | 关联布控编号 |
| `desc` | 告警描述 |
| `image_file` / `video_file` | multipart 媒体文件 |
| `image_base64` / `video_base64` | JSON 场景的 Base64 媒体 |
| `image_path` / `video_path` | 已在受控上传目录内的相对路径 |
| `alarm_type`、`alarm_level`、`algorithm_code`、`object_code` | 业务属性 |
| `stream_code`、`stream_app`、`stream_name` | 流属性 |
| `metadata`、`extra_images` | 检测框、变体图片等扩展信息 |

兼容接口 `POST /alarm/openAdd` 主要给 Analyzer 使用，并要求关联布控存在。新接入优先使用 `/open/alarm/upload` 和仓库 SDK。

## 查询与页面操作

告警列表、详情、审核、分配、导出和筛选预设由 React 页面通过 `/api/app-shell/alarms`、`/api/app-shell/alarm/detail`、`/api/app-shell/alarm/action/*` 调用。这些接口使用 Django Session，是页面内部契约，不是 API Key 资源 API。

当前没有 `/api/alarms/{id}/` 这一套 REST 路由。第三方需要查询告警时，应通过 Cloud 告警接口、Webhook 事件或新增一个明确评审后的 OpenAPI，而不是依赖 App Shell 私有路径。

## 增量通知

### HTTP

`GET /api/alarm/poll?after_id=<id>` 返回：

```json
{
  "code": 1000,
  "msg": "success",
  "data": {
    "new_count": 1,
    "newest_id": 123,
    "sound_url": ""
  }
}
```

该接口属于登录页面调用面，支持与告警列表相同的时间、布控、算法、未读和视频过滤参数。

### WebSocket

```text
ws://<host>:9991/ws/alarm/poll?after_id=0&interval_ms=3000
```

它只接受 `v3_sessionid` 登录会话。服务端消息格式为：

```json
{"type": "alarm.poll", "data": {"new_count": 1, "newest_id": 123, "sound_url": ""}}
```

没有 JWT/API Key 查询参数、订阅动作或自定义心跳协议。React 告警页当前默认使用 HTTP 轮询。

## Webhook / Cloud 投递

告警入库后会生成 `schema=beacon.event.v1`、`event_type=alarm.created` 的事件。启用 Outbox 时按 Sink 保存并至少投递一次；接收方必须按 `event_id` 幂等。签名、重试和完整字段见 [Webhook 集成](../integration/webhook.md) 与 [告警事件规范](../integration/alarm-event-bus.md)。
