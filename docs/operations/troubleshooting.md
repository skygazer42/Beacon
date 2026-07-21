# 故障排除

本文汇总 Beacon 平台常见问题的诊断方法和解决方案。

---

## 快速诊断流程

```mermaid
flowchart TD
    A[发现问题] --> B{服务能否访问?}
    B -->|否| C[检查服务状态]
    B -->|是| D{功能是否正常?}

    C --> C1{端口是否监听?}
    C1 -->|否| C2[检查启动日志]
    C1 -->|是| C3[检查防火墙/网络]

    D -->|视频流异常| E[流连接排查]
    D -->|无告警| F[告警链路排查]
    D -->|性能问题| G[资源占用排查]
    D -->|界面异常| H[前端排查]
```

---

## 服务无法启动

### 端口冲突

**症状**：启动时报 `Address already in use` 错误。

```bash
# 检查端口占用
ss -tlnp | grep -E '9991|9992|9993|9994|9995'

# 查看占用进程
lsof -i :9991
```

**解决方案**：

=== "修改端口"

    在 `config.json` 中修改冲突的端口：

    ```json
    {
      "adminPort": 9991,
      "mediaHttpPort": 9992,
      "analyzerPort": 9993,
      "mediaRtspPort": 9994,
      "mediaRtmpPort": 9995
    }
    ```

=== "终止冲突进程"

    ```bash
    # 确认占用进程后终止
    kill -15 <PID>
    ```

### 依赖缺失

**症状**：启动时报 `ModuleNotFoundError` 或动态库加载失败。

```bash
# 检查 Python 依赖
cd /opt/beacon/Admin && pip check

# 检查 C++ 动态库依赖
ldd /opt/beacon/Analyzer/Analyzer/Analyzer 2>&1 | grep "not found"

# 检查 CUDA 库
ldconfig -p | grep cuda
nvidia-smi
```

**解决方案**：

```bash
# 重新安装 Python 依赖
cd /opt/beacon/Admin && pip install -r requirements.txt

# 修复动态库路径
echo "/usr/local/lib" >> /etc/ld.so.conf.d/beacon.conf
ldconfig
```

### 权限不足

**症状**：日志中出现 `Permission denied` 错误。

```bash
# 检查关键目录权限
ls -la /opt/beacon/config.json
ls -la /opt/beacon/Admin/db.sqlite3
ls -la /opt/beacon/log/
ls -la /opt/beacon/Admin/static/upload/
```

**解决方案**：

```bash
# 修复权限
chown -R beacon:beacon /opt/beacon
chmod 640 /opt/beacon/config.json
chmod 640 /opt/beacon/Admin/db.sqlite3
chmod 755 /opt/beacon/log
chmod 755 /opt/beacon/Admin/static/upload
```

---

## 视频流连接故障

### RTSP 连接超时

**症状**：添加视频流后状态显示"连接失败"或"超时"。

```bash
# 测试 RTSP 连通性
ffprobe -v error -rtsp_transport tcp \
    "rtsp://admin:password@192.168.1.100:554/stream1" \
    2>&1 | head -20

# 测试网络连通性
ping -c 3 192.168.1.100
telnet 192.168.1.100 554
```

!!! note "常见 RTSP URL 格式"
    | 品牌 | URL 格式 |
    |------|----------|
    | 海康威视 | `rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/101` |
    | 大华 | `rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=0` |
    | 宇视 | `rtsp://<user>:<pass>@<ip>:554/video1` |
    | ONVIF 通用 | 通过 ONVIF 发现页面自动获取 |

### RTSP 认证失败

**症状**：日志中出现 `401 Unauthorized` 或 `Authentication failed`。

**排查步骤**：

1. 确认摄像头用户名和密码正确
2. 检查是否包含特殊字符（需要 URL 编码）
3. 尝试在 VLC 中播放 RTSP 流验证

```bash
# URL 编码特殊字符示例
# 密码 "p@ss#123" -> "p%40ss%23123"
ffplay -rtsp_transport tcp \
    "rtsp://admin:p%40ss%23123@192.168.1.100:554/stream1"
```

### 网络带宽不足

**症状**：视频流频繁断开重连，画面卡顿或花屏。

