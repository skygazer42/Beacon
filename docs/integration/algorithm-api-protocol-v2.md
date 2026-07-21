# Beacon 算法 API 协议 v2（基础算法 / 外部推理服务）

> 适用范围：当 `Control.api_url` 配置为外部算法服务地址时，Analyzer 会把每帧（JPEG base64）+ 布控/推流/阈值等信息按本协议 POST 到你的算法服务。
> 目标：形成"可交付、可验收"的固定口径，便于客户自研算法服务或第三方算法厂商接入。

!!! tip "三种算法接入方式的选择"
    - **外部 HTTP 算法服务** —— 本文协议(v2)
    - **本地内置算法 / 自定义模型** —— 见 [内置算法](../algorithms/builtin.md)、[模型格式](../algorithms/models.md)
    - **进程内插件 SDK** —— 见 [插件 SDK 协议 v2](algorithm-plugin-sdk-v2.md) 与 [插件 SDK 开发指南](../algorithms/plugin-sdk.md)

---

## 1. 总体约定

- 传输协议：HTTP(S) `POST`
- Content-Type：`application/json`
- 字符集：UTF-8
- 图像：`image_base64 = base64(JPEG bytes)`
- 坐标：像素坐标（左上角为原点）

> 注意：Analyzer 会把图像编码为 JPEG（默认质量 90），再做 base64。

---

## 2. Request（Analyzer -> Algorithm API）

### 2.1 必填字段

- `image_base64`：base64(JPEG bytes)
- `nodeCode`：Analyzer 节点编号（来自 `config.json.code`）
- `controlCode`：布控编号
- `streamCode/streamApp/streamName`：视频流标识信息
- `algorithmCode`：算法编号（建议你用它选择不同模型/逻辑）

### 2.2 兼容字段（历史）

Analyzer 为兼容历史字段，会同时发送：

- `flowCode`：等价 `algorithmCode`
- `classThresh/overlapThresh`：旧阈值字段（部分历史算法服务会读取它们）

### 2.3 标准参数（推荐读取）

- `algorithmParams`（object，可选但建议读取）
  - `confThresh`：分类阈值（float）
  - `nmsThresh`：NMS 阈值（float）
  - `modelConcurrency`：模型并发（int）
  - `inputWidth/inputHeight`：预处理尺寸（int）
  - `modelPrecision`：精度（FP32/FP16/INT8）

### 2.4 区域/越线/OSD 等扩展

- `polygonType/polygon`：识别区域（多边形）
- `lineCrossingConfig`：越线检测配置（当 drawType=line 时可能出现）
- `osdConfig`：OSD 配置
- `pushStreamConfig`：推流质量配置
- `videoInfo`：视频流信息
- `extensions`：通用扩展字段（frameId/timestamp/drawType 等）

### 2.5 示例 Request

```json
{
  "image_base64": "...",
  "nodeCode": "node-001",
  "controlCode": "ctrl-0001",
  "streamCode": "cam-01",
  "streamApp": "live",
  "streamName": "cam-01",
  "flowCode": "on_yolov8n_80",
  "algorithmCode": "on_yolov8n_80",
  "modelClassNames": "person,car,bus",
  "detectClassNames": "person",
  "polygonType": 3,
  "polygon": "0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9",
  "classThresh": 0.5,
  "overlapThresh": 0.5,
  "algorithmParams": {
    "confThresh": 0.25,
    "nmsThresh": 0.45,
    "modelConcurrency": 1,
    "inputWidth": 640,
    "inputHeight": 640,
    "modelPrecision": "FP16"
  },
  "extensions": {
    "frameId": 12345,
    "timestamp": 123456789,
    "drawType": "polygon"
  }
}
```

---

## 3. Response（Algorithm API -> Analyzer）

### 3.1 必填字段

- `code`：`1000` 表示成功；其他表示失败
- `msg`：字符串消息（失败原因/成功信息）

### 3.2 成功结果

成功时需要返回：

- `result.happen`：是否触发行为/告警（bool）
- `result.happenScore`：触发分值（float）
- `result.detects[]`：检测框数组
  - `x1/y1/x2/y2`：像素坐标
  - `class_id`：类别 id（int）
  - `class_score`：置信度（float）
  - `class_name`：类别名（string）

### 3.3 示例 Response（成功）

```json
{
  "code": 1000,
  "msg": "success",
  "result": {
    "happen": false,
    "happenScore": 0.0,
    "detects": [
      {
        "x1": 120,
        "y1": 80,
        "x2": 420,
        "y2": 680,
        "class_id": 0,
        "class_score": 0.93,
        "class_name": "person"
      }
    ]
  }
}
```

### 3.4 示例 Response（失败）

```json
{
  "code": 0,
  "msg": "model not ready"
}
```

---

## 4. 工业建议（强烈推荐）

- **快速失败**：接口响应建议 < 200ms（超时由 Analyzer 侧配置控制）
- **可观测性**：算法服务侧打印 `controlCode/streamCode/algorithmCode` 便于定位
- **幂等与去重**：告警/事件上报请使用 `controlCode + frameId` 等组合做幂等

---

## 5. 外部 ASR API 接入边界（OpenAPI `audioDetect`）

该能力不是“Analyzer 内置语音识别引擎”，而是 **Beacon 作为宿主，把音频 base64 转发给外部 ASR API**。

当前仓库的明确边界：

- 已支持：`POST /open/algorithm/audioDetect`
- 已支持：基础算法 subtype=`speech` 且 `basic_source=api`
- 未支持：本地 speech 模型加载
- 未支持：实时流音频拆分、边分析边识别、Analyzer 内置 speech 推理

### 5.1 Request（Beacon OpenAPI -> Speech API）

推荐外部 ASR 服务读取以下字段：

- `audio_base64`：base64 编码音频字节
- `algorithmCode`：算法编号
- `language`：可选语言提示，例如 `zh-CN`
- `hotwords`：可选热词数组
- `extensions`：保留扩展字段

示例：

```json
{
  "audio_base64": "YXVkaW8=",
  "algorithmCode": "asr_api_demo",
  "language": "zh-CN",
  "hotwords": ["报警", "入侵"],
  "extensions": {
    "source": "openapi_audio_detect"
  }
}
```

### 5.2 Response（Speech API -> Beacon OpenAPI）

成功响应建议：

```json
{
  "code": 1000,
  "msg": "success",
  "result": {
    "text": "demo transcript",
    "language": "zh-CN",
    "segments": [
      {
        "start_ms": 0,
        "end_ms": 1200,
        "text": "demo transcript"
      }
    ]
  }
}
```

字段约定：

- `result.text`：整段识别文本
- `result.language`：最终识别语言
- `result.segments[]`：可选分段结果
  - `start_ms`
  - `end_ms`
  - `text`

### 5.3 验收建议

示例服务已启动时，可直接验证：

```bash
curl -X POST "http://127.0.0.1:8000/audio/infer" \
  -H "Content-Type: application/json" \
  -d '{"audio_base64":"YXVkaW8=","algorithmCode":"asr-demo","language":"zh-CN"}'
```
