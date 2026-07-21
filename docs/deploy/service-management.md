# Beacon 进程托管与服务化（systemd / Windows Service）

本文档用于说明 Beacon 在“运行阶段测试/工业交付”场景下的进程托管方式，重点解决：

- 进程如何长期运行（前台/后台/服务）
- 崩溃如何自动拉起（Restart 策略）
- 日志如何落盘与轮转（便于离线排障）
- 多组件（Admin + Analyzer + MediaServer）如何统一编排

Beacon 常见的两种托管策略：

1. 使用内置启动器 `Admin/VideoAnalyzer.py` 统一拉起三件套（推荐交付型单机部署）。
2. 分别托管 Admin / Analyzer / MediaServer 为独立服务（更贴近标准平台运维，但需要更多编排工作）。

相关文档：

- Edge 全栈从 0 部署：`docs/deploy/edge-full-stack.md`
- 交付包目录结构规范：`docs/deploy/delivery-layout.md`
- 运维手册：`docs/deploy/ops-runbook.md`
- 安全加固：`docs/deploy/security-hardening.md`

---

## 1. 方案 A：使用 `Admin/VideoAnalyzer.py` 统一拉起（推荐）

### 1.1 启动器能力边界

`Admin/VideoAnalyzer.py` 的主要行为：

- 读取 `${BEACON_ROOT_DIR}/config.json`（启动器内部会推导 `ROOT_DIR`）
- 按约定路径寻找并启动：
  - MediaServer（二进制 + `config.ini`）
  - Analyzer（二进制）
  - Admin（`manage.py runserver --noreload` 或 `manage.exe`）
- 端口占用检查、启动失败报错
- 写入单实例锁文件（默认 `<root>/log/startup.lock`），避免重复启动
- 周期性巡检子进程状态（约每 30 秒），发现进程退出会尝试重启
- 日志落盘：默认输出到 `<root>/log/*.log`，按天轮转，默认保留 7 份

适用场景：

- 单机交付（On-Prem / Edge）
- 现场需要“一条命令把三件套跑起来”，并具备最小自愈能力

不适用场景：

- 需要分别水平扩展 Admin/Analyzer/MediaServer 的分布式部署
- 需要精细化资源隔离与独立滚动升级的场景

### 1.2 启动前准备（关键约束）

启动器依赖“目录约定”寻找二进制，建议按 `docs/deploy/delivery-layout.md` 放置：

- `config.json` 位于交付根目录
- Linux 如采用“运行库随包交付”方案，建议把运行期 `.so` 统一放在 `runtime-libs/`
- Analyzer：
  - Windows：`Analyzer/Analyzer.exe` 或 `Analyzer/x64/Release/Analyzer.exe`
  - Linux：`Analyzer/build/Analyzer`（或若干兼容路径）
- MediaServer：
  - Windows：`MediaServer/bin/bin.x86.windows10/MediaServer.exe` + 同目录 `config.ini`
  - Linux：`MediaServer/bin/bin.x86.gcc9.4/MediaServer` + 同目录 `config.ini`（ARM 目录另有约定）

Linux 交付现场建议在启动前至少核对：

```bash
find /opt/beacon/runtime-libs -maxdepth 1 -type f 2>/dev/null | sort | head
find /opt/beacon/Analyzer -maxdepth 3 -type f | head
find /opt/beacon/MediaServer -maxdepth 5 -type f | head
```

如果当前模型依赖 ONNX Runtime / OpenVINO / TBB，建议进一步确认：

```bash
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libonnxruntime.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libopenvino.so*' | head -n 3
find /opt/beacon/runtime-libs -maxdepth 1 -type f -name 'libtbb.so*' | head -n 3
```

机器类型矩阵、后端最低随包清单、`runtime-libs` 标准目录和 `LD_LIBRARY_PATH` 约定已集中整理在 [../deployment/linux-runtime-libs.md](../deployment/linux-runtime-libs.md)。

### 1.3 启动命令（前台运行）

交付根目录执行：

```bash
python Admin/VideoAnalyzer.py
```

说明：

- 启动器会创建/使用 `<root>/log/` 目录用于日志与 lock 文件。
- Admin 默认绑定 `0.0.0.0:<adminPort>`；端口来自 `config.json.adminPort`。

### 1.4 日志与排障要点

启动器日志目录：

