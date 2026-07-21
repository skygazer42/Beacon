# Beacon Edge 端到端验收（E2E）：从 RTSP 到布控到告警

本文档面向“项目进入运行阶段测试”的场景，目标是在 **1 台机器**（或同一局域网内的几台机器）上完成 Beacon 关键链路验收，并具备问题定位手段：

- 准备一个 RTSP/RTMP/SRT/HTTP 拉流源（优先 RTSP）
- 在 Admin 里添加 Stream（摄像头/视频源）
- 让 MediaServer（ZLMediaKit）把 Stream 拉进来（转发/代理）
- 验证播放（网页播放器 / ffplay / VLC）
- 创建 Control（布控）并启动
- 验证 Analyzer 已接到控制任务
- （可选）验证告警：真实算法触发，或用 OpenAPI 模拟一条外部告警

如尚未完成全栈启动，先参考：

- Edge 全栈从 0 部署：`docs/deploy/edge-full-stack.md`
- 交付包目录结构约定：`docs/deploy/delivery-layout.md`

---

## 0. 验收“通过”的定义（避免误会）

Beacon 的端到端验收可分为三层，可按资源条件选择验收层级：

### L0：服务存活 + 基础连通
- Admin 能打开并登录
- MediaServer API 能访问（带 `secret`）
- Analyzer `/api/health` 能访问（如配置 token 则带 token）

### L1：真实视频链路跑通（推荐最低门槛）
- Stream 能添加成功
- `openAddStreamProxy` 能成功（MediaServer 拉到流）
- 能在 Admin 播放器 / ffplay / VLC 播放到 MediaServer 输出的地址
- Control 能创建并启动
- Analyzer `/api/controls` 能看到该 control 在运行

### L2：算法触发告警（最完整，但依赖模型/算法）
- Analyzer 已加载相应算法（模型文件、设备等就绪）
- 布控运行后能生成告警（在 Admin 的告警列表可见，并可打开图片/视频）

说明：

- 仓库默认 **不包含模型文件**（例如 `Analyzer/models/` 可能为空或不存在）。在缺少模型的情况下，L2 通常不可达。
- 即使暂无法完成 L2，也应优先跑通 L1：用于证明“流媒体 + 布控调度 + 接口链路”已连通。
- 如需验收告警页面/权限/存储链路但暂缺模型，可使用本文档的“模拟外部告警”步骤验证告警工作流。

---

## 1. 环境变量与参数（建议复制后统一调整）

下述命令默认将端口、token、secret 统一为一组变量，建议在执行前先设置变量。

### 1.1 Linux / macOS（bash）

```bash
export ADMIN="http://127.0.0.1:9991"
export MEDIA_HTTP="http://127.0.0.1:9992"
export MEDIA_RTSP_HOST="127.0.0.1"
export MEDIA_RTSP_PORT="9994"
export ANALYZER="http://127.0.0.1:9993"

# Admin/Analyzer OpenAPI Token（未启用 token 时可暂时留空；测试阶段建议启用）
export TOKEN="<your-open-api-token>"

# ZLMediaKit API secret（必须与 config.ini 的 [api].secret 一致）
export MEDIA_SECRET="change-me-media-secret"
```

### 1.2 Windows PowerShell

注意：PowerShell 里 `curl` 通常是 `Invoke-WebRequest` 的别名，参数不兼容。本文档在 Windows 下统一使用 `curl.exe`。

```powershell
$ADMIN = "http://127.0.0.1:9991"
$MEDIA_HTTP = "http://127.0.0.1:9992"
$MEDIA_RTSP_HOST = "127.0.0.1"
$MEDIA_RTSP_PORT = "9994"
$ANALYZER = "http://127.0.0.1:9993"

$TOKEN = "<your-open-api-token>"
$MEDIA_SECRET = "change-me-media-secret"
```

### 1.3 Token Header 规则（强烈建议统一）

Admin 侧中间件支持两种方式传 token（建议用第一种）：

- `Authorization: Bearer <token>`（推荐）
- `X-Beacon-Token: <token>`（legacy，Analyzer 侧也支持）

