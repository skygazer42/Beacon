# Python SDK

## 安装

从 Beacon 仓库根目录安装：

```bash
python -m pip install ./sdk/python
```

当前未向 PyPI 发布，请勿执行 `pip install beacon-sdk`。

## 使用

```python
from beacon_sdk import BeaconClient

client = BeaconClient(
    "http://localhost:9991",
    open_api_token="replace-with-open-api-token",
)

streams = client.get_stream_data()
for stream in streams:
    print(stream.get("code"), stream.get("name"))
```

登录态接口可先调用：

```python
client.login("admin", "your-password")
algorithms = client.get_algorithms()
```

完整方法列表和验证命令见 [`sdk/python/README.md`](https://github.com/skygazer42/Beacon/blob/main/sdk/python/README.md)。
