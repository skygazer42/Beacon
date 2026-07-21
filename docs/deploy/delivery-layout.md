# Beacon 交付包目录结构规范（Edge 全栈）

本文档定义 Beacon “Edge 全栈交付包”的推荐目录布局，让下面这两件事成立：

1. 运维同事拿到包后，不需要理解源码结构，也能按约定放置二进制/配置/模型并启动。
2. `Admin/VideoAnalyzer.py` 进程守护启动器能按约定路径找到 `MediaServer` 与 `Analyzer` 并拉起。

适用场景：

- 单机交付（On-Prem / Edge）
- 需要在同一台机器跑 Admin + Analyzer + MediaServer

不适用场景：

- Cloud Docker POC（见 `deploy/cloud-saas-v1/compose.yml`）
- 纯源码开发调试（源码结构和交付包结构不同）

交付包启动完成后，建议按下面文档做端到端验收（可复现步骤 + 排障清单）：

- `docs/deploy/e2e-acceptance.md`

运行期配置与运维接口参考：

- `docs/deploy/config-reference.md`
- `docs/deploy/ops-runbook.md`
- `docs/deploy/ports-and-firewall.md`
- `docs/deploy/database-and-backup.md`
- `docs/deploy/go-live-checklist.md`
- `docs/deploy/security-hardening.md`
- `docs/deploy/reverse-proxy-nginx.md`
- `docs/deploy/service-management.md`

---

## 1. 根目录定义

交付包以一个“根目录”作为所有相对路径的基准，本文简称为 `BEACON_ROOT_DIR`。

建议：

- Windows：`C:\Beacon\` 或 `D:\Beacon\`
- Linux：`/opt/beacon/`

启动器与部分运行逻辑支持显式指定根目录：

- 环境变量：`BEACON_ROOT_DIR`

---

## 2. 目录布局（推荐）

### 2.1 Windows（推荐布局）

```
BEACON_ROOT_DIR\
  config.json
  .env                           # 可选（仅用于脚本加载环境变量）
  logs\                          # 运行日志（VideoAnalyzer.py / 组件日志）
  data\
    upload\                      # 告警图片/视频落盘（推荐用 env 覆盖到这里）
    models\                      # 模型目录（推荐用 env 覆盖到这里）
  Admin\
    manage.py
    framework\
    app\
    templates\
    static\
  Analyzer\
    Analyzer.exe                 # 推荐放这里（VideoAnalyzer 会优先找）
  MediaServer\
    bin\
      bin.x86.windows10\
        MediaServer.exe
        config.ini
```

说明：

- `config.json` 固定放根目录（Analyzer/启动器默认 `-f config.json`）。
- `Admin/` 目录可以是源码，也可以是只包含运行所需文件的裁剪版。
- `MediaServer/bin/bin.x86.windows10/` 是启动器默认搜索路径之一（见 `Admin/VideoAnalyzer.py`）。

### 2.2 Linux（推荐布局）

```
BEACON_ROOT_DIR/
  config.json
  .env                           # 可选
  runtime-libs/                  # Linux 运行期 .so（推荐集中放这里）
  logs/
  data/
    upload/
    models/
  Admin/
    manage.py
    framework/
    app/
    templates/
    static/
  Analyzer/
    build/
      Analyzer                   # 推荐：cmake 输出放这里（启动器可识别）
  MediaServer/
    bin/
      bin.x86.gcc9.4/
        MediaServer
        config.ini