为降低 401 排查成本：建议验收命令统一携带 token（即使当前认为未启用）。

### 1.4 从 `config.json` 快速确认端口/secret/token（建议）

如不确定端口、`mediaSecret`、token 的具体取值，优先以交付根目录的 `config.json` 为准（Edge 全栈文档推荐所有组件都对齐它）。

Linux/macOS：

```bash
python3 - <<'PY'
import json
from pathlib import Path

cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
keys = [
  "adminPort", "mediaHttpPort", "mediaRtspPort", "analyzerPort",
  "mediaSecret", "openApiToken",
  "uploadDir", "modelDir",
]
print({k: cfg.get(k) for k in keys})
PY
```

Windows PowerShell：

```powershell
python -c "import json; print(json.load(open('config.json','r',encoding='utf-8')))"
```

重点核对：

- `adminPort / mediaHttpPort / mediaRtspPort / analyzerPort` 是否与实际运行端口一致
- `mediaSecret` 是否与 `MediaServer/config.ini` 的 `[api].secret` 一致
- `openApiToken`（或环境变量 `BEACON_OPEN_API_TOKEN`）是否与 OpenAPI 调用时携带的 token 一致

---

## 2. L0：三大服务预检（5 分钟内判断“是不是起得来”）

### 2.1 Admin（Web/UI）

浏览器打开：

- `${ADMIN}/login`

如使用 Cloud POC（docker compose），使用 `.env` 中显式配置的 bootstrap 管理员账号。

### 2.2 MediaServer（ZLMediaKit）API 连通

ZLMediaKit 的 API 通常是 `code == 0` 表示成功。

Linux/macOS：
```bash
curl -sS "${MEDIA_HTTP}/index/api/getServerConfig?secret=${MEDIA_SECRET}" | head
```

Windows PowerShell：
```powershell
curl.exe -sS "$MEDIA_HTTP/index/api/getServerConfig?secret=$MEDIA_SECRET" | Select-Object -First 5
```

预期：

- 返回 JSON
- 包含 `code: 0`（或 `"code":0`）一类字段

如果失败，优先排查：

- `MEDIA_SECRET` 是否与 `MediaServer/config.ini` 的 `[api].secret` 对齐
- `mediaHttpPort` 是否对齐（`config.json` vs `config.ini [http].port`）
- 防火墙/端口占用

### 2.3 Analyzer 健康检查

无 token 场景：
```bash
curl -sS "${ANALYZER}/api/health"
```

有 token 场景（推荐）：
```bash
curl -sS -H "Authorization: Bearer ${TOKEN}" "${ANALYZER}/api/health"
```

如遇 401 且 token 已确认一致，可改用 legacy header（部分环境仅开启该口径）：

```bash
curl -sS -H "X-Beacon-Token: ${TOKEN}" "${ANALYZER}/api/health"
```

预期：返回 JSON 且包含 `code: 1000` 之类的成功码。

常见坑：

- **Analyzer 的绑定地址与 token 强相关**：当 token 为空时，Analyzer 可能只绑定 `127.0.0.1`；当 token 非空时会绑定 `0.0.0.0` 且强制校验 token。跨机器访问时需特别注意这一点。

---

## 3. 准备可用的 RTSP 源（必须先确保源可访问）

Beacon 的 Stream `pull_stream_url` 支持多种协议（代码中校验前缀），但验收最稳定的是 RTSP。

可选方案（按优先级从高到低）：

1. 用真实摄像头/硬盘录像机（NVR）的 RTSP
2. 用仓库自带的 RTSP 模拟器（Linux 环境）
3. 在 Windows 下用 WSL2 或 Docker 起一个 RTSP 源（或直接换真实摄像头）

### 3.1 选择 A：真实摄像头 RTSP（最贴近现场）

RTSP URL 示例：

```text
rtsp://<user>:<pass>@<camera-ip>:554/<path>
```

验证 RTSP 源本身是否可用（强烈建议先在 Beacon 之外验证）：

```bash
ffprobe -hide_banner -rtsp_transport tcp -i "rtsp://..."
```

