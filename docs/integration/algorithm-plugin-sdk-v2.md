# Beacon 算法插件 SDK v2(稳定 C ABI 协议规范)

> 适用范围:把自定义算法以 **动态库插件**(`.dll/.so/.dylib`)形式接入 Beacon Analyzer(C++)。
> 版本:v4.18 起推荐使用 SDK v2(稳定 C ABI),同时兼容旧版 C++ `Algorithm*` 插件接口。

!!! info "本页定位 — 协议规范"
    - 本页是 **协议规范** —— 函数表、ABI、数据结构、并发模型、错误码契约
    - 想要 **如何编译、调试、调试技巧** 等开发者视角内容,见 [插件 SDK 开发指南](../algorithms/plugin-sdk.md)
    - 想要 HTTP 形式的外部算法接入,见 [算法 API 协议 v2](algorithm-api-protocol-v2.md)

---

## 1. 为什么要 SDK v2

历史版本插件采用导出 `Algorithm*`（C++ 类指针）方式接入。这种方式存在典型的工业风险：

- **ABI 不稳定**：不同编译器（MSVC/clang/gcc）、不同运行库（/MD vs /MT）、不同 STL 版本可能导致崩溃或内存问题
- **交付不可控**：客户侧二次开发常常无法保证与你的编译环境一致

SDK v2 通过 **“函数表 + 纯 C struct”** 提供稳定 ABI：只要 C ABI 兼容，即可在不同编译器之间稳定运行。

---

## 2. 插件导出（必须）

插件动态库必须导出以下符号（C ABI）：

- `BeaconGetAlgorithmPluginV2`

返回一个 `BeaconAlgorithmPluginV2*` 函数表指针（静态常量即可）。

> 参考：`Analyzer/Analyzer/Core/PluginSdkV2.h`（Analyzer 侧同一份定义）  
> 示例：`examples/algorithm_plugin_cpp/plugin_demo.cpp`

---

## 3. 数据结构（核心）

### 3.1 输入图像（BGR）

Analyzer 传入的图像是 OpenCV 常见格式：

- `BGR`（8-bit，3 通道，等价 OpenCV `CV_8UC3`）
- `stride` 是每行字节数（`image.step`）

插件只需要按行读取 `bgr` 指针即可，无需依赖 OpenCV。

### 3.2 输出检测框

插件输出 `BeaconPluginDetectV2[]`：

- `x1/y1/x2/y2`：像素坐标
- `score`：置信度
- `class_id`：类别 ID
- `class_name`：可选（UTF-8）；Analyzer 会拷贝为 `std::string`

---

## 4. 并发与线程安全（重要）

Analyzer 在加载插件算法时会按 `modelConcurrency` 创建多个实例：

- `create()` 会被调用 `N` 次
- 推理时按 **round-robin** 分发到不同实例
- Analyzer 对每个实例加 **互斥锁**，因此插件实例内部不要求线程安全（但建议无共享全局状态）

建议插件：

- 把模型句柄、缓存等放进 `instance`（每实例独立）
- 避免在 `detect()` 内部使用全局可变单例

---

## 5. 错误处理约定

`detect()` 返回值：

- `>= 0`：输出框数量（已写入 `out_dets`，数量不超过 `max_dets`）
- `< 0`：表示错误（Analyzer 侧会认为推理失败）

建议你在插件内部输出日志（文件/控制台）方便交付排障。

---

## 6. 与 Beacon 的对接方式（落地）

1) 在 Admin 后台添加基础算法（来源选择“本地模型”）
- 上传/填写你的插件动态库路径（`.dll/.so/.dylib`）

2) Admin 调用 Analyzer 动态加载：
- `POST /api/algorithm/load`

3) 在 Admin 使用“算法测试”上传图片（v4.18 增强）
- Admin 会调用：`POST /api/algorithm/testInfer`

---

## 7. 示例插件（可直接编译）

示例工程目录：

- `examples/algorithm_plugin_cpp`

它实现了：

- `BeaconGetAlgorithmPluginV2()` 导出
- `create/destroy/detect` 最小闭环

编译：

```bash
cd examples/algorithm_plugin_cpp
mkdir -p build && cd build
cmake ..
cmake --build . -j
```

产物（根据平台）：

- Windows：`plugin_demo.dll`
- Linux：`libplugin_demo.so`
- macOS：`libplugin_demo.dylib`

---

## 8. 兼容旧接口（可选）

如果插件未导出 `BeaconGetAlgorithmPluginV2`，Analyzer 会自动回退到旧接口：

- `BeaconCreateAlgorithmEx` / `BeaconCreateAlgorithmV3`
- `BeaconCreateAlgorithmV2`
- `BeaconCreateAlgorithm`
- `BeaconDestroyAlgorithm`

> 旧接口存在 ABI 风险，仅建议用于“内部自用”或历史遗留插件。

