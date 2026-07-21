<div align="center">
  <img src="../assets/branding/readme-brand.png" alt="Beacon" width="720"/>
</div>

# 授权码发放、导入与验证

本文是 Beacon 授权的完整操作指南，覆盖社区模式和三种商业授权模式。仓库根目录的 `README.md` 只保留授权模式速查表，详细流程以本文为准。

> 返回：[部署总入口](README.md) · [仓库 README](https://github.com/skygazer42/Beacon#readme)

Beacon 当前支持四种授权模式：

| 模式 | `licenseType` / `BEACON_LICENSE_TYPE` | 交付物 | 适合场景 |
|------|---------------------------------------|--------|----------|
| 社区模式 | `community` | 无 | 开源默认，不启用运行授权门禁。 |
| 机器码授权 | `machine` | 一个 `licenseKey` 字符串 | 单机、简单离线授权。 |
| 加密锁授权 | `dongle` | 硬件锁、检测命令或 sentinel 文件 | 需要 USB/硬件锁控制。 |
| 授权池/租约授权 | `pool` 或 `manager` | 签名后的 `license.json` | 推荐商业交付，支持路数、节点数、算法包限制。 |

## 社区模式

源码部署默认使用 `community`，无需 `licenseKey`。商业交付需要授权约束时，再显式切换到下面三种模式之一。

## 机器码授权怎么发放

客户侧先把授权模式设为 `machine`，启动 Analyzer/Admin 后读取机器码：

```bash
export BEACON_LICENSE_TYPE=machine
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/info
```

返回里重点看：

```json
{
  "machine_code": "...",
  "machine_code_v1": "...",
  "machine_code_v2": "..."
}
```

发放端当前可发两种值之一：

```text
licenseKey = machine_code_v2
licenseKey = sha256(machine_code_v2)
```

如果需要兼容旧机器码，也可以用 `machine_code_v1` 或 `sha256(machine_code_v1)`。客户拿到授权码后配置：

```bash
export BEACON_LICENSE_TYPE=machine
export BEACON_LICENSE_KEY="<issued-license-key>"
```

或写入 `config.json`：

```json
{
  "licenseType": "machine",
  "licenseKey": "<issued-license-key>"
}
```

重启后验证：

```bash
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/info
```

期望 `data.ok` 为 `true`。

## 授权池 license.json 怎么发放

正式商业交付建议使用 `pool`。它的原则是：

```text
发放端保存 Ed25519 私钥
客户侧只配置 Ed25519 公钥
发放端按客户 cluster_id、有效期、路数、节点数、算法包生成 license.json
客户在 /license/manager 导入 license.json
Analyzer 启动布控时向 Admin 申请租约，超额或过期会拒绝
```

仓库当前没有客户侧“发码工具”。需要建设发放端时，私钥必须放在交付方自己的授权系统里，不得放进客户机器或交付包。

客户侧先固定集群 ID。生产环境建议显式设置并持久化：

```bash
export BEACON_CLUSTER_ID="customer-a-edge-001"
```

如果没有显式设置，Admin 会根据机器信息推导一个集群 ID。可以用下面命令查看当前值：

```bash
cd Admin
python manage.py shell -c "from app.utils.LicenseManager import get_current_cluster_id; print(get_current_cluster_id())"
cd ..
```

发放端生成的 `license.json` 字段示例：

```json
{
  "license_id": "LIC-2026-CUSTOMER-A-001",
  "customer": "Customer A",
  "cluster_id": "customer-a-edge-001",
  "issued_at": "2026-05-01T00:00:00Z",
  "not_before": "2026-05-01T00:00:00Z",
  "not_after": "2027-05-01T00:00:00Z",
  "limits": {
    "max_active_controls": 20,
    "max_nodes": 2
  },
  "packages": ["core", "ppe", "behavior_pro"],
  "package_limits": {
    "ppe": {
      "max_active_controls": 5
    }
  },
  "edition": "ordinary",
  "signature": {
    "alg": "ed25519",
    "kid": "prod-2026-01",
    "sig": "<base64-signature>"
  }
}
```

签名规则必须和代码一致：

```python
# 签名前先移除 signature 字段
message = json.dumps(payload_without_signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
signature = ed25519_private_key.sign(message)
```

对应校验逻辑在 `Admin/app/utils/LicenseManager.py` 的 `canonical_license_message()` 和 `validate_license_payload()`。

客户侧导入前设置：

```bash
export BEACON_LICENSE_TYPE=pool
export BEACON_CLUSTER_ID="customer-a-edge-001"
export BEACON_LICENSE_PUBLIC_KEY_B64="<ed25519-public-key-base64>"
export BEACON_OPEN_API_TOKEN="change-me-long-random-token"
```

导入方式：

```text
浏览器打开 http://<admin-host>:9991/license/manager
登录管理员账号
上传 license.json
页面显示“导入成功”后重启 Analyzer 或重新启动布控
```

导入后验证：

```bash
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/info
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/usage
```

租约接口最小验证：

```bash
curl -sS -X POST http://127.0.0.1:9991/open/license/lease/acquire \
  -H "Content-Type: application/json" \
  -H "X-Beacon-Token: <openApiToken>" \
  -d '{"node_id":"edge-1","stream_code":"stream-1","control_code":"ctrl-readme-smoke","algorithm_code":"on_yolov8n_80","ttl_seconds":120}'
```

期望返回：

```json
{
  "code": 1000,
  "msg": "success",
  "data": {
    "lease_id": "..."
  }
}
```

如果返回 `license_invalid`、`cluster_mismatch`、`missing_public_key`、`license_expired`，直接看 `/license/manager` 页面上的错误详情。

## 加密锁授权怎么配置

加密锁模式会优先执行检测命令，命令成功退出即认为授权有效；没有检测命令时，可以用 sentinel 文件作为简单检查。

```bash
export BEACON_LICENSE_TYPE=dongle
export BEACON_LICENSE_DONGLE_CMD="/opt/beacon/bin/dongle-check --ping"
export BEACON_LICENSE_DONGLE_FILE="/opt/beacon/license.dongle"
```

或写入 `config.json`：

```json
{
  "licenseType": "dongle",
  "licenseDongleCmd": "/opt/beacon/bin/dongle-check --ping",
  "licenseDongleFile": "/opt/beacon/license.dongle"
}
```

## 常见授权报错

| 现象 | 先检查什么 |
|------|------------|
| `openStartControl` 返回 `license_invalid` | 正式部署检查 `licenseType`、`licenseKey` 或 `/license/manager` 的 `license.json` 导入状态；本机边云脚本部署则重新执行 `start_edge_with_local_cloud.sh`。 |
| 导入 license 显示 `missing_public_key` | 客户侧没有配置 `BEACON_LICENSE_PUBLIC_KEY_B64`。 |
| 导入 license 显示 `cluster_mismatch` | `license.json.cluster_id` 和客户侧 `BEACON_CLUSTER_ID` 不一致。 |
| 导入 license 显示 `license_expired` | `license.json` 的 `not_after` 已过期，需要重新发放。 |

排查租约问题时，同时核对 Admin 与 Analyzer 的集群标识、公钥、系统时钟和授权有效期；两端必须使用同一套授权配置。