如环境未安装 `ffprobe/ffmpeg`，可使用 VLC 完成验证。

### 3.2 选择 B：Linux 下运行仓库 RTSP 模拟器（推荐做“最小可复现”）

仓库提供了 `tools/rtsp_simulator.py`，它会：

- 下载一个 `mediamtx`（注意：当前脚本下载的是 linux_amd64 版本）
- 用 `ffmpeg` 推一个 `testsrc` 到 mediamtx
- 产出一个本地 RTSP 地址，用于后续 Stream 添加

前置依赖：

- `python3`
- `ffmpeg`（包含 `ffmpeg` 与 `ffprobe`）

运行（示例）：

```bash
python3 tools/rtsp_simulator.py
```

运行成功后会输出一个 RTSP URL（以脚本输出为准）。例如：

```text
rtsp://127.0.0.1:8554/test
```

这就是后续 `pull_stream_url` 要用的源地址。

### 3.3 选择 C：Windows 下怎么办（重要）

当前 `tools/rtsp_simulator.py` 下载并运行的是 **linux_amd64 的 mediamtx**，所以在纯 Windows 下直接运行可能会遇到类似：

- `WinError 193`（不是有效的 Win32 应用程序）

可行替代方案：

- 方案 C1：在 WSL2 里运行 `tools/rtsp_simulator.py`，然后让 Windows 上的 MediaServer 去拉这个 RTSP
  - 关键点：确保 RTSP 监听在 `0.0.0.0`，并且 Windows 能访问到 WSL2 的端口（部分系统支持 `localhost` 转发，部分需要用 WSL2 的 IP）
- 方案 C2：用 Docker 起一个 RTSP 源（比如 mediamtx 容器）并映射端口到宿主机
- 方案 C3：直接用真实摄像头 RTSP（最省时间）

本文档不限定具体方案；验收前置条件是获得一个 **“MediaServer 所在机器可访问”的 RTSP URL**。

---

## 4. 添加 Stream（把 RTSP 源登记进 Admin）

可通过 UI 或 OpenAPI 完成操作。验收场景推荐使用 OpenAPI（可复制、可自动化、可记录）。

### 4.1 UI 路径

浏览器打开：

- `${ADMIN}/stream/index`
- 点击添加，填入：
  - 编号（code）
  - 分组（app，默认 `live`）
  - 拉流地址（pull_stream_url）
  - 昵称（nickname）

### 4.2 OpenAPI：`POST /stream/openAdd`

接口：

- `POST ${ADMIN}/stream/openAdd`

参数（最小集）：

- `code`：摄像头编号（建议只用 `[a-zA-Z0-9._-]` 这种安全字符）
- `app`：分组（可省略，默认 `live`）
- `pull_stream_url`：拉流地址（建议 RTSP）
- `pull_stream_type`：拉流类型（一般 1）
- `nickname`：展示用名称（必填）

Linux/macOS 示例（JSON body）：

```bash
curl -sS -X POST "${ADMIN}/stream/openAdd" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "cam-e2e-1",
    "app": "live",
    "pull_stream_url": "rtsp://127.0.0.1:8554/test",
    "pull_stream_type": 1,
    "nickname": "E2E Cam 1"
  }'
```

Windows PowerShell 示例：

```powershell
curl.exe -sS -X POST "$ADMIN/stream/openAdd" `
  -H "Authorization: Bearer $TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"code":"cam-e2e-1","app":"live","pull_stream_url":"rtsp://127.0.0.1:8554/test","pull_stream_type":1,"nickname":"E2E Cam 1"}'
```

预期响应：

- 成功：`{"code":1000,"msg":"success",...}`
- 失败常见原因：
  - `code` 重复
  - URL 前缀不在允许列表（必须是 rtsp/rtmp/http/https/srt 等支持的）
  - nickname 为空

### 4.3 查询 Stream（确认新增 Stream 已落库）

接口：

- `GET ${ADMIN}/stream/openGet?code=<stream_code>`

示例：

```bash
curl -sS "${ADMIN}/stream/openGet?code=cam-e2e-1" \
  -H "Authorization: Bearer ${TOKEN}"
