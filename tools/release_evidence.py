#!/usr/bin/env python3
"""Assemble and verify immutable Beacon release-evidence directories.

This utility does not create signatures. The release workflow creates Sigstore
bundles with GitHub artifact attestations, then this utility binds the source
archive, SBOM, and both attestation bundles into one manifest and checksum set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


SCHEMA = "beacon.release-evidence.v1"
MANIFEST_NAME = "release-manifest.json"
CHECKSUM_NAME = "SHA256SUMS"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_MEMBERS = 100_000
COPY_CHUNK_BYTES = 1024 * 1024
REQUIRED_ROLES = {
    "source",
    "sbom",
    "provenance-attestation",
    "sbom-attestation",
    "provenance-verification",
    "sbom-verification",
}
TAG_PATTERN = re.compile(
    r"v(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>"
    r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*"
    r"))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
ROLE_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}")
FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,254}")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
CHECKSUM_LINE_PATTERN = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]{0,254})")


class EvidenceError(RuntimeError):
    """Raised when release evidence is incomplete or cannot be trusted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise EvidenceError(f"cannot inspect path {path}: {exc}") from exc
    return True


def _require_directory(path: Path, *, label: str) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EvidenceError(f"{label} is not readable: {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise EvidenceError(f"{label} must be a directory and not a symlink: {path}")
    return path.resolve()


def _require_regular_file(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EvidenceError(f"{label} is not readable: {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvidenceError(f"{label} must be a regular file and not a symlink: {path}")
    return path


def _read_limited(path: Path, *, label: str, limit: int = MAX_JSON_BYTES) -> bytes:
    _require_regular_file(path, label=label)
    try:
        size = path.stat().st_size
        if size > limit:
            raise EvidenceError(f"{label} exceeds the {limit}-byte limit: {path}")
        with path.open("rb") as source:
            payload = source.read(limit + 1)
    except OSError as exc:
        raise EvidenceError(f"cannot read {label} {path}: {exc}") from exc
    if len(payload) > limit:
        raise EvidenceError(f"{label} exceeds the {limit}-byte limit: {path}")
    return payload


def _read_json_object(path: Path, *, label: str) -> Dict[str, object]:
    try:
        payload = json.loads(_read_limited(path, label=label).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceError(f"{label} JSON root must be an object: {path}")
    return payload


def _read_json_value(path: Path, *, label: str) -> object:
    try:
        return json.loads(_read_limited(path, label=label).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc


def _sha256_file(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise EvidenceError(f"cannot hash release evidence {path}: {exc}") from exc
    return digest.hexdigest(), total


def _validate_tag(tag: str) -> str:
    tag = str(tag or "").strip()
    if not TAG_PATTERN.fullmatch(tag):
        raise EvidenceError(f"release tag is not a supported SemVer tag: {tag!r}")
    return tag


def _semver_parts(tag: str) -> Tuple[Tuple[int, int, int], Optional[Tuple[str, ...]]]:
    tag = _validate_tag(tag)
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:  # Defensive: _validate_tag already enforces this invariant.
        raise EvidenceError(f"release tag is not a supported SemVer tag: {tag!r}")
    core = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    prerelease = match.group("prerelease")
    return core, tuple(prerelease.split(".")) if prerelease else None


def _compare_semver(left: str, right: str) -> int:
    """Compare supported release tags using SemVer precedence rules."""
    left_core, left_prerelease = _semver_parts(left)
    right_core, right_prerelease = _semver_parts(right)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_prerelease is None or right_prerelease is None:
        if left_prerelease is right_prerelease:
            return 0
        return 1 if left_prerelease is None else -1

    for left_identifier, right_identifier in zip(left_prerelease, right_prerelease):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_identifier) > int(right_identifier) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_identifier > right_identifier else -1
    if len(left_prerelease) == len(right_prerelease):
        return 0
    return 1 if len(left_prerelease) > len(right_prerelease) else -1


def _validate_commit(commit: str) -> str:
    commit = str(commit or "").strip().lower()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise EvidenceError(f"release commit must be a full lowercase Git SHA: {commit!r}")
    return commit


def _safe_filename(raw_name: str, *, label: str, allow_reserved: bool = False) -> str:
    name = str(raw_name or "")
    if not FILENAME_PATTERN.fullmatch(name) or (
        not allow_reserved and name in {MANIFEST_NAME, CHECKSUM_NAME}
    ):
        raise EvidenceError(f"invalid {label}: {name!r}")
    return name


def _safe_archive_member(raw_name: str) -> PurePosixPath:
    name = str(raw_name or "")
    if (
        not name
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise EvidenceError(f"source archive contains an invalid path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError(f"source archive contains an unsafe path: {name!r}")
    return path


def _read_project_version(project_root: Path) -> str:
    version_path = _require_regular_file(project_root / "PROJECT_VERSION", label="PROJECT_VERSION")
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise EvidenceError(f"cannot read PROJECT_VERSION: {exc}") from exc
    return _validate_tag(version)


def _validate_release_files(project_root: Path) -> None:
    for relative_path in ("LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md"):
        _require_regular_file(project_root / relative_path, label=relative_path)


def _git(project_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError(f"cannot run Git release validation: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise EvidenceError(f"Git release validation failed: {detail or arguments!r}")
    return result.stdout.strip()


def validate_release_ref(
    *, project_root: Path, tag: str, expected_commit: Optional[str] = None
) -> Dict[str, object]:
    """Require a clean tagged checkout whose version, tag, and commit agree."""
    project_root = _require_directory(project_root, label="project root")
    tag = _validate_tag(tag)
    version = _read_project_version(project_root)
    _validate_release_files(project_root)
    if version != tag:
        raise EvidenceError(f"PROJECT_VERSION {version!r} does not match release tag {tag!r}")

    head_commit = _validate_commit(
        _git(project_root, "rev-parse", "--verify", "HEAD^{commit}")
    )
    tag_commit = _validate_commit(
        _git(project_root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    )
    if tag_commit != head_commit:
        raise EvidenceError(
            f"checked-out commit {head_commit} does not match {tag} commit {tag_commit}"
        )
    if expected_commit is not None and _validate_commit(expected_commit) != head_commit:
        raise EvidenceError(
            f"workflow commit {expected_commit!r} does not match checked-out commit {head_commit}"
        )
    # Untracked files can enter a Docker build context even though they are not
    # part of the tagged commit. Treat them as release contamination too.
    dirty = _git(project_root, "status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise EvidenceError(
            "tracked or untracked files are dirty; release evidence must come from a clean tag"
        )
    return {
        "status": "ok",
        "version": version,
        "tag": tag,
        "commit": head_commit,
    }


def validate_release_history(
    *,
    project_root: Path,
    tag: str,
    releases: Sequence[object],
    latest_release: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Require a monotonic, fully tagged history of published releases.

    The GitHub ``releases/latest`` response is accepted separately because it
    can expose a published release that is temporarily absent from the paged
    releases response.  Combining both views makes the gate fail closed when
    repository release metadata and Git refs drift apart.
    """
    project_root = _require_directory(project_root, label="project root")
    candidate_tag = _validate_tag(tag)
    if isinstance(releases, (str, bytes)) or not isinstance(releases, Sequence):
        raise EvidenceError("release history JSON root must be an array")

    records = list(releases)
    if latest_release is not None:
        if not isinstance(latest_release, Mapping):
            raise EvidenceError("latest release JSON root must be an object or null")
        records.append(latest_release)

    release_tags: list[str] = []
    seen_tags = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise EvidenceError(f"release history item {index} must be an object")
        if record.get("draft") is True:
            continue
        if not isinstance(record.get("published_at"), str) or not str(
            record.get("published_at")
        ).strip():
            raise EvidenceError(f"release history item {index} is not a published release")

        raw_tag = str(record.get("tag_name") or "").strip()
        try:
            release_tag = _validate_tag(raw_tag)
        except EvidenceError as exc:
            raise EvidenceError(
                f"published release has an unsupported tag: {raw_tag!r}"
            ) from exc
        if release_tag in seen_tags:
            continue
        seen_tags.add(release_tag)

        try:
            release_commit = _git(
                project_root,
                "rev-parse",
                "--verify",
                f"refs/tags/{release_tag}^{{commit}}",
            )
        except EvidenceError as exc:
            raise EvidenceError(
                f"published release {release_tag!r} has no matching fetched Git tag"
            ) from exc
        _validate_commit(release_commit)
        release_tags.append(release_tag)

    highest_tag: Optional[str] = None
    for release_tag in release_tags:
        if highest_tag is None or _compare_semver(release_tag, highest_tag) > 0:
            highest_tag = release_tag
        if release_tag != candidate_tag and _compare_semver(candidate_tag, release_tag) <= 0:
            raise EvidenceError(
                f"candidate release {candidate_tag!r} does not advance published release "
                f"{release_tag!r}"
            )

    return {
        "status": "ok",
        "candidate_tag": candidate_tag,
        "published_release_count": len(release_tags),
        "highest_published_tag": highest_tag,
    }


def _load_release_history(path: Path) -> Sequence[object]:
    payload = _read_json_value(path, label="release history")
    if isinstance(payload, (str, bytes)) or not isinstance(payload, list):
        raise EvidenceError("release history JSON root must be an array")
    return payload


def _load_latest_release(path: Path) -> Optional[Mapping[str, object]]:
    payload = _read_json_value(path, label="latest release")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise EvidenceError("latest release JSON root must be an object or null")
    return payload


def _artifact_path(
    directory: Path, name: str, *, label: str, allow_reserved: bool = False
) -> Path:
    name = _safe_filename(name, label=label, allow_reserved=allow_reserved)
    path = directory / name
    _require_regular_file(path, label=label)
    if path.parent.resolve() != directory:
        raise EvidenceError(f"{label} escapes the evidence directory: {name!r}")
    return path


def _validate_source_archive(path: Path, tag: str) -> None:
    expected_prefix = f"Beacon-{tag}"
    required_names = {
        f"{expected_prefix}/PROJECT_VERSION",
        f"{expected_prefix}/LICENSE",
        f"{expected_prefix}/THIRD_PARTY_NOTICES.md",
        f"{expected_prefix}/SECURITY.md",
    }
    seen = set()
    present = set()
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for index, member in enumerate(archive):
                if index >= MAX_SOURCE_MEMBERS:
                    raise EvidenceError("source archive contains too many members")
                safe_path = _safe_archive_member(member.name)
                normalized = safe_path.as_posix().rstrip("/")
                if not safe_path.parts or safe_path.parts[0] != expected_prefix:
                    raise EvidenceError(
                        f"source archive member is outside {expected_prefix}/: {member.name!r}"
                    )
                folded = normalized.casefold()
                if folded in seen:
                    raise EvidenceError(f"source archive contains duplicate paths: {member.name!r}")
                seen.add(folded)
                present.add(normalized)
                if not (member.isfile() or member.isdir()):
                    raise EvidenceError(
                        f"source archive contains a non-file member: {member.name!r}"
                    )
    except (tarfile.TarError, OSError) as exc:
        raise EvidenceError(f"source archive is invalid: {path}: {exc}") from exc
    missing = sorted(required_names - present)
    if missing:
        raise EvidenceError(f"source archive is missing required release files: {missing!r}")


def _validate_sbom(path: Path) -> None:
    sbom = _read_json_object(path, label="SBOM")
    spdx_version = sbom.get("spdxVersion")
    document_name = sbom.get("name")
    namespace = sbom.get("documentNamespace")
    packages = sbom.get("packages")
    creation_info = sbom.get("creationInfo")
    creators = creation_info.get("creators") if isinstance(creation_info, dict) else None
    if spdx_version != "SPDX-2.3":
        raise EvidenceError("SBOM must use JSON-formatted SPDX 2.3")
    if document_name != "Beacon":
        raise EvidenceError("SPDX SBOM document name must be Beacon")
    if sbom.get("dataLicense") != "CC0-1.0":
        raise EvidenceError("SPDX SBOM dataLicense must be CC0-1.0")
    if not isinstance(namespace, str) or not namespace.startswith("https://"):
        raise EvidenceError("SPDX SBOM documentNamespace is missing")
    if not isinstance(creators, list) or not any(
        isinstance(value, str) and value.startswith("Tool: syft-") for value in creators
    ):
        raise EvidenceError("SPDX SBOM must identify the Syft generator")
    if not isinstance(packages, list) or not packages:
        raise EvidenceError("SPDX SBOM must contain at least one package")


def _validate_sigstore_bundle(path: Path, *, label: str) -> None:
    bundle = _read_json_object(path, label=label)
    media_type = bundle.get("mediaType")
    if not isinstance(media_type, str) or "application/vnd.dev.sigstore.bundle" not in media_type:
        raise EvidenceError(f"{label} is not a Sigstore bundle")
    if not isinstance(bundle.get("verificationMaterial"), dict):
        raise EvidenceError(f"{label} verificationMaterial is missing")
    if not isinstance(bundle.get("dsseEnvelope"), dict):
        raise EvidenceError(f"{label} dsseEnvelope is missing")


def _validate_verification_record(path: Path, *, predicate_type: str, label: str) -> None:
    try:
        records = json.loads(_read_limited(path, label=label).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(records, list) or not records:
        raise EvidenceError(f"{label} must contain at least one verified attestation")
    matching_predicate = False
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("attestation"), dict):
            raise EvidenceError(f"{label} contains an invalid attestation record")
        verification = record.get("verificationResult")
        if not isinstance(verification, dict):
            raise EvidenceError(f"{label} verificationResult is missing")
        statement = verification.get("statement")
        if isinstance(statement, dict) and statement.get("predicateType") == predicate_type:
            matching_predicate = True
    if not matching_predicate:
        raise EvidenceError(f"{label} does not verify predicate type {predicate_type!r}")


def _validate_artifact_payload(role: str, path: Path, *, tag: str) -> None:
    if role == "source":
        _validate_source_archive(path, tag)
    elif role == "sbom":
        _validate_sbom(path)
    elif role in {"provenance-attestation", "sbom-attestation"}:
        _validate_sigstore_bundle(path, label=role)
    elif role == "provenance-verification":
        _validate_verification_record(
            path,
            predicate_type="https://slsa.dev/provenance/v1",
            label=role,
        )
    elif role == "sbom-verification":
        _validate_verification_record(
            path,
            predicate_type="https://spdx.dev/Document",
            label=role,
        )


def _validate_repository(repository: str) -> str:
    repository = str(repository or "").strip()
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise EvidenceError(f"invalid GitHub repository identifier: {repository!r}")
    return repository


def _validate_workflow_url(workflow_run_url: str) -> str:
    workflow_run_url = str(workflow_run_url or "").strip()
    parsed = urlparse(workflow_run_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise EvidenceError(f"invalid HTTPS workflow run URL: {workflow_run_url!r}")
    return workflow_run_url


def _write_new_file(path: Path, payload: bytes) -> None:
    if _path_exists(path):
        raise EvidenceError(f"release evidence already exists and will not be overwritten: {path}")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise EvidenceError(f"cannot write release evidence {path}: {exc}") from exc


def assemble_evidence(
    *,
    project_root: Path,
    directory: Path,
    tag: str,
    commit: str,
    repository: str,
    workflow_run_url: str,
    artifacts: Mapping[str, str],
) -> Dict[str, object]:
    """Create a manifest and checksums without overwriting prior evidence."""
    project_root = _require_directory(project_root, label="project root")
    directory = _require_directory(directory, label="evidence directory")
    tag = _validate_tag(tag)
    commit = _validate_commit(commit)
    repository = _validate_repository(repository)
    workflow_run_url = _validate_workflow_url(workflow_run_url)
    version = _read_project_version(project_root)
    _validate_release_files(project_root)
    if tag != version:
        raise EvidenceError(f"PROJECT_VERSION {version!r} does not match release tag {tag!r}")
    if set(artifacts) != REQUIRED_ROLES:
        missing = sorted(REQUIRED_ROLES - set(artifacts))
        unexpected = sorted(set(artifacts) - REQUIRED_ROLES)
        raise EvidenceError(
            f"release artifacts must contain exactly the required roles; "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )

    if _path_exists(directory / MANIFEST_NAME) or _path_exists(directory / CHECKSUM_NAME):
        raise EvidenceError("release manifest/checksum output already exists")

    entries = []
    seen_names = set()
    for role in sorted(artifacts):
        if not ROLE_PATTERN.fullmatch(role):
            raise EvidenceError(f"invalid artifact role: {role!r}")
        name = _safe_filename(artifacts[role], label=f"{role} filename")
        folded = name.casefold()
        if folded in seen_names:
            raise EvidenceError(f"duplicate artifact filename: {name!r}")
        seen_names.add(folded)
        path = _artifact_path(directory, name, label=role)
        _validate_artifact_payload(role, path, tag=tag)
        digest, size = _sha256_file(path)
        entries.append({"role": role, "name": name, "sha256": digest, "size": size})

    manifest = {
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "version": version,
        "tag": tag,
        "source_ref": f"refs/tags/{tag}",
        "commit": commit,
        "repository": repository,
        "workflow_run_url": workflow_run_url,
        "artifacts": entries,
        "verification": {
            "checksums": CHECKSUM_NAME,
            "github_cli": (
                f"gh attestation verify --repo {repository} --source-ref refs/tags/{tag} "
                f"--source-digest {commit} <source-archive>"
            ),
        },
    }
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_new_file(directory / MANIFEST_NAME, manifest_payload)

    checksum_rows = []
    for entry in sorted(entries, key=lambda value: str(value["name"])):
        checksum_rows.append(f"{entry['sha256']}  {entry['name']}")
    manifest_hash, _ = _sha256_file(directory / MANIFEST_NAME)
    checksum_rows.append(f"{manifest_hash}  {MANIFEST_NAME}")
    checksum_payload = ("\n".join(checksum_rows) + "\n").encode("ascii")
    _write_new_file(directory / CHECKSUM_NAME, checksum_payload)

    return {
        "status": "assembled",
        "schema": SCHEMA,
        "version": version,
        "commit": commit,
        "artifact_count": len(entries),
        "directory": str(directory),
    }


def _manifest_artifacts(manifest: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
    raw_entries = manifest.get("artifacts")
    if not isinstance(raw_entries, list):
        raise EvidenceError("release manifest artifacts must be an array")
    entries: Dict[str, Dict[str, object]] = {}
    roles = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise EvidenceError("release manifest contains a non-object artifact")
        role = str(raw_entry.get("role", ""))
        name = _safe_filename(str(raw_entry.get("name", "")), label="manifest artifact name")
        digest = str(raw_entry.get("sha256", ""))
        try:
            size = int(raw_entry.get("size"))
        except (TypeError, ValueError) as exc:
            raise EvidenceError(f"invalid manifest artifact size for {name!r}") from exc
        if not ROLE_PATTERN.fullmatch(role) or role in roles:
            raise EvidenceError(f"invalid or duplicate manifest artifact role: {role!r}")
        if name.casefold() in entries:
            raise EvidenceError(f"duplicate manifest artifact name: {name!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or size < 0:
            raise EvidenceError(f"invalid manifest digest or size for {name!r}")
        roles.add(role)
        entries[name.casefold()] = {
            "role": role,
            "name": name,
            "sha256": digest,
            "size": size,
        }
    if roles != REQUIRED_ROLES:
        raise EvidenceError("release manifest does not contain all required artifact roles")
    return entries


def _read_checksums(path: Path) -> Dict[str, str]:
    try:
        text = _read_limited(path, label=CHECKSUM_NAME, limit=4 * 1024 * 1024).decode("ascii")
    except UnicodeError as exc:
        raise EvidenceError(f"{CHECKSUM_NAME} must be ASCII: {exc}") from exc
    checksums: Dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = CHECKSUM_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise EvidenceError(f"invalid {CHECKSUM_NAME} line {line_number}")
        digest, name = match.groups()
        folded = name.casefold()
        if folded in checksums:
            raise EvidenceError(f"duplicate {CHECKSUM_NAME} filename: {name!r}")
        checksums[folded] = digest
    if not checksums:
        raise EvidenceError(f"{CHECKSUM_NAME} is empty")
    return checksums


def verify_evidence(*, directory: Path) -> Dict[str, object]:
    """Verify exact file membership, hashes, and semantic release evidence."""
    directory = _require_directory(directory, label="evidence directory")
    manifest_path = _artifact_path(
        directory, MANIFEST_NAME, label="release manifest", allow_reserved=True
    )
    checksum_path = _artifact_path(
        directory, CHECKSUM_NAME, label=CHECKSUM_NAME, allow_reserved=True
    )
    manifest = _read_json_object(manifest_path, label="release manifest")
    if manifest.get("schema") != SCHEMA:
        raise EvidenceError("unsupported release evidence schema")
    version = _validate_tag(str(manifest.get("version", "")))
    if manifest.get("tag") != version or manifest.get("source_ref") != f"refs/tags/{version}":
        raise EvidenceError("release manifest version, tag, and source_ref do not agree")
    commit = _validate_commit(str(manifest.get("commit", "")))
    _validate_repository(str(manifest.get("repository", "")))
    _validate_workflow_url(str(manifest.get("workflow_run_url", "")))
    entries = _manifest_artifacts(manifest)
    checksums = _read_checksums(checksum_path)

    expected_checksum_names = set(entries) | {MANIFEST_NAME.casefold()}
    if set(checksums) != expected_checksum_names:
        raise EvidenceError(f"{CHECKSUM_NAME} file membership does not match the manifest")

    expected_directory_names = expected_checksum_names | {CHECKSUM_NAME.casefold()}
    actual_directory_names = set()
    try:
        children = list(directory.iterdir())
    except OSError as exc:
        raise EvidenceError(f"cannot list evidence directory: {exc}") from exc
    for child in children:
        _require_regular_file(child, label="evidence member")
        folded = child.name.casefold()
        if folded in actual_directory_names:
            raise EvidenceError(f"duplicate case-insensitive evidence filename: {child.name!r}")
        actual_directory_names.add(folded)
    if actual_directory_names != expected_directory_names:
        raise EvidenceError("evidence directory contains missing or unmanifested files")

    for folded_name, entry in entries.items():
        path = _artifact_path(directory, str(entry["name"]), label=str(entry["role"]))
        digest, size = _sha256_file(path)
        if digest != entry["sha256"] or size != entry["size"]:
            raise EvidenceError(f"manifest hash or size mismatch for {entry['name']!r}")
        if checksums[folded_name] != digest:
            raise EvidenceError(f"{CHECKSUM_NAME} mismatch for {entry['name']!r}")
        _validate_artifact_payload(str(entry["role"]), path, tag=version)

    manifest_digest, _ = _sha256_file(manifest_path)
    if checksums[MANIFEST_NAME.casefold()] != manifest_digest:
        raise EvidenceError("release manifest checksum mismatch")
    return {
        "status": "ok",
        "schema": SCHEMA,
        "version": version,
        "commit": commit,
        "artifact_count": len(entries),
        "directory": str(directory),
    }


def _parse_artifacts(values: Sequence[str]) -> Dict[str, str]:
    artifacts: Dict[str, str] = {}
    for value in values:
        role, separator, name = value.partition("=")
        if not separator or not ROLE_PATTERN.fullmatch(role):
            raise EvidenceError(f"artifact must use ROLE=FILENAME syntax: {value!r}")
        if role in artifacts:
            raise EvidenceError(f"duplicate artifact role: {role!r}")
        artifacts[role] = _safe_filename(name, label=f"{role} filename")
    return artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate refs/history, assemble, or verify Beacon release evidence"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-ref", help="Validate a clean tagged release checkout")
    validate.add_argument("--root", type=Path, default=Path.cwd())
    validate.add_argument("--tag", required=True)
    validate.add_argument("--commit")

    history = commands.add_parser(
        "validate-history",
        help="Validate published release tags and monotonic version precedence",
    )
    history.add_argument("--root", type=Path, default=Path.cwd())
    history.add_argument("--tag", required=True)
    history.add_argument("--releases", type=Path, required=True)
    history.add_argument("--latest-release", type=Path, required=True)

    assemble = commands.add_parser("assemble", help="Write release manifest and SHA256SUMS")
    assemble.add_argument("--project-root", type=Path, default=Path.cwd())
    assemble.add_argument("--directory", type=Path, required=True)
    assemble.add_argument("--tag", required=True)
    assemble.add_argument("--commit", required=True)
    assemble.add_argument("--repository", required=True)
    assemble.add_argument("--workflow-run-url", required=True)
    assemble.add_argument("--artifact", action="append", default=[], metavar="ROLE=FILENAME")

    verify = commands.add_parser("verify", help="Verify a release-evidence directory")
    verify.add_argument("--directory", type=Path, required=True)
    return parser


def _print_result(result: Mapping[str, object]) -> None:
    print(json.dumps(dict(result), ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "validate-ref":
            result = validate_release_ref(
                project_root=arguments.root,
                tag=arguments.tag,
                expected_commit=arguments.commit,
            )
        elif arguments.command == "validate-history":
            result = validate_release_history(
                project_root=arguments.root,
                tag=arguments.tag,
                releases=_load_release_history(arguments.releases),
                latest_release=_load_latest_release(arguments.latest_release),
            )
        elif arguments.command == "assemble":
            result = assemble_evidence(
                project_root=arguments.project_root,
                directory=arguments.directory,
                tag=arguments.tag,
                commit=arguments.commit,
                repository=arguments.repository,
                workflow_run_url=arguments.workflow_run_url,
                artifacts=_parse_artifacts(arguments.artifact),
            )
        else:
            result = verify_evidence(directory=arguments.directory)
    except EvidenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
