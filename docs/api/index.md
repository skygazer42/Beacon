# API 概览

Beacon Admin 默认监听 `9991`。当前接口沿用已有工业交付路径，并不是统一的 `/api/v1/resources` REST 设计；对接时请使用本页列出的真实路径或仓库内 SDK，不要根据资源名猜测 URL。

## 接口分层

| 接口 | 路径 | 面向对象 | 稳定性 |
|---|---|---|---|
| Machine OpenAPI | `/open/*`、`/stream/open*`、`/control/open*`、`/algorithm/open*` | SDK、Analyzer、边缘节点、第三方系统 | 对外集成面 |
| Ops | `/healthz`、`/readyz`、`/metrics`、`/open/ops/*` | 探针、监控和运维工具 | 对外集成面 |
| Cloud | `/open/cloud/v1/*` | Edge 到 Cloud | 独立 Bearer Token 协议 |
| Digital Human runtime | `/open/agent/*`、`/open/human/report` | 数字人采集端 | 独立运行时协议 |
| App Shell | `/api/app-shell/*` | Beacon React 页面 | 内部接口，可能随 UI 调整 |
| Web 页面 | `/stream/index`、`/controls` 等 | 浏览器 | Django Session |

## 认证示例

生产环境应设置 `BEACON_REQUIRE_OPEN_API_TOKEN=1`，并使用后台创建的 API Key，或设置一个共享的 `BEACON_OPEN_API_TOKEN`：

```bash
curl http://localhost:9991/open/getStreamData \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}"
```

数据库 API Key 推荐使用相同请求头，也可以使用：

```http
Authorization: Bearer <api-key>
```

作用域当前只有 `openapi` 和 `ops`。不存在 `streams:read`、`alarms:write` 等资源级 API Key scope。

## 响应约定

大部分兼容接口返回：

```json
{
  "code": 1000,
  "msg": "success",
  "data": {}
}
```

- `code == 1000` 表示业务成功。
- 旧接口的业务失败通常仍返回 HTTP 200，但 `code == 0`；调用方必须同时检查 HTTP 状态和 `code`。
- 网关认证、WAF 和限流失败使用 HTTP 401、403 或 429，并返回 `{"code": 0, "msg": "..."}`。
- 个别下载、Prometheus 指标和媒体接口返回文件或纯文本，不使用 JSON envelope。

## 推荐调用方式

仓库包含 [Python、JavaScript 和 Go SDK](../sdk/index.md)，其方法与当前服务端路径一起测试。新增集成优先从 SDK 开始；如果 SDK 未覆盖所需接口，再根据 `Admin/app/urls.py` 和对应 view 确认方法、参数与认证边界。

## 主题文档

- [认证鉴权](authentication.md)
- [视频流接口](streams.md)
- [布控接口](controls.md)
- [告警接口](alarms.md)
- [系统与运维接口](system.md)
- [错误处理](errors.md)
