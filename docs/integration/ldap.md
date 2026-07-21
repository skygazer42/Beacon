# LDAP / Active Directory 登录

Beacon 可在本地密码校验失败或账号尚不存在时尝试 LDAP。LDAP 是可选依赖，默认关闭；配置仅来自 `BEACON_LDAP_*` 环境变量，不读取 `config.json` 中的嵌套 `auth.ldap` 对象。

## 安装与启用

先安装可选依赖，其中包含 `ldap3`：

```bash
cd Admin
python -m pip install -r requirements-optional.txt
```

公共设置：

```bash
BEACON_LDAP_ENABLED=1
BEACON_LDAP_URL=ldaps://ad.example.com:636
BEACON_LDAP_TLS_VERIFY=1
BEACON_LDAP_CONNECT_TIMEOUT_SECONDS=5
BEACON_LDAP_EMAIL_ATTR=mail
```

生产使用 LDAPS，或在 `ldap://` 上设置 `BEACON_LDAP_STARTTLS=1`。不要设置 `BEACON_LDAP_TLS_VERIFY=0`。

## 模式一：直接 Bind

适用于可以由用户名直接构造 DN 的目录：

```bash
BEACON_LDAP_USER_DN_TEMPLATE='uid={username},ou=people,dc=example,dc=com'
```

登录时 Beacon 以该 DN 和用户输入的密码 Bind，再尽力读取邮箱属性。

## 模式二：服务账号搜索后 Bind

适用于 Active Directory 或 DN 无法直接推导的目录：

```bash
BEACON_LDAP_BIND_DN='cn=beacon-reader,ou=service,dc=example,dc=com'
BEACON_LDAP_BIND_PASSWORD='CHANGE_ME'
BEACON_LDAP_BASE_DN='dc=example,dc=com'
BEACON_LDAP_USER_FILTER='(sAMAccountName={username})'
```

Beacon 先使用服务账号搜索一条用户记录，再使用找到的用户 DN 和用户密码 Bind。用户名会在填入 LDAP filter 前转义。

`BEACON_LDAP_USER_DN_TEMPLATE` 非空时优先使用直接 Bind，不使用服务账号搜索配置。

## 本地账号行为

- LDAP 成功后，Beacon 按不区分大小写的用户名、再按邮箱查找本地 Django 用户。
- 找不到时会创建一个普通本地用户，并同步邮箱。
- 当前 LDAP 实现不读取组，也不自动授予 staff、superuser 或模块权限；管理员必须在 Beacon 内单独授权。
- 本地密码校验优先于 LDAP；LDAP 不会替代 Django Session、CSRF 或 TOTP。

## 验证

仓库没有 `/api/v1/auth/ldap/test` 之类的 LDAP 测试 API。先使用 `tools/ldap_check.py` 查看参数，再通过正常 `/login` 测试一个最小权限账号：

```bash
python tools/ldap_check.py --help
```

也可以在部署主机使用 `ldapsearch` 验证网络、TLS、服务账号和过滤器。不要把真实密码写进 shell 历史、文档或 Issue。

## 常见问题

| 现象 | 核对项 |
|---|---|
| LDAP 完全未尝试 | `BEACON_LDAP_ENABLED=1`、`ldap3` 已安装、Admin 已重启 |
| `missing_url` | `BEACON_LDAP_URL` 未设置 |
| `missing_bind_config` | 搜索模式缺少 Bind DN、密码或 Base DN |
| `service_bind_failed` | 服务账号、TLS、证书链或网络错误 |
| `user_not_found` | Base DN 或用户过滤器不匹配 |
| `bind_failed` | 用户密码、用户 DN 或账号状态不正确 |
| 登录后权限不足 | LDAP 不做组权限映射，请在本地用户管理中授权 |

完整变量列表见 [环境变量参考](../configuration/env-vars.md#ldap)。
