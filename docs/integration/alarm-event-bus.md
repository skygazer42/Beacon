# 告警事件规范

Beacon 对 Webhook 与 Cloud 使用同一份 `beacon.event.v1` 告警载荷。投递语义是至少一次，下游必须按 `event_id` 幂等处理。

## 核心字段

- `schema`：`beacon.event.v1`
- `event_id`：事件 UUID
- `event_type`：`alarm.created`
- `event_source`：告警来源
- `timestamp`：ISO 8601 时间
- `node_code`：边缘节点编码
- `alarm_id`、`control_code`、`desc`
- `image_path`、`video_path`、`image_url`、`video_url`
- `data`：算法、视频流和扩展业务字段

## Webhook

请求为 UTF-8 JSON `POST`，并可能包含：

- `X-Beacon-Event-Id`
- `X-Beacon-Schema`
- `X-Beacon-Signature: sha256=<base64>`

配置 `alarmWebhookSecret` 后，签名值为 `base64(HMAC-SHA256(secret, raw_body))`。验签必须使用原始请求体并通过常量时间比较。

响应规则：

- 2xx：成功
- 429 或 5xx：重试
- 其他 4xx：永久失败

接收端应先持久化并快速返回 2xx，耗时工作异步执行。重复的 `event_id` 也应返回成功。

## Cloud

Cloud 出口使用边缘令牌调用 Beacon Cloud：

1. 有本地截图时请求预签名上传地址。
2. 上传截图。
3. 提交 `alarm.created` 事件；没有截图时直接提交。

Cloud 端同样以 `event_id` 做幂等处理。运行配置见 [告警事件总线](alarm-bus.md)。
