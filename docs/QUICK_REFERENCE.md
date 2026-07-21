# Beacon 快速参考手册

!!! tip "速查表用法"
    本页汇总常用命令、端口、路径和接口验收命令，适合现场部署、联调和故障排查时快速查阅。
    需要完整步骤时，请进入 [快速开始](getting-started/index.md)、[部署总览](deployment/index.md)、[运维手册](operations/index.md) 等正文章节。

---

## 先找入口

需要完整步骤时，先按下面这张表选页面，再回来查命令。

| 当前目标 | 直接入口 |
|----------|----------|
| Linux 开发 | [Linux 本机开发](deployment/local-linux.md) → [Linux 运行库参考](deployment/linux-runtime-libs.md) → [Linux 构建与打包](deployment/build-and-package-linux.md) |
| Linux 现场部署 | [Linux 运行库参考](deployment/linux-runtime-libs.md) → [Linux 用户部署](deployment/linux.md) |
| Windows 开发 | [Windows 本机开发](deployment/local-windows.md) → [Windows 运行库参考](deployment/windows-runtime-libs.md) → [Windows 构建与打包](deployment/build-and-package-windows.md) |
| Windows 现场部署 | [Windows 运行库参考](deployment/windows-runtime-libs.md) → [Windows 用户部署](deployment/windows.md) |
| 按角色查看平台入口 | [部署总览](deployment/index.md) |

---

## 快速启动

### Windows

```powershell
Set-Location C:\Beacon
.\Admin\venv\Scripts\Activate.ps1
python Admin\VideoAnalyzer.py
```

### Linux

```bash
# 前台运行
cd /opt/beacon
source /opt/beacon/Admin/venv/bin/activate
python /opt/beacon/Admin/VideoAnalyzer.py

# 后台服务
sudo systemctl start beacon
```

### Docker

```bash
docker compose up -d
```

---

## 状态检查

以下命令主要用于 Linux 和 Docker 场景。Windows 现场检查请优先参见 [Windows 用户部署](deployment/windows.md)。

```bash
# 检查端口监听
sudo ss -ltnp | grep -E '9991|9992|9993|9994|9995'

# 检查进程
ps -ef | grep -E 'VideoAnalyzer.py|Analyzer|MediaServer' | grep -v grep

# 检查服务状态（Linux）
sudo systemctl status beacon

# 查看 Docker 容器
docker compose ps
```

---

## 日志查看

以下命令主要用于 Linux 和 Docker 场景。Windows 目录位置请看下文“常见路径”中的 Windows 表。

```bash
# systemd 托管日志（Linux）
sudo journalctl -u beacon -f

# 启动器日志目录（Admin/VideoAnalyzer.py 默认写到这里）
find /opt/beacon/log -maxdepth 1 -type f | sort
tail -f /opt/beacon/log/*.log

# Admin 文件日志（仅在启用 BEACON_LOG_TO_FILE=1 时存在）
find /opt/beacon/Admin/logs -maxdepth 1 -type f | sort

# Docker 日志
docker compose logs -f
```

---

## 常用管理命令

### 服务控制

```bash
# Linux systemd
sudo systemctl start beacon      # 启动
sudo systemctl stop beacon       # 停止
sudo systemctl restart beacon    # 重启
sudo systemctl status beacon     # 查看状态
sudo systemctl enable beacon     # 开机自启

# Docker
docker compose up -d             # 后台启动
docker compose stop              # 停止
docker compose restart           # 重启
docker compose down              # 停止并删除容器
```

### 数据库操作

```bash
# SQLite 备份
cp Admin/Admin.sqlite3 Admin/Admin.sqlite3.bak

# SQLite 查询
sqlite3 Admin/Admin.sqlite3 "SELECT * FROM av_stream;"

# 启用 WAL 模式
sqlite3 Admin/Admin.sqlite3 "PRAGMA journal_mode=WAL;"
```

---

## API 测试

`<mediaSecret>` 取自 `config.json.mediaSecret`。
`<openApiToken>` 取自环境变量 `BEACON_OPEN_API_TOKEN`，或取自 `config.json.openApiToken`。
Windows PowerShell 下，请把下面的 `curl` 替换为 `curl.exe`。

```bash
# 1. Admin 登录页
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9991/login

# 2. MediaServer API
curl -sS "http://127.0.0.1:9992/index/api/getServerConfig?secret=<mediaSecret>" | head

# 3. Analyzer 健康检查
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9993/api/health

# 4. 授权状态
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/license/usage

# 5. 视频流列表
curl -sS -H "X-Beacon-Token: <openApiToken>" http://127.0.0.1:9991/open/getAllStreamData
```

