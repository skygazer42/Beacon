<div align="center">
  <img src="../docs/assets/branding/readme-brand.png" alt="Beacon" width="680"/>
</div>

# Beacon Admin

后台管理、配置中心与控制平面。

### 安装
| 程序         | 版本               |
| ---------- |------------------|
| python     | 3.10+            |
| 核心依赖库  | requirements-windows.txt (Windows) / requirements-linux.txt (Linux) |
| 可选依赖库  | requirements-optional.txt（OpenTelemetry、LDAP、Cloud S3） |

### 启动
~~~
//首次创建管理员（按提示设置密码）
python manage.py createsuperuser

//启动后台管理服务
python manage.py runserver 0.0.0.0:9991

~~~

### 部署模式（Edge / Cloud）

本仓库复用同一套 Django Admin 代码，通过环境变量 `BEACON_DEPLOYMENT_MODE=edge|cloud` 支持：

- `edge`（默认）：边缘/本地交付（On-Prem）。报警/布控/视频流管理等原有功能不变。
- `cloud`：Cloud SaaS v1（告警聚合 + 截图上云 S3 兼容 + 控制台查看）。

**Cloud SaaS v1 集成说明**：请看 `docs/integration/cloud-saas-v1.md`。

### Windows打包过程

~~~
python -m pip install -r requirements-build.txt

// 根据 manage.spec 文件 打包后台服务
pyinstaller manage.spec

//打包启动工具
pyinstaller -i logo.ico -F  VideoAnalyzer.py

~~~



### linux 创建python虚拟环境
~~~

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 更新虚拟环境的pip版本
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple

# 在虚拟环境中安装依赖库
python -m pip install -r requirements-linux.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 如果需要 OpenTelemetry、LDAP 或 Cloud S3，再安装可选依赖
python -m pip install -r requirements-optional.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

~~~

### windows 创建python虚拟环境
~~~
# 创建虚拟环境
python -m venv venv

# 切换到虚拟环境
venv\Scripts\activate

# 更新虚拟环境的pip版本
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple

# 在虚拟环境中安装依赖库
python -m pip install -r requirements-windows.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 如果需要 OpenTelemetry、LDAP 或 Cloud S3，再安装可选依赖
python -m pip install -r requirements-optional.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

~~~

### 可选功能说明

系统保留以下告警出口：

| 功能 | 依赖库 | 配置项 | 说明 |
|-----|-------|-------|------|
| Webhook 报警推送 | requests（核心依赖已包含） | alarmWebhookEnabled=true / alarmWebhookUrls=[...] | 将报警事件以 HTTP POST 推送到外部系统（支持签名） |
| Cloud SaaS v1（S3 presign） | boto3==1.34.162 | `BEACON_DEPLOYMENT_MODE=cloud` + S3 env | 云端生成 presigned PUT/GET，让边缘截图直传对象存储 |

Webhook 不需要可选依赖；未启用 LDAP、Cloud S3 或 OpenTelemetry 时可跳过 `requirements-optional.txt`。
