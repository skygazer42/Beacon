# 系统与运维接口

本页只列出当前代码中存在的机器接口。React 系统设置页使用 `/api/app-shell/*` 会话接口，不等同于公开 REST 配置 API。

## 健康与指标

| 方法 | 路径 | scope | 返回 |
|---|---|---|---|
| GET | `/healthz` 或 `/open/ops/health` | `ops` | 进程存活状态 |
| GET | `/readyz` 或 `/open/ops/ready` | `ops` | 数据库及关键依赖就绪状态 |
| GET | `/metrics` 或 `/open/ops/metrics` | `ops` | Prometheus 文本 |

```bash
curl http://localhost:9991/open/ops/ready \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}"
```

## 平台信息

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/open/platform/basicInfo` | 节点、版本和进程基础信息 |
| GET | `/open/platform/storageInfo` | 受控存储目录和容量信息 |
| POST | `/open/platform/restartSoftware` | 重启 Beacon 软件；高风险 |
| POST | `/open/platform/restartSystem` | 重启主机；高风险且依赖部署权限 |
| GET | `/open/getAllCoreProcessData` | 云远程控制面进程列表 |
| GET | `/open/getAllCoreProcessData2` | 兼容的扩展进程信息 |

重启动作必须配合最小权限、审计、TOTP 二次确认或上游审批；不要直接暴露到公网。

## 授权

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/open/license/info` | 查询当前授权状态 |
| GET | `/open/license/usage` | 查询授权用量 |
| POST | `/open/license/lease/acquire` | 获取池化授权租约 |
| POST | `/open/license/lease/renew` | 续租 |
| POST | `/open/license/lease/release` | 释放租约 |

## 运维动作

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/open/ops/cleanup` | 按允许的 target 执行预览或清理 |
| POST | `/open/ops/outbox/replay` | 重放失败的 Outbox 记录 |
| POST | `/open/ops/logging/level` | 调整运行时日志级别 |
| GET | `/open/ops/audit/export` | 导出审计记录 |
| GET | `/open/ops/diagnostics/export` | 导出诊断包 |
| GET / POST | `/open/ops/upgrade/*` | 离线升级包上传、校验、应用和回滚 |

具体参数优先使用 [SDK](../sdk/index.md)，并先在测试环境调用 `dry_run`/校验接口。升级、清理、重启和日志级别变更都应视为高风险操作。

## ONVIF 与设备发现

`GET /open/discover` 返回 Beacon 节点和服务发现信息，不是 ONVIF 扫描。ONVIF 设备扫描与管理目前是登录页面能力（`/onvif/discover` 和 `/api/app-shell/onvif/*`），没有 `/api/onvif/discover/` 或 `/api/onvif/ptz/` REST 路由。

GB28181 PTZ 使用 `POST /stream/openGb28181Ptz`，详见 [视频流接口](streams.md)。

## 只读文件服务

设置 `BEACON_FILE_SERVICE_ENABLED=1` 后，`GET /open/fileService/<relative-path>` 可从配置的根目录下载文件。路径会做目录边界校验，但生产仍应强制 Token、限制根目录并通过反向代理限制来源。
