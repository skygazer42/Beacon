#!/usr/bin/env python3
"""Fail-closed runtime validation for the Beacon Cloud container."""

from __future__ import annotations

import os
import socket
import time
from urllib.parse import parse_qs, unquote, urlsplit


COMMON_REQUIRED_SECRETS = {
    "BEACON_OPEN_API_TOKEN": 32,
    "BEACON_DJANGO_SECRET_KEY": 32,
    "BEACON_CLOUD_EDGE_TOKEN_PEPPER": 32,
    "BEACON_CLOUD_S3_SECRET_ACCESS_KEY": 16,
}
INIT_REQUIRED_SECRETS = {
    "BEACON_BOOTSTRAP_ADMIN_PASSWORD": 12,
}
REQUIRED_SECRETS = {**COMMON_REQUIRED_SECRETS, **INIT_REQUIRED_SECRETS}
POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})
TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "n", "off"})
PLACEHOLDER_MARKERS = ("CHANGE_ME", "CHANGEME", "PLACEHOLDER")
CLOUD_PROCESS_ROLES = frozenset({"web", "worker", "init"})
SECURE_POSTGRES_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})


def _environment_value(name: str) -> str:
    value = str(os.environ.get(name, "") or "").strip()
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise SystemExit(f"[beacon-cloud] {name} contains a forbidden control character")
    return value


def _boolean_environment(name: str, *, default: bool) -> bool:
    raw = _environment_value(name).lower()
    if not raw:
        return bool(default)
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    raise SystemExit(f"[beacon-cloud] {name} must be an explicit boolean value")


def _validate_secret_value(name: str, value: str, minimum_length: int) -> str:
    normalized = value.upper().replace("-", "_")
    if (
        len(value) < minimum_length
        or any(marker in normalized for marker in PLACEHOLDER_MARKERS)
        or len(set(value)) < 6
    ):
        raise SystemExit(f"[beacon-cloud] {name} must be replaced with a strong secret")
    return value


def _parse_postgres_url(database_url: str):
    try:
        parsed = urlsplit(database_url)
        if parsed.scheme.lower() not in POSTGRES_SCHEMES:
            raise ValueError("scheme must be postgres or postgresql")
        if not parsed.username or parsed.password is None or not parsed.path.strip("/"):
            raise ValueError("username, password, and database name are required")
        # Accessing these properties validates brackets and the numeric port.
        if not parsed.hostname:
            raise ValueError("hostname is required")
        parsed.port
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"[beacon-cloud] invalid PostgreSQL connection target: {exc}") from exc
    return parsed


def _validate_transport_security(database_url: str) -> None:
    parsed = _parse_postgres_url(database_url)
    if _boolean_environment("BEACON_REQUIRE_DATABASE_TLS", default=False):
        try:
            query = (
                parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                if parsed.query
                else {}
            )
        except ValueError as exc:
            raise SystemExit("[beacon-cloud] PostgreSQL URL query is invalid") from exc
        ssl_modes = query.get("sslmode") or []
        if len(ssl_modes) != 1 or str(ssl_modes[0] or "").lower() not in SECURE_POSTGRES_SSL_MODES:
            raise SystemExit(
                "[beacon-cloud] external PostgreSQL requires sslmode=require, verify-ca, or verify-full"
            )

    endpoint = _environment_value("BEACON_CLOUD_S3_ENDPOINT_URL")
    allow_insecure_object_storage = _boolean_environment(
        "BEACON_ALLOW_INSECURE_OBJECT_STORAGE",
        default=False,
    )
    if endpoint:
        try:
            object_target = urlsplit(endpoint)
        except ValueError as exc:
            raise SystemExit("[beacon-cloud] object storage endpoint is invalid") from exc
        if not object_target.hostname or object_target.scheme.lower() not in {"http", "https"}:
            raise SystemExit("[beacon-cloud] object storage endpoint must be an absolute HTTP(S) URL")
        if object_target.scheme.lower() != "https" and not allow_insecure_object_storage:
            raise SystemExit(
                "[beacon-cloud] insecure object storage requires BEACON_ALLOW_INSECURE_OBJECT_STORAGE=1"
            )