```

说明：

- `Analyzer/build/Analyzer` 是启动器默认搜索路径之一。
- `MediaServer/bin/bin.x86.gcc9.4/` 是启动器默认搜索路径之一。
- Linux 交付如采用“运行库随包附带”方案，建议把运行期 `.so` 集中到 `runtime-libs/`，避免散落在多个目录后难以排障。

---

## 3. 关键配置对齐清单（必须）

下面这些必须对齐，否则 UI/接口会出现“服务启动了但功能不可用”的假象。

### 3.1 端口对齐（Admin/Analyzer/MediaServer）

`config.json`（Beacon 统一配置）：

- `adminPort`（默认 `9991`）
- `mediaHttpPort`（默认 `9992`）
- `analyzerPort`（默认 `9993`）
- `mediaRtspPort`（默认 `9994`）
- `mediaRtmpPort`（默认 `9995`）

MediaServer（ZLMediaKit）`config.ini`（实际运行目录下的那份）至少要对齐：

- `[http].port` == `mediaHttpPort`
- `[rtsp].port` == `mediaRtspPort`
- `[rtmp].port` == `mediaRtmpPort`（如启用 RTMP）

建议：

- Linux 不要用 `80/554` 这种特权端口，统一改到 `9992/9994/9995`，不需要 root 就能跑。

### 3.2 `mediaSecret` 对齐（Admin <-> MediaServer）

Admin 会用 ZLMediaKit 的 HTTP API（例如 `/index/api/addStreamProxy`）来管理拉流/推流。

必须对齐：

- `config.json.mediaSecret`
- MediaServer `config.ini [api].secret`

否则表现为：

- Admin 页面能打开，但所有“媒体相关动作”失败（返回权限错误）。

### 3.3 上传目录/模型目录（推荐用 env 固化）

交付包建议把“可变数据”集中到 `BEACON_ROOT_DIR/data/` 下。

推荐用环境变量覆盖（更工业化，不依赖手动修改 json）：

- `BEACON_UPLOAD_DIR=%BEACON_ROOT_DIR%\\data\\upload`（Windows）
- `BEACON_MODEL_DIR=%BEACON_ROOT_DIR%\\data\\models`（Windows）
- `BEACON_UPLOAD_DIR=$BEACON_ROOT_DIR/data/upload`（Linux）
- `BEACON_MODEL_DIR=$BEACON_ROOT_DIR/data/models`（Linux）

对应 `config.json` 里也可以设置：

- `uploadDir`
- `modelDir`

但建议交付以 env 为准，避免“复制 config.json 到不同机器后路径不一致”。

### 3.4 OpenAPI Token（建议生产必配）

Token 统一口径：

- `BEACON_OPEN_API_TOKEN`（环境变量）优先
- 其次 `config.json.openApiToken`

重要行为差异：

- Analyzer：如果 token 为空，默认只绑定到 `127.0.0.1`（更安全，但远程不可调）；如果 token 非空，会绑定 `0.0.0.0` 并要求 token。
- Admin：运维路径（如 `/metrics`）等会要求 token（取决于中间件路径策略与环境开关）。

### 3.5 Linux 运行库交付规则（强烈建议写进交付说明）

Linux 交付最常见的现场故障不是二进制不存在，而是：

- `Analyzer`、`MediaServer` 文件在
- `config.json` 也在
- 但运行期缺 `.so`，或者 `.so` 与机器架构不匹配

建议 Linux 正式交付统一采用下面规则：

1. 所有运行期 `.so` 尽量集中到 `BEACON_ROOT_DIR/runtime-libs/`
2. 交付说明必须写清楚“目标系统 / 架构 / 对应运行库来源”
3. systemd 或 shell 启动前显式设置 `LD_LIBRARY_PATH`

需要集中查看机器类型矩阵、后端最低随包清单、`runtime-libs` 目录示意和现场核对命令时，可直接参见 [../deployment/linux-runtime-libs.md](../deployment/linux-runtime-libs.md)。

#### 3.5.1 按机器类型交付的最低要求

| 目标机器 | 交付说明里至少要写什么 | `runtime-libs/` 里建议至少有 |
|----------|------------------------|------------------------------|
| Ubuntu 20.04 x86_64 | ONNX Runtime `x64`、OpenVINO `ubuntu20 x86_64` | `libonnxruntime.so*`、`libopenvino.so*`、`libtbb.so*` |
| Ubuntu 22.04 x86_64 | ONNX Runtime `x64`、OpenVINO `ubuntu22 x86_64` | `libonnxruntime.so*`、`libopenvino.so*`、`libtbb.so*` |
| Ubuntu 20 arm64 / aarch64 | ONNX Runtime `aarch64`、OpenVINO `ubuntu20 arm64` | `libonnxruntime.so*`、`libopenvino.so*`、`libtbb.so*` |

如果交付方无法明确回答“这套运行库对应哪类机器”，交付包就还不够完整。

#### 3.5.2 常见后端随包运行库最低清单

| 后端场景 | 模型文件 | 随包最低要求 |
|----------|----------|--------------|
| ONNX Runtime | `.onnx` | `libonnxruntime.so*` |
| OpenVINO | `.xml` + `.bin` | `libopenvino.so*`、对应 CPU / GPU plugin `.so`、`libtbb.so*` |
| TensorRT Engine | `.engine` / `.plan` | TensorRT / CUDA 相关 `.so`、插件 `.so` |
| RKNN Compat | `.rknn` | `libbeacon_compat.so`、RKNN 后端插件 `.so`、RKNN SDK runtime |
| Ascend Compat | `.om` | `libbeacon_compat.so`、Ascend 后端插件 `.so`、CANN / Ascend runtime |
| FFmpeg 视频链路 | 任意视频场景 | `libavcodec.so*`、`libavformat.so*`、`libavutil.so*`、`libswscale.so*`、`libswresample.so*` |

#### 3.5.3 建议交付方附一份“运行库清单”

正式交付时，建议附下面这类信息，而不是只写一句“依赖已附带”：

| 项目 | 示例 |
|------|------|
| 目标系统 | `Ubuntu 22.04 x86_64` |
| ONNX Runtime 包来源 | `onnxruntime-linux-x64-1.17.3.tgz` |
| OpenVINO 包来源 | `l_openvino_toolkit_ubuntu22_2024.6.0..._x86_64.tgz` |
| 运行库落位 | `BEACON_ROOT_DIR/runtime-libs/` |
| 是否要求配置 `LD_LIBRARY_PATH` | `是` |
| 是否随包附带 `Admin/venv/` | `是` / `否` |
| 是否随包附带模型文件 | `是` / `否` |

#### 3.5.4 Linux 交付目录最少应长这样

```text
BEACON_ROOT_DIR/
  config.json
  runtime-libs/
    libonnxruntime.so*
    libopenvino.so*
    libtbb.so*
    libavcodec.so*
    libavformat.so*
    libavutil.so*
    libswscale.so*
    libswresample.so*
  Admin/
  Analyzer/
    build/
      Analyzer
    compat/
      libbeacon_compat.so       # 仅兼容后端场景需要
    plugins/
      libtrt_helper.so          # 仅 TensorRT Engine 场景需要
  MediaServer/
    bin/
      bin.x86.gcc9.4/
        MediaServer
        config.ini
