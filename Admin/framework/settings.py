"""
Django settings for framework project.

Maintained for Django 5.2 LTS.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path
import os
import secrets
import time
from typing import List, Optional

from framework.versioning import get_project_version
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_UA = "admin"
PROJECT_BUILT = "admin built on 2026/02/27"
PROJECT_VERSION = get_project_version(BASE_DIR.parent)
PROJECT_FLAG = "open"
PROJECT_ADMIN_START_TIMESTAMP = int(time.time()) # 软件启动时间戳（秒单位）
TIMEOUT = 30

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

def _env_bool(name: str, default: bool = False) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_csv(name: str, default: Optional[List[str]] = None) -> List[str]:
    """读取环境变量并拆分为列表。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]

def _env_str(name: str, default: str = "") -> str:
    """读取环境变量并转换为字符串。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip()

def _env_int(name: str, default: int = 0, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """读取环境变量并转换为整数。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        value = int(default)
    else:
        try:
            value = int(str(raw).strip())
        except Exception:
            value = int(default)
    if min_value is not None:
        value = max(int(min_value), value)
    if max_value is not None:
        value = min(int(max_value), value)
    return int(value)


# SECURITY WARNING: keep the secret key used in production secret!
def _load_or_generate_dev_secret_key(path: Path) -> str:
    """加载`or``generate``dev``secret`键。
    
    Dev-only secret key persistence:
        - Avoid hard-coding secrets in the repo.
        - Keep the key stable across restarts for local sessions/cookies.
    """
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except Exception:
        pass

    key = secrets.token_urlsafe(48)
    try:
        path.write_text(key, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return key

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("BEACON_DJANGO_DEBUG", default=True)

SECRET_KEY = _env_str("BEACON_DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = _load_or_generate_dev_secret_key(BASE_DIR / ".beacon_dev_secret_key")
    else:
        raise RuntimeError("BEACON_DJANGO_SECRET_KEY must be set when BEACON_DJANGO_DEBUG=0")

ALLOWED_HOSTS = _env_csv("BEACON_DJANGO_ALLOWED_HOSTS", default=(["*"] if DEBUG else []))

if not DEBUG:
    if SECRET_KEY.startswith("django-insecure-") or len(str(SECRET_KEY)) < 32:
        raise RuntimeError("BEACON_DJANGO_SECRET_KEY must be a strong random value when BEACON_DJANGO_DEBUG=0")
    if not ALLOWED_HOSTS:
        raise RuntimeError("BEACON_DJANGO_ALLOWED_HOSTS must be set when BEACON_DJANGO_DEBUG=0")
    if "*" in ALLOWED_HOSTS:
        raise RuntimeError("BEACON_DJANGO_ALLOWED_HOSTS must not contain '*' when BEACON_DJANGO_DEBUG=0")


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app.apps.AppConfig'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'app.middleware.OpenApiCsrfBypassMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'app.middleware.IframeEmbedMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "app.middleware.SimpleMiddleware",  # 配置拦截器
]

ROOT_URLCONF = 'framework.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR,'templates')
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'app.context_processors.branding',
            ],
        },
    },
]

WSGI_APPLICATION = 'framework.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'Admin.sqlite3',
        # 工业交付：SQLite 在多线程/多并发场景下容易出现 "database is locked"。
        # 通过增加 timeout 让写锁等待更久（单位：秒），并配合 connection_created PRAGMA（见 app.apps）。
        "OPTIONS": {
            "timeout": _env_int("BEACON_SQLITE_TIMEOUT_SECONDS", default=30, min_value=1, max_value=300),
        },
    }
}

# Optional SQLite DB path override (useful for CI / dev smoke tests).
_sqlite_db_path = str(os.environ.get("BEACON_SQLITE_DB_PATH", "") or "").strip()
if _sqlite_db_path:
    try:
        DATABASES["default"]["NAME"] = _sqlite_db_path
    except Exception:
        pass

# Cloud SaaS v1: optional DB override (recommended for cloud deployments).
# Example: BEACON_CLOUD_DB_URL=postgres://user:pass@host:5432/dbname
_cloud_db_url = str(os.environ.get("BEACON_CLOUD_DB_URL", "") or "").strip()
if _cloud_db_url:
    from app.utils.DbUrl import parse_database_url

    try:
        DATABASES = {"default": parse_database_url(_cloud_db_url)}
    except Exception as e:
        raise RuntimeError(f"invalid BEACON_CLOUD_DB_URL: {e}")


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

