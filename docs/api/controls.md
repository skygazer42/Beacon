# 布控接口

布控把一个视频流、算法编码、目标类别和检测参数组合成 Analyzer 任务。保存布控只写数据库；启动成功才表示 Analyzer 接受了任务。

## 查询

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/open/getControlData?code=<code>` | 查询全部或单个布控的核心字段 |
| GET | `/control/openIndex?p=1&ps=10` | 兼容分页列表，同时查询 MediaServer/Analyzer 状态 |

```bash
curl 'http://localhost:9991/open/getControlData?code=ctrl-01' \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}"
```

## 创建与修改

`POST /api/postAddControl` 可创建或按 `controlCode` 更新布控。最小请求：

```bash
curl -X POST http://localhost:9991/api/postAddControl \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "controlCode": "ctrl-01",
    "streamApp": "live",
    "streamName": "cam-01",
    "streamVideo": "video",
    "streamAudio": "audio",
    "algorithmCode": "on_yolo11n_cpu",
    "objectCode": "person"
  }'
```

`POST /api/postEditControl` 支持以 `controlCode` 加需要变更的字段做部分更新。参数名沿用 Analyzer 的 camelCase 协议；完整算法、Pipeline、OSD、硬件编解码和告警参数应以 [算法 API 协议 v2](../integration/algorithm-api-protocol-v2.md) 及当前 `ControlEditorPage` 提交内容为准。

## 生命周期

| 方法 | 路径 | 参数 |
|---|---|---|
| POST | `/control/openStartControl` | `code` |
| POST | `/control/openStopControl` | `code` |
| POST | `/control/openDel` | `code`；会先确认 Analyzer 已取消任务，再删除关联告警和布控记录 |
| POST | `/control/openBatchStart` | `codes` |
| POST | `/control/openBatchStop` | `codes` |
| POST | `/control/openCopy` | `code` |
| POST | `/control/openBatchCopyToStreams` | `src_code`、`stream_codes` |

删除不是单纯数据库操作：当 Analyzer 无法确认取消时，接口会保留布控，避免出现数据库已删但分析仍在运行的孤儿任务。

## 快捷参数

`POST /control/openQuickSet` 可更新：

- `decode_stride`
- `alarm_video_type`
- `alarm_image_count`
- `alarm_image_draw_mode`
- `restart=1`（运行中任务重启后生效）

每个响应都应同时检查 HTTP 状态和 `code == 1000`。启动失败常见原因包括流未在线、算法未加载、模型/Provider 不可用、授权限制或 Analyzer `9993` 不可达。

页面内部的 `/api/app-shell/control/*` 依赖登录会话，不属于第三方稳定接口。
