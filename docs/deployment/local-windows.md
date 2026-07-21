---
title: Windows 本机开发
icon: material/monitor
---

# Windows 本机开发

本文面向 **开发者**，目标是在 Windows 本机用源码完成后台、前端和视频分析链路联调。

本页只讲开发环境怎么跑。交付包下载、构建素材、打包清单请看 [Windows 构建与打包](build-and-package-windows.md)；客户机器安装请看 [Windows 用户部署](windows.md)；DLL、`.lib`、`Analyzer\3rdparty` 细节请看 [Windows 运行库参考](windows-runtime-libs.md)。

---

## 1. 先选开发场景

不同开发任务不需要一开始就跑完整三件套。

| 场景 | 建议做法 |
|------|----------|
| 后台页面、接口、权限逻辑 | 只启动 `Admin` |
| React 页面改动 | 启动 `Admin`，改完后重新构建前端静态资源 |
| 视频流、布控、告警联调 | 启动 `Admin`、`MediaServer`、`Analyzer` |
| C++ 原生程序改动 | 进入 VS Developer Shell，从源码编译 `Analyzer.exe` 或 `MediaServer.exe` |
| 客户部署验收 | 不走本页，使用 [Windows 用户部署](windows.md) 的根目录 `VideoAnalyzer.exe` |

开发时不要直接在最终用户 ZIP 解压目录里改源码。最终用户包是运行目录，不是源码工作区。

---

## 2. 安装基础工具

建议先准备：

| 工具 | 用途 | 备注 |
|------|------|------|
| Python 3.10–3.12 | `Admin` 本机 venv | 使用当前 `requirements-windows.txt` 从空 venv 安装 |
| Git | 拉源码 | 任意可用版本 |
| Node.js 18+ / npm 9+ | 前端构建 | 只改后台接口时可先不装 |
| Visual Studio 2019+ / 2022 | 编译 `Analyzer.exe` | 需要 C++ 桌面开发工作负载 |
| CMake 3.16+ | 编译 `MediaServer` | 仅原生构建需要 |
| Visual C++ Redistributable 2019+ | 运行原生 EXE | 最终包已附 `VC_redist.x64.exe` |
| FFmpeg 命令行 | 调试视频链路 | Analyzer 自身依赖 DLL 随包处理，命令行 FFmpeg 只用于额外排障 |

快速确认：

```powershell
python --version
git --version
node --version
npm --version
cmake --version
```

如果 PowerShell 阻止 venv 激活脚本，可在当前终端临时放开：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

---

## 3. 拉源码并启动 Admin

下面统一用 `C:\Work\Beacon` 作为源码目录。

```powershell
git clone <your-beacon-repo-url> C:\Work\Beacon
Set-Location C:\Work\Beacon\Admin

python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
python manage.py migrate --noinput
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:9991
```

浏览器打开：

```text
http://127.0.0.1:9991/login
```

新数据库没有预置账号；`createsuperuser` 只需在首次创建管理员时执行。只做后台页面或接口开发时，跑到这里即可。此时不需要 `Analyzer.exe`、`MediaServer.exe`、`Analyzer\3rdparty`。

---

## 4. 前端改动后的构建

未改 `Admin\frontend\` 时可跳过。

```powershell
Set-Location C:\Work\Beacon\Admin\frontend
npm ci
npm run build
Set-Location C:\Work\Beacon
```

构建产物会进入：

```text
Admin\static\app-shell\
```

然后重启 `Admin`，再刷新页面确认改动。

---

## 5. 准备 Analyzer 和 MediaServer

全栈联调才需要这一步。

### 5.1 推荐路径：先用已有 Windows 二进制联调

Windows 开发最实际的做法，是先用已有 `Analyzer.exe` 和 `MediaServer.exe` 验证业务链路，不要一开始同时解决源码编译、第三方 SDK 和业务问题。

启动器和示例命令优先识别这些位置：

| 组件 | 推荐位置 |
|------|----------|
| Analyzer | `Analyzer\Analyzer.exe` 或 `Analyzer\x64\Release\Analyzer.exe` |
| MediaServer | `MediaServer\bin\bin.x86.windows10\MediaServer.exe` 或 `MediaServer\MediaServer.exe` |
| 模型 | `data\models\` |
| 上传/截图/录像 | `data\upload\` |

如果本机没有这些二进制或模型素材，先按 [Windows 构建与打包](build-and-package-windows.md) 准备 BXC v3.52 Windows 素材包，或直接从源码构建。

### 5.2 从源码编译 Analyzer

当前源码仓库通常不自带完整的 `Analyzer\3rdparty\` Windows SDK 目录。编译前必须先补齐头文件、`.lib` 和运行 DLL；具体清单见 [Windows 运行库参考](windows-runtime-libs.md)。

在 **Developer PowerShell for VS** 或 **x64 Native Tools Command Prompt for VS** 中执行：

```powershell
$dev = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
cmd /c "call `"$dev`" -arch=x64 -host_arch=x64 && msbuild Analyzer\Analyzer.sln /m /p:Configuration=Release /p:Platform=x64 /t:Rebuild /v:minimal"
```

本机 2026-05-04 实测产物：

```text
Analyzer\x64\Release\Analyzer.exe
```

已知提示：

- `C4244`、`LNK4098` 警告不阻断本次生成和启动
- 如果报缺头文件或 `.lib`，不要在本页继续展开排查，直接回到 [Windows 运行库参考](windows-runtime-libs.md)

