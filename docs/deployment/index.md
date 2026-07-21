---
title: 部署总览
icon: material/rocket-launch
---

# 部署总览

本文档用于区分两类使用场景：

1. **用户 / 实施 / 运维**：目标是完成安装、启动、授权配置和交付验收。
2. **开发者**：目标是完成代码修改、接口调试和全链路联调。

未区分这两个角色时，常见问题如下：

- 用户跑了开发命令，环境越装越乱。
- 开发者照着交付步骤走，改代码和编译效率很低。

---

## 先按角色选

| 当前场景 | 对应文档 |
|----------------|----------------|
| 源码方式在 Linux 本机开发与联调 | [Linux 本机开发](local-linux.md) |
| 源码方式在 Windows 本机开发与联调 | [Windows 本机开发](local-windows.md) |
| 从 Linux 源码构建交付包、生成 `.so`、组装 `Beacon-linux-x64.tar.gz` | [Linux 构建与打包](build-and-package-linux.md) |
| 集中查看 Linux 运行库、机器类型矩阵、`runtime-libs`、`LD_LIBRARY_PATH` | [Linux 运行库参考](linux-runtime-libs.md) |
| 从 Windows 源码构建交付包、生成 DLL、组装 `Beacon-windows-x64.zip` 或安装包素材 | [Windows 构建与打包](build-and-package-windows.md) |
| 集中查看 Windows `Analyzer\3rdparty`、DLL 收集、前置安装项 | [Windows 运行库参考](windows-runtime-libs.md) |
| 交付包部署到 Linux 机器 | [Linux 用户部署](linux.md) |
| 交付包部署到 Windows 机器 | [Windows 用户部署](windows.md) |
| 数字人采集端直连 Beacon 联调 | [数字人运行时接入](digital-human-runtime.md) |

Linux 交付部署当前标准形态通常为 `Beacon-linux-x64.tar.gz` 或已解压运行目录，而不是 `.deb`、`.rpm` 或一键安装器。

---

## 再按系统选

推荐阅读顺序统一为：

1. 本机开发
2. 构建与打包
3. 运行库核对
4. 用户部署

### 开发者

开发场景通常对应源码仓库，而非交付包。

开发者文档覆盖以下内容：

- 后端 Python 环境怎么建
- 前端 `npm run build` 什么时候要跑
- `Analyzer` 怎么编译
- `MediaServer` 怎么接入
- 只跑 `Admin` 怎么做
- 全栈联调怎么验活

入口：

- Linux: [local-linux.md](local-linux.md)
- Windows: [local-windows.md](local-windows.md)

### 用户 / 实施 / 运维

该角色通常不需要自行编译 C++ 组件。

标准交付物建议为完整运行目录，例如：

```text
Beacon/
  config.json
  Admin/
  Analyzer/
  MediaServer/
  data/
    models/
    upload/
```

相关文档覆盖以下内容：

- 第一步把包解压到哪里
- 第二步改哪个配置
- 第三步怎么放模型
- 第四步怎么导入授权
- 第五步怎么启动
- 第六步怎么验收

入口：

- Linux: [linux.md](linux.md)
- Windows: [windows.md](windows.md)

---

## 先理解项目结构

Beacon 不是单一服务，而是三个组件一起工作：

| 组件 | 作用 | 默认端口 |
|------|------|----------|
| `Admin/` | 页面、配置、OpenAPI、授权导入、运维 | `9991` |
| `MediaServer/` | 视频流接入、转发、播放 | `9992` / `9994` / `9995` |
| `Analyzer/` | 推理、布控执行、告警生成 | `9993` |

仅查看页面时，保证 `Admin` 正常运行即可。
完整业务闭环场景，即“视频接入 -> 分析处理 -> 产生告警 -> 页面展示结果”，要求三个组件全部正常。

---

## 先理解两种使用方式

### 方式一：源码开发模式

适用于研发环境。

特点：

