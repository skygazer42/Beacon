# 贡献指南

完整规则见仓库根目录的
[CONTRIBUTING.md](https://github.com/skygazer42/Beacon/blob/main/CONTRIBUTING.md)。
下面是提交前最小验证集。

## 后端

```bash
cd Admin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-linux.txt
python manage.py test
python -m unittest test_video_analyzer_launcher_paths
```

Windows 使用 `requirements-windows.txt`。当前支持 Python 3.10、3.11 和 3.12。

## 前端

```bash
cd Admin/frontend
npm ci
npm test
npm run build
npm audit --audit-level=high
```

前端产物 `Admin/static/app-shell/` 需要随源码一同提交。

## Analyzer

安装 C++17 编译器、`pkg-config` 和 OpenCV 4 开发包后运行：

```bash
bash tools/run_analyzer_unit_tests.sh
```

完整构建所需的 ONNX Runtime、OpenVINO 和 GPU 依赖见
[Analyzer 构建文档](../deployment/build-and-package-linux.md)。

## SDK 与文档

```bash
(cd sdk/python && python -m unittest discover -s tests)
(cd sdk/javascript && npm ci && npm test && npm pack --dry-run)

python -m pip install -r docs/requirements.txt
python tools/docs_strict_check.py
```

## 提交要求

- 行为修改必须有对应测试。
- 不提交口令、Token、客户数据、录像、人脸图片、模型权重或构建目录。
- 修改前端后重新构建受版本控制的 app shell。
- 修改 `MediaServer/source/` 时保留上游署名和全部许可证文件。
- PR 中写清变更影响以及实际执行过的验证命令。