```

关注字段：

- `data.pull_stream_url`：是否为预期 RTSP
- `data.forward_state`：`0` 表示未转发，`1` 表示已转发（下一步会变为 1）

---

## 5. 让 MediaServer 拉流（转发/代理）：`POST /stream/openAddStreamProxy`

创建 Stream 仅登记数据，不代表 MediaServer 已在拉流。

要让 MediaServer 实际去拉 `pull_stream_url` 并对外提供播放地址，需要调用：

- `POST ${ADMIN}/stream/openAddStreamProxy`
- body: `{"code":"<stream_code>"}`

示例：

```bash
curl -sS -X POST "${ADMIN}/stream/openAddStreamProxy" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"cam-e2e-1"}'
```

预期：

- `code == 1000`

然后再次查询：

```bash
curl -sS "${ADMIN}/stream/openGet?code=cam-e2e-1" \
  -H "Authorization: Bearer ${TOKEN}"
```

预期：

- `data.forward_state == 1`

### 5.1 从 MediaServer 侧确认“流真的在”

调用 ZLMediaKit：

```bash
curl -sS "${MEDIA_HTTP}/index/api/getMediaList?secret=${MEDIA_SECRET}" | head
```

预期在返回中可看到 `app=live`、`stream=cam-e2e-1` 相关条目（字段名以 ZLM 返回为准）。

如果 `openAddStreamProxy` 失败，优先排查：

- `mediaSecret` 不一致导致 Admin 调 ZLM API 失败
- MediaServer 无法访问 RTSP 源（网络/防火墙/用户名密码/端口）
- RTSP 源只支持 UDP，但网络不通（可尝试改源或改拉流策略；ZLM 默认 `rtp_type=0` 即 TCP）

---

## 6. 播放验证（必须确认能看到画面/码流，才能继续布控）

### 6.1 Admin 自带播放器页（最快）

打开：

```text
${ADMIN}/stream/player?app=live&name=cam-e2e-1
```

如果页面提示“请先选择一个在线视频流”，通常表示：

- 尚未成功调用 `openAddStreamProxy`
- 或者流不在线（MediaServer 没拉到源）

### 6.2 用 ffplay / VLC 验证（排除前端问题）

MediaServer 输出 RTSP 地址通常形如：

```text
rtsp://${MEDIA_RTSP_HOST}:${MEDIA_RTSP_PORT}/live/cam-e2e-1
```

ffplay（低延迟倾向）：

```bash
ffplay -hide_banner -fflags nobuffer -flags low_delay -rtsp_transport tcp \
  "rtsp://${MEDIA_RTSP_HOST}:${MEDIA_RTSP_PORT}/live/cam-e2e-1"
```

如果 ffplay 能播，但网页播不了，优先排查：

- 浏览器协议支持（HLS/FLV/WebRTC 等）
- WebSocket / HTTP 端口是否可达（例如 WS-FLV 需要 `mediaHttpPort`）
- 反向代理（Nginx）是否正确转发了 ws

---

## 7. 创建 Control（布控）

控制（Control）是“某个算法在某个 Stream 上跑”的配置项。

同样可通过 UI 或 OpenAPI 完成操作。验收场景建议使用 OpenAPI（最可复现）。

### 7.1 UI 路径

打开：

- `${ADMIN}/controls`
- 点击添加（`/control/add`）

至少需要选择：

- Stream（通常来自 MediaServer 的在线流列表）
- Algorithm（算法条目）
- Object（目标类别）

注意：UI 依赖算法条目已存在，如尚未导入/创建算法条目，需先完成算法配置。

### 7.2 OpenAPI：`POST /api/postAddControl`（最推荐的可复制路径）

接口：

- `POST ${ADMIN}/api/postAddControl`

根据仓库测试用例，最小 payload 可包含：

- `controlCode`：布控编号
- `streamApp`：`live`
- `streamName`：`cam-e2e-1`
- `streamVideo`：一般填 `"video"`
- `streamAudio`：一般填 `"audio"`
- `algorithmCode`：算法编号（示例 `"alg-1"`）
- `objectCode`：目标类别（示例 `"person"`）

示例：

```bash
curl -sS -X POST "${ADMIN}/api/postAddControl" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "controlCode=ctrl-e2e-1" \
  --data-urlencode "streamApp=live" \
  --data-urlencode "streamName=cam-e2e-1" \
  --data-urlencode "streamVideo=video" \
  --data-urlencode "streamAudio=audio" \
  --data-urlencode "algorithmCode=alg-1" \
  --data-urlencode "objectCode=person"
