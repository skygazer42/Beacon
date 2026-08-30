from urllib.parse import parse_qs, unquote, urlparse


_ALLOWED_QUERY_PARAMETERS = frozenset(
    {
        "application_name",
        "connect_timeout",
        "sslcert",
        "sslkey",
        "sslmode",
        "sslrootcert",
        "target_session_attrs",
    }
)
_ALLOWED_SSL_MODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
_ALLOWED_TARGET_SESSION_ATTRS = frozenset(
    {"any", "read-write", "read-only", "primary", "standby", "prefer-standby"}
)


def _single_query_value(query: dict, name: str) -> str:
    values = query.get(name) or []
    if len(values) != 1:
        raise ValueError(f"database URL parameter {name} must appear exactly once")
    value = str(values[0] or "").strip()
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"database URL parameter {name} is invalid")
    return value


def _parse_database_options(parsed) -> dict:
    query = (
        parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if parsed.query
        else {}
    )
    unknown = sorted(set(query) - _ALLOWED_QUERY_PARAMETERS)
    if unknown:
        raise ValueError(f"unsupported database URL parameter: {unknown[0]}")

    options = {"connect_timeout": 10}
    for name in sorted(query):
        value = _single_query_value(query, name)
        if name == "connect_timeout":
            try:
                timeout = int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("database connect_timeout must be an integer") from exc
            if not (1 <= timeout <= 60):
                raise ValueError("database connect_timeout must be between 1 and 60")
            options[name] = timeout
        elif name == "sslmode":
            normalized = value.lower()
            if normalized not in _ALLOWED_SSL_MODES:
                raise ValueError("database sslmode is invalid")
            options[name] = normalized
        elif name == "target_session_attrs":
            normalized = value.lower()
            if normalized not in _ALLOWED_TARGET_SESSION_ATTRS:
                raise ValueError("database target_session_attrs is invalid")
            options[name] = normalized
        else:
            options[name] = value
    return options


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
        "OPTIONS": _parse_database_options(parsed),
    }
