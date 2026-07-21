import logging
import os
from typing import Any, Dict, List, Tuple

from django.db import close_old_connections

from app.models import Alarm
from app.utils.AlarmDataCleaner import configured_alarm_storage_roots, remove_alarm_data
from app.utils.SystemConfigHelper import get_int



logger = logging.getLogger(__name__)
def _dir_size_bytes(root: str) -> int:
    """返回目录占用的字节数。"""
    if not root or not os.path.isdir(root):
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            p = os.path.join(dirpath, filename)
            try:
                total += int(os.path.getsize(p) or 0)
            except Exception:
                continue
    return int(total)


def _cleanup_empty_dirs(root: str) -> None:
    """清理空目录。"""
    if not root or not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        if dirnames or filenames:
            continue
        try:
            os.rmdir(dirpath)
        except Exception:
            logger.debug("suppressed exception in app/utils/StorageQuotaCleaner.py:38", exc_info=True)


def _alarm_roots_size_bytes(roots: List[str]) -> int:
    """Return total bytes across canonical, non-overlapping alarm roots."""
    return sum(_dir_size_bytes(root) for root in roots)


def _get_recordings_root(config: Any) -> str:
    """获取`recordings`根目录。"""
    root = str(getattr(config, "recordingStoragePath", "") or "").strip()
    if root:
        return root
    storage_root = str(getattr(config, "storageRootPath", "") or "").strip()
    if storage_root:
        return os.path.join(storage_root, "recordings")
    upload_dir = str(getattr(config, "uploadDir", "") or "").strip()
    if upload_dir:
        return os.path.join(upload_dir, "recordings")
    return ""


def _trim_alarm_rows_until_under_quota(config: Any, *, max_bytes: int, current_bytes: int) -> Tuple[int, int]:
    """裁剪告警记录`until`低于配额。"""
    current = int(current_bytes or 0)
    deleted_rows = 0
    qs = Alarm.objects.all().order_by("create_time", "id")
    for alarm in qs.iterator(chunk_size=200):
        close_old_connections()
        if current <= max_bytes:
            break

        removed, removed_bytes = remove_alarm_data(
            config,
            alarm.id,
            require_reclaimed_bytes=True,
        )
        if removed:
            deleted_rows += 1

        if removed_bytes > 0:
            current = max(0, current - removed_bytes)

    return deleted_rows, current


def cleanup_alarm_data_by_quota(config: Any, max_bytes: int) -> Dict[str, Any]:
    """清理告警数据`by`配额。
    
    Enforce alarm data storage quota by deleting oldest Alarm rows and their referenced files.
    
        This is best-effort and safe:
        - only deletes validated alarm/* file references
        - keeps DB rows when any storage step fails
    """
    max_bytes = int(max_bytes or 0)
    alarm_roots = configured_alarm_storage_roots(config, collapse_overlaps=True)
    before = _alarm_roots_size_bytes(alarm_roots)
    deleted_rows = 0

    if max_bytes <= 0 or before <= max_bytes:
        return {
            "enabled": bool(max_bytes > 0),
            "max_bytes": max_bytes,
            "before_bytes": before,
            "after_bytes": before,
            "deleted_rows": 0,
            "remaining_rows": Alarm.objects.count(),
        }

    deleted_rows, _current = _trim_alarm_rows_until_under_quota(config, max_bytes=max_bytes, current_bytes=before)

    after = _alarm_roots_size_bytes(alarm_roots)
    return {
        "enabled": True,
        "max_bytes": max_bytes,
        "before_bytes": before,
        "after_bytes": after,
        "deleted_rows": deleted_rows,
        "remaining_rows": Alarm.objects.count(),
    }


def _collect_recording_files(recordings_root: str) -> List[Tuple[float, str, int]]:
    """处理`collect`录制`files`。"""
    files: List[Tuple[float, str, int]] = []
    if not recordings_root or not os.path.isdir(recordings_root):
        return files
    for dirpath, _dirnames, filenames in os.walk(recordings_root):
        for filename in filenames:
            p = os.path.join(dirpath, filename)
            try:
                st = os.stat(p)
            except Exception:
                continue
            files.append((float(st.st_mtime), p, int(st.st_size or 0)))
    return files


def _delete_oldest_files_until_under_quota(
    files: List[Tuple[float, str, int]],
    *,
    current_bytes: int,
    max_bytes: int,
) -> Tuple[int, int]:
    """处理`delete``oldest``files``until`低于配额。"""
    deleted_files = 0
    current = int(current_bytes or 0)
    for _mtime, p, size in files:
        if current <= max_bytes:
            break
        try:
            os.remove(p)
            deleted_files += 1
            current = max(0, current - int(size or 0))
        except Exception:
            continue
    return deleted_files, current


def cleanup_recording_data_by_quota(config: Any, max_bytes: int) -> Dict[str, Any]:
    """清理录制数据`by`配额。
    
    Enforce recording storage quota by deleting oldest files under recordings root.
    
        Recordings are currently filesystem-only (no DB rows), so we delete by mtime.
    """
    max_bytes = int(max_bytes or 0)
    recordings_root = _get_recordings_root(config)
    before = _dir_size_bytes(recordings_root)
    deleted_files = 0

    if max_bytes <= 0 or before <= max_bytes:
        return {
            "enabled": bool(max_bytes > 0),
            "max_bytes": max_bytes,
            "before_bytes": before,
            "after_bytes": before,
            "deleted_files": 0,
        }

    files = _collect_recording_files(recordings_root)
    files.sort(key=lambda item: item[0])  # oldest first

    deleted_files, _current = _delete_oldest_files_until_under_quota(files, current_bytes=before, max_bytes=max_bytes)

    _cleanup_empty_dirs(recordings_root)
    after = _dir_size_bytes(recordings_root)
    return {
        "enabled": True,
        "max_bytes": max_bytes,
        "before_bytes": before,
        "after_bytes": after,
        "deleted_files": deleted_files,
    }


def cleanup_by_storage_quota(config: Any) -> Dict[str, Any]:
    """清理`by`存储配额。
    
    Entry point for background services: reads SystemConfig keys and enforces quotas.
    
        Keys:
          - alarmDataMaxStorageMB
          - recordingDataMaxStorageMB
    """
    # Upper bounds are intentionally generous; operators can tune in UI.
    alarm_max_mb = int(get_int("alarmDataMaxStorageMB", 0, min_value=0, max_value=1024 * 1024))
    rec_max_mb = int(get_int("recordingDataMaxStorageMB", 0, min_value=0, max_value=1024 * 1024))

    res: Dict[str, Any] = {}
    res["alarm"] = cleanup_alarm_data_by_quota(config, alarm_max_mb * 1024 * 1024 if alarm_max_mb > 0 else 0)
    res["recordings"] = cleanup_recording_data_by_quota(config, rec_max_mb * 1024 * 1024 if rec_max_mb > 0 else 0)
    return res