### 5.3 从源码编译 MediaServer

在 VS Developer Shell 中执行：

```powershell
$dev = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
cmd /c "call `"$dev`" -arch=x64 -host_arch=x64 && cmake -S MediaServer\source -B MediaServer\build-win -G `"Visual Studio 17 2022`" -A x64 && cmake --build MediaServer\build-win --config Release -- /m"
```

本机 2026-05-04 实测产物：

```text
MediaServer\source\release\windows\Debug\Release\MediaServer.exe
```

联调时建议复制到统一位置：

```text
MediaServer\bin\bin.x86.windows10\MediaServer.exe
```

若 CMake 未找到 OpenSSL，TLS 与依赖 TLS 的 WebRTC 能力可能不会启用；以构建日志和实际功能测试为准。

---

## 6. 检查 config.json

根目录 `config.json` 至少确认下面几类字段：

```json
{
  "adminPort": 9991,
  "mediaHttpPort": 9992,
  "analyzerPort": 9993,
  "mediaRtspPort": 9994,
  "mediaRtmpPort": 9995,
  "mediaSecret": "CHANGE_ME",
  "uploadDir": "data/upload",
  "modelDir": "data/models",
  "openApiToken": "",
  "usbCameraEnabled": false
}
```

开发联调建议：

- `uploadDir` 和 `modelDir` 使用仓库根目录下的相对路径，便于换目录联调
- `mediaSecret` 必须和 `MediaServer\bin\bin.x86.windows10\config.ini` 里的 `[api].secret` 一致
- Windows 未配置 USB 摄像头时，保持 `usbCameraEnabled=false`
- `openApiToken` 本机 loopback 验活可先留空；如果设为非空，测 Analyzer API 时必须带 `X-Beacon-Token`
- `config.json` 保存为 UTF-8 无 BOM

准备目录：

```powershell
Set-Location C:\Work\Beacon
New-Item -ItemType Directory -Force data\upload | Out-Null
New-Item -ItemType Directory -Force data\models | Out-Null
New-Item -ItemType Directory -Force log | Out-Null
```

---

## 7. 启动全栈

### 方式一：分进程启动

适合需要分别看日志、定位问题的开发场景。

```powershell
# 终端 1：MediaServer
Set-Location C:\Work\Beacon\MediaServer\bin\bin.x86.windows10
.\MediaServer.exe -c .\config.ini
```

```powershell
# 终端 2：Analyzer
Set-Location C:\Work\Beacon
.\Analyzer\x64\Release\Analyzer.exe -f .\config.json
```

```powershell
# 终端 3：Admin
Set-Location C:\Work\Beacon\Admin
.\venv\Scripts\Activate.ps1
python manage.py runserver 0.0.0.0:9991
```

### 方式二：开发启动器

二进制已放在约定目录时，可用源码环境的开发启动器：

```powershell
Set-Location C:\Work\Beacon
.\Admin\venv\Scripts\Activate.ps1
python Admin\VideoAnalyzer.py
```

注意：这是开发场景。最终用户部署使用根目录 `VideoAnalyzer.exe`，详见 [Windows 用户部署](windows.md)。

---

## 8. 开发者验活

启动后先确认端口和 HTTP 状态：

```powershell
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:9991/login
curl.exe -s "http://127.0.0.1:9992/index/api/getServerConfig?secret=<你的mediaSecret>"
curl.exe -s http://127.0.0.1:9993/api/health
```

如果设置了 `openApiToken`：

```powershell
curl.exe -s -H "X-Beacon-Token: <你的openApiToken>" http://127.0.0.1:9993/api/health
```

期望结果：

| 服务 | 期望 |
|------|------|
| Admin | `/login` 返回 `200` |
| MediaServer | `getServerConfig` 返回配置 |
| Analyzer | `/api/health` 返回健康状态 |

业务闭环验收还需要继续添加视频流、放置模型、配置算法、启动布控并检查告警结果。页面/API 开发可以先不做完整闭环。

---

## 9. 常见开发问题

| 现象 | 先看什么 |
|------|----------|
| `Admin` 起不来 | venv 是否激活、依赖是否安装、迁移是否执行 |
| `pip install -r requirements-windows.txt` 在 OpenCV / numpy 处失败 | Python 是否为 3.10–3.12、pip 是否已升级、是否误用了旧 venv 缓存 |
| 页面改了没生效 | 是否重新执行 `npm run build` 并重启 `Admin` |
| 启动器找不到 `Analyzer.exe` | EXE 是否放在约定目录 |
| MediaServer 接口鉴权失败 | `mediaSecret` 是否和 `config.ini` 一致 |
| Analyzer 健康检查 401 | 是否配置了 `openApiToken` 且请求未带 `X-Beacon-Token` |
| Analyzer 秒退或提示缺 DLL | 运行 DLL 是否跟 EXE 放在一起；看 [Windows 运行库参考](windows-runtime-libs.md) |
| 三件套都启动但没有告警 | 视频流、模型、算法、布控、检测目标是否都到位 |

---

## 10. 后续文档

- 需要生成正式 ZIP 和校验值：看 [Windows 构建与打包](build-and-package-windows.md)
- 需要核对 DLL、`.lib`、`Analyzer\3rdparty`：看 [Windows 运行库参考](windows-runtime-libs.md)
- 需要给客户机器部署：看 [Windows 用户部署](windows.md)
