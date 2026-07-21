---
title: 数字人运行时接入
icon: material/robot-industrial
---

# 数字人运行时接入

本文档用于把数字人采集端和日志上报端真正切到 Beacon Django，而不是继续依赖外部数字人后端。

适用范围：

- 已接入 Beacon 的数字人 6 个页面
- 采集端直连 Beacon 开放接口
- Beacon 本地承接设备、指标、告警、日志、截图、钉钉、AI 诊断

---

## 1. 先决条件

至少满足以下条件：

- Beacon `Admin` 已能正常启动
- 已执行数据库迁移：
  - `cd Admin`
  - `python manage.py migrate`
- 若启用共享防重放 Redis 或对象存储，已安装可选依赖：

```bash
cd Admin
python -m pip install -r requirements-optional.txt
```

---

## 2. 最小环境变量

开发/单机最小可运行：

```bash
export BEACON_DJANGO_DEBUG=1
export BEACON_OPEN_API_TOKEN=change-me
export BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET=replace-with-real-secret
export BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY=replace-with-real-sm4-key
```

生产/联调建议最少补齐：

```bash
export BEACON_DJANGO_DEBUG=0
export BEACON_DJANGO_SECRET_KEY='replace-with-random-secret'
export BEACON_DJANGO_ALLOWED_HOSTS='beacon.example.com'
export BEACON_DJANGO_CSRF_TRUSTED_ORIGINS='https://beacon.example.com'
export BEACON_OPEN_API_TOKEN='replace-with-random-openapi-token'
export BEACON_REQUIRE_OPEN_API_TOKEN=1

export BEACON_DIGITAL_HUMAN_AUTHORIZATION_SECRET='replace-with-real-secret'
export BEACON_DIGITAL_HUMAN_UPLOAD_AUTH_SM4_SECRET_KEY='replace-with-real-sm4-key'
export BEACON_DIGITAL_HUMAN_REPLAY_REDIS_URL='redis://127.0.0.1:6379/8'
export BEACON_DIGITAL_HUMAN_REPLAY_CACHE_PREFIX='beacon:digital-human:replay'
export BEACON_DIGITAL_HUMAN_S3_BUCKET='digital-human-screenshots'
export BEACON_CLOUD_S3_REGION='us-east-1'
export BEACON_CLOUD_S3_ENDPOINT_URL='http://127.0.0.1:9000'
export BEACON_CLOUD_S3_ACCESS_KEY_ID='beacon-minio'
export BEACON_CLOUD_S3_SECRET_ACCESS_KEY='<strong-random-secret>'
```

---

## 3. 运行链路

Beacon 直接提供以下运行时接口：

- `POST /open/agent/token`
- `POST /open/agent/register`
- `GET /open/agent/config/latest`
- `GET /open/agent/commands/pull`
- `POST /open/agent/commands/result`
- `POST /open/agent/report`
- `POST /open/human/report`

管理端还提供截图预览：

- `GET /digital-human/device-screenshot?id=<deviceId>`

---

## 4. 联调步骤

### 4.1 启动 Beacon Admin

```bash
cd Admin
python manage.py runserver 0.0.0.0:9991
```

### 4.2 签发 JWT 账户 token

先在数字人系统设置页里创建 JWT 账户，然后让采集端调用：

```http
POST /open/agent/token
Content-Type: application/json

{
  "tenantName": "front-desk",
  "secret": "tenant-secret"
}
```

### 4.3 设备注册

采集端拿到 bearer token 后调用：

```http
POST /open/agent/register
Authorization: Bearer <jwtToken>
Content-Type: application/json
```

请求体至少包含：

- `machineCode`
- `machineMac`
- `tenantName`
- `osName`

### 4.4 遥测上报

设备遥测与截图调用：

```http
POST /open/agent/report
Authorization: Bearer <sm4(machineCode*timestamp)>
Content-Type: application/json
```

验证点：

- 设备在线状态更新
- 指标历史落表
- 告警自动衍生
- 截图写入对象存储或本地 `uploadDir`

### 4.5 日志上报

日志调用：

```http
POST /open/human/report
Authorization: Bearer <sm4(machineCode*timestamp)>
Content-Type: application/json
```

验证点：

- 日志行落表
- 非 `INFO` 日志自动触发 AI 诊断
- `INFO` 日志标记为 `skipped`

### 4.6 Beacon 页面回归

登录 Beacon 后验证：

- `/digital-human/dashboard`
- `/digital-human/device-monitor`
- `/digital-human/alert-center`
- `/digital-human/monitor-logs`
- `/digital-human/ops-report`
- `/digital-human/system-settings`

重点看：

- 数据来自 Beacon 本地表
- 告警会真实触发钉钉推送状态变化
- 日志与告警的 AI 诊断状态可见
- 设备截图能从 Beacon 管理端预览

---

## 5. 中间件核对清单

### Redis

- 推荐直接配置 `BEACON_DIGITAL_HUMAN_REPLAY_REDIS_URL`
- 未配置时使用 Django cache，再退到单实例内存防重放

### MinIO / S3

- 优先使用 `BEACON_DIGITAL_HUMAN_S3_BUCKET`
- 不设时回退 `BEACON_CLOUD_S3_BUCKET`
- 若 S3 写入失败，会回退本地 `uploadDir`

### DingTalk

- 路由与开关在数字人系统设置页维护
- 如果路由配置了 `secret`，Beacon 会自动拼 `timestamp` / `sign`
- 成功/失败都会持久化到告警行

### AI 诊断

- 配置入口在数字人系统设置页
- 告警刷新会调用 chat-completions 风格接口
- 日志上报时就会做一次诊断

---

## 6. 常见问题

### 多实例下重复上报没有被拦住

先检查：

- 是否安装了 `redis`
- 是否设置了 `BEACON_DIGITAL_HUMAN_REPLAY_REDIS_URL`
- Redis 是否可连通

### 截图没有走对象存储

先检查：

- 是否安装了 `boto3`
- `BEACON_DIGITAL_HUMAN_S3_BUCKET` 或 `BEACON_CLOUD_S3_BUCKET` 是否已设置
- `BEACON_CLOUD_S3_ENDPOINT_URL` / AK / SK 是否正确

### 钉钉状态是 failed

先检查：

- 路由 webhook 是否可达
- `secret` 是否和钉钉机器人配置一致
- Beacon 所在机器是否能访问外网或钉钉专线

### AI 诊断一直 skipped

先检查：

- 是否在数字人系统设置里保存了 AI 配置
- `baseUrl` / `apiKey` / `model` 是否完整
- 对于日志诊断，`INFO` 级别会被显式跳过
