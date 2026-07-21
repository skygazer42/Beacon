# 项目结构

本页只描述当前源码树中的稳定入口。构建产物、数据库、模型、上传文件和本机配置均不属于发布源码。

## 顶层目录

```text
Beacon/
├── Admin/                  # Django Admin 与 React/Vite 前端
├── Analyzer/               # C++17 视频分析引擎
├── MediaServer/            # 基于 ZLMediaKit 的媒体服务源码
├── sdk/                    # Python、JavaScript、Go SDK
├── deploy/                 # Edge、Cloud POC、Helm、systemd 与观测配置
├── docs/                   # MkDocs 文档
├── examples/               # 算法插件示例
├── tests/                  # 少量跨组件契约测试
├── tools/                  # 构建、模拟、验收和文档检查工具
├── config.json             # 可提交的安全默认配置
├── PROJECT_VERSION         # 构建版本源
├── mkdocs.yml              # 文档站点配置
└── LICENSE                 # Beacon 自研代码许可证
```

`settings.json`、`db.sqlite3`、`data/`、`log/`、`site/` 和各类 `build/` 是本机运行或构建产物，已由 `.gitignore` 排除。

## Admin

```text
Admin/
├── Admin/                  # Django project 配置、ASGI/WSGI 入口
├── app/
│   ├── models.py           # 数据模型
│   ├── urls.py             # 真实路由表
│   ├── views/              # 页面、OpenAPI、Cloud 与运维视图
│   ├── services/           # 应用服务
│   ├── utils/              # 媒体、告警、鉴权等工具
│   ├── migrations/         # 数据库迁移
│   ├── tests/              # Django 测试
│   └── ws.py               # /ws/alarm/poll ASGI 处理器
├── frontend/               # React 18 + Vite 源码
├── static/app-shell/       # 提交的前端生产包及第三方声明
├── templates/app/          # 登录页、React 壳及少量服务端表单
├── manage.py
└── requirements-*.txt
```

浏览器 UI 主要使用 `/api/app-shell/*` 内部接口；机器对接使用 `/open/*`、`/stream/open*`、`/control/open*` 等既有 OpenAPI。两者不要混为统一 REST v1。

## Analyzer

```text
Analyzer/
├── Analyzer/
│   ├── main.cpp
│   ├── Core/               # 解码、推理、追踪、行为与告警逻辑
│   └── Analyzer.vcxproj
├── Compat/                 # 可选硬件后端插件接口与 stub
├── CMakeLists.txt
├── Analyzer.sln
└── README.md
```

顶层 CMake 要求 3.16+ 和 C++17，并直接链接 OpenCV、FFmpeg、libevent、curl、jsoncpp、ONNX Runtime；x86_64/AArch64 构建还会按配置链接 OpenVINO。TensorRT Engine 和厂商 NPU 路径依赖额外插件，不由基础 CMake 参数自动提供。

模型目录是部署输入，不是开源仓库的一部分。测试入口为 `tools/run_analyzer_unit_tests.sh`。

## MediaServer

```text
MediaServer/
├── source/                 # ZLMediaKit 分支源码及上游依赖
├── UPSTREAM.md             # 来源、基线与本地差异说明
└── README.md
```

默认端口由根目录 `config.json` 协调：HTTP `9992`、RTSP `9994`、RTMP `9995`。第三方许可和必须保留的标识见根目录 `THIRD_PARTY_NOTICES.md` 与源码目录中的许可证。

## SDK 与集成

```text
sdk/
├── python/
├── javascript/
└── go/

examples/
└── algorithm_plugin_cpp/  # C ABI 插件示例
```

SDK 封装的是当前兼容 OpenAPI 路径，不代表服务端存在自动生成的 Swagger 或完整资源型 REST API。接口清单见 [API 概览](../api/index.md)。

## 部署与工具

- `deploy/cloud-saas-v1/`：单实例 Cloud POC、PostgreSQL、MinIO 和 Helm 参考。
- `deploy/local-fullstack/`：本地全栈辅助配置。
- `deploy/systemd/`：服务托管样例。
- `deploy/observability/`：可选追踪配置；不等于默认启用完整监控栈。
- `tools/rtsp_simulator.py`：本地 RTSP 测试源。
- `tools/build_analyzer_local.sh`：Analyzer 本地依赖/构建辅助。
- `tools/docs_strict_check.py`：文档路径与结构检查。

发布候选应从 Git 受控文件及明确允许的未跟踪源码生成，不要直接打包整个工作目录。
