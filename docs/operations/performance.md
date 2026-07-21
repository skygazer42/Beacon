# 性能调优

Beacon 的容量取决于模型、输入尺寸、抽帧策略、编解码格式、推理后端和硬件。
本仓库不发布脱离这些条件的“通用路数”或 FPS 承诺；上线前应在目标机器上用真实模型和视频做容量测试。

---

## 先定义验收口径

测试前固定以下条件，否则两次结果不可比：

| 类别 | 必须记录的信息 |
|---|---|
| 硬件 | CPU 型号/核数、内存、GPU 型号/显存、磁盘与网卡 |
| 软件 | OS、驱动、CUDA/TensorRT/OpenVINO/ONNX Runtime 版本、Beacon commit |
| 模型 | 文件哈希、输入尺寸、精度、推理后端与有效 device |
| 视频 | 编码、分辨率、帧率、码率、GOP、音频、来源数量 |
| 任务 | 并发流数、每路算法数、抽帧间隔、`modelConcurrency`、是否回推/录像 |
| 结果 | 预热时间、测试时长、处理 FPS、P50/P95/P99 延迟、丢帧、队列深度、错误率、资源峰值 |

建议先跑单路基线，再逐路增加。以“P99 延迟、丢帧或错误率首次超过业务阈值”作为容量边界，不要只看 GPU 利用率。

---

## 推理后端

| 后端 | 适用场景 | 验证重点 |
|---|---|---|
| ONNX Runtime CPU | 无 GPU、功能验证、低负载 | 线程竞争、实时性与 CPU 余量 |
| ONNX Runtime CUDA | NVIDIA GPU 通用推理 | 日志/API 中的实际 provider，不要只看配置名 |
| TensorRT EP | 已安装匹配版本的 CUDA/TensorRT | 引擎构建、算子支持、显存和首次加载时间 |
| OpenVINO | Intel CPU/iGPU 或已验证的设备 | `openvinoDevices` 与有效设备，确认未意外回落 CPU |
| Compat Plugin | RKNN/Ascend 等外部 SDK | 必须配置真实 backend；`stub` 不代表推理成功 |

`AUTO` 可以在不同机器上选择不后端。做性能对比时应显式固定 device，并从 Analyzer 的设备信息和加载日志确认最终选择。

---

## 调优顺序

1. **先确认源流稳定**：用 `ffprobe` 或播放器排除断流、时间戳和网络抖动。
2. **固定模型和 device**：确认模型加载成功且实际 provider 符合预期。
3. **调整分辨率与抽帧**：使用能保持目标像素尺寸的最小输入；非必要时不逐帧推理。
4. **从 `modelConcurrency=1` 开始**：只在队列持续积压且 CPU/GPU 还有余量时逐步增加。
5. **最后再加回推、录像和告警视频**：分开测量解码、推理、编码和存储开销。

### 视频流建议

- 录像可使用主码流，分析优先使用摄像头子码流。
- 人脸、车牌等场景先校验目标在画面中的像素尺寸，不能只按“720p/1080p”选择。
- 动作类算法的抽帧上限由事件持续时间决定；调整后必须重做召回率验证。
- 码率与带宽以摄像头实际输出为准。如果平均码率为 `R Mbps`，单路每小时原始数据约为 `R × 0.45 GB`（未计容器和文件系统开销）。

### 硬件编解码

`hardwareDecoderType` / `hardwareEncoderType` 建议先使用 `auto`，并保持 `forceHardwareCodec=false`，然后从日志确认实际编解码器。会话上限与编码格式由 GPU 型号、驱动和厂商政策决定，不要把某张显卡的经验值当成通用上限。

---

## 数据库与存储

- SQLite 适合单实例和较低的并发写入；Cloud 或持续高并发写入使用 PostgreSQL。
- 不要直接复制固定 PRAGMA、`shared_buffers`、`work_mem` 或连接数。先记录慢查询、缓存命中率、WAL 和磁盘延迟，再根据数据库文档调整。
- 索引通过 Django migration 管理。新增索引前保存真实慢查询并运行 `EXPLAIN (ANALYZE, BUFFERS)`。
- 告警截图、短视频和录像分开计算保留周期，用实际样本文件大小推算磁盘，并保留备份和高水位安全空间。

---

## Admin 看板探测缓存

`/api/app-shell/dashboard` 会聚合 Admin、Analyzer 和 MediaServer 状态。Analyzer 探测默认使用短 TTL 缓存：

```bash
BEACON_INDEX_ANALYZER_CACHE_TTL_SECONDS=10
```

- 更短 TTL 提高新鲜度，但增加 Analyzer 探测压力。
- 更长 TTL 适合多用户高频刷新的看板，但会延迟状态变化。

可用仓库的轻量压测脚本比较修改前后的延迟分位数和错误率：

```bash
python3 tools/admin_api_load_test.py \
  --url http://127.0.0.1:9991/api/app-shell/dashboard \
  --cookie-file /tmp/beacon-full.cookies \
  --concurrency 8 \
  --requests 200 \
  --warmup-requests 10 \
  --timeout-seconds 5 \
  --output /tmp/beacon-dashboard-load-test.json
```

比较时必须保持硬件、数据量、并发数和预热条件一致。仓库不收录特定机器的临时压测产物。

---

## 发布前容量清单

- [ ] 功能回归与容量测试使用同一模型哈希和配置。
- [ ] 记录了有效 provider，没有将 GPU 回落 CPU 误判为 GPU 结果。
- [ ] 持续测试时长覆盖模型缓存、断流重连、告警视频和数据库写入。
- [ ] 记录 P95/P99、丢帧、队列、错误率和资源峰值，而不是只记平均值。
- [ ] 为告警、磁盘、GPU 内存、进程重启和队列积压设置可观测阈值。
- [ ] 保留容量余量，并验证了降载、重启与回滚路径。