---

## 性能监控

以下命令主要用于 Linux 和 Docker 场景。

```bash
# CPU 和内存
top -p "$(pgrep -d',' -f Analyzer)"

# GPU 使用情况（NVIDIA）
nvidia-smi

# Docker 资源
docker stats --no-stream

# 磁盘空间
df -h /opt/beacon/data/upload
du -sh /opt/beacon/data/upload /opt/beacon/data/models /opt/beacon/log 2>/dev/null
```

---

## 故障排查

以下命令主要用于 Linux 场景。

### 端口被占用

```bash
# 查找占用进程
lsof -i:9991

# 杀死进程
kill -9 <PID>
```

### 视频流测试

```bash
# FFmpeg 测试拉流
ffmpeg -i rtsp://192.168.1.100/live/stream -t 5 -f null -

# FFplay 直接播放
ffplay rtsp://192.168.1.100/live/stream
```

### RTSP 模拟器 / Golden 回归

```bash
# 启动本地 RTSP 模拟器（首次会下载固定版本 MediaMTX 到 ~/.cache）
python3 tools/rtsp_simulator.py

# 运行 golden regression
python3 -m unittest tests.test_rtsp_simulator_golden
```

### 清理旧文件

```bash
# 清理启动器旧日志
find /opt/beacon/log -type f -name '*.log' -mtime +7 -delete

# 清理旧上传文件
find /opt/beacon/data/upload -type f -mtime +30 -delete
```

---

## 常见路径

### Linux

| 作用 | 路径 |
|------|------|
| 交付根目录 | `/opt/beacon` |
| 主配置 | `/opt/beacon/config.json` |
| 上传目录 | `/opt/beacon/data/upload/` |
| 模型目录 | `/opt/beacon/data/models/` |
| 启动器日志目录 | `/opt/beacon/log/` |
| systemd 服务文件 | `/etc/systemd/system/beacon.service` |
| systemd 环境变量文件 | `/opt/beacon/beacon.env` |
| Nginx 配置（反向代理场景） | `/etc/nginx/sites-available/beacon` |

### Windows

| 作用 | 路径 |
|------|------|
| 交付根目录 | `C:\Beacon` |
| 主配置 | `C:\Beacon\config.json` |
| 上传目录 | `C:\Beacon\data\upload\` |
| 模型目录 | `C:\Beacon\data\models\` |
| Admin Python 环境 | `C:\Beacon\Admin\venv\` |
| 启动器脚本 | `C:\Beacon\Admin\VideoAnalyzer.py` |
| Analyzer 目录 | `C:\Beacon\Analyzer\` |
| MediaServer 目录 | `C:\Beacon\MediaServer\` |

---

## 模型加密（v2）

用于交付“加密模型 + 试用时长 + 自定义编号”。Analyzer 侧会在加载时自动解密到 `modelDecryptDir`。

### 配置项（`config.json` / 环境变量）

```json
{
  "modelEncrypt": true,
  "modelEncryptKey": "请替换为随机长串",
  "modelEncryptSuffix": ".enc",
  "modelDecryptDir": "/opt/beacon/model_decrypt_cache"
}
```

### 预加密工具

```bash
# 普通模型加密（输出：<src>.enc，例如 demo.engine.enc）
python3 tools/model_encrypt.py --key <modelEncryptKey> demo.engine

# OpenVINO IR（xml + bin）一起加密
python3 tools/model_encrypt.py --key <modelEncryptKey> --openvino-pair demo.xml

# 带试用时长与自定义编号
python3 tools/model_encrypt.py --key <modelEncryptKey> --trial-seconds 86400 --custom-id CID001 demo.onnx
```

---

## 默认信息

| 项目 | 值 |
|------|-----|
| 登录地址 | `http://127.0.0.1:9991/login` |
| 管理员账号 | 本地使用 `createsuperuser`；Cloud 使用 bootstrap 环境变量 |
| Admin 端口 | `9991` |
| MediaServer HTTP 端口 | `9992` |
| Analyzer API 端口 | `9993` |
| MediaServer RTSP 端口 | `9994` |
| MediaServer RTMP 端口 | `9995` |

---

## 获取帮助

- [快速开始](getting-started/index.md)
- [部署总览](deployment/index.md)
- [运维手册](operations/index.md)
- Issues: https://github.com/skygazer42/Beacon/issues
