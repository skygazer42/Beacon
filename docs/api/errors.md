# 错误处理

Beacon 目前同时保留兼容接口和较新的网关响应，错误格式并未完全统一。调用方不要依赖一份虚构的全局错误码表。

## 判断顺序

1. 检查网络错误、超时和 TLS 错误。
2. 检查 HTTP 状态码。
3. 对 JSON 响应检查 `code`；只有 `code == 1000` 才视为业务成功。
4. 记录 `msg`、`X-Request-Id` 和 `X-Correlation-Id`，但不要根据可变的中文 `msg` 写业务分支。

## 常见响应

### 业务成功

```json
{"code": 1000, "msg": "success", "data": {}}
```

### 兼容接口业务失败

不少旧接口返回 HTTP 200：

```json
{"code": 0, "msg": "视频流不存在"}
```

因此只调用 `raise_for_status()` 不够。

### 网关拒绝

```json
{"code": 0, "msg": "unauthorized"}
```

| HTTP | 当前含义 |
|---|---|
| 400 | 请求体或参数无法解析（部分兼容接口仍会用 HTTP 200 + `code=0`） |
| 401 | OpenAPI/Ops Token 缺失、无效或已过期 |
| 403 | IP/WAF/权限策略拒绝，或 Cloud/Digital Human 凭据无权访问 |
| 404 | 路由或资源不存在 |
| 410 | 可选的 App Shell legacy API 阻断 |
| 429 | OpenAPI 网关限流 |
| 500 | 未处理的服务端错误 |
| 503 | 网关、密钥配置或依赖未就绪 |

## 客户端示例

```python
response = session.get(url, timeout=10)
response.raise_for_status()
payload = response.json()
if int(payload.get("code", 0)) != 1000:
    raise RuntimeError(payload.get("msg") or "Beacon API request failed")
data = payload.get("data")
```

对于清理、重启、升级、布控启停和告警上报，不要自动无限重试。只有网络错误、429 或明确的 5xx 才适合带抖动的有界退避；创建类请求应携带业务幂等键或先查询状态。

## 排障信息

- 响应头：`X-Request-Id`、`X-Correlation-Id`、限流相关头。
- Admin 日志中的同一 request ID。
- `/readyz` 的依赖状态。
- 布控操作对应的 ControlLog。
- 告警投递对应的 Outbox `status`、`attempts`、`last_http_status` 和 `last_error`。

如果准备把某组接口作为正式第三方契约，应先补充可机器验证的 OpenAPI Schema 和稳定错误枚举；当前仓库尚未提供这两项。
