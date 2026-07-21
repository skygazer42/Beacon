# 视频流接口

视频流包含两层状态：数据库中的“启用/停用”和 MediaServer 中的“转发中/未转发”。添加一条记录不会自动证明源地址可拉取，也不会自动开始代理；需要分别调用转发接口或在系统设置中启用自动转发。

## 查询

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/open/getStreamData?code=<code>` | 查询全部或单个流，并返回常用播放地址 |
| GET | `/open/getAllStreamData` | 云远程控制面使用的流列表 |
| GET | `/stream/openIndex?p=1&ps=10` | 兼容分页列表，`ps` 只接受 10–20 |
| GET / POST | `/stream/openGet?code=<code>` | 查询可编辑字段 |

```bash
curl 'http://localhost:9991/open/getStreamData?code=cam-01' \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}"
```

## 添加与编辑

### 添加

`POST /stream/openAdd`，支持表单或 JSON：

```bash
curl -X POST http://localhost:9991/stream/openAdd \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "cam-01",
    "app": "live",
    "nickname": "东门摄像头",
    "pull_stream_type": 1,
    "pull_stream_url": "rtsp://camera.example/live/main"
  }'
```

必填字段为 `code`、`nickname` 和合法的 `pull_stream_url`。`app` 默认 `live`，MediaServer 中的流名固定使用 `code`。GB28181 使用 `pull_stream_type=21`，并提供 `gb28181_device_id`、`gb28181_channel_id`。

### 编辑与删除

| 方法 | 路径 | 关键参数 |
|---|---|---|
| POST | `/stream/openEdit` | `code` 以及要保存的流字段 |
| POST | `/stream/openDel` | `code`，删除单条；兼容 `handle=all` 会清空全部流，调用前必须二次确认 |

## 转发

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/stream/openAddStreamProxy` | 按 `code` 在 MediaServer 启动拉流代理 |
| POST | `/stream/openDelStreamProxy` | 按 `code` 停止代理 |
| POST | `/stream/openBatchAddStreamProxy` | 批量启动代理 |
| POST | `/stream/openBatchDelStreamProxy` | 批量停止代理 |
| POST | `/stream/openAddStreamPusherProxy` | 将现有流转推到另一个 RTSP 目标 |
| POST | `/stream/openGb28181Ptz` | 对 GB28181 流执行受支持的 PTZ 动作 |

“未转发”只表示本机 MediaServer 没有对应代理链路；数据库记录仍可存在，大屏也可能保留旧的窗口分配。调用转发接口成功后再查询在线状态，才能判断真实链路是否可用。

## 播放地址

`/open/getStreamData` 返回 `ws_flv`、`http_flv`、`ws_mp4`、`http_mp4` 和 `rtsp`。这些是按当前配置拼出的候选地址，客户端仍应处理 MediaServer 离线、编码不兼容和反向代理未开放对应协议的情况。

页面内部还使用 `/api/app-shell/streams`、`/api/app-shell/stream-player` 和 `/api/app-shell/stream/action/*`。它们依赖登录会话，属于 UI 内部接口，不建议第三方直接绑定。