```

说明：

- 这个接口设计用于“集群/机器调用”，即使没有 web session 也可以创建（`user_id=0`）。
- 很多参数都有默认值（比如 `minInterval=180`、`classThresh=0.5`、`overlapThresh=0.5`），可先采用最小化 payload，待链路稳定后再细调。

创建成功后，建议用 UI 或 OpenAPI 列表确认它存在：

```bash
curl -sS "${ADMIN}/control/openIndex?p=1&ps=10&search_text=ctrl-e2e-1" \
  -H "Authorization: Bearer ${TOKEN}"
```

返回里的 `data` 结构是一个二维数组（历史兼容原因），需在其中找到 `code == ctrl-e2e-1` 的条目。

---

## 8. 启动 Control：`POST /control/openStartControl`

接口：

- `POST ${ADMIN}/control/openStartControl`
- body: `{"code":"<control_code>"}`

示例：

```bash
curl -sS -X POST "${ADMIN}/control/openStartControl" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"ctrl-e2e-1"}'
```

预期：

- `code == 1000`

### 8.1 验证 Analyzer 已经接到任务

Analyzer 提供了控制列表接口：

- `POST ${ANALYZER}/api/controls`

示例（无额外过滤，拉全量）：

```bash
curl -sS -X POST "${ANALYZER}/api/controls" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

如遇 401，将 header 替换为：

```bash
curl -sS -X POST "${ANALYZER}/api/controls" \
  -H "X-Beacon-Token: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

预期：返回 JSON，`code == 1000`，并且在 `data` 里能找到 `code == ctrl-e2e-1`。

如果 Admin 返回启动成功，但 Analyzer `controls` 看不到：

- 检查 Admin 的 Analyzer 配置（host/port/token）
- 检查 Analyzer 是否正在运行、端口是否对齐
- 查看 Admin 日志里是否有调用 Analyzer 失败信息

---

## 9. 告警验收（两种路径）

### 9.1 路径 A：真实算法触发（L2）

该路径依赖以下条件：

- 可用模型文件（ONNX/OpenVINO 等）
- Analyzer 已加载算法（可能需要通过 Admin 的算法管理页面或 OpenAPI 调用加载）
- 布控参数合理（例如阈值/间隔/区域等）

当布控在运行时，告警应出现在：

- `${ADMIN}/alarms`

如果没有告警：

- 先确保 L1 全通（能看到视频，control 在 Analyzer 中 running）
- 再看算法加载状态（Analyzer `GET /api/algorithm/list` 一类接口）
- 最后排查模型路径/设备/阈值/输入尺寸等算法侧配置

### 9.2 路径 B：没有模型也要验收告警页面（推荐补齐“工作流验收”）

Admin 提供了一个 OpenAPI：`POST /alarm/openAdd`，用于外部系统上报告警。

它要求：

- `control_code` 必须存在（因此至少需先创建一个 control）
- `image_path` / `video_path` 可选（且必须在 uploadDir 下，并以 `alarm/` 开头）

最小化创建一条告警（不带图片/视频）：

```bash
curl -sS -X POST "${ADMIN}/alarm/openAdd" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "control_code": "ctrl-e2e-1",
    "desc": "E2E 外部告警（模拟）"
  }'
