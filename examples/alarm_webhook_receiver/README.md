# Beacon Alarm Webhook Receiver（示例）

这是一个 **可直接运行** 的 Webhook 接收端示例，用于对接 Beacon 的 Alarm Event Bus（`alarm.created`）。

特性：
- 可选签名验签：`X-Beacon-Signature: sha256=<base64>`
- 幂等去重：按 `event_id` 去重（SQLite）
- 快速 ACK：先去重落库，再返回 `200`

---

## 1) 运行方式

### 1.1 无签名（仅开发测试）

```bash
cd examples/alarm_webhook_receiver
python3 receiver.py --host 0.0.0.0 --port 9000
```

默认监听：
- `http://0.0.0.0:9000/webhook/alarm`

### 1.2 开启签名验签（生产推荐）

```bash
cd examples/alarm_webhook_receiver
python3 receiver.py --host 0.0.0.0 --port 9000 --secret "please-change-me"
```

也可以通过环境变量传入：

```bash
export BEACON_ALARM_WEBHOOK_SECRET="please-change-me"
python3 receiver.py
```

---

## 2) Beacon 侧配置（指向 receiver）

在 `config.json` 中配置：

```json
{
  "alarmOutboxEnabled": true,
  "alarmWebhookEnabled": true,
  "alarmWebhookUrls": ["http://127.0.0.1:9000/webhook/alarm"],
  "alarmWebhookSecret": "please-change-me"
}
```

说明：
- `alarmWebhookUrls` 支持多个地址（Beacon 会逐个尝试投递）
- `alarmWebhookSecret` 设置后，receiver 必须验签，否则会返回 401

---

## 3) 本地测试（curl）

### 3.1 不验签

```bash
curl -sS -X POST "http://127.0.0.1:9000/webhook/alarm" \
  -H "Content-Type: application/json" \
  -d '{"schema":"beacon.event.v1","event_id":"evt-1","event_type":"alarm.created","event":"alarm_openAdd","alarm_id":1,"control_code":"ctrl-001"}'
```

### 3.2 带签名（与 Beacon 一致）

生成签名（Python 一行）：

```bash
python3 - <<'PY'
import base64, hashlib, hmac
secret = b"please-change-me"
body = b'{"schema":"beacon.event.v1","event_id":"evt-1","event_type":"alarm.created"}'
sig = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode("ascii")
print("sha256=" + sig)
PY
```

然后带上 header：

```bash
curl -sS -X POST "http://127.0.0.1:9000/webhook/alarm" \
  -H "Content-Type: application/json" \
  -H "X-Beacon-Signature: sha256=<替换成上一步输出>" \
  -d '{"schema":"beacon.event.v1","event_id":"evt-1","event_type":"alarm.created"}'
```

---

## 4) 幂等去重说明（event_id）

Beacon 投递语义是 **at-least-once**（至少一次投递），因此重复投递是正常现象。

该示例会把 `event_id` 写入 SQLite（默认 `./processed_events.sqlite3`）：
- 首次 event_id：打印一条日志并返回 `{"ok":true}`
- 重复 event_id：直接返回 `{"ok":true,"duplicate":true}`（不重复处理）

---

## 5) 运行自测（unittest）

```bash
cd examples/alarm_webhook_receiver
python3 -m unittest discover -p 'test_*.py' -v
```

