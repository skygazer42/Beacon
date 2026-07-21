# SDK

Beacon 仓库包含 Python、JavaScript 和 Go 三个轻量客户端，源码位于 `sdk/`。当前没有向 PyPI 或 npm 发布同名包；不要安装公共仓库中的 `beacon-sdk`，它们不是本项目。

| SDK | 安装/引用 | 运行时 |
|---|---|---|
| Python | `python -m pip install ./sdk/python` | Python 3.10+ |
| JavaScript | `npm install ./sdk/javascript` | Node.js 18+ 或现代浏览器 |
| Go | `go get github.com/skygazer42/Beacon/sdk/go@main` | Go 1.20+ |

三个客户端均覆盖仓库中已经实现的开发者接口和核心 OpenAPI，包括流/算法查询、告警上报、录像与任务计划、人脸、运维及云端告警接入。具体方法以各 SDK 的 README 和源码为准：

- [Python](python.md)
- [JavaScript](javascript.md)
- [Go](go.md)

服务端启用 OpenAPI Token 时，客户端必须传入相同的 `BEACON_OPEN_API_TOKEN`。不要把 Token 写进源码或提交到 Git。