def _validate_security_mode() -> None:
    if _environment_value("BEACON_DEPLOYMENT_MODE").lower() != "cloud":
        raise SystemExit("[beacon-cloud] BEACON_DEPLOYMENT_MODE must be cloud")
    if _boolean_environment("BEACON_DJANGO_DEBUG", default=True):
        raise SystemExit("[beacon-cloud] BEACON_DJANGO_DEBUG must be disabled")
    if not _boolean_environment("BEACON_REQUIRE_OPEN_API_TOKEN", default=False):
        raise SystemExit("[beacon-cloud] BEACON_REQUIRE_OPEN_API_TOKEN must be enabled")
    process_role = _environment_value("BEACON_BACKGROUND_ROLE").lower()
    if process_role not in CLOUD_PROCESS_ROLES:
        raise SystemExit(
            "[beacon-cloud] BEACON_BACKGROUND_ROLE must explicitly select web, worker, or init"
        )

    allowed_hosts = [
        host.strip()
        for host in _environment_value("BEACON_DJANGO_ALLOWED_HOSTS").split(",")
        if host.strip()
    ]
    if not allowed_hosts or any("*" in host for host in allowed_hosts):
        raise SystemExit("[beacon-cloud] BEACON_DJANGO_ALLOWED_HOSTS must be explicit")

    allow_insecure_http = _boolean_environment(
        "BEACON_CLOUD_ALLOW_INSECURE_HTTP",
        default=False,
    )
    session_cookie_secure = _boolean_environment(
        "BEACON_DJANGO_SESSION_COOKIE_SECURE",
        default=True,
    )
    csrf_cookie_secure = _boolean_environment(
        "BEACON_DJANGO_CSRF_COOKIE_SECURE",
        default=True,
    )
    if not allow_insecure_http and not (session_cookie_secure and csrf_cookie_secure):
        raise SystemExit(
            "[beacon-cloud] insecure cookies require BEACON_CLOUD_ALLOW_INSECURE_HTTP=1"
        )


def validate_runtime_environment() -> str:
    _validate_security_mode()
    process_role = _environment_value("BEACON_BACKGROUND_ROLE").lower()
    required_secrets = dict(COMMON_REQUIRED_SECRETS)
    if process_role == "init":
        required_secrets.update(INIT_REQUIRED_SECRETS)
    secret_values = []
    for name, minimum_length in required_secrets.items():
        value = _environment_value(name)
        secret_values.append(_validate_secret_value(name, value, minimum_length))

    required_values = [
        "BEACON_CLOUD_S3_ACCESS_KEY_ID",
        "BEACON_CLOUD_S3_BUCKET",
    ]
    if process_role == "init":
        required_values.append("BEACON_BOOTSTRAP_ADMIN_USERNAME")
    for name in required_values:
        value = _environment_value(name)
        normalized = value.upper().replace("-", "_")
        if not value or any(marker in normalized for marker in PLACEHOLDER_MARKERS):
            raise SystemExit(f"[beacon-cloud] {name} must be configured")

    database_url = _environment_value("BEACON_CLOUD_DB_URL")
    if not database_url or any(
        marker in database_url.upper().replace("-", "_") for marker in PLACEHOLDER_MARKERS
    ):
        raise SystemExit("[beacon-cloud] BEACON_CLOUD_DB_URL must contain real credentials")
    parsed = _parse_postgres_url(database_url)
    database_password = unquote(str(parsed.password or ""))
    if any(character in database_password for character in ("\x00", "\r", "\n")):
        raise SystemExit("[beacon-cloud] database password contains a forbidden control character")
    secret_values.append(
        _validate_secret_value("BEACON_CLOUD_DB_URL password", database_password, 16)
    )
    _validate_transport_security(database_url)

    if len(secret_values) != len(set(secret_values)):
        raise SystemExit("[beacon-cloud] security-sensitive values must be unique")
    return database_url


def postgres_target(database_url: str) -> tuple[str, int]:
    try:
        parsed = _parse_postgres_url(database_url)
        host = _environment_value("BEACON_PG_HOST") or parsed.hostname
        configured_port = _environment_value("BEACON_PG_PORT")
        port = int(configured_port) if configured_port else (parsed.port or 5432)
    except ValueError as exc:
        raise SystemExit(f"[beacon-cloud] invalid PostgreSQL connection target: {exc}") from exc

    if not host or not (1 <= port <= 65535):
        raise SystemExit("[beacon-cloud] BEACON_CLOUD_DB_URL must include a valid PostgreSQL host and port")
    return host, port


def wait_for_postgres(host: str, port: int, *, attempts: int = 60) -> None:
    for attempt in range(1, attempts + 1):
        try:
            connection = socket.create_connection((host, port), timeout=2)
            connection.close()
            print(f"[beacon-cloud] postgres reachable: {host}:{port}")
            return
        except OSError as exc:
            print(f"[beacon-cloud] waiting postgres ({attempt}/{attempts}): {exc}")
            if attempt < attempts:
                time.sleep(1)
    raise SystemExit("[beacon-cloud] postgres not reachable, abort")


def main() -> int:
    database_url = validate_runtime_environment()
    host, port = postgres_target(database_url)
    wait_for_postgres(host, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
