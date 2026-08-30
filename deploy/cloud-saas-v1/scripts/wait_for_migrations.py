#!/usr/bin/env python3
"""Wait until the separately managed Cloud schema migration has completed."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANAGE_PY = ROOT / "Admin" / "manage.py"
MAX_DIAGNOSTIC_BYTES = 4096


def _bounded_number(name: str, default: str, *, minimum: float, maximum: float) -> float:
    raw = str(os.environ.get(name, default) or default).strip()
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SystemExit(f"[beacon-cloud] {name} must be numeric") from exc
    if not (minimum <= value <= maximum):
        raise SystemExit(
            f"[beacon-cloud] {name} must be between {minimum:g} and {maximum:g}"
        )
    return value


def wait_for_migrations(
    *,
    attempts: int,
    delay_seconds: float,
    run=subprocess.run,
    sleep=time.sleep,
) -> None:
    last_output = ""
    command = [sys.executable, str(MANAGE_PY), "migrate", "--check", "--noinput"]
    for attempt in range(1, int(attempts) + 1):
        try:
            result = run(
                command,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
                check=False,
            )
            last_output = str(result.stdout or "")[-MAX_DIAGNOSTIC_BYTES:]
            if int(result.returncode) == 0:
                print("[beacon-cloud] database migrations are current")
                return
        except subprocess.TimeoutExpired:
            last_output = "migration check timed out"
        except OSError as exc:
            last_output = f"migration check failed: {type(exc).__name__}"

        print(f"[beacon-cloud] waiting for database migrations ({attempt}/{attempts})")
        if attempt < int(attempts):
            sleep(float(delay_seconds))

    if last_output:
        print(last_output, file=sys.stderr)
    raise SystemExit("[beacon-cloud] database migrations were not completed in time")


def main() -> int:
    attempts = int(
        _bounded_number(
            "BEACON_MIGRATION_WAIT_ATTEMPTS",
            "180",
            minimum=1,
            maximum=600,
        )
    )
    delay_seconds = _bounded_number(
        "BEACON_MIGRATION_WAIT_DELAY_SECONDS",
        "2",
        minimum=0.1,
        maximum=10,
    )
    wait_for_migrations(attempts=attempts, delay_seconds=delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
