import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from app.utils.BackgroundRoles import get_background_role
from app.utils.PostgresAdvisoryLock import PostgresAdvisoryLock


CLOUD_INITIALIZATION_LOCK_ID = 47744514073167


class Command(BaseCommand):
    help = "Serialize Cloud database migrations and idempotent bootstrap"

    def add_arguments(self, parser):
        parser.add_argument(
            "--lock-timeout-seconds",
            type=float,
            default=300.0,
            help="Maximum time to wait for another initializer (default: 300)",
        )

    def handle(self, *args, **options):
        if get_background_role() != "init":
            raise CommandError("BEACON_BACKGROUND_ROLE must be init")
        dsn = str(os.environ.get("BEACON_CLOUD_DB_URL", "") or "").strip()
        if not dsn:
            raise CommandError("BEACON_CLOUD_DB_URL is required")
        timeout = float(options.get("lock_timeout_seconds") or 0)
        if not (1 <= timeout <= 1800):
            raise CommandError("lock timeout must be between 1 and 1800 seconds")

        lock = PostgresAdvisoryLock(
            dsn,
            CLOUD_INITIALIZATION_LOCK_ID,
            application_name="beacon-cloud-initializer",
        )
        try:
            with lock:
                if not lock.wait_acquire(timeout, poll_interval_seconds=1.0):
                    raise CommandError("timed out waiting for Cloud initialization lock")
                self.stdout.write("Cloud initialization lock acquired")
                call_command(
                    "migrate",
                    interactive=False,
                    verbosity=int(options.get("verbosity", 1)),
                )
                call_command(
                    "beacon_cloud_bootstrap",
                    verbosity=int(options.get("verbosity", 1)),
                )
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                f"Cloud initialization failed: {type(exc).__name__}"
            ) from exc
        self.stdout.write(self.style.SUCCESS("Cloud initialization completed"))
