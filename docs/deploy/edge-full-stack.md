# Beacon 从 0 部署（Edge 全栈：Admin + Analyzer + MediaServer）

本文档面向“要在一台机器上把 Beacon 全栈跑起来”的场景，覆盖：

- Admin（Django Web）如何启动
- MediaServer（ZLMediaKit）如何编译/启动，并与 Admin 对齐端口与 `secret`
- Analyzer（C++）如何编译/启动，并与 Admin/MediaServer 对齐配置
- 最小可验证的验收命令（不用先跑真实算法也能判断系统是否起来）

在本仓库 Linux 工作区内，需要已按当前路径和命令验证过的操作手册时，直接看：

- `docs/deployment/local-linux.md`

全栈三件套启动完成后，建议按下述文档进行“可复现的端到端验收”（从 RTSP 到布控到告警/模拟告警）：

- `docs/deploy/e2e-acceptance.md`

运行期配置与运维接口参考：

- `docs/deploy/config-reference.md`
- `docs/deploy/ops-runbook.md`
- `docs/deploy/ports-and-firewall.md`
- `docs/deploy/database-and-backup.md`
- `docs/deploy/observability.md`
- `docs/deploy/go-live-checklist.md`
- `docs/deploy/security-hardening.md`
- `docs/deploy/secrets-and-rotation.md`
- `docs/deploy/reverse-proxy-nginx.md`
- `docs/deploy/service-management.md`
- `docs/deploy/troubleshooting.md`
- `docs/deploy/performance-tuning.md`

如仅需尽快进入“运行阶段测试”（偏 Web/权限/云端/告警工作流），优先采用 Docker Cloud POC：

- `deploy/cloud-saas-v1/compose.yml`
- 见 `docs/deploy/README.md`

---

## 1. 前置准备

### 1.1 一台机器的最小诉求

- CPU：建议 4 核起
- 内存：建议 8GB 起（跑全栈更建议 16GB+）
- 磁盘：建议 SSD，至少 20GB 可用空间（日志 + 上传文件 + 编译产物）
- 网络：可访问 RTSP 源（如后续需做真实拉流/布控）

### 1.2 软件依赖（按角色拆开看）

Admin（Python）：

- Python 3.10–3.12

MediaServer（ZLMediaKit，C++）：

- CMake + 编译器工具链（Linux: gcc/g++; Windows: Visual Studio）
- OpenSSL 等依赖（不同平台略有差异）
- FFmpeg（如需转码/截图等能力）

Analyzer（C++）：

- CMake + 编译器工具链
- OpenCV
- FFmpeg 开发库（`avformat/avcodec/avutil/swscale/swresample`）
- libevent, libcurl, jsoncpp
- onnxruntime
- openvino + tbb

注意：

- 当前仓库的 `Analyzer/CMakeLists.txt` 默认按 Linux “/usr/local 下有依赖”来写（偏工业交付环境）。若依赖安装路径不同，需调整 CMake 或准备对应 SDK。
- 仓库 **不自带模型文件**（`Analyzer/models` 默认不存在）。全栈能启动不等于“能立刻跑检测”，跑算法需另行准备模型并配置算法条目。

---

## 2. 统一的配置来源：`config.json`

Edge 全栈建议把所有组件的端口/目录/密钥都统一到仓库根目录的 `config.json`。

当前仓库根目录已经有一个示例：`config.json`，主要字段包括：

- `adminPort`：Admin Web（默认 `9991`）
- `mediaHttpPort`：MediaServer HTTP（默认 `9992`）
- `analyzerPort`：Analyzer HTTP（默认 `9993`）
- `mediaRtspPort`：MediaServer RTSP（默认 `9994`）
- `mediaRtmpPort`：MediaServer RTMP（默认 `9995`）
- `mediaSecret`：Admin 调用 ZLMediaKit HTTP API 的 `secret`（必须与 MediaServer 的 `config.ini [api].secret` 一致）
- `uploadDir`：告警图片/视频落盘目录（可用相对路径）
- `modelDir`：模型目录（可用相对路径）
- `openApiToken`：开放接口 Token（为空时通常只允许 localhost 调用；生产建议设置强 Token）

