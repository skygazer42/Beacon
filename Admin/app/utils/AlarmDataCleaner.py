import errno
import json
import logging
import os
from datetime import timedelta
from typing import Tuple

from django.db import close_old_connections, transaction
from django.utils import timezone

from app.models import Alarm
from app.utils.SafeLog import safe_json_dumps
from app.utils.Security import resolve_under_base, validate_upload_rel_path
from app.utils.SystemConfigHelper import get_bool, get_int


logger = logging.getLogger(__name__)


class _AlarmDeleteNotConfirmed(RuntimeError):
    pass


def _alarm_media_paths(alarm: Alarm) -> list[str]:
    """Return validated, de-duplicated media paths referenced by one alarm."""
    paths = []
    for field_name in ("image_path", "video_path"):
        value = getattr(alarm, field_name, "")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        value = value.strip()
        if value:
            paths.append(value)

    raw_extra_images = getattr(alarm, "extra_images", "")
    if raw_extra_images is not None and not isinstance(raw_extra_images, str):
        raise ValueError("extra_images must be a JSON array")
    raw_extra_images = str(raw_extra_images or "").strip()
    if raw_extra_images:
        extra_images = json.loads(raw_extra_images)
        if not isinstance(extra_images, list):
            raise ValueError("extra_images must be a JSON array")
        for item in extra_images:
            if not isinstance(item, str):
                raise ValueError("extra_images items must be strings")
            item = item.strip()
            if item:
                paths.append(item)

    normalized_paths = []
    seen = set()
    for path in paths:
        normalized = validate_upload_rel_path(path, required_prefix="alarm/")
        if normalized not in seen:
            normalized_paths.append(normalized)
            seen.add(normalized)
    return normalized_paths


def _path_is_within(base_path: str, candidate_path: str) -> bool:
    base = os.path.normcase(os.path.abspath(base_path))
    candidate = os.path.normcase(os.path.abspath(candidate_path))
    prefix = base if base.endswith(os.sep) else base + os.sep
    return candidate.startswith(prefix)


def configured_alarm_storage_roots(
    config,
    *,
    collapse_overlaps: bool = False,
) -> list[str]:
    """Return canonical alarm directories managed by the shared cleaner."""
    explicit_root = str(getattr(config, "alarmStoragePath", "") or "").strip()
    storage_root = str(getattr(config, "storageRootPath", "") or "").strip()
    upload_root = str(getattr(config, "uploadDir", "") or "").strip()
    raw_roots = [
        explicit_root,
        os.path.join(storage_root, "alarm") if storage_root else "",
        os.path.join(upload_root, "alarm") if upload_root else "",
    ]

    roots = []
    seen = set()
    for raw_root in raw_roots:
        if not raw_root:
            continue
        root = os.path.realpath(os.path.abspath(raw_root))
        root_key = os.path.normcase(root)
        if root_key in seen:
            continue
        roots.append(root)
        seen.add(root_key)

    if not collapse_overlaps:
        return roots

    non_overlapping_roots = []
    for root in roots:
        if any(
            os.path.normcase(root) == os.path.normcase(existing_root)
            or _path_is_within(existing_root, root)
            for existing_root in non_overlapping_roots
        ):
            continue
        non_overlapping_roots = [
            existing_root
            for existing_root in non_overlapping_roots
            if not _path_is_within(root, existing_root)
        ]
        non_overlapping_roots.append(root)
    return non_overlapping_roots


def _resolve_alarm_media_files(media_paths, roots):
    """Resolve every path before mutating any file."""
    files_to_remove = []
    parent_dirs = set()
    for media_path in media_paths:
        relative_path = media_path.split("/", 1)[1]
        existing_candidates = []
        for alarm_root in roots:
            candidate = resolve_under_base(alarm_root, relative_path)
            candidate_real = os.path.realpath(candidate)
            if not _path_is_within(alarm_root, candidate_real):
                raise ValueError("media path escapes configured storage root")
            if os.path.normcase(candidate_real) != os.path.normcase(os.path.abspath(candidate)):
                raise ValueError("symbolic links are not allowed in alarm media paths")

            parent_dirs.add((os.path.dirname(candidate), alarm_root))
            if os.path.lexists(candidate):
                existing_candidates.append(candidate)

        if len(existing_candidates) > 1:
            raise ValueError("alarm media path exists in multiple configured roots")
        if existing_candidates:
            candidate = existing_candidates[0]
            if os.path.islink(candidate) or not os.path.isfile(candidate):
                raise ValueError("alarm media path is not a regular file")
            files_to_remove.append(candidate)

    return files_to_remove, parent_dirs