USE_I18N = True

USE_L10N = True

USE_TZ = False


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'


""" 新增配置 """
STATICFILES_DIRS = (
    os.path.join(BASE_DIR, "static"),
)
# 不拦截的 URL 配置
SESSION_COOKIE_NAME = 'v3_sessionid' # 自定义sessionid名称
SESSION_COOKIE_AGE = _env_int(
    "BEACON_SESSION_COOKIE_AGE_SECONDS",
    default=7 * 24 * 60 * 60,
    min_value=60,
    max_value=3650 * 24 * 60 * 60,
)  # session过期，单位（秒） 7天=7*24*60*60，1小时=1*60*60
SESSION_EXPIRE_AT_BROWSER_CLOSE=False #会话cookie可以在用户浏览器中保持有效期  True：关闭浏览器则Cookie失效。

# Production security knobs (opt-in via env, but safe defaults when DEBUG=0)
SESSION_COOKIE_SECURE = _env_bool("BEACON_DJANGO_SESSION_COOKIE_SECURE", default=(not DEBUG))
CSRF_COOKIE_SECURE = _env_bool("BEACON_DJANGO_CSRF_COOKIE_SECURE", default=(not DEBUG))
SECURE_SSL_REDIRECT = _env_bool("BEACON_DJANGO_SECURE_SSL_REDIRECT", default=False)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if _env_bool(
    "BEACON_DJANGO_TRUST_X_FORWARDED_PROTO", default=False
) else None
SECURE_HSTS_SECONDS = _env_int(
    "BEACON_DJANGO_HSTS_SECONDS",
    default=0,
    min_value=0,
    max_value=2 * 365 * 24 * 60 * 60,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("BEACON_DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = _env_bool("BEACON_DJANGO_HSTS_PRELOAD", default=False)
CSRF_TRUSTED_ORIGINS = _env_csv("BEACON_DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField' # 设置Model的主键自增

# ========== Logging（工业交付：可观测性基础能力）==========
# BEACON_LOG_LEVEL / BEACON_LOG_FORMAT 在 `.env*.example` 中有逐行中文注释说明。

_log_level = _env_str("BEACON_LOG_LEVEL", "INFO").upper() or "INFO"
if _log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    _log_level = "INFO"

_log_format = _env_str("BEACON_LOG_FORMAT", "text").lower() or "text"
if _log_format not in ("text", "json"):
    _log_format = "text"

_log_to_file = _env_bool("BEACON_LOG_TO_FILE", default=False)
_log_dir = _env_str("BEACON_LOG_DIR", str(BASE_DIR / "logs"))
_log_file_max_mb = _env_int("BEACON_LOG_FILE_MAX_MB", default=50, min_value=1, max_value=1024)
_log_file_backup_count = _env_int("BEACON_LOG_FILE_BACKUP_COUNT", default=10, min_value=1, max_value=100)
_log_file_retention_days = _env_int("BEACON_LOG_FILE_RETENTION_DAYS", default=0, min_value=0, max_value=3650)
_log_formatter_name = "json" if _log_format == "json" else "text"
_log_file_path = os.path.join(_log_dir, "admin.log")
if _log_to_file:
    try:
        os.makedirs(_log_dir, exist_ok=True)
    except Exception:
        # Must not break startup due to filesystem permissions.
        _log_to_file = False

_log_file_rotation_config = {}
if int(_log_file_retention_days or 0) > 0:
    _log_file_rotation_config = {
        "class": "logging.handlers.TimedRotatingFileHandler",
        "when": "midnight",
        "interval": 1,
        "backupCount": int(_log_file_retention_days),
    }
else:
    _log_file_rotation_config = {
        "class": "logging.handlers.RotatingFileHandler",
        "maxBytes": int(_log_file_max_mb) * 1024 * 1024,
        "backupCount": int(_log_file_backup_count),
    }

_log_file_handler_config = {}
if _log_to_file:
    _log_file_handler_config = {
        "file": {
            **_log_file_rotation_config,
            "level": _log_level,
            "formatter": _log_formatter_name,
            "filename": _log_file_path,
            "encoding": "utf-8",
        }
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "text": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
        "json": {
            "()": "app.utils.JsonLogFormatter.JsonLogFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": _log_level,
            "formatter": _log_formatter_name,
        },
        **_log_file_handler_config,
    },
    "root": {
        "handlers": ["console"] + (["file"] if _log_to_file else []),
        "level": _log_level,
    },
}