```

#### 3.5.5 Linux 启动环境约定

建议把下面这类环境变量写进交付说明或 systemd `EnvironmentFile`：

```bash
BEACON_ROOT_DIR=/opt/beacon
BEACON_UPLOAD_DIR=/opt/beacon/data/upload
BEACON_MODEL_DIR=/opt/beacon/data/models
LD_LIBRARY_PATH=/opt/beacon/runtime-libs:${LD_LIBRARY_PATH}
```

如果采用“完整运行时目录随包附带”而不是纯 `runtime-libs/`，还可按需约定：

```bash
BEACON_ONNXRUNTIME_DIR=/opt/beacon/onnxruntime
BEACON_OPENVINO_RUNTIME_DIR=/opt/beacon/openvino/runtime
```

但从交付稳定性看，更推荐优先保证 `runtime-libs/` 可直接满足运行期动态库搜索。

---

## 4. 启动方式建议

### 4.1 推荐：用启动器守护拉起

当二进制放置在“推荐布局”的位置后，可直接使用：

```bash
python Admin/VideoAnalyzer.py
```

它会按约定搜索：

- MediaServer 二进制与 `config.ini`
- Analyzer 二进制
- 然后拉起 Admin（Django runserver）

### 4.2 交付最小验收（不依赖真实算法）

1. Admin 能打开：

- `http://127.0.0.1:<adminPort>/login`

2. MediaServer API 可访问（带 secret）：

```bash
curl -sS "http://127.0.0.1:<mediaHttpPort>/index/api/getServerConfig?secret=<mediaSecret>" | head
```

3. Analyzer 健康接口可访问：

```bash
curl -sS http://127.0.0.1:<analyzerPort>/api/health
```

如设置了 token，则携带：

```bash
curl -sS -H "Authorization: Bearer <token>" http://127.0.0.1:<analyzerPort>/api/health
```

---

## 5. 交付建议（经验规则）

1. 源码仓库不等于交付包：交付包尽量只包含“运行所需文件 + 证据/文档”，不要把完整构建系统暴露给现场。
2. 所有可变数据进入 `data/`：上传、模型、数据库（如使用 SQLite）都集中到一处，方便备份/迁移/清理。
3. `config.json` 不要写死绝对路径：现场机器路径差异很大，优先用相对路径或 env 注入。
4. `mediaSecret` / token / pepper 都当作密钥：不要用 demo 默认值进入生产。