与路径相关的关键事实（重要）：

- Analyzer 侧支持用环境变量覆盖路径：`BEACON_UPLOAD_DIR`、`BEACON_MODEL_DIR`。
- Analyzer 侧的相对路径是 **相对 `config.json` 所在目录** 解析的。

建议至少确保这些目录存在：

- `Admin/static/upload/` 或配置的 `uploadDir`
- `Analyzer/models/` 或配置的 `modelDir`

---

## 3. 启动顺序（推荐）

推荐的启动顺序：

1. MediaServer（先起来，便于 Admin 页面测试播放器/流地址拼接）
2. Analyzer（先起来，便于 Admin 调用 Analyzer API）
3. Admin（最后起来）

原因：Admin 页面很多动作会去探测 Analyzer/MediaServer 状态或拼接 URL。

---

## 4. MediaServer（ZLMediaKit）从 0 编译与启动

仓库中的 ZLMediaKit 源码在：`MediaServer/source/`。

### 4.1 Linux（推荐）编译示例

```bash
cd MediaServer/source
mkdir -p build
cd build

# 具体编译开关请按需求调整；最保守做法是先跑最小 Release 编译
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j
```

ZLMediaKit 的构建产物通常会在类似目录（示例）：

- `MediaServer/source/release/linux/Release/MediaServer`
- `MediaServer/source/release/linux/Release/config.ini`

说明：`config.ini` 文件头也写明了它会被拷贝到 `release/<platform>/<build_type>/` 下，并且 MediaServer 默认加载同目录下的 `config.ini`。

### 4.2 配置端口与 `secret`（必须对齐 Beacon）

需修改 MediaServer 实际运行目录下的 `config.ini`，至少对齐下面三件事：

1. `[api].secret` 必须等于 `config.json` 里的 `mediaSecret`
2. `[http].port` 必须等于 `config.json` 里的 `mediaHttpPort`（默认 9992）
3. `[rtsp].port` 必须等于 `config.json` 里的 `mediaRtspPort`（默认 9994）

可能还需对齐：

- `[rtmp].port` 对齐 `mediaRtmpPort`（默认 9995）
- `[ffmpeg].bin` 指向实际环境中的 `ffmpeg` 路径（Linux 常见为 `/usr/bin/ffmpeg`）

### 4.3 启动 MediaServer

在 `MediaServer` 二进制所在目录执行：

```bash
./MediaServer
```

如需显式指定配置文件：

```bash
./MediaServer -c ./config.ini
```

### 4.4 最小验收（MediaServer）

用 `mediaSecret` 调用 ZLMediaKit API 验证它已启动：

```bash
curl -sS "http://127.0.0.1:9992/index/api/getServerConfig?secret=<mediaSecret>" | head
```

期望：返回 JSON，且包含 `code: 0`（ZLMediaKit 约定）。

---

## 5. Analyzer 从 0 编译与启动

### 5.1 Linux：CMake 编译（依赖已在 /usr/local 的工业环境）

```bash
cmake -S Analyzer -B Analyzer/build -DCMAKE_BUILD_TYPE=Release
cmake --build Analyzer/build -j
```

编译成功后可执行文件通常在：

- `Analyzer/build/Analyzer`

### 5.2 Windows：Visual Studio 编译（建议）

用 Visual Studio 2019+ 打开：

- `Analyzer/Analyzer.sln`

选择：

- `Release` + `x64`

编译后请确认生成的 `Analyzer.exe` 位置，Beacon 的启动器（`Admin/VideoAnalyzer.py`）会优先寻找：