```bash
# 检查网络带宽
iperf3 -c <摄像头网关> -t 10

# 估算带宽需求
# 1080P @ 25fps H.264 ≈ 4-8 Mbps
# 720P @ 25fps H.264 ≈ 2-4 Mbps
# 所需带宽 ≈ 单路码率 x 路数 x 1.2（余量系数）
```

**解决方案**：

- 降低摄像头分辨率或帧率
- 使用子码流（substream）进行分析
- 升级交换机或网络链路

---

## 无告警生成

### 诊断流程

```mermaid
flowchart TD
    A[无告警] --> B{布控已启动?}
    B -->|否| B1[启动布控]
    B -->|是| C{Analyzer 运行中?}

    C -->|否| C1[检查 Analyzer 日志]
    C -->|是| D{检测区域正确?}

    D -->|否| D1[重新配置检测区域]
    D -->|是| E{灵敏度设置?}

    E -->|过低| E1[调高灵敏度阈值]
    E -->|合理| F{模型已加载?}

    F -->|否| F1[检查模型文件]
    F -->|是| G[使用测试图片验证]
```

### Analyzer 未运行

```bash
# 检查 Analyzer 进程
ps aux | grep -i analyzer

# 查看 Analyzer 日志
tail -100 /opt/beacon/log/analyzer.log

# 检查 Analyzer 端口
ss -tlnp | grep 9993
```

### 检测区域未配置

在 **布控管理** 页面检查：

1. 布控状态是否为"运行中"
2. 检测区域（ROI）是否覆盖了目标区域
3. 检测区域是否过小导致目标被忽略

### 灵敏度过低

- 置信度阈值过高会导致漏报——建议从 0.5 开始逐步调整
- 不同算法的最佳阈值不同，参考算法文档的推荐值

### 模型文件问题

```bash
# 检查模型文件是否存在
ls -la /opt/beacon/Analyzer/models/

# 检查模型文件完整性（如有校验文件）
md5sum /opt/beacon/Analyzer/models/*.onnx
```

---

## CPU/内存使用过高

### 诊断

```bash
# 查看进程资源占用
top -b -n 1 | grep -E 'beacon|analyzer|media'

# 查看内存详情
free -h
cat /proc/meminfo | head -10

# 查看各进程内存占用
ps aux --sort=-%mem | head -20
```

### 常见原因与解决方案

| 原因 | 表现 | 解决方案 |
|------|------|----------|
| 流路数过多 | CPU 持续 > 90% | 减少流路数或升级硬件 |
| 未使用 GPU 加速 | 推理全在 CPU 运行 | 安装 GPU 驱动和 CUDA，启用 GPU 推理 |
| 解码线程过多 | 每路流多线程解码 | 降低 `ffmpegDecodeThreadCount` |
| 内存泄漏 | 内存持续增长 | 检查日志并联系开发团队 |
| 模型并发过高 | GPU 显存不足回退 CPU | 降低 `modelConcurrency` |

```json
// config.json 调优示例
{
  "maxControls": 16,
  "modelConcurrency": 1,
  "ffmpegDecodeThreadCount": 1,
  "ffmpegEncodeThreadCount": 1
}
```

---

## GPU 问题

### 驱动不匹配

**症状**：`nvidia-smi` 报错或 CUDA 初始化失败。

```bash
# 检查 GPU 驱动
nvidia-smi

# 检查 CUDA 版本
nvcc --version

# 检查 cuDNN 版本
cat /usr/local/cuda/include/cudnn_version.h | grep MAJOR -A 2
```

!!! warning "版本兼容性"
    | 组件 | 推荐版本 |
    |------|----------|
    | NVIDIA 驱动 | >= 525.60 |
    | CUDA | 11.8 或 12.x |
    | cuDNN | 8.6+ |
    | TensorRT | 8.5+（可选） |

### CUDA 版本不兼容

```bash
# 查看已安装的 CUDA 工具包
ls /usr/local/cuda*

# 切换 CUDA 版本
sudo update-alternatives --config cuda

# 确认环境变量
echo $CUDA_HOME
echo $LD_LIBRARY_PATH
```

### GPU 显存不足

**症状**：日志中出现 `CUDA out of memory` 错误。

