# 算法配置参数与推流质量优化指南

!!! tip "本页是详细参数手册"
    总览与场景选型请先看 [算法与模型概览](algorithms/index.md)、[内置算法](algorithms/builtin.md)、[算法 Pipeline](algorithms/pipeline.md)。
    本页提供 **逐字段、逐参数** 的最详细解释,适合需要精细调参或写自动化脚本的用户。

## 📋 目录

- [功能概述](#功能概述)
- [算法模型配置参数](#算法模型配置参数)
- [推流视频质量配置](#推流视频质量配置)
- [数据库迁移](#数据库迁移)
- [API 使用示例](#api-使用示例)
- [最佳实践](#最佳实践)
- [常见问题](#常见问题)

---

## 功能概述 {#功能概述}

Beacon 提供了算法模型配置参数和推流视频质量优化功能，允许用户精细控制：

### 算法推理参数（AlgorithmModel 级别）
- **模型精度**: FP32 / FP16 / INT8 (文档标识用途)
- **输入分辨率**: 自定义预处理宽高
- **NMS 阈值**: 非极大值抑制阈值
- **置信度阈值**: 分类置信度阈值

### 推流质量参数（Control 级别）
- **视频编码器**: H.264 / H.265 / VP8 / VP9
- **视频码率**: 可配置 kbps
- **帧率**: 10-30 fps
- **分辨率**: 自定义宽高
- **GOP**: 关键帧间隔

---

## 算法模型配置参数 {#算法模型配置参数}

### 模型文件格式支持矩阵（工业交付）

> 说明：Beacon 的推理引擎是“按模型文件后缀自动路由”的。不同格式可能依赖不同的运行时或插件动态库。

| 模型/插件格式 | 推理路径 | 依赖 | 备注 |
|---|---|---|---|
| `.onnx` | ONNX Runtime | `onnxruntime` | 支持 CPU/CUDA/TRT/AUTO provider（按设备可用性降级） |
| `.xml + .bin` | OpenVINO IR | OpenVINO Runtime | 支持 CPU/GPU（按设备可用性降级） |
| `.engine / .plan` | TensorRT Engine | `tensorrtEnginePluginPath` 指定的插件动态库 | 由插件负责加载 engine（Analyzer 侧仅做 host 路由） |
| `.rknn / .om` | Compat Plugin | `libbeacon_compat.*`（可通过 `compatLibPath` 覆盖） | 内置层是 delegating shim：未配置后端时如实报告 `stub`，配置 `BEACON_COMPAT_BACKEND_PATH` 后委托外部硬件 SDK backend |
| `.dll / .so / .dylib` | 行为/自定义插件 | 插件自身依赖 | 通过 `AlgorithmPlugin` 加载（SDK v2/v3/legacy ABI 兼容） |

### 0. 授权算法包 (License Package)

**字段**: `license_package`  
**类型**: String  
**默认值**: `core`  
**说明**: 算法所属的“可售卖授权包(SKU)”。用于 License Manager 在启动布控时校验该算法是否在授权范围内（例如：`core` / `ppe` / `traffic_lpr`）。  

#### 默认 SKU 映射（Analyzer 内置算法）

> 说明：下表是“推荐默认值”，后台“算法管理”中可按售卖策略调整任意算法的 `license_package`。
> 对于 License Manager：即使数据库中尚未创建对应算法，LM 也能识别这些 **Analyzer 内置算法 code** 并做包校验（避免 `algorithm_not_found` 影响交付）。

| 内置算法 code | 功能说明 | 推荐 `license_package` |
|---|---|---|
| `ov_yolov11n_safehat` | 安全帽检测 | `ppe` |
| `ov_yolov8n_fight_nofight` | 打架检测（二分类） | `behavior_pro` |
| `ov_yolov8n_smoke` | 抽烟检测 | `behavior_pro` |
| `ov_yolov8n_fire_smoke` | 火焰/烟雾检测 | `core` |
| `on_yolov5s_80` / `ov_yolov5s_80` | 通用检测（COCO 80 类） | `core` |
| `on_yolov8n_80` / `ov_yolov8n_80` | 通用检测（COCO 80 类） | `core` |
| `on_yolov8s_80` / `ov_yolov8s_80` | 通用检测（COCO 80 类） | `core` |
| `on_xcfacenet` / `ov_xcfacenet` | 人脸特征提取（XcFaceNet 模板） | `core` |

#### 一键导入内置算法模板（可选）

需要在后台 UI 中默认展示这些内置算法（并自动带上推荐 `license_package`、目标列表等）时，可以运行：

```bash
cd Admin
python manage.py beacon_seed_builtin_algorithms
```

参数：

- 默认（不带参数）：只导入“可售卖 SKU”相关内置算法（`license_package != core`，例如安全帽/打架/抽烟），避免通用 COCO80 模型把列表弄得很长
- `--all`：导入完整内置算法目录（包含 core/COCO80 通用检测）
- `--dry-run`：只打印将要执行的变更，不写入 DB
- `--force`：强制覆盖已存在算法的 `license_package`（谨慎使用）

### 0.1 XcFaceNet 模板边界

- `on_xcfacenet` / `ov_xcfacenet` 是内置的 **算法模板和代码映射**。
- 这意味着：
  - Admin 可以 seed 出对应算法模板
  - 人脸 add/search 的图片入参链路可以依赖显式 `featureAlgorithmCode`，或服务端默认 `faceDefaultFeatureAlgorithmCode`
- 这 **不意味着**：
  - 仓库已经自带真实 XcFaceNet 模型文件
  - 安装包已经完成“免费内置人脸模型”发行闭环

部署时需把有合法来源的模型文件放到 `Analyzer.modelDir` 下，然后分别调用 `/open/face/add` 和 `/open/face/search` 完成最小验证。

### 1. 模型精度 (Model Precision)

**字段**: `model_precision`
**类型**: String
**选项**: `FP32` (默认), `FP16`, `INT8`
**说明**: 模型量化精度标识，用于文档和UI展示

```python
# Django 模型定义
class AlgorithmModel(models.Model):
    model_precision = models.CharField(
        max_length=10,
        default='FP32',
        choices=[
            ('FP32', 'FP32 (单精度浮点)'),
            ('FP16', 'FP16 (半精度浮点)'),
            ('INT8', 'INT8 (8位整数)'),
        ],
        verbose_name='模型精度'
    )
```

| 精度 | 一般特征 | 验证要求 |
|------|---------|---------|
| FP32 | 基准精度，资源开销通常较高 | 作为转换前对照 |
| FP16 | 可在支持的 GPU/NPU 上减少存储和计算开销 | 对目标数据集重测精度与延迟 |
| INT8 | 需要后端支持，通常还需校准数据 | 必须重测精度，不能假设固定损失比例 |

### 2. 输入分辨率 (Input Dimensions)

**字段**: `input_width`, `input_height`
**类型**: Integer
**默认值**: 640 × 640
**说明**: 模型预处理输入尺寸（实际值从ONNX模型自动提取）

> ✅ v4.20.0 起：不再需要填写/传递历史字段 `dimension`（部分旧项目会把它当成“输出维度/类别维度”）。  
> - 旧配置仍携带 `dimension`：系统会兼容读取并忽略（不影响升级）。  
> - 新配置：只需要维护 `input_width/input_height`、阈值等标准字段即可。

```python
# Django 模型定义
input_width = models.IntegerField(default=640, verbose_name='输入宽度')
input_height = models.IntegerField(default=640, verbose_name='输入高度')
```

**推荐配置**:
| 分辨率 | 取舍 |
|--------|------|
| 320×320 | 计算量较低，小目标更容易丢失 |
| 640×640 | 常见起点，仍需按模型的实际输入和目标像素尺寸校验 |
| 1280×1280 | 可保留更多细节，但计算和内存开销显著增加 |

### 3. NMS 阈值 (NMS Threshold)

**字段**: `nms_thresh`
**类型**: Float
**默认值**: 0.45
**范围**: 0.0 - 1.0
**说明**: 非极大值抑制阈值，用于过滤重叠的检测框

```python
# Django 模型定义
nms_thresh = models.FloatField(
    default=0.45,
    verbose_name='NMS阈值',
    help_text='非极大值抑制阈值，范围 0.0-1.0，默认 0.45'
)
```

**调优建议**:
- **0.3 - 0.4**: 严格去重，适合密集场景
- **0.45 - 0.5**: **默认推荐**，通用场景
- **0.6 - 0.7**: 宽松去重，保留更多检测框

### 4. 置信度阈值 (Confidence Threshold)

**字段**: `conf_thresh`
**类型**: Float
**默认值**: 0.25
**范围**: 0.0 - 1.0
**说明**: 分类置信度阈值，低于此值的检测结果将被过滤

```python
# Django 模型定义
conf_thresh = models.FloatField(
    default=0.25,
    verbose_name='置信度阈值',
    help_text='分类置信度阈值，范围 0.0-1.0，默认 0.25'
)
```

**C++ 实现** (Analyzer.cpp:73):
```cpp
// 使用新的标准参数名称：confThresh (置信度阈值), nmsThresh (NMS阈值)
mAlgorithm->objectDetect(image, happenDetects, mControl->confThresh, mControl->nmsThresh);
```

**调优建议**:
- **0.15 - 0.25**: 高召回率，可能有误报
- **0.25 - 0.50**: **默认推荐**，平衡准确率和召回率
- **0.50 - 0.70**: 高精度，可能漏检

---

## 推流视频质量配置 {#推流视频质量配置}

### 1. 视频编码器 (Video Codec)

**字段**: `push_video_codec`
**类型**: String
**默认值**: `h264`
**选项**: `h264`, `h265`, `vp8`, `vp9`

```python
# Django 模型定义
push_video_codec = models.CharField(
    max_length=20,
    default='h264',
    verbose_name='推流视频编码器',
    help_text='视频编码器: h264, h265, vp8, vp9'
)
```

**C++ 实现** (AvPushStream.cpp:55-62):
```cpp
// 根据配置选择编码器
AVCodecID codecId = AV_CODEC_ID_H264;  // 默认 H.264
if (pushVideoCodec == "h265" || pushVideoCodec == "hevc") {
    codecId = AV_CODEC_ID_H265;
} else if (pushVideoCodec == "vp8") {
    codecId = AV_CODEC_ID_VP8;
} else if (pushVideoCodec == "vp9") {
    codecId = AV_CODEC_ID_VP9;
}
```

**编码器对比**:
| 编码器 | 压缩率 | CPU 占用 | 兼容性 | 推荐场景 |
|--------|--------|---------|--------|---------|
| H.264 | 1x | 低 | 最佳 | **默认推荐**，通用场景 |
| H.265 | 2x | 高 | 较好 | 带宽受限、存储优化 |
| VP8 | 0.8x | 中 | 良好 | WebRTC 场景 |
| VP9 | 1.5x | 高 | 中等 | YouTube 等流媒体 |

### 2. 视频码率 (Bitrate)

**字段**: `push_video_bitrate`
**类型**: Integer
**单位**: kbps
**默认值**: 2000 (2 Mbps)

```python
# Django 模型定义
push_video_bitrate = models.IntegerField(
    default=2000,
    verbose_name='推流码率(kbps)',
    help_text='视频码率，单位kbps，默认2000 (2Mbps)'
)
```

**C++ 实现** (AvPushStream.cpp:79):
```cpp
int bit_rate = pushVideoBitrate * 1000;  // kbps 转换为 bps
```

**推荐配置**:
| 分辨率 | 低质量 | 标准质量 | 高质量 | 适用场景 |
|--------|--------|---------|--------|---------|
| 640×480 | 500 kbps | 1000 kbps | 1500 kbps | 低带宽 |
| 1280×720 | 1000 kbps | **2000 kbps** | 3000 kbps | **推荐** |
| 1920×1080 | 2000 kbps | 4000 kbps | 6000 kbps | 高清 |

### 3. 帧率 (FPS)

**字段**: `push_video_fps`
**类型**: Integer
**默认值**: 25
**推荐范围**: 10 - 30 fps

```python
# Django 模型定义
push_video_fps = models.IntegerField(
    default=25,
    verbose_name='推流帧率(fps)',
    help_text='视频帧率，建议10-30fps，默认25'
)
```

**C++ 实现** (AvPushStream.cpp:94):
```cpp
mVideoCodecCtx->time_base = { 1, pushVideoFps };
```

**帧率选择**:
| FPS | CPU 占用 | 流畅度 | 适用场景 |
|-----|---------|--------|---------|
| 10 | 低 | 一般 | 静态场景、节省资源 |
| 15 | 中 | 较好 | 一般监控 |
| **25** | 中 | 流畅 | **默认推荐**，标准监控 |
| 30 | 高 | 非常流畅 | 快速运动场景 |

### 4. 分辨率 (Resolution)

**字段**: `push_video_width`, `push_video_height`
**类型**: Integer
**默认值**: 1280 × 720

```python
# Django 模型定义
push_video_width = models.IntegerField(
    default=1280,
    verbose_name='推流宽度',
    help_text='推流视频宽度，默认1280'
)
push_video_height = models.IntegerField(
    default=720,
    verbose_name='推流高度',
    help_text='推流视频高度，默认720'
)
```

**C++ 实现** (AvPushStream.cpp:289-291):
```cpp
// BGR 转 YUV420P 并支持缩放
SwsContext* sws_ctx = sws_getContext(width, height,
    AV_PIX_FMT_BGR24,
    pushWidth, pushHeight,  // 输出使用推流分辨率，支持自动缩放
    AV_PIX_FMT_YUV420P,
    SWS_BILINEAR, nullptr, nullptr, nullptr);
```

**常用分辨率**:
| 名称 | 分辨率 | 宽高比 | 文件大小 | 适用场景 |
|------|--------|--------|---------|---------|
| SD | 640×480 | 4:3 | 小 | 低带宽、边缘设备 |
| **HD** | **1280×720** | **16:9** | **中** | **默认推荐** |
| Full HD | 1920×1080 | 16:9 | 大 | 高清监控 |
| 2K | 2560×1440 | 16:9 | 很大 | 专业级监控 |

### 5. GOP (关键帧间隔)

**字段**: `push_video_gop`
**类型**: Integer
**默认值**: 50
**说明**: 两个关键帧之间的帧数（I帧间隔）

```python
# Django 模型定义
push_video_gop = models.IntegerField(
    default=50,
    verbose_name='关键帧间隔(GOP)',
    help_text='关键帧间隔，默认50帧'
)
```

**C++ 实现** (AvPushStream.cpp:95):
```cpp
mVideoCodecCtx->gop_size = pushVideoGop;
```

**GOP 值选择**:
| GOP 值 | 压缩率 | 随机访问 | 适用场景 |
|--------|--------|---------|---------|
| 10-25 | 低 | 快速 | 需要频繁seek、实时性要求高 |
| **50** | **中** | **正常** | **默认推荐**，标准监控 |
| 100-250 | 高 | 慢 | 存储优先、网络带宽受限 |

**计算示例**:
- GOP = 50, FPS = 25 → 关键帧间隔 = 50/25 = **2秒**
- GOP = 100, FPS = 25 → 关键帧间隔 = 100/25 = **4秒**

---

## 数据库迁移 {#数据库迁移}

### 执行迁移

```bash
cd Admin
python manage.py migrate
```

### 迁移文件内容

文件: `Admin/app/migrations/0006_algorithm_and_control_enhancements.py`

```python
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('app', '0005_control_log'),
    ]

    operations = [
        # 算法模型新增字段
        migrations.AddField(
            model_name='algorithmmodel',
            name='model_precision',
            field=models.CharField(
                choices=[('FP32', 'FP32 (单精度浮点)'),
                        ('FP16', 'FP16 (半精度浮点)'),
                        ('INT8', 'INT8 (8位整数)')],
                default='FP32',
                max_length=10,
                verbose_name='模型精度'
            ),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='input_width',
            field=models.IntegerField(default=640, verbose_name='输入宽度'),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='input_height',
            field=models.IntegerField(default=640, verbose_name='输入高度'),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='nms_thresh',
            field=models.FloatField(
                default=0.45,
                help_text='非极大值抑制阈值，范围 0.0-1.0，默认 0.45',
                verbose_name='NMS阈值'
            ),
        ),
        migrations.AddField(
            model_name='algorithmmodel',
            name='conf_thresh',
            field=models.FloatField(
                default=0.25,
                help_text='分类置信度阈值，范围 0.0-1.0，默认 0.25',
                verbose_name='置信度阈值'
            ),
        ),

        # 布控模型新增推流质量配置字段
        migrations.AddField(
            model_name='control',
            name='push_video_codec',
            field=models.CharField(
                default='h264',
                help_text='视频编码器: h264, h265, vp8, vp9',
                max_length=20,
                verbose_name='推流视频编码器'
            ),
        ),
        migrations.AddField(
            model_name='control',
            name='push_video_bitrate',
            field=models.IntegerField(
                default=2000,
                help_text='视频码率，单位kbps，默认2000 (2Mbps)',
                verbose_name='推流码率(kbps)'
            ),
        ),
        migrations.AddField(
            model_name='control',
            name='push_video_fps',
            field=models.IntegerField(
                default=25,
                help_text='视频帧率，建议10-30fps，默认25',
                verbose_name='推流帧率(fps)'
            ),
        ),
        migrations.AddField(
            model_name='control',
            name='push_video_width',
            field=models.IntegerField(
                default=1280,
                help_text='推流视频宽度，默认1280',
                verbose_name='推流宽度'
            ),
        ),
        migrations.AddField(
            model_name='control',
            name='push_video_height',
            field=models.IntegerField(
                default=720,
                help_text='推流视频高度，默认720',
                verbose_name='推流高度'
            ),
        ),
        migrations.AddField(
            model_name='control',
            name='push_video_gop',
            field=models.IntegerField(
                default=50,
                help_text='关键帧间隔，默认50帧',
                verbose_name='关键帧间隔(GOP)'
            ),
        ),
    ]
```

---

## API 使用示例 {#api-使用示例}

### 1. 添加布控任务（完整参数）

```bash
POST /api/control/add
Content-Type: application/json

{
  "code": "ctrl001",
  "algorithmCode": "yolov8n",
  "streamCode": "camera001",
  "streamApp": "live",
  "streamName": "office",
  "streamUrl": "rtsp://192.168.1.100:554/stream",
  "pushStream": true,
  "pushStreamUrl": "rtsp://localhost:9994/live/output",
  "api_url": "",
  "object_str": "person,car,truck",
  "objectCode": "person",
  "recognitionRegion": "0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9",
  "minInterval": "5",

  // ========== 新增：算法推理参数 ==========
  "confThresh": "0.5",      // 置信度阈值
  "nmsThresh": "0.45",      // NMS阈值
  "modelPrecision": "FP32", // 模型精度
  "inputWidth": 640,        // 输入宽度
  "inputHeight": 640,       // 输入高度

  // ========== 新增：推流视频质量参数 ==========
  "pushVideoCodec": "h264",     // 编码器
  "pushVideoBitrate": 2000,     // 码率 (kbps)
  "pushVideoFps": 25,           // 帧率
  "pushVideoWidth": 1280,       // 宽度
  "pushVideoHeight": 720,       // 高度
  "pushVideoGop": 50,           // GOP

  "alarmVideoType": "mp4",
  "alarmImageCount": 3
}
```

### 2. Python SDK 示例

```python
from beacon_sdk import BeaconClient

# SDK 源码位置：sdk/python
# 本地开发可直接：
#   pip install -e sdk/python

client = BeaconClient(
    "http://localhost:9991",
    open_api_token="CHANGE_ME_OPEN_API_TOKEN",
    cloud_edge_token="edge-token-001",
)
client.login("admin", "<your-admin-password>")

controls = client.get_controls()
algorithms = client.get_algorithms()
license_info = client.get_license_info()
basic_info = client.get_platform_basic_info()

print(controls)
print(algorithms)
print(license_info)
print(basic_info)
print(client.acquire_license_lease(node_id="node-1", control_code="ctrl-1", algorithm_code="alg-1"))
print(client.list_recording_plans())
print(client.list_recording_files(streamCode="stream001"))
print(client.list_faces())
print(client.ops_cleanup(targets=["logs"], dry_run=True))

client.report_detection(
    control_code="control_12345",
    detections=[
        {"class_name": "person", "confidence": 0.95, "bbox": [100, 100, 200, 300]}
    ],
    frame_index=100,
    trigger_alarm=True,
)
```

### 3. JavaScript/TypeScript SDK 示例

```typescript
import { BeaconClient } from "./sdk/javascript/beacon-sdk.mjs";

// SDK 源码位置：sdk/javascript
const client = new BeaconClient("http://localhost:9991", {
  openApiToken: "CHANGE_ME_OPEN_API_TOKEN",
  cloudEdgeToken: "edge-token-001",
});
await client.login("admin", "<your-admin-password>");

const controls = await client.getControls();
const algorithms = await client.getAlgorithms();
const licenseInfo = await client.getLicenseInfo();
const basicInfo = await client.getPlatformBasicInfo();

console.log(controls);
console.log(algorithms);
console.log(licenseInfo);
console.log(basicInfo);
console.log(await client.acquireLicenseLease({
  nodeId: "node-1",
  controlCode: "ctrl-1",
  algorithmCode: "alg-1"
}));
console.log(await client.listRecordingPlans());
console.log(await client.listRecordingFiles({ streamCode: "stream001" }));
console.log(await client.listFaces());
console.log(await client.opsCleanup({ targets: ["logs"], dry_run: true }));

await client.reportDetection({
  controlCode: "control_12345",
  detections: [
    { class_name: "person", confidence: 0.95, bbox: [100, 100, 200, 300] }
  ],
  frameIndex: 100,
  triggerAlarm: true
});
```

### 4. Go SDK 示例

```go
package main

import (
	"log"

	beaconsdk "beacon-sdk-go"
)

func main() {
	client, err := beaconsdk.NewClient(
		"http://localhost:9991",
		beaconsdk.WithOpenAPIToken("CHANGE_ME_OPEN_API_TOKEN"),
		beaconsdk.WithCloudEdgeToken("edge-token-001"),
	)
	if err != nil {
		log.Fatal(err)
	}

	if _, err := client.Login("admin", "<your-admin-password>", ""); err != nil {
		log.Fatal(err)
	}

	controls, err := client.GetControls()
	if err != nil {
		log.Fatal(err)
	}

	algorithms, err := client.GetAlgorithms()
	if err != nil {
		log.Fatal(err)
	}

	licenseInfo, err := client.GetLicenseInfo()
	if err != nil {
		log.Fatal(err)
	}

	log.Println(controls)
	log.Println(algorithms)
	log.Println(licenseInfo)

	lease, err := client.AcquireLicenseLease(beaconsdk.AcquireLicenseLeaseRequest{
		NodeID:        "node-1",
		ControlCode:   "control_12345",
		AlgorithmCode: "alg-1",
	})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(lease)

	recordingPlans, err := client.ListRecordingPlans(map[string]any{})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(recordingPlans)

	recordingFiles, err := client.ListRecordingFiles(map[string]any{"streamCode": "stream001"})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(recordingFiles)

	faces, err := client.ListFaces()
	if err != nil {
		log.Fatal(err)
	}
	log.Println(faces)

	ops, err := client.OpsCleanup(map[string]any{"targets": []string{"logs"}, "dry_run": true})
	if err != nil {
		log.Fatal(err)
	}
	log.Println(ops)

	if _, err := client.ReportDetection(beaconsdk.ReportDetectionRequest{
		ControlCode: "control_12345",
		FrameIndex:  100,
		Detections: []beaconsdk.Detection{
			{ClassName: "person", Confidence: 0.95, BBox: []float64{100, 100, 200, 300}},
		},
		TriggerAlarm: true,
	}); err != nil {
		log.Fatal(err)
	}
}
```

---

## 最佳实践 {#最佳实践}

### 1. 场景优化配置

#### 🏢 办公室监控（标准配置）
```json
{
  "pushVideoCodec": "h264",
  "pushVideoBitrate": 2000,
  "pushVideoFps": 25,
  "pushVideoWidth": 1280,
  "pushVideoHeight": 720,
  "pushVideoGop": 50,
  "confThresh": "0.5",
  "nmsThresh": "0.45"
}
```

#### 🌐 远程低带宽场景
```json
{
  "pushVideoCodec": "h265",      // 更高压缩率
  "pushVideoBitrate": 800,       // 低码率
  "pushVideoFps": 15,            // 降低帧率
  "pushVideoWidth": 640,         // 降低分辨率
  "pushVideoHeight": 480,
  "pushVideoGop": 100,           // 更大GOP
  "confThresh": "0.5",
  "nmsThresh": "0.45"
}
```

#### 🎯 高精度检测场景
```json
{
  "pushVideoCodec": "h264",
  "pushVideoBitrate": 4000,      // 高码率保证质量
  "pushVideoFps": 30,            // 高帧率
  "pushVideoWidth": 1920,        // Full HD
  "pushVideoHeight": 1080,
  "pushVideoGop": 50,
  "confThresh": "0.65",          // 高置信度阈值
  "nmsThresh": "0.35"            // 严格NMS
}
```

#### 🚀 高性能/边缘设备场景
```json
{
  "pushVideoCodec": "h264",
  "pushVideoBitrate": 1500,
  "pushVideoFps": 20,
  "pushVideoWidth": 960,
  "pushVideoHeight": 540,
  "pushVideoGop": 40,
  "confThresh": "0.4",           // 降低阈值提高召回
  "nmsThresh": "0.5"
}
```

### 2. 性能调优建议

#### 降低 CPU 占用
1. 降低推流帧率：30 fps → 20 fps → 15 fps
2. 降低推流分辨率：1920×1080 → 1280×720 → 960×540
3. 使用硬件编码器（如果支持）

#### 降低网络带宽
1. 在摄像头、MediaServer、播放端和 Analyzer 都支持时，实测 H.264/H.265 的质量、码率与解码开销
2. 逐步降低码率，同时复核小目标、快速运动和夜间画面
3. 只在首帧时间、拖动定位和告警剪辑仍满足要求时增大 GOP

#### 提高检测精度
1. 提高置信度阈值：0.25 → 0.50 → 0.65
2. 降低 NMS 阈值：0.5 → 0.4 → 0.3
3. 精确绘制检测区域，避免复杂背景

#### 提高检测召回率
1. 降低置信度阈值：0.5 → 0.35 → 0.25
2. 提高 NMS 阈值：0.4 → 0.5 → 0.6

### 3. 监控最佳实践

#### 实时监控系统状态
```bash
# 查看推流质量
curl http://localhost:9993/api/controls | jq

# 查看系统资源使用
curl http://localhost:9993/api/resource/info | jq

# 查看调度器统计
curl http://localhost:9993/api/scheduler/info | jq
```

#### 日志分析
```bash
# 查看推流日志
tail -f Analyzer/log/*.log | grep "Push stream using codec"

# 输出示例：
# Push stream using codec: h264, resolution: 1280x720, bitrate: 2000 kbps, fps: 25, gop: 50
```

---

## 常见问题 {#常见问题}

### Q1: 修改推流参数后需要重启吗？

**A**: 需要重新启动布控任务。修改 Control 的推流参数后，需要：
1. 停止当前布控：`POST /control/openStopControl`
2. 启动布控（新参数生效）：`POST /control/openStartControl`

### Q2: 如何验证参数是否生效？

**A**: 查看 Analyzer 日志：
```bash
tail -f Analyzer/log/*.log | grep "Push stream"
```
输出示例：
```
Push stream using codec: h265, resolution: 1920x1080, bitrate: 4000 kbps, fps: 30, gop: 60
```

### Q3: confThresh 和 classThresh 有什么区别？

**A**:
- `confThresh`: **新参数**，标准命名，YOLO模型的置信度阈值
- `classThresh`: **旧参数**，为了向后兼容保留
- 系统优先使用 `confThresh`，如果未提供则使用 `classThresh`

### Q4: 推流分辨率可以和源视频不一致吗？

**A**: 可以！系统会自动缩放：
```cpp
// AvPushStream.cpp:289-293
SwsContext* sws_ctx = sws_getContext(
    width, height,           // 源视频分辨率
    AV_PIX_FMT_BGR24,
    pushWidth, pushHeight,   // 推流分辨率（自动缩放）
    AV_PIX_FMT_YUV420P,
    SWS_BILINEAR, nullptr, nullptr, nullptr);
```

### Q5: H.265 编码失败怎么办？

**A**: 可能原因：
1. FFmpeg 未编译 H.265 支持
2. 系统缺少 libx265 库

解决方案：
```bash
# 检查编码器支持
ffmpeg -codecs | grep hevc

# 如果不支持，降级使用 H.264
"pushVideoCodec": "h264"
```

### Q6: 如何选择合适的 GOP 值？

**A**:
- **实时监控**: GOP = FPS × 2 (例如 25fps → GOP=50)
- **录像存储**: GOP = FPS × 4 (例如 25fps → GOP=100)
- **关键帧越密集，随机访问越快，但文件越大**

### Q7: modelPrecision 字段有什么用？

**A**:
- 该字段用于 **文档和 UI 展示**，标识模型的量化精度
- 实际推理时，模型精度由 ONNX 模型文件本身决定
- 如需使用 FP16/INT8 模型，需要导出对应精度的 .onnx 文件

### Q8: 系统会自动降级吗？

**A**: 会！当资源不足时：
```cpp
// Scheduler.cpp 资源自适应
if (cpuUsage > 80%) {
    detectStride = 3;  // 跳帧检测，降低负载
}
if (cpuUsage > 90%) {
    canAddControl = false;  // 暂停接受新布控
}
```

### Q9: 如何批量修改所有布控的推流质量？

**A**: 通过 Django Shell 批量更新：
```bash
cd Admin
python manage.py shell
```

```python
from app.models import Control

# 批量更新所有布控的推流参数
Control.objects.all().update(
    push_video_codec='h265',
    push_video_bitrate=1500,
    push_video_fps=20,
    push_video_width=960,
    push_video_height=540,
    push_video_gop=80
)

# 更新后需要重启布控才能生效
```

### Q10: 如何调试推流问题？

**A**:
1. **查看推流日志**：
   ```bash
   tail -f Analyzer/log/*.log | grep -E "Push|encode|write"
   ```

2. **使用 FFplay 测试**：
   ```bash
   ffplay rtsp://localhost:9994/live/your_control_code
   ```

3. **检查编码器是否成功初始化**：
   日志中查找 "avcodec_find_encoder error"

4. **监控编码性能**：
   日志中查找 "encode 1 frame spend" 查看编码耗时

---

## 技术支持

如有问题，请：
1. 查看 [部署总入口](deploy/README.md)
2. 提交 [GitHub Issue](https://github.com/skygazer42/Beacon/issues)
3. 查看 [常见问题](#常见问题)

---

**适用版本**：当前 `main` 与根目录 `PROJECT_VERSION` 对应的最新发布版。
