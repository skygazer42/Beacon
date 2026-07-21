# JavaScript SDK

## 安装

从 Beacon 仓库根目录安装本地包：

```bash
npm install ./sdk/javascript
```

当前未向 npm 发布，请勿安装公共仓库中的同名包，也不要使用第三方 CDN 地址。

## 使用

```javascript
import { BeaconClient } from '@skygazer42/beacon-sdk';

const client = new BeaconClient('http://localhost:9991', {
  openApiToken: 'replace-with-open-api-token',
});

const streams = await client.getStreamData();
for (const stream of streams) {
  console.log(stream.code, stream.name);
}
```

直接从源码引用时可使用 `sdk/javascript/beacon-sdk.mjs`。完整方法列表见 [`sdk/javascript/README.md`](https://github.com/skygazer42/Beacon/blob/main/sdk/javascript/README.md)。
