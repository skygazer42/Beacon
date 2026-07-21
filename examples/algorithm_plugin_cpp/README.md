# C++ 算法插件示例（SDK v2）

这个示例展示如何用 **稳定 C ABI**（SDK v2）开发一个 Beacon 算法插件（动态库）。

- 输出：固定返回 1 个检测框（用于验证接入链路）
- 不依赖 OpenCV（输入是 BGR 指针 + 宽高 + stride）

---

## 1) 编译

```bash
cd examples/algorithm_plugin_cpp
mkdir -p build && cd build
cmake ..
cmake --build . -j
```

产物（按平台）：

- Windows：`plugin_demo.dll`
- Linux：`libplugin_demo.so`
- macOS：`libplugin_demo.dylib`

---

## 2) 在 Analyzer 侧加载（示例）

假设 Analyzer 运行在 `http://127.0.0.1:9993`，你的开放接口 Token 为 `${BEACON_OPEN_API_TOKEN}`。

```bash
curl -X POST "http://127.0.0.1:9993/api/algorithm/load" \
  -H "Content-Type: application/json" \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}" \
  -d '{
    "code": "demo_plugin",
    "modelPath": "/abs/path/to/libplugin_demo.so",
    "device": "CPU"
  }'
```

然后用 v4.18 新增的一次性推理测试接口：

```bash
curl -X POST "http://127.0.0.1:9993/api/algorithm/testInfer" \
  -H "Content-Type: application/json" \
  -H "X-Beacon-Token: ${BEACON_OPEN_API_TOKEN}" \
  -d '{
    "code": "demo_plugin",
    "image_base64": "<base64(jpeg)>",
    "confThresh": 0.25,
    "nmsThresh": 0.45
  }'
```

---

## 3) 关键点

- 插件必须导出：`BeaconGetAlgorithmPluginV2`
- `detect()` 返回值：`>=0` 表示输出框数量；`<0` 表示错误

