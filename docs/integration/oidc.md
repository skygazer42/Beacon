# OIDC SSO

Beacon 使用 OIDC Authorization Code Flow。入口为 `/login/oidc/start`，回调为 `/login/oidc/callback`。

## 单 Provider 配置

```bash
BEACON_OIDC_ENABLED=1
BEACON_OIDC_CLIENT_ID=beacon
BEACON_OIDC_CLIENT_SECRET=replace-me
BEACON_OIDC_AUTHORIZATION_ENDPOINT=https://idp.example.com/authorize
BEACON_OIDC_TOKEN_ENDPOINT=https://idp.example.com/token
BEACON_OIDC_JWKS_URI=https://idp.example.com/jwks
BEACON_OIDC_ISSUER=https://idp.example.com/
BEACON_OIDC_SCOPE=openid email profile
BEACON_OIDC_REQUIRE_NONCE=1
```

在 IdP 注册回调地址：

```text
https://<beacon-host>/login/oidc/callback
```

可选配置包括 `BEACON_OIDC_USERINFO_ENDPOINT`、`BEACON_OIDC_END_SESSION_ENDPOINT`、超时、JWKS 缓存和 token 最大年龄。完整变量见 [环境变量](../configuration/env-vars.md)。

## 多 Provider

`BEACON_OIDC_PROVIDERS_JSON` 只接受以 Provider ID 为键的 JSON 对象：

```json
{
  "corp": {
    "client_id": "beacon",
    "client_secret": "replace-me",
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/token",
    "issuer": "https://idp.example.com/",
    "jwks_uri": "https://idp.example.com/jwks"
  }
}
```

通过 `/login/oidc/start?provider=corp` 选择 Provider；可用 `BEACON_OIDC_PROVIDER_DEFAULT=corp` 指定默认值。Provider ID 区分大小写，只允许字母、数字、`_`、`-`、`.`。

## 组与权限

- `BEACON_OIDC_REQUIRED_GROUPS`
- `BEACON_OIDC_STAFF_GROUPS`
- `BEACON_OIDC_SUPERUSER_GROUPS`

环境变量使用逗号分隔。Provider JSON 中对应字段可使用字符串或字符串数组。

Token/UserInfo 只读取标准 JSON 形态：

- `groups`、`roles`、`role`、`cognito:groups`
- Keycloak `realm_access.roles`
- Keycloak `resource_access.<client>.roles`

这些值应为字符串或字符串数组；不会解析嵌套引号、Python tuple/set、对象映射或序列化在字符串中的 JSON。

权限映射使用严格 JSON 布尔值：

```bash
BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON='{"beacon_viewer":{"streams":true}}'
BEACON_OIDC_SYNC_USER_PERMISSIONS=1
```

## 安全校验

Beacon 始终验证 RS256 签名，并校验配置的 issuer、audience、nonce、exp、nbf、iat 和 token 最大年龄。旧的“关闭 token 验证”配置不会绕过签名校验。

生产环境建议使用 `BEACON_OIDC_ACCOUNT_LINK_MODE=deny`，预先建立身份映射，避免按用户名或邮箱误绑定账号。
