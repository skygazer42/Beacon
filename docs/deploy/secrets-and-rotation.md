# Beacon 密钥资产与轮换（Token / ApiKey / Pepper / Secret）

本文档用于将 Beacon 的密钥资产管理与轮换流程固化为企业级操作口径，覆盖：

- 密钥资产清单与推荐存放方式（env/Secret Manager）
- OpenAPI Token 与 DB ApiKey 的轮换策略
- ApiKey Pepper 的特殊性（变更会导致历史 ApiKey 全部失效）
- MediaServer `secret`、Django `SECRET_KEY` 等其他关键 secret 的轮换影响

相关文档：

- 安全加固基线：`docs/deploy/security-hardening.md`
- 配置参考：`docs/deploy/config-reference.md`
- 上线检查清单：`docs/deploy/go-live-checklist.md`

---

## 1. 密钥资产清单（建议建立台账）

Beacon 常见敏感配置项（建议统一纳入密钥台账与访问控制）：

OpenAPI 与运维：

- `BEACON_OPEN_API_TOKEN`（legacy 单 Token）
- DB ApiKey（多 key；明文仅在创建时返回）
- `BEACON_API_KEY_PEPPER`（ApiKey hash 混入 Pepper）

Admin（Django）：

- `BEACON_DJANGO_SECRET_KEY`

MediaServer：

- `config.json.mediaSecret` 与 ZLMediaKit `config.ini [api].secret`

告警外发与第三方集成（按启用项纳入）：

- Webhook：`BEACON_ALARM_WEBHOOK_SECRET`
- Cloud：`BEACON_CLOUD_EDGE_TOKEN`
- OIDC：`BEACON_OIDC_CLIENT_SECRET`
- LDAP：`BEACON_LDAP_BIND_PASSWORD`
- TURN：`BEACON_WEBRTC_TURN_PASSWORD`
- License：`BEACON_LICENSE_KEY` / 相关 dongle 配置
- 模型加密：`BEACON_MODEL_ENCRYPT_KEY`

说明：

- `config.json` 可能包含 token/secret/password 等字段；工业交付建议将敏感项改为 env 注入，避免落盘明文与诊断包泄露风险。

---

## 2. 推荐存放方式（工业交付）

推荐优先级（从强到弱）：

1. Secret Manager/KMS（按平台能力：k8s secret、Vault、云厂商 Secret Manager 等）
2. 环境变量注入（由服务管理器/systemd/k8s 注入，避免在命令行参数出现明文）
3. `.env` 文件（仅限交付脚本加载；需严格权限控制；不进入版本库）
4. `config.json`（不推荐存放密钥；仅作为兼容或开发场景）

对 `.env` 的要求（如使用）：

- 权限最小化（仅运行账号可读）
- 禁止进入版本库
- 轮换时与发布流程绑定（避免“配置漂移”）

---

## 3. OpenAPI Token（legacy）轮换

能力边界：

- legacy Token 为“单值”校验（不支持双 token 并行）。
- OpenAPI Token 与 DB ApiKey 可并行存在；即使设置了 `BEACON_OPEN_API_TOKEN`，ApiKey 仍可用于授权 OpenAPI/Ops（按 scope）。

轮换策略（推荐：以 ApiKey 承担常态授权，Token 仅作为兼容兜底）：

1. 在 Admin 中创建新的 ApiKey（scope=ops 与 scope=openapi 按需拆分）
2. 将新 ApiKey 分发到探针/自动化脚本/集成系统
3. 验证新 ApiKey 可正常访问 `/open/ops/*` 与业务 OpenAPI
4. 将 legacy Token 更新为新值（维护窗口内执行）
5. 验证旧 token 请求已失效（避免遗留系统继续使用）

说明：

- 若仍存在必须使用 legacy Token 的旧系统，轮换通常需要停机窗口或严格的分批切换与回滚预案。

---

## 4. DB ApiKey 轮换（推荐）

ApiKey 轮换建议采用“新建 -> 验证 -> 替换 -> 吊销”的标准流程：

1. 新建 ApiKey（配置 scopes、过期时间、行级 rate limit）
2. 分发明文 token（仅在创建时可见，需按密钥分发规范执行）
3. 验证调用链路（OpenAPI/Ops）
4. 将旧 key 标记为 revoked/disabled（或设置过期）
5. 导出运维审计留档（可选）

建议：

- 运维探针与业务系统使用不同 key（便于最小权限与事件追溯）
- 为每个 key 设置 name 与 token_prefix 以便现场识别

---

## 5. ApiKey Pepper（特殊：不建议频繁轮换）

Pepper 的作用：

- ApiKey token 在 DB 中存储为 hash（SHA-256），hash 计算会混入 `BEACON_API_KEY_PEPPER`。

关键约束：

- 多实例部署必须使用同一 Pepper，否则将出现“部分实例校验失败”。
- Pepper 变更会导致历史 ApiKey hash 全部失效（等价于所有 ApiKey 失效）。

轮换建议：

- Pepper 视为“长期根密钥”，默认不轮换。
- 如必须轮换（合规/泄露事件），应按“全量重新发放 ApiKey”的应急流程执行，并准备集中切换窗口。

---

## 6. MediaServer `secret` 轮换

轮换影响面：

- Admin 与 MediaServer 的控制面通信依赖 `mediaSecret`（ZLMediaKit HTTP API）。
- 轮换需同时更新：
  - `config.json.mediaSecret`
  - ZLMediaKit 运行目录 `config.ini [api].secret`

建议流程：

1. 在维护窗口内更新配置（两处同时）
2. 重启 MediaServer
3. 验证 `getServerConfig?secret=` 返回 `code=0`
4. 验证 Stream 代理与播放链路

---

## 7. Django `SECRET_KEY` 轮换

影响：

- Django `SECRET_KEY` 参与 Session/签名，轮换后通常会导致已有会话失效（需重新登录）。

建议：

- 在维护窗口执行
- 配合强制重新登录与审计要求

---

## 8. 轮换留痕与回滚（建议固化）

建议对每次轮换固化输出物：

- 轮换时间、变更范围（哪些系统/哪些 key）
- 新旧 key 生效窗口与回滚策略
- 验证证据（健康检查、E2E 验收片段、审计导出）

回滚原则：

- legacy Token：回滚为旧值（需确保旧值仍受控）
- ApiKey：保留旧 key 为 disabled 之前的短暂窗口，便于紧急回退
- Pepper：回滚等价于恢复旧 Pepper（涉及全部 key 的一致性，风险较高）
