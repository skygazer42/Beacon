---
title: Windows 构建与打包
icon: fontawesome/brands/windows
---

# Windows 构建与打包

本页只描述从当前仓库源码生成 Windows 产物的流程。仓库不附带模型权重、
CUDA/TensorRT SDK、第三方推理运行库或预构建客户包；请分别从原厂取得，并确认
其许可证允许你的使用和再分发方式。

## 1. 构建环境

- 64 位 Windows 10/11 或 Windows Server
- Visual Studio 2022，安装“使用 C++ 的桌面开发”和 CMake
- Python 3.10、3.11 或 3.12
- Node.js 20.19+ 或 22.12+
- Git、CMake 3.16+

在 Developer PowerShell for VS 2022 中确认：

```powershell
python --version
node --version
cmake --version
cl
```

## 2. 构建 Admin

```powershell
Set-Location Admin
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
python manage.py migrate --noinput
python manage.py createsuperuser
python manage.py check
Set-Location ..
```

首次运行必须自行创建管理员；项目不提供通用默认密码。

## 3. 构建前端

```powershell
Set-Location Admin\frontend
npm ci
npm test
npm run build
Set-Location ..\..
```

构建结果写入 `Admin\static\app-shell`。提交源码变更时，静态产物应与源码同步。

## 4. 构建 Analyzer

Visual Studio 工程位于 `Analyzer\Analyzer.sln`。准备工程引用的 OpenCV、推理
后端和其他原厂 SDK 后执行：

```powershell
msbuild Analyzer\Analyzer.sln /m /t:Rebuild /p:Configuration=Release /p:Platform=x64
```

也可以使用 CMake；具体开关见 [Analyzer 架构文档](../architecture/analyzer.md)。
不要把本机 SDK、模型或构建目录提交到 Git。

## 5. 构建 MediaServer

```powershell
cmake -S MediaServer\source -B build\mediaserver -G "Visual Studio 17 2022" -A x64
cmake --build build\mediaserver --config Release --target MediaServer
```

TLS/WebRTC 能力取决于构建时是否找到 OpenSSL 等可选依赖。以 CMake 输出和最终
二进制的依赖检查结果为准。

## 6. 可选：打包 Python 启动入口

PyInstaller 不属于运行时依赖，只有制作独立启动入口时才安装：

```powershell
Set-Location Admin
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
pyinstaller --clean -i logo.ico -F VideoAnalyzer.py
Set-Location ..
```

## 7. 组装发布目录

建议从空目录开始，只复制运行必需文件：

```text
Beacon-windows-x64\
  LICENSE
  THIRD_PARTY_NOTICES.md
  SECURITY.md
  config.json
  Admin\
  Analyzer\
  MediaServer\
  data\
    models\
    upload\
  log\
```

发布包中不要包含：

- `.env`、数据库、日志、截图、录像或其他现场数据
- 源码树中的 `build`、`x64`、`node_modules`、`venv`
- 未确认再分发权的模型、驱动、SDK、DLL 或授权文件
- 开发机绝对路径和真实访问令牌

如果随包提供 Python 运行时或第三方 DLL，需要同时携带其许可证要求的 notices。

## 8. 发布前验证

```powershell
git diff --check

Set-Location Admin\frontend
npm ci
npm test
npm run build
Set-Location ..\..

Set-Location Admin
$env:BEACON_DISABLE_BACKGROUND = "1"
.\venv\Scripts\python manage.py test
Set-Location ..
```

在一台未安装项目开发依赖的干净 Windows 虚拟机中解压发布包，再验证登录、
流媒体 API、Analyzer 健康接口和实际推理链路。最终 ZIP 应发布到项目 Releases，
并同时提供 SHA-256；不要把个人网盘地址写入源码文档。
