---
title: Windows 运行库参考
icon: material/library-shelves
---

# Windows 运行库参考

Beacon 不在源码仓库中再分发 Windows SDK、模型和运行库。本页用于区分编译期与
运行期依赖，最终清单必须以实际构建选项和二进制检查结果为准。

## 编译期与运行期

| 类型 | 示例 | 是否放入用户包 |
|---|---|---|
| 头文件 | `.h`、`.hpp` | 否 |
| 静态/导入库 | `.lib` | 通常否 |
| 动态库 | `.dll` | 运行时确实依赖时 |
| 模型 | `.onnx`、`.engine`、`.xml/.bin` | 许可证允许且业务需要时 |
| 调试符号 | `.pdb` | 单独受控保存，不默认公开 |

## 常见依赖

Analyzer 的构建选项可能引入 OpenCV、ONNX Runtime、OpenVINO、TensorRT/CUDA、
FFmpeg、curl、libevent、JsonCpp、jpeg-turbo 或 TBB。不是每个构建都会需要全部
组件，不应从另一台机器整目录复制 DLL。

MediaServer 的可选 TLS/WebRTC 能力会引入 OpenSSL 等依赖。Python Admin 的依赖
由 `requirements-windows.txt` 管理；PyInstaller 仅在打包时使用
`requirements-build.txt`。

## 如何生成准确清单

在 Developer PowerShell 中对最终产物执行：

```powershell
dumpbin /DEPENDENTS .\Analyzer\Analyzer.exe
dumpbin /DEPENDENTS .\MediaServer\MediaServer.exe
Get-ChildItem -Recurse -Filter *.dll | Get-FileHash -Algorithm SHA256
```

也可以使用 Process Monitor 在干净虚拟机中观察启动时实际加载的 DLL。重点确认：

- DLL 架构与程序一致，均为 x64。
- Debug 和 Release 运行库没有混用。
- DLL 搜索路径不包含当前目录之外的用户可写目录。
- Microsoft Visual C++ Redistributable 版本满足构建工具链要求。
- GPU 驱动、CUDA、TensorRT 与模型引擎版本匹配。

## 再分发要求

复制任何 DLL、模型或 SDK 文件前，先核对其许可证和再分发条款。发布包应附：

- 组件名称、版本、来源 URL 和 SHA-256
- 许可证或 notice
- 构建时启用的功能
- 对应 CVE/安全更新策略

缺少来源或许可证明的二进制不能进入公开 Release。详细打包流程见
[Windows 构建与打包](build-and-package-windows.md)。