- `<root>/log/`（文件名形如 `<timestamp>.log`，按天轮转）

常见失败原因：

- `config.json` 不存在或 JSON 无法解析（编码/格式）
- Analyzer/MediaServer 二进制未放到启动器可识别路径
- 端口被占用（Admin/Analyzer/MediaServer 任一端口）
- 手工分开启动时 MediaServer `secret` 未对齐；统一启动器会为留空配置生成并注入同一个随机值

---

## 2. Linux：systemd 托管（示例）

### 2.1 使用 `VideoAnalyzer.py` 作为单一 systemd 服务

示例文件：`/etc/systemd/system/beacon.service`

```ini
[Unit]
Description=Beacon (Admin + Analyzer + MediaServer) via VideoAnalyzer.py
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/beacon

# 建议使用 Admin 自带虚拟环境（按交付方案决定）
ExecStart=/opt/beacon/Admin/venv/bin/python /opt/beacon/Admin/VideoAnalyzer.py

# 环境变量建议单独放入 beacon.env，由交付侧控制权限和内容
EnvironmentFile=/opt/beacon/beacon.env

Restart=always
RestartSec=3

# 建议限制打开文件数（多路 RTSP/媒体连接时更稳妥）
LimitNOFILE=65535

# 日志建议交由 journald 采集；如需文件日志，可在 .env 中启用 BEACON_LOG_TO_FILE
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

推荐的 `/opt/beacon/beacon.env` 至少包含：

```bash
BEACON_ROOT_DIR=/opt/beacon
BEACON_UPLOAD_DIR=/opt/beacon/data/upload
BEACON_MODEL_DIR=/opt/beacon/data/models
BEACON_OPEN_API_TOKEN=change-me-long-random-token
LD_LIBRARY_PATH=/opt/beacon/runtime-libs:${LD_LIBRARY_PATH}
```

如果交付采用“完整运行时目录随包附带”而不是纯 `runtime-libs/`，再按需补：

```bash
BEACON_ONNXRUNTIME_DIR=/opt/beacon/onnxruntime
BEACON_OPENVINO_RUNTIME_DIR=/opt/beacon/openvino/runtime
```

启用与启动：

```bash
systemctl daemon-reload
grep -n 'LD_LIBRARY_PATH' /opt/beacon/beacon.env
systemctl show beacon.service --property=Environment | tr ' ' '\n' | grep LD_LIBRARY_PATH || true
systemctl enable beacon.service
systemctl start beacon.service
systemctl status beacon.service
journalctl -u beacon.service -f
```

说明：

- 若不使用 `Admin/venv`，可将 `ExecStart` 替换为系统 Python 路径。
- 如交付采用 PyInstaller，可将 `ExecStart` 指向打包后的启动器可执行文件（按交付输出路径调整）。
- 如果 `Analyzer` / `MediaServer` 启动时报 `.so` 缺失，优先检查 `runtime-libs/` 是否齐全，以及 systemd 环境里是否真的带上了 `LD_LIBRARY_PATH`。

### 2.2 端口与防火墙建议

建议仅对外放行 Admin 入口与必要的媒体播放端口；其他端口保持内网可达或仅本机可达。  
安全基线与 IP 策略参考：

- `docs/deploy/security-hardening.md`

---

## 3. Windows：服务化托管（思路）

Windows 现场常见托管方式：

- 方式 A：使用任务计划程序（Task Scheduler）在开机/登录时启动启动器
- 方式 B：使用通用服务包装器（例如 NSSM）将启动器包装为 Windows Service

无论采用哪种方式，建议保持以下约束：

- 工作目录固定为交付根目录（确保相对路径一致）
- 环境变量通过受控方式注入（避免在命令行明文携带 token/secret）
- 日志目录固化到 `<root>/log` 与 `<root>/logs`（便于统一采集/打包）

Windows 下 `Analyzer\3rdparty` 默认目录、DLL 收集规则、前置安装项和常见缺 DLL 报错，可直接参见 [../deployment/windows-runtime-libs.md](../deployment/windows-runtime-libs.md)。

说明：

- 启动器 `Admin/VideoAnalyzer.py` 自带单实例锁文件机制（`startup.lock`），可降低重复启动风险。
- 如需进一步标准化，可在交付侧提供 `start.ps1` / `stop.ps1` 与服务安装脚本，将现场操作固化为 SOP。
