from urllib.parse import unquote, urlparse


def parse_database_url(db_url: str) -> dict:
    """
    解析形如 `postgres://user:pass@host:5432/dbname` 的连接串，转换为 Django DATABASES['default'] 配置。

    设计目标：
    - 仅用于 Cloud 部署（docker / SaaS），避免在 settings.py 内写一堆解析逻辑
    - 失败时直接抛 ValueError，调用方决定是否降级
    """
    raw = str(db_url or "").strip()
    if not raw:
        raise ValueError("db_url is empty")

    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()

    if scheme in ("postgres", "postgresql"):
        engine = "django.db.backends.postgresql"
    else:
        raise ValueError(f"unsupported db scheme: {scheme}")

    name = unquote(str(parsed.path or "").lstrip("/"))
    if not name:
        raise ValueError("database name is missing")

    host = str(parsed.hostname or "").strip()
    user = unquote(str(parsed.username or "").strip())
    password = unquote(str(parsed.password or "").strip())
    try:
        port = str(parsed.port) if parsed.port else ""
    except Exception as e:
        raise ValueError(f"invalid port: {e}")

    if not host:
        raise ValueError("db host is missing")

    return {
        "ENGINE": engine,
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
    }

