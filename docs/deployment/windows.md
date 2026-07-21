---
title: Windows 用户部署
icon: fontawesome/brands/windows
---

# Windows 用户部署

本页面向已经取得可信发布包的实施和运维人员。当前源码仓库不承诺提供预构建
Windows 包；需要自行构建时请先看 [Windows 构建与打包](build-and-package-windows.md)。

## 1. 发布包要求

发布方至少应提供：

- Beacon 版本号、Git commit 和 SHA-256
- Admin、Analyzer、MediaServer 的同版本产物
- `LICENSE`、`THIRD_PARTY_NOTICES.md` 和运行库 notices
- 经过授权的模型和第三方运行库清单
- 不含现场数据库、日志、截图、录像及真实密钥的默认配置

不要运行来源不明、只有可执行文件而没有版本和校验值的压缩包。

## 2. 安装目录

```text
C:\Beacon\
  config.json
  Admin\
  Analyzer\
  MediaServer\
  data\
    models\
    upload\
  log\
```

服务账号需要对 `data\upload` 和 `log` 有写权限，对程序及模型目录只需读取
权限。不要安装在个人下载目录或允许普通用户写入的共享目录。

## 3. 配置

从仓库示例开始配置，至少检查：

- `adminPort`、`mediaHttpPort`、`analyzerPort`
- `modelDir`、`uploadDir`
- MediaServer API secret 与两端配置一致
- `BEACON_DJANGO_SECRET_KEY`、`BEACON_OPEN_API_TOKEN`
- `BEACON_DJANGO_ALLOWED_HOSTS` 和 HTTPS/Cookie 设置

生成密钥示例：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

通过受控环境变量或 Windows Secret 管理工具注入密钥，不要把真实值提交到
`config.json`、脚本或工单。首次部署使用 `createsuperuser` 创建管理员，
系统没有通用默认密码。

## 4. 启动

源码运行方式：

```powershell
Set-Location C:\Beacon\Admin
.\venv\Scripts\Activate.ps1
python manage.py migrate --noinput
python manage.py runserver 127.0.0.1:9991
```

Analyzer 和 MediaServer 使用发布包提供的配置分别启动。生产环境应使用 Windows
服务包装器或受管进程，而不是长期使用 Django `runserver`。服务账号、工作目录、
环境变量和失败重启策略都应显式配置。

## 5. 反向代理与防火墙

- 浏览器入口只暴露 HTTPS 反向代理端口。
- Admin、Analyzer 管理接口默认限制在管理网。
- RTSP/RTMP/GB28181 端口仅向业务所需网段开放。
- 不要把数据库、MinIO 控制台或内部调试端口暴露到公网。

## 6. 验收

```powershell
Invoke-WebRequest http://127.0.0.1:9991/login -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:9993/api/health
```

MediaServer 管理接口需要使用部署时设置的 secret。随后完成一条真实或合规测试
视频流的端到端验收：

1. 添加视频源并确认拉流正常。
2. 创建布控并确认 Analyzer 使用预期 CPU/GPU 后端。
3. 检查报警、截图、停止任务和资源释放。
4. 重启三项服务，确认配置和数据恢复正确。
5. 核对日志中没有密钥、Bearer token 或摄像头密码。

## 7. 升级与卸载

升级前备份数据库和用户上传数据，先在测试环境验证迁移，再滚动替换程序目录。
回滚时同时恢复与旧版本兼容的数据库备份。卸载时删除 Windows 服务、程序目录和
按保留策略允许删除的数据；密钥应在外部系统中轮换，而不是只删除本地文件。