- 直接在仓库里运行
- 会创建 Python 虚拟环境
- 会自己编译前端
- 会自己编译 `Analyzer`
- 会自己处理 `MediaServer` 二进制或源码构建

对应文档：

- [Linux 本机开发](local-linux.md)
- [Windows 本机开发](local-windows.md)

### 方式二：交付部署模式

适合客户现场、测试环境、生产环境。

特点：

- 优先使用交付包，不让客户自己编译
- 只做配置、授权、启动、验收
- 需要把模型和运行库放到约定目录

对应文档：

- [Linux 用户部署](linux.md)
- [Windows 用户部署](windows.md)

---

## 标准授权方式

当前项目支持社区模式和三种商业授权模式：

| 模式 | 配置值 | 适用情况 |
|------|--------|----------|
| 社区模式 | `licenseType=community` | 开源默认，不启用运行授权门禁 |
| 机器码授权 | `licenseType=machine` | 单机、最简单的离线授权 |
| 加密锁授权 | `licenseType=dongle` | 必须依赖硬件锁的项目 |
| 授权池授权 | `licenseType=pool` 或 `manager` | 正式商业交付，推荐默认方案 |

新部署项目建议优先使用 **授权池授权**，即：

```text
客户机器配置公钥和 cluster_id
客户在后台导入签名后的 license.json
Analyzer 启动布控时向 Admin 申请租约
```

这套流程已经在当前代码里闭环了。

---

## 常用文档入口

| 场景 | 文档 |
|------|------|
| Linux 本机开发与联调 | [local-linux.md](local-linux.md) |
| Windows 本机开发与联调 | [local-windows.md](local-windows.md) |
| Linux 构建交付包 | [build-and-package-linux.md](build-and-package-linux.md) |
| Linux 运行库参考 | [linux-runtime-libs.md](linux-runtime-libs.md) |
| Windows 构建交付包 | [build-and-package-windows.md](build-and-package-windows.md) |
| Windows 运行库参考 | [windows-runtime-libs.md](windows-runtime-libs.md) |
| Linux 用户部署 | [linux.md](linux.md) |
| Windows 用户部署 | [windows.md](windows.md) |
| 数字人运行时接入 | [digital-human-runtime.md](digital-human-runtime.md) |
| 更底层的 Edge 全栈部署说明 | [../deploy/edge-full-stack.md](../deploy/edge-full-stack.md) |
| Linux 全栈实操清单 | [Linux 本机开发](local-linux.md) |
| 二进制交付目录规范 | [../deploy/delivery-layout.md](../deploy/delivery-layout.md) |
| 配置字段说明 | [../deploy/config-reference.md](../deploy/config-reference.md) |
| 服务托管方式 | [../deploy/service-management.md](../deploy/service-management.md) |
| 端到端验收 | [../deploy/e2e-acceptance.md](../deploy/e2e-acceptance.md) |

---

## 文档选用建议

仍需判断文档入口时，可按以下原则选择：

- 后台页面和接口开发：看 [Linux 本机开发](local-linux.md) 或 [Windows 本机开发](local-windows.md)，并先只跑 `Admin`
- 需要产出交付包：看 [Linux 构建与打包](build-and-package-linux.md) 或 [Windows 构建与打包](build-and-package-windows.md)
- 需要核对 Linux `.so`、机器类型和 `LD_LIBRARY_PATH`：看 [Linux 运行库参考](linux-runtime-libs.md)
- 需要核对 Windows `Analyzer\3rdparty`、DLL 和前置安装项：看 [Windows 运行库参考](windows-runtime-libs.md)
- 仅需安装使用：看 [Linux 用户部署](linux.md) 或 [Windows 用户部署](windows.md)
- 想验证完整分析链路：先按开发者文档把本机环境跑通，再看 [../deploy/e2e-acceptance.md](../deploy/e2e-acceptance.md)
- 仅需快速查看页面：可直接走 Docker 快速体验，见 [docker.md](docker.md)
