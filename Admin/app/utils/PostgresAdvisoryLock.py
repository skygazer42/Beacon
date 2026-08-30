import time


MIN_POSTGRES_BIGINT = -(2**63)
MAX_POSTGRES_BIGINT = (2**63) - 1


def validate_advisory_lock_id(value) -> int:
    if isinstance(value, bool):
        raise ValueError("PostgreSQL advisory lock id must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("PostgreSQL advisory lock id must be an integer") from exc
    if not (MIN_POSTGRES_BIGINT <= parsed <= MAX_POSTGRES_BIGINT):
        raise ValueError("PostgreSQL advisory lock id is outside the signed bigint range")
    return parsed


class PostgresAdvisoryLock:
    """Hold a session-scoped PostgreSQL advisory lock on a dedicated connection."""

    def __init__(
        self,
        dsn: str,
        lock_id: int,
        *,
        application_name: str,
        connect_timeout_seconds: int = 10,
        connect_factory=None,
    ):
        normalized_dsn = str(dsn or "").strip()
        if not normalized_dsn:
            raise ValueError("PostgreSQL DSN is required")
        normalized_application_name = str(application_name or "").strip()
        if not normalized_application_name:
            raise ValueError("PostgreSQL application_name is required")
        try:
            timeout = int(connect_timeout_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("connect timeout must be an integer") from exc
        if not (1 <= timeout <= 60):
            raise ValueError("connect timeout must be between 1 and 60 seconds")

        self._dsn = normalized_dsn
        self._lock_id = validate_advisory_lock_id(lock_id)
        self._application_name = normalized_application_name[:63]
        self._connect_timeout_seconds = timeout
        self._connect_factory = connect_factory
        self._connection = None
        self._cursor = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return bool(self._acquired)

    def open(self) -> None:
        if self._connection is not None:
            return
        connect_factory = self._connect_factory
        if connect_factory is None:
            import psycopg2

            connect_factory = psycopg2.connect
        connection = connect_factory(
            self._dsn,
            connect_timeout=self._connect_timeout_seconds,
            application_name=self._application_name,
        )
        connection.autocommit = True
        self._connection = connection
        self._cursor = connection.cursor()

    def try_acquire(self) -> bool:
        self.open()
        if self._acquired:
            return True
        self._cursor.execute("SELECT pg_try_advisory_lock(%s)", (self._lock_id,))
        row = self._cursor.fetchone()
        self._acquired = bool(row and row[0] is True)
        return self._acquired

    def wait_acquire(
        self,
        timeout_seconds: float,
        *,
        poll_interval_seconds: float = 1.0,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> bool:
        timeout = float(timeout_seconds)
        poll_interval = float(poll_interval_seconds)
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("advisory lock wait values must be positive")
        deadline = monotonic() + timeout
        while True:
            if self.try_acquire():
                return True
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            sleep(min(poll_interval, remaining))

    def keepalive(self) -> None:
        if not self._acquired or self._cursor is None:
            raise RuntimeError("PostgreSQL advisory lock is not held")
        # Reusing this cursor is intentional: a broken session raises instead
        # of transparently reconnecting without the advisory lock.
        self._cursor.execute("SELECT 1")
        row = self._cursor.fetchone()
        if not row or row[0] != 1:
            raise RuntimeError("PostgreSQL advisory lock connection is unhealthy")

    def close(self) -> None:
        cursor = self._cursor
        connection = self._connection
        self._cursor = None
        self._connection = None
        try:
            if self._acquired and cursor is not None:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (self._lock_id,))
                cursor.fetchone()
        finally:
            self._acquired = False
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()
        return False
