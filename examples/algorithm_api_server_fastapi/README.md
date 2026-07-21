# FastAPI 算法服务示例（API 协议 v2）

这个示例用于演示“API 类型基础算法”如何接入 Beacon：

- Analyzer 会把 `image_base64` + 布控参数按协议 v2 POST 到你的服务
- 你的服务返回 `{ code, msg, result: { happens, detects } }`
- 对于 Wave 1 ASR，Beacon OpenAPI 也可以把 `audio_base64` POST 到你的语音接口

本示例实现的是一个 **最小可运行** 的 API（不做真实推理，只返回固定检测框），用于验证链路。

---

## 1) 安装依赖

建议使用虚拟环境：

```bash
cd examples/algorithm_api_server_fastapi
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2) 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 3) Analyzer 配置

把布控的 `api_url` 配置为：

- `http://127.0.0.1:8000/infer`

然后 Analyzer 会按协议 v2 调用你的服务。

如果要演示 ASR Wave 1，可把语音算法的 `api_url` 配置为：

- `http://127.0.0.1:8000/audio/infer`

---

## 4) 手工测试

可以用 curl 发送一张图片的 base64：

```bash
python - <<'PY'
import base64, sys
path = sys.argv[1] if len(sys.argv) > 1 else "test.jpg"
data = open(path, "rb").read()
print(base64.b64encode(data).decode("ascii"))
PY
```

把输出粘贴到：

```bash
curl -X POST "http://127.0.0.1:8000/infer" \
  -H "Content-Type: application/json" \
  -d '{"image_base64":"...","algorithmCode":"demo"}'
```

ASR 也可以直接验证：

```bash
curl -X POST "http://127.0.0.1:8000/audio/infer" \
  -H "Content-Type: application/json" \
  -d '{"audio_base64":"YXVkaW8=","algorithmCode":"asr-demo","language":"zh-CN"}'
```

预期返回：

```json
{
  "code": 1000,
  "msg": "success",
  "result": {
    "text": "demo transcript",
    "language": "zh-CN",
    "segments": [
      {
        "start_ms": 0,
        "end_ms": 1200,
        "text": "demo transcript"
      }
    ]
  }
}
```
