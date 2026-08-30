#!/usr/bin/env python3
"""Verify that the Cloud requirements lock is pinned, hashed, and current."""

from __future__ import annotations

import argparse
import re
import stat
from pathlib import Path


PIN_PATTERN = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)(?:\s*\\)?"
)
HASH_PATTERN = re.compile(r"--hash=sha256:[a-f0-9]{64}(?:\s*\\)?")
MAX_REQUIREMENTS_BYTES = 2 * 1024 * 1024


class LockValidationError(RuntimeError):
    """Raised when a requirements declaration or lock is unsafe or stale."""


def _read_regular_text(path: Path) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LockValidationError(f"cannot read requirements file {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise LockValidationError(f"requirements path must be a regular file: {path}")
    if metadata.st_size > MAX_REQUIREMENTS_BYTES:
        raise LockValidationError(f"requirements file is too large: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LockValidationError(f"cannot decode requirements file {path}: {exc}") from exc


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_direct_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line_number, raw_line in enumerate(_read_regular_text(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_PATTERN.fullmatch(line)
        if match is None or line.endswith("\\"):
            raise LockValidationError(
                f"direct requirement must use an exact name==version pin at {path}:{line_number}"
            )
        name, version = _normalize_name(match.group(1)), match.group(2)
        if name in requirements:
            raise LockValidationError(f"duplicate direct requirement {name!r} in {path}")
        requirements[name] = version
    if not requirements:
        raise LockValidationError(f"direct requirements file is empty: {path}")
    return requirements


def _parse_hashed_lock(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    current: tuple[str, str, int] | None = None

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        name, version, hash_count = current
        if hash_count < 1:
            raise LockValidationError(f"locked requirement {name}=={version} has no SHA-256 hash")
        if name in requirements:
            raise LockValidationError(f"duplicate locked requirement {name!r} in {path}")
        requirements[name] = version
        current = None

    for line_number, raw_line in enumerate(_read_regular_text(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pin_match = PIN_PATTERN.fullmatch(line)
        if pin_match is not None and not raw_line[:1].isspace():
            finish_current()
            current = (_normalize_name(pin_match.group(1)), pin_match.group(2), 0)
            continue
        if HASH_PATTERN.fullmatch(line) is not None and current is not None:
            current = (current[0], current[1], current[2] + 1)
            continue
        raise LockValidationError(f"unexpected lock syntax at {path}:{line_number}")

    finish_current()
    if not requirements:
        raise LockValidationError(f"requirements lock is empty: {path}")
    return requirements


def verify_requirements_lock(direct_path: Path, lock_path: Path) -> None:
    direct = _parse_direct_requirements(Path(direct_path))
    locked = _parse_hashed_lock(Path(lock_path))
    missing = sorted(name for name in direct if name not in locked)
    mismatched = sorted(
        f"{name}: declared {direct[name]}, locked {locked[name]}"
        for name in direct.keys() & locked.keys()
        if direct[name] != locked[name]
    )
    if missing or mismatched:
        details = []
        if missing:
            details.append("missing direct pins: " + ", ".join(missing))
        if mismatched:
            details.append("version mismatch: " + "; ".join(mismatched))
        raise LockValidationError("requirements lock is stale: " + "; ".join(details))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direct", type=Path)
    parser.add_argument("lock", type=Path)
    arguments = parser.parse_args(argv)
    try:
        verify_requirements_lock(arguments.direct, arguments.lock)
    except LockValidationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