def _remove_empty_alarm_parent_dirs(parent_dir: str, alarm_root: str) -> None:
    """Remove empty media parents without ever removing the alarm root itself."""
    alarm_root = os.path.abspath(alarm_root)
    current = os.path.abspath(parent_dir)
    while current != alarm_root:
        if not _path_is_within(alarm_root, current):
            raise ValueError("refuse to remove directory outside alarm root")
        try:
            os.rmdir(current)
        except OSError as e:
            if e.errno == errno.ENOENT:
                pass
            elif e.errno in (errno.ENOTEMPTY, errno.EEXIST):
                return
            else:
                raise
        current = os.path.dirname(current)


def _delete_alarm_row_atomically(alarm: Alarm, alarm_id) -> None:
    """Delete and confirm one Alarm row in the same database transaction."""
    alarm_pk = alarm.pk
    with transaction.atomic():
        deleted_count, _deleted_objects = alarm.delete()
        if int(deleted_count or 0) <= 0 or Alarm.objects.filter(id=alarm_pk).exists():
            raise _AlarmDeleteNotConfirmed("alarm row deletion was not confirmed")


def remove_alarm_data(
    config,
    alarm_id,
    *,
    require_reclaimed_bytes: bool = False,
) -> Tuple[bool, int]:
    """Strictly remove one Alarm's files and row, returning success and removed bytes.

    Configured storage roots are a trusted service boundary. A future hardening
    pass may use dir_fd/openat to further reduce filesystem TOCTOU exposure.
    """
    removed_bytes = 0
    try:
        alarm = Alarm.objects.get(id=alarm_id)
        media_paths = _alarm_media_paths(alarm)
        files_to_remove = []
        parent_dirs = set()
        if media_paths:
            roots = configured_alarm_storage_roots(config)
            if not roots:
                raise ValueError("alarm storage path is not configured")
            files_to_remove, parent_dirs = _resolve_alarm_media_files(media_paths, roots)

        files_with_sizes = []
        reclaimable_bytes = 0
        for path in files_to_remove:
            try:
                file_size = max(0, int(os.path.getsize(path) or 0))
            except FileNotFoundError:
                continue
            files_with_sizes.append((path, file_size))
            reclaimable_bytes += file_size

        if require_reclaimed_bytes and reclaimable_bytes <= 0:
            return False, 0

        for path, file_size in files_with_sizes:
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            removed_bytes += file_size

        if require_reclaimed_bytes and removed_bytes <= 0:
            return False, 0

        for parent_dir, alarm_root in sorted(
            parent_dirs,
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            _remove_empty_alarm_parent_dirs(parent_dir, alarm_root)

        _delete_alarm_row_atomically(alarm, alarm_id)
        return True, removed_bytes
    except Exception as e:
        logger.warning(
            "alarm data cleanup failed: alarm_id=%s err=%s",
            safe_json_dumps(str(alarm_id), max_len=128),
            safe_json_dumps(str(e), max_len=512),
        )
        return False, removed_bytes


def cleanup_alarm_data(config) -> Tuple[int, int]:
    """Remove alarms older than the configured retention period."""
    enabled = get_bool("alarmDataAutoCleanEnabled", False)
    retention_days = get_int("alarmDataRetentionDays", 0, min_value=0, max_value=3650)

    if not enabled or retention_days <= 0:
        return 0, Alarm.objects.count()

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted = 0
    alarm_ids = (
        Alarm.objects.filter(create_time__lt=cutoff)
        .order_by("id")
        .values_list("id", flat=True)
    )
    for alarm_id in alarm_ids.iterator(chunk_size=200):
        close_old_connections()
        removed, _removed_bytes = remove_alarm_data(config, alarm_id)
        if removed:
            deleted += 1

    return deleted, Alarm.objects.count()