```

预期：

- 返回 `code == 1000`
- 在 `${ADMIN}/alarms` 能看到新告警

如需连同图片一起验收存储链路：

1. 先把一张图片放到 `uploadDir/alarm/<some-dir>/snapshot.jpg`
2. 用相对路径上报：`image_path: "alarm/<some-dir>/snapshot.jpg"`

注意：接口会做路径安全校验，必须以 `alarm/` 开头，并且必须落在配置的 `uploadDir` 下。

---

## 10. 清理（使测试环境可重复）

建议按“先停布控，再停转发，再删数据”的顺序。

### 10.1 停止 Control

```bash
curl -sS -X POST "${ADMIN}/control/openStopControl" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"ctrl-e2e-1"}'
```

### 10.2 （可选）删除 Control（会清理关联告警与落盘文件，谨慎）

如用于“反复重跑验收”，且该 control 仅用于测试，建议删除，避免后续列表里堆满历史数据。

注意：该接口会 best-effort 取消 Analyzer 侧运行，并删除该 control 对应的告警记录及相关文件（如果有落盘）。

```bash
curl -sS -X POST "${ADMIN}/control/openDel" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"ctrl-e2e-1"}'
```

### 10.3 关闭 Stream 转发

```bash
curl -sS -X POST "${ADMIN}/stream/openDelStreamProxy" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"cam-e2e-1"}'
```

### 10.4 删除 Stream

```bash
curl -sS -X POST "${ADMIN}/stream/openDel" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"cam-e2e-1","handle":"one"}'
```

如用于“反复重跑验收”，且确认库内均为测试数据，可用 `handle=all` 清空（谨慎）：

```bash
curl -sS -X POST "${ADMIN}/stream/openDel" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"handle":"all"}'
```

---

## 11. 常见排障（按症状定位）

### 11.1 所有 OpenAPI 都 401/403

 排查顺序：

1. 是否携带 header：
   - `Authorization: Bearer <token>`
2. token 是否与服务端一致：
   - 环境变量 `BEACON_OPEN_API_TOKEN`（优先）
   - `config.json.openApiToken`
3. 是否打开强制校验：
   - `BEACON_REQUIRE_OPEN_API_TOKEN=1`
4. 是否为“跨机器调用”：
   - 当 `openApiToken` 为空（且未配置 DB ApiKey）时，Admin 默认只放行 loopback（`127.0.0.1` / `::1`），跨机器请求会被拒绝。

建议：测试阶段固定 token，并写入验收脚本，减少“时好时坏”的误判。

### 11.2 `openAddStreamProxy` 失败，但 `openAdd` 成功

典型原因：

- `mediaSecret` 不一致，导致 Admin 调 ZLM `addStreamProxy` 失败
- MediaServer 拉不到 RTSP 源（网络不通/账号密码错误/源不在线）
- RTSP 源只支持 UDP，或者存在 NAT/防火墙阻断

验证方式：

- 直接在 MediaServer 机器上用 `ffprobe` 拉源（绕开 Beacon）：
  - `ffprobe -rtsp_transport tcp -i rtsp://...`
- 看 ZLM `getMediaList` 是否出现该 stream

### 11.3 能拉到流，但网页播放器不出画面

优先用 ffplay / VLC 验证 RTSP 输出，确认流媒体侧 OK。

然后再排查前端：

- WebSocket 端口是否可达（WS-FLV/WS-MP4）
- HLS 是否开启/可达（`/live/<name>/hls.m3u8`）
- WebRTC 是否需要 STUN/TURN（取决于网络环境）

### 11.4 Analyzer 能 health，但 control 启动后没有效果

先做最小化验证：

1. Admin `control/openIndex` 能看到 control
2. Analyzer `/api/controls` 能看到 control running

如果 (2) 看不到：

- Admin 到 Analyzer 的 host/port/token 未对齐
- Analyzer 未运行或端口被占用

如果 (2) 能看到，但没有告警：

- 算法/模型未加载（仓库默认可能没有模型）
- 阈值/区域/间隔参数不合理
- 输入流编码/分辨率与模型预期不匹配

---

## 12. 建议将本验收流程固化为“可复跑脚本”

在首次跑通 L1 后，建议将关键请求整理成脚本（bash 或 PowerShell），做到：

- 1 条命令完成：add stream -> add proxy -> add control -> start control
- 1 条命令完成：stop control -> del proxy -> del stream

可显著提升回归/联调效率，并减少“人为操作差异”。
