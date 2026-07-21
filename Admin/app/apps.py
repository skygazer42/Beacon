import os
import sys
import logging
from django.apps import AppConfig as DjangoAppConfig


logger = logging.getLogger(__name__)

_SKIP_BACKGROUND_COMMANDS = {
    "test",
    "check",
    "migrate",
    "makemigrations",
    "collectstatic",
    "shell",
}


def _exec_pragma_best_effort(cursor, sql: str) -> None:
    """尽力执行 PRAGMA 语句。"""
    try:
        cursor.execute(sql)
    except Exception:
        pass


def _apply_sqlite_pragmas(sender, connection, **kwargs):  # type: ignore
    """处理应用SQLitePRAGMA 配置。"""
    try:
        if getattr(connection, "vendor", "") != "sqlite":
            return
        with connection.cursor() as cursor:
            # WAL improves concurrency: readers don't block writers.
            _exec_pragma_best_effort(cursor, "PRAGMA journal_mode=WAL;")
            # Normal is a good balance for edge devices; FULL is safer but slower.
            _exec_pragma_best_effort(cursor, "PRAGMA synchronous=NORMAL;")
            # Wait up to 30s when the database is locked.
            _exec_pragma_best_effort(cursor, "PRAGMA busy_timeout=30000;")
            # Keep FK constraints on (Django already does, but keep it explicit).
            _exec_pragma_best_effort(cursor, "PRAGMA foreign_keys=ON;")
    except Exception:
        return


def _install_sqlite_pragmas_best_effort() -> None:
    """尽力应用 SQLite PRAGMA 配置。"""
    from django.db.backends.signals import connection_created

    try:
        connection_created.connect(_apply_sqlite_pragmas, dispatch_uid="beacon_sqlite_pragmas")
    except Exception:
        pass


def _init_otel_best_effort() -> None:
    """尽力处理`init``otel`。"""
    from app.utils.Otel import init_otel

    try:
        init_otel()
    except Exception as e:
        # Must not break startup due to observability features.
        if os.environ.get("DJANGO_DEBUG_STARTUP_LOGS") == "1":
            logger.exception("AppConfig.ready() init_otel error")
        else:
            logger.warning("AppConfig.ready() init_otel error: %s", e)


def _should_skip_background_services(argv) -> bool:
    """判断`skip``background``services`。"""
    try:
        return bool(len(argv) > 1 and argv[1] in _SKIP_BACKGROUND_COMMANDS)
    except Exception:
        return False


def _start_background_services_best_effort() -> None:
    """尽力处理起始`background``services`。"""
    from app.utils.BackgroundServices import start_background_services

    try:
        start_background_services()
    except Exception as e:
        if os.environ.get("DJANGO_DEBUG_STARTUP_LOGS") == "1":
            logger.exception("AppConfig.ready() start_background_services error")
        else:
            logger.exception("AppConfig.ready() start_background_services error: %s", e)


class AppConfig(DjangoAppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        # ========= SQLite multi-thread safety hardening =========
        # Best-effort: set WAL + busy_timeout so concurrent readers/writers are less likely to hit
        # "database is locked" in real deployments.
        # Notes:
        # - Django tests may run with an in-memory sqlite URL; WAL may not be supported there.
        # - We intentionally swallow all errors here; this must never break startup.
        """处理`ready`。"""
        _install_sqlite_pragmas_best_effort()
        # ========================================================

        # ========= OpenTelemetry tracing (optional; best-effort) =========
        # Keep this early so request instrumentation is active before other services start.
        _init_otel_best_effort()
        # ===============================================================

        # Avoid starting background threads during management commands (tests/migrations/etc.)
        if _should_skip_background_services(sys.argv):
            return
        _start_background_services_best_effort()
