import json
import os
import signal
import tempfile
import threading
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app.utils.BackgroundRoles import get_background_role
from app.utils.PostgresAdvisoryLock import PostgresAdvisoryLock


BACKGROUND_WORKER_LOCK_ID = 47744514073166
DEFAULT_HEARTBEAT_PATH = "/tmp/beacon-background-worker.json"


class BackgroundWorkerRuntimeError(RuntimeError):
    pass


def _bounded_float(value, *, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not (minimum <= parsed <= maximum):
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def _heartbeat_path(value: str) -> Path:
    path = Path(str(value or DEFAULT_HEARTBEAT_PATH).strip())
    if not path.is_absolute():
        raise ValueError("background worker heartbeat path must be absolute")
    return path


def write_worker_heartbeat(
    path: Path,
    *,
    state: str,
    background_state: str,
    now=time.time,
) -> None:
    normalized_state = str(state or "").strip().lower()
    if normalized_state not in {"leader", "standby", "stopping"}:
        raise ValueError("background worker heartbeat state is invalid")
    target = _heartbeat_path(str(path))
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "role": "worker",
        "state": normalized_state,
        "background_state": str(background_state or "unknown"),
        "pid": os.getpid(),
        "updated_at": float(now()),
    }

    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def run_background_worker_loop(
    lock,
    stop_event: threading.Event,
    *,
    heartbeat_path: Path,
    heartbeat_interval_seconds: float,
    standby_poll_seconds: float,
    start_services,
    get_status,
    shutdown_services,
    write_heartbeat=write_worker_heartbeat,
    max_cycles=None,
) -> str:
    leader_started = False
    cycles = 0
    last_state = "standby"
    try:
        while not stop_event.is_set():
            cycles += 1
            if not lock.acquired:
                if not lock.try_acquire():
                    write_heartbeat(
                        heartbeat_path,
                        state="standby",
                        background_state="standby",
                    )
                    last_state = "standby"
                    if max_cycles is not None and cycles >= int(max_cycles):
                        break
                    stop_event.wait(standby_poll_seconds)
                    continue

                status = start_services(role="worker")
                # A degraded startup can still leave some components running.
                # Record ownership before validating so the finally block always
                # gives those components a chance to shut down cleanly.
                leader_started = True
                if str((status or {}).get("state") or "") != "running":
                    write_heartbeat(
                        heartbeat_path,
                        state="leader",
                        background_state=str((status or {}).get("state") or "degraded"),
                    )
                    raise BackgroundWorkerRuntimeError(
                        "singleton background services failed to start"
                    )
            lock.keepalive()
            status = get_status()
            background_state = str((status or {}).get("state") or "unknown")
            write_heartbeat(
                heartbeat_path,
                state="leader",
                background_state=background_state,
            )
            last_state = "leader"
            if background_state != "running":
                raise BackgroundWorkerRuntimeError(
                    "singleton background services became unhealthy"
                )
            if max_cycles is not None and cycles >= int(max_cycles):
                break
            stop_event.wait(heartbeat_interval_seconds)
    finally:
        if leader_started:
            shutdown_services()
        if lock.acquired:
            write_heartbeat(
                heartbeat_path,
                state="stopping",
                background_state="stopped",
            )
    return last_state


class Command(BaseCommand):
    help = "Run singleton Beacon background schedulers with PostgreSQL leader election"

    def handle(self, *args, **options):
        if get_background_role() != "worker":
            raise CommandError("BEACON_BACKGROUND_ROLE must be worker")
        dsn = str(os.environ.get("BEACON_CLOUD_DB_URL", "") or "").strip()
        if not dsn:
            raise CommandError("BEACON_CLOUD_DB_URL is required")
        try:
            heartbeat_path = _heartbeat_path(
                os.environ.get("BEACON_BACKGROUND_HEARTBEAT_PATH", DEFAULT_HEARTBEAT_PATH)
            )
            heartbeat_interval = _bounded_float(
                os.environ.get("BEACON_BACKGROUND_HEARTBEAT_SECONDS", "5"),
                name="BEACON_BACKGROUND_HEARTBEAT_SECONDS",
                minimum=1,
                maximum=30,
            )
            standby_poll = _bounded_float(
                os.environ.get("BEACON_BACKGROUND_STANDBY_POLL_SECONDS", "5"),
                name="BEACON_BACKGROUND_STANDBY_POLL_SECONDS",
                minimum=1,
                maximum=30,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        from app.utils.BackgroundServices import (
            get_background_services_status,
            shutdown_background_services,
            start_background_services,
        )

        stop_event = threading.Event()

        def request_stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        lock = PostgresAdvisoryLock(
            dsn,
            BACKGROUND_WORKER_LOCK_ID,
            application_name="beacon-background-worker",
        )
        self.stdout.write("Beacon background worker is waiting for leadership")
        try:
            with lock:
                final_state = run_background_worker_loop(
                    lock,
                    stop_event,
                    heartbeat_path=heartbeat_path,
                    heartbeat_interval_seconds=heartbeat_interval,
                    standby_poll_seconds=standby_poll,
                    start_services=start_background_services,
                    get_status=get_background_services_status,
                    shutdown_services=shutdown_background_services,
                )
        except BackgroundWorkerRuntimeError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(
                f"background worker leader election failed: {type(exc).__name__}"
            ) from exc
        self.stdout.write(f"Beacon background worker stopped from {final_state} state")
