# 本地规则与模型目录

“内置”在当前源码里有两种含义：一是 Analyzer 编译进来的模型元数据目录，二是 Behavior API v2 对检测结果执行的本地后处理。两者都不包含模型权重，也不代表场景精度已经验证。

## 模型元数据目录

`Analyzer/Analyzer/Core/AlgorithmBuiltinCatalog.cpp` 当前识别以下类别：

| 类型 | 编码示例 | 说明 |
|---|---|---|
| COCO 检测 | `on_yolov5s_80`、`on_yolov8n_80`、`on_yolov8s_80` 及 OpenVINO 变体 | 预期 COCO 80 类模型 |
| 事件专用检测 | `ov_yolov8n_fight_nofight`、`ov_yolov8n_fire_smoke`、`ov_yolov8n_smoke` | 只记录预期类别和文件名 |
| PPE | `ov_yolov11n_safehat` | 预期 `head` / `safehat` 类别 |
| OCR | `on_xcocr_plate`、`ov_xcocr_plate` | 车牌字符模型元数据 |
| ReID | `on_xcfacenet`、`ov_xcfacenet` | 特征模型元数据 |

这些文件名对应的模型不在 Git 候选源码中。部署者必须提供合法资产，并验证模型输出和 Analyzer 实现匹配。也可以使用不同编码注册自己的模型，不要求使用目录中的名字。

## Behavior API v2 后处理

API v2 由外部算法返回 `detects`，Analyzer 再执行下列本地规则：

| 名称 | 逻辑 | 额外条件 |
|---|---|---|
| `intrusion` | 目标类别和 ROI 过滤后命中 | 可配置覆盖比例 |
| `super` | 使用框内可配置点做 ROI 命中 | 需要 ROI 时使用中心点参数 |
| `crowd` | 区域内目标数大于等于或小于等于阈值 | 依赖类别/ROI |
| `crossing` | 追踪目标越过配置线 | 需要线段、视频尺寸和稳定追踪 |
| `crosscount` | 越线事件并按 track id 做帧内去重 | 条件同 crossing |
| `loitering` | 追踪目标在区域内持续达到阈值帧数 | 依赖 FPS、追踪和 ROI |
| `absence` | 区域持续没有目标 | 可按区域独立计时 |
| `unattended` | 与 absence 类似，事件语义为无人值守 | 可按区域独立计时 |
| `motion` | 追踪轨迹位移超过像素阈值 | 依赖稳定追踪 |
| `occlusion` | 本地图像质量判断 | 不调用外部行为 API |
| `grayscreen` | 本地图像质量判断 | 不调用外部行为 API |
| `corruptscreen` | 本地图像质量判断 | 不调用外部行为 API |

解析器对未知名称存在兼容回退，因此 API v2 集成只应使用上表中的规范名称，并通过 Analyzer 单元测试/真实视频确认结果。`stranger` 属于特定高级 Pipeline 模式，不是通用 API v2 后处理。

## 容易混淆的行为

`fight`、`fire/smoke`、`safehat` 等通常由专用模型或外部 API 直接产生类别/事件；`fall` 也存在 Pipeline 行为节点。它们不是“无需模型即可运行”的规则。

Admin 页面可能允许保存更广泛的行为标签，以兼容外部 API 或历史 Pipeline。使用 API v1/v3 时，事件 `happen` 由外部服务返回；使用 API v2 时必须选择 Analyzer 真正支持的本地规则。

## 验收方法

1. 记录模型来源、许可证、哈希、输入输出和类别。
2. 在算法表单执行单图测试，确认有效设备和输出框。
3. 创建单路布控，核对 Analyzer 实际加载日志。
4. 对有/无事件的标注视频分别测试，记录误报和漏报。
5. 再增加并发并观察 P99 延迟、丢帧、队列、CPU/GPU 和告警媒体开销。

模型格式见 [模型指南](models.md)，外部行为响应格式见 [算法 API 协议](../integration/algorithm-api-protocol-v2.md)。
