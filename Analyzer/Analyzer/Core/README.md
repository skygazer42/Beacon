# Analyzer Core - 源代码说明

## 目录结构

```
Core/
├── Algorithm.cpp/h           # 算法基类
├── AlgorithmOnYolo.cpp/h     # ONNX Runtime 推理引擎
├── AlgorithmOvYolo.cpp/h     # OpenVINO 推理引擎
├── Analyzer.cpp/h            # 分析器主逻辑
├── AvPullStream.cpp/h        # 视频拉流解码
├── AvPushStream.cpp/h        # 视频推流编码
├── Config.cpp/h              # 配置文件读取
├── Control.h                 # 布控任务数据结构
├── Frame.cpp/h               # 视频帧封装
├── GenerateAlarmVideo.cpp/h  # 告警视频生成
├── Scheduler.cpp/h           # 任务调度器
├── Server.cpp/h              # HTTP API 服务
├── Worker.cpp/h              # 工作线程
├── Var.h                     # 全局变量
├── Version.h                 # 版本号定义
└── Utils/                    # 工具类
    ├── Base64.h              # Base64 编解码
    ├── CalcuIOU.cpp/h        # IOU 计算
    ├── Common.h              # 通用函数
    ├── Log.h                 # 日志输出
    └── Request.cpp/h         # HTTP 请求
```

---

## 核心文件详解

### 1. 推理引擎

#### `Algorithm.cpp/h` - 算法基类
- 所有推理算法的抽象基类
- 定义通用接口：`detect()`, `preprocess()`, `postprocess()`
- 存储配置信息和类别名称

#### `AlgorithmOvYolo.cpp/h` - OpenVINO 推理 (主要使用)
- 使用 Intel OpenVINO 框架进行 YOLO 推理
- 支持 CPU/GPU 加速
- 加载 `.xml` + `.bin` 模型文件
- 主要函数：
  - `AlgorithmOvYolo()` - 构造函数，加载模型
  - `detect()` - 执行目标检测
  - `letterBox()` - 图像预处理（保持宽高比缩放）
  - `postProcess()` - 后处理（NMS 非极大值抑制）

#### `AlgorithmOnYolo.cpp/h` - ONNX Runtime 推理
- 使用 ONNX Runtime 框架进行 YOLO 推理
- 通用性更强，支持多种硬件
- 加载 `.onnx` 模型文件
- 结构与 OpenVINO 版本类似

---

### 2. 任务调度

#### `Scheduler.cpp/h` - 任务调度器 (核心)
- 管理所有布控任务的生命周期
- 初始化所有 AI 模型
- 主要函数：
  - `initAlgorithm()` - 初始化所有 YOLO 模型
  - `addControl()` - 添加布控任务
  - `removeControl()` - 移除布控任务
  - `getAlgorithm()` - 根据算法代码获取对应算法实例
  - `loop()` - 主循环，处理告警队列
- 管理的算法：
  - `on_yolov8n_80` - ONNX 80类通用检测
  - `ov_yolov8n_80` - OpenVINO 80类通用检测
  - `ov_yolov8n_fight_nofight` - 打架检测
  - `ov_yolov8n_fire_smoke` - 火焰烟雾检测
  - `ov_yolov8n_smoke` - 抽烟检测
  - `ov_yolov11n_safehat` - 安全帽检测

#### `Worker.cpp/h` - 工作线程
- 每个布控任务对应一个 Worker 线程
- 负责：拉流 → 解码 → 推理 → 判断告警 → 生成告警视频
- 主要函数：
  - `start()` - 启动工作线程
  - `stop()` - 停止工作线程
  - `run()` - 主工作循环
  - `analyze()` - 对单帧进行分析
  - `checkAlarm()` - 判断是否触发告警

#### `Control.h` - 布控数据结构
- 定义布控任务的数据结构
- 包含：任务ID、视频流地址、算法类型、检测区域、置信度阈值等

---

### 3. 视频处理

#### `AvPullStream.cpp/h` - 拉流解码
- 使用 FFmpeg 从 RTSP/RTMP/HTTP 拉取视频流
- 解码视频帧为 OpenCV Mat 格式
- 主要函数：
  - `open()` - 打开视频流
  - `read()` - 读取一帧
  - `close()` - 关闭视频流
  - `getFrame()` - 获取解码后的帧

#### `AvPushStream.cpp/h` - 推流编码
- 使用 FFmpeg 编码视频并推送到流媒体服务器
- 支持 RTMP 推流
- 主要函数：
  - `open()` - 打开推流
  - `write()` - 写入一帧
  - `close()` - 关闭推流

#### `Frame.cpp/h` - 视频帧封装
- 封装视频帧数据
- 包含：图像数据、时间戳、帧序号等

#### `GenerateAlarmVideo.cpp/h` - 告警视频生成
- 当检测到异常行为时，生成告警视频和截图
- 主要函数：
  - `generate()` - 生成告警视频
  - `saveImage()` - 保存告警截图
  - `saveVideo()` - 保存告警视频
  - `callback()` - 回调通知 Django Admin

---

### 4. 服务接口

#### `Server.cpp/h` - HTTP API 服务
- 基于 libevent 实现的 HTTP 服务器
- 监听端口：9993（默认）
- API 接口：
  - `POST /control/add` - 添加布控
  - `POST /control/remove` - 移除布控
  - `GET /control/list` - 获取布控列表
  - `GET /status` - 获取服务状态

#### `Analyzer.cpp/h` - 分析器主逻辑
- 处理具体的 API 请求
- 解析 JSON 参数
- 调用 Scheduler 执行操作

#### `Config.cpp/h` - 配置读取
- 读取 `config.json` 配置文件
- 解析配置项：端口、路径、模型目录等

---

### 5. 工具类 (Utils/)

#### `CalcuIOU.cpp/h` - IOU 计算
- 计算两个边界框的交并比 (Intersection over Union)
- 用于周界入侵等算法判断目标是否在检测区域内

#### `Request.cpp/h` - HTTP 请求
- 使用 libcurl 发送 HTTP 请求
- 用于回调通知 Django Admin

#### `Common.h` - 通用函数
- 字符串分割、时间格式化等工具函数

#### `Log.h` - 日志输出
- 日志宏定义：`LOGI()`, `LOGE()`, `LOGW()`

#### `Base64.h` - Base64 编解码
- 图像数据的 Base64 编解码

---

## 数据流向

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ AvPullStream│───▶│   Worker    │───▶│  Algorithm  │───▶│GenerateAlarm│
│  (拉流解码)  │    │  (工作线程)  │    │  (YOLO推理) │    │  (生成告警)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                          │                                     │
                          ▼                                     ▼
                   ┌─────────────┐                       ┌─────────────┐
                   │  Scheduler  │                       │   Django    │
                   │  (任务调度)  │                       │  (回调通知)  │
                   └─────────────┘                       └─────────────┘
```

---

## 添加新算法步骤

1. 准备模型文件（.onnx 或 .xml+.bin）放入 `models/` 目录
2. 在 `Scheduler.cpp` 的 `initAlgorithm()` 中添加模型加载代码
3. 在 `Scheduler.h` 中添加算法指针成员
4. 在 `getAlgorithm()` 中添加算法代码映射
5. 重新编译项目

---

## 编译

使用 Visual Studio 2019+ 打开 `Analyzer.sln`，选择 Release x64 编译。

## 运行

```cmd
Analyzer.exe -f config.json
```
