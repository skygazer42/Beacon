# Beacon README 图像资料包 v1.0.0

本目录和仓库 <code>docs/</code> 用于制作 README 的品牌图、产品图和架构图。所有文字与结构必须以当前代码和文档为准，不补写尚未实现的能力。

## 现有素材

| 素材 | 用途 |
|---|---|
| <code>product-dashboard.png</code> | 当前 Edge 控制台实拍，主机标识与运行值已匿名化 |
| <code>hero-candidate.png</code> | 横向品牌首图候选；确认 Logo 细节后再用于 README |
| <code>../architecture.svg</code> | 当前三进程架构参考 |
| <code>../logo.svg</code> | 可编辑矢量 Logo 参考 |
| <code>../branding/readme-brand.png</code> | 现有横向品牌图参考 |
| <code>../branding/logo-icon.png</code> | 当前产品图标参考，不应把透明棋盘格画进新图 |

## 需要重新制作的三类图

### 1. 品牌首图

- 建议尺寸：<code>1600 × 480</code>，同时提供高分辨率 PNG/WebP。
- 内容：Beacon 标志、产品名“Beacon 新一代 AI 视频分析系统”、一句短描述。
- 风格：可信、克制、偏工程产品；避免复杂光效、伪 3D 和大段装饰文字。
- 不写性能数字、客户名称、默认账号或未验证的硬件能力。

### 2. 产品图

- 以 <code>product-dashboard.png</code> 为唯一 UI 依据，可裁切、加统一背景或设备边框。
- 不重新绘制不存在的页面；截图中的匿名演示值不作为性能指标。
- 建议输出 <code>1600 × 900</code>，正文中保持文字可读。

### 3. 架构图

- 建议尺寸：<code>1600 × 900</code>，优先输出 SVG，再导出 PNG/WebP。
- 必须表达：视频源 → MediaServer → Analyzer → Admin → Webhook / Beacon Cloud。
- Admin：Django 5.2 + React，端口 <code>9991</code>。
- MediaServer：ZLMediaKit 体系，HTTP <code>9992</code>、RTSP <code>9994</code>、RTMP <code>9995</code>。
- Analyzer：C++17，端口 <code>9993</code>。
- 数据库只写 SQLite / PostgreSQL；告警出口只写 Webhook / Beacon Cloud。

## 不要出现

- “无状态微服务”“任意横向扩容”等当前不成立的描述。
- Django 4.2、10091 端口，或已停用的 MQTT / Kafka / SNMP / Syslog / 邮件出口。
- “20+ 路”“亚秒级”“100% 准确率”等未经统一基准验证的数字。
- 模型权重、客户数据、真实主机名、Token、密码或授权密钥。

## 推荐交付文件名

    docs/assets/readme/hero.webp
    docs/assets/readme/product-overview.webp
    docs/assets/readme/architecture.svg
    docs/assets/readme/logo.svg

新图验收后再替换 README 引用；当前 README 继续使用仓库内可验证的 Logo、实拍产品图和架构 SVG。
