import os
import sys
import logging
import threading
import time
from django.apps import AppConfig as DjangoAppConfig

from app.utils.BackgroundRoles import get_background_role


logger = logging.getLogger(__name__)

_background_bootstrap_lock = threading.Lock()
_background_bootstrap_scheduled = False

_SKIP_BACKGROUND_COMMANDS = {
    "test",
    "check",
    "help",
    "migrate",
    "makemigrations",
    "collectstatic",
    "shell",
    "prepare_cloud_runtime",
    "run_background_worker",
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


def _should_skip_background_services(argv, *, role: str = None) -> bool:
    """判断`skip``background``services`。"""
    try:
        resolved_role = role or get_background_role()
        if resolved_role in {"worker", "init", "disabled"}:
            return True
        return bool(len(argv) > 1 and argv[1] in _SKIP_BACKGROUND_COMMANDS)
    except Exception:
        raise


def _start_background_services_best_effort(*, role: str = None) -> None:
    """尽力处理起始`background``services`。"""
    from app.utils.BackgroundServices import start_background_services

    try:
        start_background_services(role=role or get_background_role())
    except Exception as e:
        if os.environ.get("DJANGO_DEBUG_STARTUP_LOGS") == "1":
            logger.exception("AppConfig.ready() start_background_services error")
        else:
            logger.exception("AppConfig.ready() start_background_services error: %s", e)


def _start_background_services_after_registry_ready(
    apps_registry=None,
    sleep=time.sleep,
    *,
    role: str = None,
) -> None:
    """Start background services only after Django finishes app population."""
    if apps_registry is None:
        from django.apps import apps as apps_registry

    while not apps_registry.ready:
        sleep(0.01)
    _start_background_services_best_effort(role=role or get_background_role())


def _schedule_background_services_best_effort(*, role: str = None) -> None:
    """Schedule one post-registry background-service bootstrap per process."""
    global _background_bootstrap_scheduled

    with _background_bootstrap_lock:
        if _background_bootstrap_scheduled:
            return
        _background_bootstrap_scheduled = True

    resolved_role = role or get_background_role()
    try:
        thread = threading.Thread(
            target=_start_background_services_after_registry_ready,
            name="beacon-background-bootstrap",
            daemon=True,
            kwargs={"role": resolved_role},
        )
        thread.start()
    except Exception as exc:
        with _background_bootstrap_lock:
            _background_bootstrap_scheduled = False
        if os.environ.get("DJANGO_DEBUG_STARTUP_LOGS") == "1":
            logger.exception("Unable to schedule background services")
        else:
            logger.error(
                "Unable to schedule background services: %s",
                type(exc).__name__,
            )


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
        role = get_background_role()
        if _should_skip_background_services(sys.argv, role=role):
            return
        _schedule_background_services_best_effort(role=role)
