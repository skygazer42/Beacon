# Webhook 集成

Beacon 可以把已入库的 `alarm.created` 事件通过 HTTP POST 投递到一个或多个地址。当前实现使用数据库 Outbox、至少一次投递和可选的 HMAC-SHA256 签名。

## 配置

`config.json` 使用扁平字段：

```json
{
  "alarmWebhookEnabled": true,
  "alarmWebhookUrls": [
    "https://receiver.example.com/beacon/alarms"
  ],
  "alarmWebhookTimeoutSeconds": 5,
  "alarmWebhookSecret": ""
}
```

敏感值优先通过环境变量提供：

```dotenv
BEACON_ALARM_WEBHOOK_URLS=https://receiver.example.com/beacon/alarms
BEACON_ALARM_WEBHOOK_TIMEOUT_SECONDS=5
BEACON_ALARM_WEBHOOK_SECRET=<random-secret>
```

只要 `alarmWebhookUrls` 非空，运行时会启用 Webhook。生产必须使用 HTTPS，并避免把密钥写入 `config.json` 或 Git。

## 请求

```http
POST /beacon/alarms HTTP/1.1
Content-Type: application/json
User-Agent: beacon-alarm-webhook
X-Beacon-Event-Id: 550e8400-e29b-41d4-a716-446655440000
X-Beacon-Schema: beacon.event.v1
X-Beacon-Signature: sha256=<base64-hmac>
```

只有设置 `alarmWebhookSecret` 时才发送 `X-Beacon-Signature`。当前实现不会发送自定义时间戳、`X-Beacon-Event` 或任意用户配置的附加 Header。

## 事件格式

```json
{
  "schema": "beacon.event.v1",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "alarm.created",
  "event_source": "uploadAlarm",
  "timestamp": "2026-07-20T10:20:30.123456",
  "node_code": "beacon-edge-01",
  "event": "alarm_upload",
  "alarm_id": 123,
  "control_code": "ctrl-01",
  "desc": "发现人员",
  "image_path": "alarm/ctrl-01/main.jpg",
  "video_path": "",
  "image_url": "/static/upload/alarm/ctrl-01/main.jpg",
  "video_url": "",
  "alarm_type": "intrusion",
  "alarm_level": 1,
  "algorithm_code": "on_yolo11n_cpu",
  "object_code": "person",
  "stream_code": "cam-01",
  "metadata": {},
  "extra_images": [],
  "data": {
    "alarm_id": 123,
    "control_code": "ctrl-01",
    "desc": "发现人员",
    "image_path": "alarm/ctrl-01/main.jpg",
    "video_path": "",
    "image_url": "/static/upload/alarm/ctrl-01/main.jpg",
    "video_url": "",
    "alarm_type": "intrusion",
    "alarm_level": 1,
    "algorithm_code": "on_yolo11n_cpu",
    "object_code": "person",
    "stream_code": "cam-01",
    "metadata": {},
    "extra_images": []
  }
}
```

顶层业务字段为旧接收方保留，`data` 是规范化业务对象。新接收方应读取 `schema`、`event_type` 和 `data`，忽略未知字段，并以 `event_id` 做幂等去重。媒体 URL 可能是相对路径；能否下载还取决于部署的静态文件/对象存储配置和认证策略。

## 签名验证

签名算法与当前源码完全一致：

```text
signature = "sha256=" + Base64(HMAC-SHA256(secret, exact_request_body_bytes))
```

Python 示例：

```python
import base64
import hashlib
import hmac


def verify_beacon_signature(body: bytes, signature: str, secret: str) -> bool:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = "sha256=" + base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)
```

必须对收到的原始 body 字节验签，不能先解析再重新序列化 JSON。当前签名本身不含时间戳；接收方应保存 `event_id`，同时按业务需要限制来源网络和事件时间窗口。

## 投递与重试

启用 `alarmOutboxEnabled` 后，每个启用的 Sink 会生成一条 Outbox 记录：

- 成功条件：HTTP 2xx。
- 可重试：网络错误、超时、HTTP 429、HTTP 5xx。
- 永久失败：其他 HTTP 4xx。
- 退避：2、4、8、16、32 秒，之后每次 60 秒；当前没有最大重试次数。
- 语义：至少一次，不是恰好一次。

配置多个 URL 时会按顺序发送。后面的 URL 失败会导致整条 Outbox 重试，因此前面已经成功的接收方可能再次收到同一个 `event_id`。

## 接收端最小实现

1. 在读取/解析前保留原始 body。
2. 验证 `X-Beacon-Signature`；未配置签名时至少使用 TLS、来源限制和独立入口。
3. 校验 `schema == "beacon.event.v1"` 和 `event_type == "alarm.created"`。
4. 对 `event_id` 做唯一约束或幂等表。
5. 成功持久化后尽快返回 2xx；异步执行耗时业务。
6. 对无法修复的载荷返回明确 4xx，避免无限重试；临时故障返回 429/5xx。

## 联调

管理端“诊断中心”的 Sink 探测会构造测试事件并直接调用当前启用的 Webhook/Cloud Sink。正式告警仍应再做一次端到端测试，确认告警入库、Outbox、网络、验签和幂等全部生效。

相关文档：

- [告警事件规范](alarm-event-bus.md)
- [Cloud SaaS v1](cloud-saas-v1.md)
- [配置参考](../configuration/config-json.md)