- `Analyzer/Analyzer.exe`
- `Analyzer/x64/Release/Analyzer.exe`

如果 VS 的输出目录不同，建议把最终 exe 复制到上述两者之一的位置（让自动启动器能找到）。

### 5.3 启动 Analyzer

Linux（示例）：

```bash
./Analyzer/build/Analyzer -f config.json
```

Windows（示例）：

```powershell
Analyzer\\x64\\Release\\Analyzer.exe -f config.json
```

### 5.4 最小验收（Analyzer）

默认情况下（`openApiToken` 为空），Analyzer 只监听 `127.0.0.1`，并允许本机不带 token 调用。

```bash
curl -sS http://127.0.0.1:9993/api/health
```

期望：返回 JSON，且包含 `code: 1000`。

如设置了 `openApiToken`（或环境变量 `BEACON_OPEN_API_TOKEN`），Analyzer 会绑定到 `0.0.0.0` 且要求 token：

```bash
curl -sS -H "Authorization: Bearer <token>" http://127.0.0.1:9993/api/health
```

---

## 6. Admin（Django）从 0 启动

### 6.1 创建 Python 虚拟环境 + 安装依赖

Windows：

```powershell
cd Admin
python -m venv venv
venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
```

Linux：

```bash
cd Admin
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-linux.txt
```

### 6.2 迁移数据库

```bash
python manage.py migrate --noinput
```

如果这是全新库，还需要创建管理员：

```bash
python manage.py createsuperuser
```

### 6.3 启动 Admin

```bash
python manage.py runserver 0.0.0.0:9991
```

浏览器访问：

- `http://127.0.0.1:9991/login`

---

## 7. 可选：用启动器一键拉起（`Admin/VideoAnalyzer.py`）

仓库里有一个进程守护式启动器：`Admin/VideoAnalyzer.py`。

它会：

- 读取根目录 `config.json`
- 启动 MediaServer / Analyzer / Admin（如果它能找到对应二进制）
- 做端口占用检查
- 进程挂掉会尝试重启（有最小重启间隔）

直接运行（前提：已将 MediaServer/Analyzer 的二进制放在启动器可识别的路径）：

```bash
python Admin/VideoAnalyzer.py
```

启动器寻找的关键路径（用于对齐产物位置）：

- MediaServer（Linux）：`MediaServer/bin/bin.x86.gcc9.4/MediaServer` + 同目录 `config.ini`
- MediaServer（Windows）：`MediaServer/bin/bin.x86.windows10/MediaServer.exe` 或 `MediaServer/MediaServer.exe`
- Analyzer（Linux）：`Analyzer/build/Analyzer`（推荐 CMake 放这里）
- Analyzer（Windows）：`Analyzer/x64/Release/Analyzer.exe` 或 `Analyzer/Analyzer.exe`

---

## 8. 常见问题（从 0 部署最容易踩的坑）

1. MediaServer 能启动，但 Admin 里所有媒体 API 调用都失败
原因通常是 `mediaSecret` 没对齐：`config.json.mediaSecret` 必须等于 ZLMediaKit `config.ini [api].secret`。

2. MediaServer 端口没改，默认在 80/554 导致权限问题
Linux 下 80/554 需要 root 权限；建议改成 `9992/9994` 与 `config.json` 一致。

3. Analyzer 启动后 `curl /api/health` 401
如已设置 `openApiToken` 或 `BEACON_OPEN_API_TOKEN`，需携带：
`Authorization: Bearer <token>` 或 `X-Beacon-Token: <token>`。

4. Analyzer 编译失败
多数是依赖库路径不匹配。`Analyzer/CMakeLists.txt` 假定依赖位于 `/usr/local/...`，需准备对应 SDK 或调整 CMake。

5. “全栈都起来了，但没有任何算法可用”
仓库默认不含模型文件（`Analyzer/models` 不存在）。需按交付包准备模型目录，并在 Admin 中配置/导入算法条目。
