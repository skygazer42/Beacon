# Go SDK

## 安装

```bash
go get github.com/skygazer42/Beacon/sdk/go@main
```

## 使用

```go
package main

import (
	"fmt"
	"log"

	beaconsdk "github.com/skygazer42/Beacon/sdk/go"
)

func main() {
	client, err := beaconsdk.NewClient(
		"http://localhost:9991",
		beaconsdk.WithOpenAPIToken("replace-with-open-api-token"),
	)
	if err != nil {
		log.Fatal(err)
	}

	streams, err := client.GetStreamData("")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(streams)
}
```

完整方法列表和测试命令见 [`sdk/go/README.md`](https://github.com/skygazer42/Beacon/blob/main/sdk/go/README.md)。
