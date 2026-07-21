---
title: API 兼容性与变更
icon: material/history
---

# API 兼容性与变更

当前仓库没有独立、连续维护的 API 语义版本，也没有生成式 OpenAPI Schema。根目录 `PROJECT_VERSION` 是产品版本，不等于 `/api/v1` 契约版本。

## 当前原则

- Machine OpenAPI、SDK 方法和 `beacon.event.v1` 是需要优先保持兼容的对接面。
- `/api/app-shell/*` 服务于 React 页面，可以随 UI 同步调整，不作为第三方长期契约。
- 破坏性变更必须在 [完整变更日志](../CHANGELOG.md) 和发布说明中列出真实路径、字段、替代方案及迁移步骤。
- 新增字段保持向后兼容；调用方应忽略未知字段。
- 调用方不应依赖可变的中文 `msg` 文本。

## 已知兼容路径

| 项目 | 状态 | 建议 |
|---|---|---|
| `/stream/open*`、`/control/open*` 和部分 `/api/post*` | 保留的工业兼容路径 | 新增调用优先使用仓库 SDK；不要猜测 REST 路由 |
| `Control.classThresh` / `overlapThresh` | v1 字段兼容保留 | 新协议使用 `algorithmParams.confThresh` / `nmsThresh` |
| Plugin SDK v2/v3 | 稳定 C ABI 方向 | 以头文件和协议文档为准 |
| `beacon.event.v1` | 当前告警事件 schema | 接收端按 `event_id` 幂等并忽略未知字段 |

## 发布前要求

任何准备公开承诺的 API 变更至少应包含：

1. 服务端测试和对应 SDK 测试。
2. 本目录中的真实请求示例。
3. 认证、权限和幂等语义。
4. 失败响应与回滚方式。
5. 在 `docs/CHANGELOG.md` 中记录首次提供或废弃的产品版本。

需要更严格的生态兼容性时，下一步应从当前 SDK 覆盖的 Machine OpenAPI 生成一份版本化 schema，而不是给现有 App Shell 接口套上并不存在的 `/api/v1` 承诺。
