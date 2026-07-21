# 集成对接

Beacon 当前提供两类稳定的外部契约：告警输出、企业认证。视频设备与算法接入另见对应协议文档。

## 告警输出

| 通道 | 用途 | 文档 |
|------|------|------|
| Webhook | 将 `alarm.created` 事件推送到第三方 HTTP 服务 | [Webhook 集成](webhook.md) |
| Beacon Cloud | 边缘告警与截图上云 | [Cloud SaaS v1](cloud-saas-v1.md) |
| WebSocket | 已登录管理端的告警增量显示 | [告警接口](../api/alarms.md#websocket) |
| PSIM / SOC | 通过 Webhook 对接安防平台或工单系统 | [PSIM 对接契约](psim.md) |

Webhook 与 Cloud 共用 `beacon.event.v1`，通过 DB Outbox 提供至少一次投递。接收方必须按 `event_id` 幂等处理。字段和签名规则见 [告警事件规范](alarm-event-bus.md)。

## 认证

| 通道 | 用途 | 文档 |
|------|------|------|
| LDAP/AD | 企业目录账号登录 | [LDAP/AD 认证](ldap.md) |
| OIDC SSO | Keycloak、Azure AD、Okta 等单点登录 | [OIDC SSO](oidc.md) |

## 视频与算法

- [GB28181 Provider TCP 模式](gb28181-provider-tcp-mode.md)
- [算法 API 协议 v2](algorithm-api-protocol-v2.md)
- [算法插件 SDK v2](algorithm-plugin-sdk-v2.md)
- [Cloud 远程控制面](cloud-remote-control-plane.md)
