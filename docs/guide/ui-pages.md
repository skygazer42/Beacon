<div align="center">
  <img src="../assets/branding/readme-brand.png" alt="Beacon" width="720"/>
</div>

# 页面与路由导览

下面这些都是当前 `Admin` 在 `9991` 上已经存在的前端页面，不是只剩后端接口。可作为验收功能、排查“页面能不能打开”时的对照表。

> 返回：[仓库 README](https://github.com/skygazer42/Beacon#readme) · [使用指南](index.md)

## 左侧主导航

| 分组 | 页面 | 路由 | 说明 |
|------|------|------|------|
| 核心入口 | 系统总览 | `/` | 设备、节点、任务、服务与模型状态 |
| 核心入口 | 视频资源 | `/stream/index` | 视频源接入、编辑、启停与转发 |
| 核心入口 | 大屏监控 | `/screen/index` | 多画面预览、窗口分配与告警联动 |
| 核心入口 | 告警中心 | `/alarms` | 告警筛选、批量处置与详情入口 |
| 核心入口 | 布控中心 | `/controls` | 布控任务列表、启停与编辑 |
| 视频与算法 | 录像管理 | `/recording/manager` | 录像检索与回放 |
| 视频与算法 | 算法管理 | `/algorithm/index` | 算法列表、版本、加载与测试 |
| 视频与算法 | 人脸库管理 | `/face/index` | 人脸条目、分组、搜索与分页 |
| 云中心 | 云边连接 | `/cloud/edge-clusters` | 云端登记边缘集群并验证连接 |
| 云中心 | 云端告警 | `/cloud/alarms` | 聚合边缘告警并查看详情 |
| 云中心 | 云端权限 | `/cloud/iam` | 云租户、项目、成员与权限 |
| 云中心 | 数字人监管 | `/digital-human/dashboard` | 数字人终端、告警、日志与设置；仅管理员可见 |
| 平台运维 | 平台概览 | `/ops/platform` | 节点、进程与资源状态 |
| 平台运维 | 诊断中心 | `/ops/diagnostics` | 健康检查、诊断操作与诊断导出 |
| 平台运维 | 日志中心 | `/ops/audit` | 审计记录与操作追踪 |
| 平台运维 | 升级中心 | `/ops/upgrade` | 升级包上传、校验、应用与回滚 |
| 平台运维 | 设备扫描 | `/onvif/discover` | ONVIF 设备发现与接入 |
| 系统管理 | 系统设置 | `/config/system` | 系统参数与运行配置 |
| 系统管理 | 账号权限 | `/user/manage` | 用户与功能权限配置 |
| 系统管理 | 授权管理 | `/license/manager` | 许可证导入与状态诊断 |
| 系统管理 | API 安全 | `/ops/apikeys` | API Key 与作用域管理 |
| 系统管理 | 开发入口 | `/developer/index` | OpenAPI 与集成信息 |
| 系统管理 | 告警声管理 | `/alarm_sound/index` | 告警提示音资源管理 |

菜单会根据登录用户权限隐藏部分入口；云端页面还需要按部署文档完成云模式初始化。

## 关键扩展页面

| 类别 | 页面 | 路由 | 说明 |
|------|------|------|------|
| 账号 | 个人资料 | `/profile` | 资料、密码与 TOTP 设置 |
| 告警 | 告警审核 | `/alarm/review` | 复用告警中心并打开审核筛选 |
| 告警 | 告警详情 | `/alarm/detail` | 单条告警、媒体、处置与证据导出 |
| 视频 | 新建 / 编辑视频源 | `/stream/add`、`/stream/edit` | 维护视频源参数 |
| 视频 | 单流 / 多流播放器 | `/stream/player`、`/stream/multi` | 播放链路验证 |
| 布控 | 新建 / 编辑布控 | `/control/add`、`/control/edit` | 绑定视频流、算法与检测区域 |
| 布控 | 分析日志 | `/control/logs` | 布控执行记录 |
| 算法 | 新建 / 编辑算法 | `/algorithm/add`、`/algorithm/edit` | 维护模型与算法参数 |
| 算法 | 算法版本 | `/algorithm/versions` | 版本列表与状态管理 |
| 配置 | 导入 / 导出 / 历史 | `/config/import`、`/config/export`、`/config/history` | 复用系统设置中的对应工作区 |
| 云端 | 远程流 / 录像 / 平台 | `/cloud/remote/streams`、`/cloud/remote/recordings`、`/cloud/remote/platform` | 查看已接入边缘集群的远程资源 |
| 数字人 | 设备 / 告警 / 日志 / 报告 / 设置 | `/digital-human/*` | 管理员使用的数字人监管子页面 |
