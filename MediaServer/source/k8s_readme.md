# k8s部署建议

## 编译

- 方式一 

    可以自己写脚本编译

- 方式二

    可以使用自带`build_docker_images.sh`脚本编译，具体参见[部署](##部署)

## 部署
- 可以是用根目录下面build_docker_images.sh脚本进行编译与推送到指定仓库

    - 推送

        推送之前务必修改脚本中`镜像仓库用户名与仓库地址`。有需要也可以同时修改`命名空间与包名`。

    - 编译

        ```shell
        sh build_docker_images.sh [-t build|push] [-m Debug|Release] [-v [version]]
        -t: 指定编译类型，build 编译镜像 push 推送到指定仓库
        -m: 编译类型
        -v：版本号
        ```

- 如果需要自定义配置文件，可以使用`configMap`挂载到pod中`/opt/media/conf/`目录来覆盖默认配置文件
- 如需启用 TLS（HTTPS/WSS），请通过 Secret/ConfigMap 挂载证书到容器内，并在启动参数中显式指定 `-s /path/to/your.pem`（默认不启用 TLS）。
