---
title: 构建与打包总览
icon: material/package-variant-closed
---

# 构建与打包总览

这篇现在只保留为**兼容入口页**。
详细步骤已经按平台拆开，避免“开发”和“打包”内容混在一页里。

请按目标平台进入：

| 场景 | 对应文档 |
|------|----------|
| 从 Linux 源码环境产出 `Beacon-linux-x64.tar.gz` | [Linux 构建与打包](build-and-package-linux.md) |
| 从 Windows 源码环境产出 `Beacon-windows-x64.zip` 或安装包素材 | [Windows 构建与打包](build-and-package-windows.md) |

当前拆分原则如下：

- 本机开发文档：讲怎么把源码环境跑起来、怎么联调
- 构建与打包文档：讲怎么从已可运行的源码环境产出交付件
- 用户部署文档：讲拿到交付件后怎么安装、配置、授权和验收

相关入口：

- Linux 本机开发：参见 [local-linux.md](local-linux.md)
- Windows 本机开发：参见 [local-windows.md](local-windows.md)
- Linux 用户部署：参见 [linux.md](linux.md)
- Windows 用户部署：参见 [windows.md](windows.md)
