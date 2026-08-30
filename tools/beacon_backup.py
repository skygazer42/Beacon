#!/usr/bin/env python3
"""Create, verify, and safely restore Beacon SQLite backup bundles.

The bundle is an integrity-checked transport artifact, not an encrypted or
authenticated archive. Store it on encrypted, access-controlled storage and
apply an external signature when authenticity is required.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA = "beacon.backup.v1"
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


class BackupError(RuntimeError):
    """Raised when a backup cannot be created or trusted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_stream(source: BinaryIO, destination: Optional[BinaryIO] = None) -> Tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = source.read(COPY_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        if destination is not None:
            destination.write(chunk)
    return digest.hexdigest(), total


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        digest, _ = _sha256_stream(source)
    return digest


def _safe_relative_path(raw_value: str, *, field: str) -> PurePosixPath:
    value = str(raw_value or "")
    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise BackupError(f"invalid {field}: {value!r}")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError(f"unsafe {field}: {value!r}")
    if path.as_posix() != value:
        raise BackupError(f"non-canonical {field}: {value!r}")
    return path


def _load_json_object(path: Path) -> Dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupError(f"required file does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"cannot read JSON object from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BackupError(f"JSON root must be an object: {path}")
    return payload


def _absolute_path(value: object, base_dir: Optional[Path] = None) -> Path:
    path = Path(os.path.expanduser(str(value or "").strip()))
    if not path.is_absolute():
        path = (Path.cwd() if base_dir is None else base_dir) / path
    return Path(os.path.abspath(path))


def _resolve_path(value: object, root_dir: Path) -> Path:
    return _absolute_path(value, root_dir)


def _configured_path(
    *,
    explicit: Optional[Path],
    environ: Mapping[str, str],
    env_name: str,
    config: Mapping[str, object],
    config_name: str,
    default: str,
    root_dir: Path,
) -> Path:
    if explicit is not None:
        return _absolute_path(explicit)
    env_value = str(environ.get(env_name, "") or "").strip()
    config_value = str(config.get(config_name, "") or "").strip()
    value = env_value or config_value or default
    return _resolve_path(value, root_dir)


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise BackupError(f"cannot inspect path {path}: {exc}") from exc
    return True


def _require_regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BackupError(f"{label} is not readable: {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BackupError(f"{label} must be a regular file and not a symlink: {path}")


def _require_directory(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BackupError(f"{label} is not readable: {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise BackupError(f"{label} must be a directory and not a symlink: {path}")


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _walk_regular_files(root: Path) -> Iterable[Tuple[Path, PurePosixPath]]:
    _require_directory(root, label="backup source")
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for directory_name in directory_names:
            directory_path = current_path / directory_name
            if directory_path.is_symlink():
                raise BackupError(f"symlinked directories are not allowed in backups: {directory_path}")
        for file_name in file_names:
            source_path = current_path / file_name
            _require_regular_file(source_path, label="backup source")
            relative = source_path.relative_to(root)
            yield source_path, _safe_relative_path(relative.as_posix(), field="source path")


def _sqlite_quick_check(database_path: Path) -> None:
    try:
        with sqlite3.connect(str(database_path), timeout=30) as connection:
            rows = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite validation failed for {database_path}: {exc}") from exc
    results = [str(row[0]) for row in rows if row]
    if results != ["ok"]:
        raise BackupError(f"SQLite quick_check failed for {database_path}: {results!r}")


def _snapshot_sqlite(source_path: Path, destination_path: Path) -> None:
    _require_regular_file(source_path, label="SQLite database")
    source_uri = source_path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True, timeout=30) as source:
            with sqlite3.connect(str(destination_path), timeout=30) as destination:
                source.backup(destination, pages=256, sleep=0.02)
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite online backup failed: {exc}") from exc
    try:
        os.chmod(destination_path, 0o600)
    except OSError:
        pass
    _sqlite_quick_check(destination_path)


class _HashingReader:
    def __init__(self, source: BinaryIO):
        self._source = source
        self.digest = hashlib.sha256()
        self.total = 0

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size)
        if data:
            self.digest.update(data)
            self.total += len(data)
        return data


def _add_file(
    archive: tarfile.TarFile,
    *,
    source_path: Path,
    archive_path: str,
    restore_path: str,
    kind: str,
) -> Dict[str, object]:
    safe_archive_path = _safe_relative_path(archive_path, field="archive path").as_posix()
    safe_restore_path = _safe_relative_path(restore_path, field="restore path").as_posix()
    before = source_path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise BackupError(f"backup source changed type while reading: {source_path}")

    with source_path.open("rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise BackupError(f"backup source changed while opening: {source_path}")
        info = tarfile.TarInfo(safe_archive_path)
        info.size = int(opened.st_size)
        info.mtime = int(opened.st_mtime)
        info.mode = stat.S_IMODE(opened.st_mode) & 0o777
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        hashing_reader = _HashingReader(source)
        archive.addfile(info, hashing_reader)

    after = source_path.stat()
    if hashing_reader.total != int(opened.st_size):
        raise BackupError(f"backup source was truncated while reading: {source_path}")
    if (
        after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
    ):
        raise BackupError(f"backup source changed while reading: {source_path}")

    return {
        "archive_path": safe_archive_path,
        "restore_path": safe_restore_path,
        "kind": kind,
        "size": hashing_reader.total,
        "sha256": hashing_reader.digest.hexdigest(),
        "mode": info.mode,
    }


def _add_bytes(archive: tarfile.TarFile, *, name: str, payload: bytes, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    info.mode = mode
    info.uid = 0
    info.gid = 0
    archive.addfile(info, io.BytesIO(payload))


def _component(name: str, restore_root: str, file_count: int) -> Dict[str, object]:
    return {
        "name": name,
        "restore_root": _safe_relative_path(restore_root, field="component restore root").as_posix(),
        "file_count": int(file_count),
    }


def create_backup(
    *,
    root_dir: Path,
    output_path: Path,
    database_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    upload_dir: Optional[Path] = None,
    model_dir: Optional[Path] = None,
    include_upload: bool = True,
    include_models: bool = True,
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    """Create a new backup bundle without overwriting any existing artifact."""
    environ = dict(os.environ if environ is None else environ)
    root_dir = _absolute_path(root_dir)
    _require_directory(root_dir, label="project root")
    output_path = _absolute_path(output_path)
    if _path_exists(output_path):
        raise BackupError(f"backup output already exists: {output_path}")
    _require_directory(output_path.parent, label="backup output parent")

    if config_path is None:
        configured_config = str(environ.get("BEACON_CONFIG_PATH", "") or "").strip()
        config_path = Path(configured_config) if configured_config else root_dir / "config.json"
    config_path = _absolute_path(config_path)
    _require_regular_file(config_path, label="config.json")
    config = _load_json_object(config_path)

    if database_path is None and str(environ.get("BEACON_CLOUD_DB_URL", "") or "").strip():
        raise BackupError("Postgres is configured; use pg_dump instead of the SQLite backup tool")
    database_path = _configured_path(
        explicit=database_path,
        environ=environ,
        env_name="BEACON_SQLITE_DB_PATH",
        config=config,
        config_name="__unused_database_path",
        default="Admin/Admin.sqlite3",
        root_dir=root_dir,
    )
    upload_dir = _configured_path(
        explicit=upload_dir,
        environ=environ,
        env_name="BEACON_UPLOAD_DIR",
        config=config,
        config_name="uploadDir",
        default="Admin/static/upload",
        root_dir=root_dir,
    )
    model_dir = _configured_path(
        explicit=model_dir,
        environ=environ,
        env_name="BEACON_MODEL_DIR",
        config=config,
        config_name="modelDir",
        default="Analyzer/models",
        root_dir=root_dir,
    )

    source_directories: List[Path] = []
    if include_upload:
        _require_directory(upload_dir, label="upload directory")
        source_directories.append(upload_dir)
    if include_models:
        _require_directory(model_dir, label="model directory")
        source_directories.append(model_dir)
    for source_directory in source_directories:
        if _path_is_within(output_path, source_directory):
            raise BackupError(f"backup output cannot be inside a backed-up directory: {source_directory}")

    version_path = root_dir / "PROJECT_VERSION"
    _require_regular_file(version_path, label="PROJECT_VERSION")
    project_version = version_path.read_text(encoding="utf-8").strip()
    if not project_version:
        raise BackupError("PROJECT_VERSION is empty")

    temporary_output = output_path.parent / f".{output_path.name}.{uuid.uuid4().hex}.tmp"
    entries: List[Dict[str, object]] = []
    components: List[Dict[str, object]] = []
    seen_archive_names = set()
    seen_restore_names = set()

    try:
        with tempfile.TemporaryDirectory(prefix="beacon-sqlite-backup-") as temporary_dir:
            database_snapshot = Path(temporary_dir) / "Admin.sqlite3"
            _snapshot_sqlite(database_path, database_snapshot)

            with tarfile.open(temporary_output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
                fixed_sources: Sequence[Tuple[Path, str, str, str]] = (
                    (database_snapshot, "payload/database/Admin.sqlite3", "Admin/Admin.sqlite3", "sqlite"),
                    (config_path, "payload/config/config.json", "config.json", "config"),
                    (version_path, "payload/config/PROJECT_VERSION", "PROJECT_VERSION", "version"),
                )
                settings_path = root_dir / "settings.json"
                if _path_exists(settings_path):
                    _require_regular_file(settings_path, label="settings.json")
                    fixed_sources = (*fixed_sources, (settings_path, "payload/config/settings.json", "settings.json", "settings"))

                for source_path, archive_name, restore_name, kind in fixed_sources:
                    entry = _add_file(
                        archive,
                        source_path=source_path,
                        archive_path=archive_name,
                        restore_path=restore_name,
                        kind=kind,
                    )
                    entries.append(entry)

                components.append(_component("database", "Admin", 1))

                for component_name, source_root, archive_prefix, restore_prefix, kind, enabled in (
                    ("upload", upload_dir, "payload/upload", "data/upload", "upload", include_upload),
                    ("models", model_dir, "payload/models", "data/models", "model", include_models),
                ):
                    if not enabled:
                        continue
                    component_count = 0
                    for source_path, relative in _walk_regular_files(source_root):
                        entry = _add_file(
                            archive,
                            source_path=source_path,
                            archive_path=f"{archive_prefix}/{relative.as_posix()}",
                            restore_path=f"{restore_prefix}/{relative.as_posix()}",
                            kind=kind,
                        )
                        entries.append(entry)
                        component_count += 1
                    components.append(_component(component_name, restore_prefix, component_count))

                for entry in entries:
                    archive_name = str(entry["archive_path"])
                    restore_name = str(entry["restore_path"])
                    archive_key = archive_name.casefold()
                    restore_key = restore_name.casefold()
                    if archive_key in seen_archive_names:
                        raise BackupError(f"duplicate archive path: {archive_name}")
                    if restore_key in seen_restore_names:
                        raise BackupError(f"duplicate restore path: {restore_name}")
                    seen_archive_names.add(archive_key)
                    seen_restore_names.add(restore_key)

                manifest: Dict[str, object] = {
                    "schema": SCHEMA,
                    "created_at": _utc_now(),
                    "project_version": project_version,
                    "database_engine": "sqlite",
                    "components": components,
                    "entries": entries,
                    "restore_environment": {
                        "BEACON_CONFIG_PATH": "config.json",
                        "BEACON_SQLITE_DB_PATH": "Admin/Admin.sqlite3",
                        "BEACON_UPLOAD_DIR": "data/upload",
                        "BEACON_MODEL_DIR": "data/models",
                    },
                    "integrity": "sha256",
                    "authenticity": "external-signature-required",
                }
                manifest_payload = (
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
                _add_bytes(archive, name=MANIFEST_NAME, payload=manifest_payload)

        os.chmod(temporary_output, 0o600)
        os.replace(temporary_output, output_path)
    except Exception:
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return {
        "schema": SCHEMA,
        "archive": str(output_path),
        "project_version": project_version,
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "sha256": _sha256_file(output_path),
    }


def _validated_members(archive: tarfile.TarFile) -> Dict[str, tarfile.TarInfo]:
    members: Dict[str, tarfile.TarInfo] = {}
    casefold_names = set()
    for member in archive.getmembers():
        safe_name = _safe_relative_path(member.name, field="archive member").as_posix()
        if not member.isfile():
            raise BackupError(f"archive contains a non-regular member: {member.name}")
        folded = safe_name.casefold()
        if folded in casefold_names:
            raise BackupError(f"archive contains duplicate member names: {member.name}")
        casefold_names.add(folded)
        members[safe_name] = member
    return members


def _read_manifest(archive: tarfile.TarFile, members: Mapping[str, tarfile.TarInfo]) -> Dict[str, object]:
    member = members.get(MANIFEST_NAME)
    if member is None:
        raise BackupError("backup manifest is missing")
    if member.size > MAX_MANIFEST_BYTES:
        raise BackupError("backup manifest is too large")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise BackupError("backup manifest cannot be read")
    try:
        manifest = json.loads(extracted.read(MAX_MANIFEST_BYTES + 1).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"backup manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise BackupError("unsupported backup manifest schema")
    if manifest.get("database_engine") != "sqlite":
        raise BackupError("unsupported backup database engine")
    entries = manifest.get("entries")
    components = manifest.get("components")
    if not isinstance(entries, list) or not isinstance(components, list):
        raise BackupError("backup manifest entries/components must be arrays")
    return manifest


def _validate_manifest_entries(
    manifest: Mapping[str, object], members: Mapping[str, tarfile.TarInfo]
) -> List[Dict[str, object]]:
    validated: List[Dict[str, object]] = []
    expected_members = {MANIFEST_NAME}
    archive_names = set()
    restore_names = set()
    sqlite_entries = 0
    for raw_entry in manifest.get("entries", []):
        if not isinstance(raw_entry, dict):
            raise BackupError("backup manifest contains a non-object entry")
        archive_path = _safe_relative_path(
            str(raw_entry.get("archive_path", "")), field="manifest archive path"
        ).as_posix()
        restore_path = _safe_relative_path(
            str(raw_entry.get("restore_path", "")), field="manifest restore path"
        ).as_posix()
        archive_key = archive_path.casefold()
        restore_key = restore_path.casefold()
        if archive_key in archive_names or restore_key in restore_names:
            raise BackupError("backup manifest contains duplicate paths")
        archive_names.add(archive_key)
        restore_names.add(restore_key)
        member = members.get(archive_path)
        if member is None:
            raise BackupError(f"backup payload is missing: {archive_path}")
        try:
            expected_size = int(raw_entry.get("size"))
            mode = int(raw_entry.get("mode", 0o600)) & 0o777
        except (TypeError, ValueError) as exc:
            raise BackupError(f"invalid size or mode for {archive_path}") from exc
        expected_hash = str(raw_entry.get("sha256", ""))
        if expected_size < 0 or member.size != expected_size:
            raise BackupError(f"backup size mismatch for {archive_path}")
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise BackupError(f"invalid SHA-256 for {archive_path}")
        kind = str(raw_entry.get("kind", ""))
        if kind == "sqlite":
            sqlite_entries += 1
        validated.append(
            {
                "archive_path": archive_path,
                "restore_path": restore_path,
                "kind": kind,
                "size": expected_size,
                "sha256": expected_hash,
                "mode": mode,
            }
        )
        expected_members.add(archive_path)
    if sqlite_entries != 1:
        raise BackupError("backup must contain exactly one SQLite database")
    if expected_members != set(members):
        unexpected = sorted(set(members) - expected_members)
        raise BackupError(f"backup contains unmanifested payload: {unexpected!r}")
    return validated


def _verify_open_archive(
    archive: tarfile.TarFile,
) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    members = _validated_members(archive)
    manifest = _read_manifest(archive, members)
    entries = _validate_manifest_entries(manifest, members)
    with tempfile.TemporaryDirectory(prefix="beacon-backup-verify-") as temporary_dir:
        database_copy = Path(temporary_dir) / "Admin.sqlite3"
        database_size = next(int(entry["size"]) for entry in entries if entry["kind"] == "sqlite")
        available_bytes = shutil.disk_usage(temporary_dir).free
        if database_size > available_bytes:
            raise BackupError("insufficient temporary disk space to verify the SQLite snapshot")
        for entry in entries:
            member = members[str(entry["archive_path"])]
            extracted = archive.extractfile(member)
            if extracted is None:
                raise BackupError(f"backup payload cannot be read: {member.name}")
            if entry["kind"] == "sqlite":
                with database_copy.open("wb") as destination:
                    actual_hash, actual_size = _sha256_stream(extracted, destination)
            else:
                actual_hash, actual_size = _sha256_stream(extracted)
            if actual_size != entry["size"] or actual_hash != entry["sha256"]:
                raise BackupError(f"backup checksum mismatch for {member.name}")
        _sqlite_quick_check(database_copy)
    return manifest, entries


def verify_backup(archive_path: Path) -> Dict[str, object]:
    archive_path = _absolute_path(archive_path)
    _require_regular_file(archive_path, label="backup archive")
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            manifest, entries = _verify_open_archive(archive)
    except (tarfile.TarError, OSError) as exc:
        raise BackupError(f"cannot verify backup archive: {exc}") from exc
    return {
        "schema": manifest["schema"],
        "archive": str(archive_path),
        "project_version": manifest.get("project_version", ""),
        "created_at": manifest.get("created_at", ""),
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "sha256": _sha256_file(archive_path),
        "status": "ok",
    }


def _restore_components(destination: Path, manifest: Mapping[str, object]) -> None:
    seen = set()
    for component in manifest.get("components", []):
        if not isinstance(component, dict):
            raise BackupError("backup manifest contains a non-object component")
        restore_root = _safe_relative_path(
            str(component.get("restore_root", "")), field="component restore root"
        )
        key = restore_root.as_posix().casefold()
        if key in seen:
            raise BackupError("backup manifest contains duplicate component roots")
        seen.add(key)
        destination.joinpath(*restore_root.parts).mkdir(parents=True, exist_ok=True, mode=0o700)


def restore_backup(*, archive_path: Path, destination: Path) -> Dict[str, object]:
    """Restore into a brand-new directory; existing destinations are never overwritten."""
    archive_path = _absolute_path(archive_path)
    destination = _absolute_path(destination)
    _require_regular_file(archive_path, label="backup archive")
    if _path_exists(destination):
        raise BackupError(f"restore destination already exists: {destination}")
    _require_directory(destination.parent, label="restore destination parent")

    staging = destination.parent / f".{destination.name}.restore-{uuid.uuid4().hex}"
    try:
        staging.mkdir(mode=0o700)
        with tarfile.open(archive_path, mode="r:*") as archive:
            manifest, entries = _verify_open_archive(archive)
            members = _validated_members(archive)
            required_bytes = sum(int(entry["size"]) for entry in entries)
            if required_bytes > shutil.disk_usage(destination.parent).free:
                raise BackupError("insufficient disk space for the restored payload")
            _restore_components(staging, manifest)
            for entry in entries:
                restore_path = _safe_relative_path(
                    str(entry["restore_path"]), field="restore path"
                )
                target = staging.joinpath(*restore_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                extracted = archive.extractfile(members[str(entry["archive_path"])])
                if extracted is None:
                    raise BackupError(f"backup payload cannot be read: {entry['archive_path']}")
                with target.open("xb") as output:
                    actual_hash, actual_size = _sha256_stream(extracted, output)
                if actual_size != entry["size"] or actual_hash != entry["sha256"]:
                    raise BackupError(f"backup changed during restore: {entry['archive_path']}")
                try:
                    os.chmod(target, int(entry["mode"]) & 0o777)
                except OSError:
                    pass
        _sqlite_quick_check(staging / "Admin" / "Admin.sqlite3")
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "schema": SCHEMA,
        "archive": str(archive_path),
        "destination": str(destination),
        "project_version": manifest.get("project_version", ""),
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "status": "restored",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, verify, or safely restore Beacon backup bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a new SQLite and file-data backup")
    create.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--database", type=Path)
    create.add_argument("--config", type=Path)
    create.add_argument("--upload-dir", type=Path)
    create.add_argument("--model-dir", type=Path)
    create.add_argument("--skip-upload", action="store_true")
    create.add_argument("--skip-models", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify hashes, structure, and SQLite integrity")
    verify.add_argument("archive", type=Path)

    restore = subparsers.add_parser("restore", help="Restore into a brand-new isolated directory")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create_backup(
                root_dir=args.root,
                output_path=args.output,
                database_path=args.database,
                config_path=args.config,
                upload_dir=args.upload_dir,
                model_dir=args.model_dir,
                include_upload=not args.skip_upload,
                include_models=not args.skip_models,
            )
        elif args.command == "verify":
            result = verify_backup(args.archive)
        else:
            result = restore_backup(archive_path=args.archive, destination=args.destination)
    except BackupError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
