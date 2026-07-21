# Beacon 反向代理部署（Nginx / HTTPS）

本文档提供 Beacon 在“工业交付/试运行/公网访问”场景下的反向代理部署口径，覆盖：

- Nginx 反向代理 Admin（Django）
- HTTPS/TLS 与 Django 安全相关 env
- 上传/升级包等大请求体的代理参数
- 反代场景下 OpenAPI 鉴权与源 IP 的注意事项

说明：

- 本文档以 Admin（默认 `adminPort=9991`）为主；Analyzer/MediaServer 的端口暴露策略建议按 `docs/deploy/security-hardening.md` 收敛。
- 生产部署建议使用 WSGI Server（gunicorn/uwsgi 等）承载 Django；仓库默认示例使用 `manage.py runserver`，需按交付方案决定是否替换。

---

## 1. 反向代理后的关键环境变量（Admin/Django）

反向代理（TLS 终止在 Nginx）时，建议显式配置：

- `BEACON_DJANGO_DEBUG=0`
- `BEACON_DJANGO_SECRET_KEY=<random>`
- `BEACON_DJANGO_ALLOWED_HOSTS=beacon.example.com`
- `BEACON_DJANGO_CSRF_TRUSTED_ORIGINS=https://beacon.example.com`
- `BEACON_DJANGO_TRUST_X_FORWARDED_PROTO=1`
- `BEACON_DJANGO_SECURE_SSL_REDIRECT=1`（可选：强制 HTTPS）
- `BEACON_DJANGO_SESSION_COOKIE_SECURE=1`
- `BEACON_DJANGO_CSRF_COOKIE_SECURE=1`

OpenAPI/Ops 建议：

- `BEACON_REQUIRE_OPEN_API_TOKEN=1`
- 通过 `BEACON_OPEN_API_TOKEN` 或 DB ApiKey(scope) 保护 `/open/*`、`/metrics` 等接口

原因说明：

- 反代后，应用侧看到的 `REMOTE_ADDR` 与协议（HTTP/HTTPS）可能与外部实际不一致；需通过 `X-Forwarded-Proto` 等 header 进行纠正，并禁止“loopback 误放行”。

---

## 2. Nginx 站点配置示例（仅代理 Admin）

示例目标：

- 外部访问：`https://beacon.example.com` -> 内部 `http://127.0.0.1:9991`
- 支持较大的请求体（升级包上传、导入文件等）
- 统一写入转发 header（Host/X-Real-IP/X-Forwarded-*）

示例配置（按实际证书与域名调整）：

```nginx
server {
    listen 443 ssl http2;
    server_name beacon.example.com;

    ssl_certificate     /etc/nginx/certs/beacon.crt;
    ssl_certificate_key /etc/nginx/certs/beacon.key;

    # 上传/升级包等接口可能包含较大请求体
    client_max_body_size 200m;

    # 代理超时按现场网络与上传大小调整
    proxy_connect_timeout 10s;
    proxy_send_timeout    300s;
    proxy_read_timeout    300s;

    location / {
        proxy_pass http://127.0.0.1:9991;

        # 保持原始 Host，便于 Django ALLOWED_HOSTS/CSRF 校验
        proxy_set_header Host $host;

        # 真实源地址（如部署链路存在多级代理，建议在最边界代理层进行统一治理）
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # TLS 终止在 Nginx 时，需透传协议
        proxy_set_header X-Forwarded-Proto $scheme;

        # 可选：透传 Request-Id 便于链路排障（如上游已携带 X-Request-Id）
        proxy_set_header X-Request-Id $http_x_request_id;
    }
}

server {
    listen 80;
    server_name beacon.example.com;
    return 301 https://$host$request_uri;
}
```

说明：

- `client_max_body_size` 需覆盖升级包上传接口（`/open/ops/upgrade/upload`）的最大包体；如升级包较大需按场景调高。
- 若启用 OIDC SSO，回调路径为 `/login/oidc/callback`，应确保可被正常代理并保持 `Host` 一致。

---

## 3. 同机部署下的“端口暴露建议”

常见同机场景：

- Admin：通过 Nginx 对外（443）
- Analyzer/MediaServer：仅本机/内网可达（避免直接暴露到公网）

建议：

- 安全组/防火墙层面仅放行 443（以及必要的媒体播放端口，按业务需要开放）
- OpenAPI/Ops 的 token 与 IP 策略作为应用层兜底（见 `docs/deploy/security-hardening.md`）

---

## 4. 反代场景下的源 IP 与登录安全注意事项

登录失败锁定（Login Lockout）默认使用 `REMOTE_ADDR` 作为源 IP。反代场景如需使用 `X-Real-IP`、`X-Forwarded-For` 或 RFC7239 `Forwarded`，需显式开启对应 trust 开关（见 `docs/deploy/security-hardening.md`）。

安全建议：

- 仅在反向代理层确保 header 不可被外部伪造时启用 trust 开关。
- 如无法确保 header 安全，建议保持默认（只信任 `REMOTE_ADDR`），并在网关层做访问控制与审计。