```bash
# 查看 GPU 显存使用
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv

# 查看占用显存的进程
nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv
```

**解决方案**：

1. 降低 `modelConcurrency`（模型并发数）
2. 使用更轻量的模型（如 YOLOv8n 替代 YOLOv8x）
3. 降低输入分辨率
4. 关闭不必要的布控任务
5. 升级至显存更大的 GPU

---

## Web 界面问题

### 页面空白

**排查步骤**：

1. 打开浏览器开发者工具（F12），查看 Console 报错
2. 检查 Network 面板中静态资源是否加载成功
3. 清除浏览器缓存后重试

```bash
# 检查 React 生产包是否存在
test -f /opt/beacon/Admin/static/app-shell/beacon-shell.js
test -f /opt/beacon/Admin/static/app-shell/beacon-shell.css

# 检查 Admin 服务日志
tail -50 /opt/beacon/log/admin.log
```

### 告警 WebSocket 断开

**症状**：使用可选告警增量通道的客户端无法更新。React 告警页当前主要使用 HTTP 轮询，因此页面更新异常不一定是 WebSocket 导致。

```bash
# 测试 WebSocket 连接
curl -i -N \
    -H "Connection: Upgrade" \
    -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Version: 13" \
    -H "Sec-WebSocket-Key: test" \
    http://127.0.0.1:9991/ws/alarm/poll?after_id=0&interval_ms=3000
```

**常见原因**：

- 客户端没有携带已登录的 Django Session Cookie；该端点不接受 API Key 或通用 JWT
- Admin 只通过 WSGI 启动；需要 WebSocket 时必须使用仓库 ASGI 入口
- Nginx 未配置 `/ws/` WebSocket 代理（参考 [安全加固](security.md)）
- 代理超时时间过短——在 Nginx 中增加：
  ```nginx
  proxy_read_timeout 86400s;
  proxy_send_timeout 86400s;
  ```

---

## 日志分析指南

### 快速定位错误

```bash
# 搜索 Admin 错误日志
grep -i "error\|exception\|traceback" /opt/beacon/log/admin.log | tail -30

# 搜索 Analyzer 错误日志
grep -i "error\|fatal\|crash" /opt/beacon/log/analyzer.log | tail -30

# 搜索 MediaServer 错误日志
grep -i "error\|fail" /opt/beacon/log/media.log | tail -30

# 按时间段筛选（示例：最近 1 小时）
awk -v d="$(date -d '1 hour ago' '+%Y-%m-%d %H:%M')" '$0 >= d' \
    /opt/beacon/log/admin.log | grep -i error
```

### 常见错误信息速查

| 错误信息 | 可能原因 | 解决方向 |
|----------|----------|----------|
| `Address already in use` | 端口被占用 | 检查端口冲突 |
| `Connection refused` | 目标服务未启动 | 启动对应服务 |
| `CUDA out of memory` | GPU 显存不足 | 降低并发或换卡 |
| `Permission denied` | 文件权限不足 | 修复文件权限 |
| `ModuleNotFoundError` | Python 依赖缺失 | 重新安装依赖 |
| `RTSP timeout` | 摄像头网络不通 | 检查网络连通性 |
| `Model file not found` | 模型文件缺失 | 检查模型路径 |
| `Database is locked` | SQLite 并发冲突 | 考虑迁移至 PostgreSQL |
| `SSL handshake failed` | TLS 证书问题 | 检查证书有效期 |
| `Too many open files` | 文件描述符不足 | 增大 ulimit |

### 增加文件描述符限制

```bash
# 临时修改
ulimit -n 65536

# 永久修改
cat >> /etc/security/limits.conf << 'EOF'
beacon  soft  nofile  65536
beacon  hard  nofile  65536
EOF
```

---

## 获取技术支持

如果以上方法无法解决问题，请准备以下信息后联系技术支持：

1. Beacon 版本号（在 Web 界面底部或通过 API 查询）
2. 操作系统版本（`cat /etc/os-release`）
3. GPU 信息（`nvidia-smi`）
4. 相关日志文件（`log/` 目录下的最近日志）
5. `config.json`（**请先移除敏感信息**，如密码和密钥）
6. 问题复现步骤
