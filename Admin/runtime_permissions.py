"""Harden permissions for secret-bearing runtime state files.

The Edge runtime keeps API tokens and other credentials in ``config.json``
and stores account/API-key metadata in SQLite.  Both files must be private to
the service account on POSIX hosts.  Windows ACLs are managed by the installer
or the deployment platform, so POSIX mode changes are intentionally skipped
there.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PRIVATE_FILE_MODE = 0o600
_SQLITE_SIDECAR_SUFFIXES = ("", "-wal", "-shm", "-journal")
_SENSITIVE_CONFIG_KEY_SUFFIXES = ("password", "secret", "token", "key")
_NON_SECRET_PLACEHOLDERS = frozenset({"change_me", "replace_me"})


class RuntimeFilePermissionError(RuntimeError):
    """Raised when a sensitive runtime file cannot be made private."""


def _is_windows(platform_name: str | None = None) -> bool:
    return str(os.name if platform_name is None else platform_name).lower() == "nt"


def _private_mode(current_mode: int) -> int:
    """Remove execute, special, group, and other bits without adding access."""
    owner_mode = int(current_mode) & 0o600
    return owner_mode or PRIVATE_FILE_MODE


def ensure_private_regular_file(
    path: str | os.PathLike[str],
    *,
    missing_ok: bool = False,
    platform_name: str | None = None,
) -> bool:
    """Ensure an existing regular file is accessible only by its owner.

    Returns ``True`` when a POSIX mode was changed.  The opened descriptor is
    used for both verification and ``fchmod`` so a path swap cannot redirect
    the permission change after the file is opened.
    """
    if _is_windows(platform_name):
        return False

    resolved = os.fspath(path)
    flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
    try:
        descriptor = os.open(resolved, flags)
    except FileNotFoundError:
        if missing_ok:
            return False
        raise RuntimeFilePermissionError(f"runtime file does not exist: {resolved}") from None
    except OSError as exc:
        raise RuntimeFilePermissionError(
            f"cannot open runtime file for permission validation: {resolved}: {exc}"
        ) from exc

    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeFilePermissionError(f"runtime path is not a regular file: {resolved}")

        current_mode = stat.S_IMODE(file_stat.st_mode)
        desired_mode = _private_mode(current_mode)
        changed = current_mode != desired_mode
        if changed:
            os.fchmod(descriptor, desired_mode)

        verified_mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
        if verified_mode != desired_mode:
            raise RuntimeFilePermissionError(
                f"runtime file permissions remain unsafe: {resolved}: mode={verified_mode:04o}"
            )
        return changed
    except RuntimeFilePermissionError:
        raise
    except OSError as exc:
        raise RuntimeFilePermissionError(
            f"cannot secure runtime file permissions: {resolved}: {exc}"
        ) from exc
    finally:
        os.close(descriptor)


def _is_embedded_secret(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    normalized = raw.lower()
    return normalized not in _NON_SECRET_PLACEHOLDERS


def config_contains_embedded_secrets(config_data: Mapping[str, Any] | None) -> bool:
    """Return whether a flat runtime configuration embeds credential material."""
    if not isinstance(config_data, Mapping):
        return False
    for key, value in config_data.items():
        normalized_key = str(key or "").strip().lower()
        if normalized_key.endswith(_SENSITIVE_CONFIG_KEY_SUFFIXES) and _is_embedded_secret(value):
            return True
    return False


def ensure_runtime_config_private(
    path: str | os.PathLike[str],
    config_data: Mapping[str, Any] | None,
    *,
    environ: Mapping[str, Any] | None = None,
    platform_name: str | None = None,
) -> bool:
    """Secure Edge config and every config that embeds real credentials.

    The checked-in Cloud fallback config is intentionally non-secret and is
    mounted read-only in containers.  Cloud secrets are injected through the
    environment, so that one placeholder-only file may remain image-readable.
    """
    environ = os.environ if environ is None else environ
    deployment_mode = str(
        environ.get("BEACON_DEPLOYMENT_MODE")
        or (config_data or {}).get("deploymentMode")
        or "edge"
    ).strip().lower()
    if deployment_mode == "cloud" and not config_contains_embedded_secrets(config_data):
        return False
    return ensure_private_regular_file(
        path,
        missing_ok=False,
        platform_name=platform_name,
    )


def ensure_sqlite_files_private(
    database_path: str | os.PathLike[str],
    *,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """Secure a SQLite database and any WAL/shared-memory sidecars present."""
    if _is_windows(platform_name):
        return ()

    raw_path = os.fspath(database_path)
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        return ()

    changed: list[str] = []
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        candidate = raw_path + suffix
        if ensure_private_regular_file(candidate, missing_ok=True, platform_name=platform_name):
            changed.append(candidate)
    return tuple(changed)


def _fsync_parent_directory(path: str) -> None:
    """Best-effort directory sync after an atomic replacement."""
    if _is_windows():
        return
    directory = os.path.dirname(path) or "."
    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)) | int(getattr(os, "O_CLOEXEC", 0))
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def write_private_text_atomic(
    path: str | os.PathLike[str],
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically write a private text file in the destination directory."""
    destination = Path(path)
    parent = destination.parent
    descriptor = -1
    temporary_path = ""
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=os.fspath(parent),
        )
        if not _is_windows():
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as stream:
            descriptor = -1
            stream.write(str(content))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
        temporary_path = ""
        ensure_private_regular_file(destination, platform_name=os.name)
        _fsync_parent_directory(os.fspath(destination))
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
