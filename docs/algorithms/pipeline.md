# 算法 Pipeline

Analyzer 当前通过 `Control.algorithmPipelineMode` 选择固定的 1–9 模式。它不是一个可从任意 `stages` JSON 动态组装节点的通用工作流引擎；Admin 画面保存的是模式编号和各算法编码/配置。

## 模式表

| 模式 | 当前链路 | 必要条件 |
|---:|---|---|
| 1 | 检测 → ROI/类别行为过滤 | 主检测模型或基础 API |
| 2 | 检测 → ByteTrack/ReID 追踪 → ROI/类别过滤 | 主检测；追踪可选，缺失时仍做无追踪过滤 |
| 3 | 检测 → ROI 分类 → ROI/类别过滤 | 主检测 + `classificationAlgorithmCode` |
| 4 | 整图分类 → 类别过滤 | `classificationAlgorithmCode` |
| 5 | 外部行为 API；v2 可接本地规则后处理 | `behaviorApiUrl`，响应契约与版本配置 |
| 6 | 整图分类门控 → 检测 → ROI/类别过滤 | 主检测 + 分类算法 |
| 7 | 检测 → ROI 分类 → 特征 → 行为 | 主检测 + 分类 + 特征；可选陌生人配置/人脸库 |
| 8 | 检测 1 → 检测 2 → 行为 | 主检测，可选二级检测；支持 ROI/full 与 AND/OR |
| 9 | 检测 1 → 特征 → 检测 2 → 行为 | 主检测 + 特征，可选二级检测；可选陌生人配置 |

模式编号由 `Admin/app/views/api.py` 校验为 1–9，并由 `Analyzer.cpp` 的对应 `executePipelineMode*` 执行。不同模式对“缺失可选算法”的处理并不完全一致，部署前必须按实际配置测试。

## 保存字段

布控协议使用下列字段，而不是通用 `stages` 数组：

```json
{
  "usePipelineMode": true,
  "pipelineMode": 8,
  "algorithmCode": "primary-detector",
  "secondaryAlgorithmCode": "secondary-detector",
  "trackingAlgorithmCode": "",
  "classificationAlgorithmCode": "",
  "featureAlgorithmCode": "",
  "behaviorAlgorithmCode": "",
  "behaviorApiUrl": "",
  "trackingConfig": "{}",
  "classificationConfig": "{}",
  "featureConfig": "{}",
  "behaviorConfig": "{\"pipeline\":{\"detect1Enabled\":true,\"detect2Enabled\":true,\"detectLogic\":\"and\",\"detect2Input\":\"roi\"}}"
}
```

字段含义还依赖模式：

- 模式 5 的 API v1/v3 由外部服务返回 `happen`；API v2 返回 `detects` 后由 Analyzer 执行受支持的本地规则。
- 模式 8/9 从 `behaviorConfig.pipeline` 读取 `detect1Enabled`、`detect2Enabled`、`detectLogic` 和 `detect2Input`。
- 模式 7/9 的 `builtinBehavior=stranger` 会使用特征向量和本地人脸库判断陌生人；需要真实特征模型和阈值验证。
- ROI、目标类别、`lineCoordinates`、置信度/NMS、输入尺寸等仍由 Control 其他字段提供。

## 配置流程

1. 分别注册并单图测试主检测、分类、特征或二级检测算法。
2. 在布控编辑器选择固定模式，填写该模式要求的算法编码。
3. 保存后检查 Admin 下发的 Control JSON 和 Analyzer 加载日志。
4. 用同时覆盖“应触发”和“不应触发”的视频验证每个阶段。
5. 记录每阶段耗时、总 P99、显存/内存和失败时行为，再决定并发。

## 常见误区

- 选择模式不会自动下载或寻找缺失模型。
- `classificationConfig`、`trackingConfig`、`featureConfig` 虽要求是 JSON，但并非其中任意字段都会被 Analyzer 使用。
- 文档中的概念节点不代表运行时支持任意拖拽组合。
- 二级模型在每个 ROI 上运行时，延迟随一级目标数增长；不能只测空画面。
- 特征步骤在部分高级模式中是 best-effort，失败可能不会停止整个布控，必须检查日志和结果元数据。

外部行为 API 见 [算法 API 协议 v2](../integration/algorithm-api-protocol-v2.md)，本地规则见 [本地规则与模型目录](builtin.md)。
