import logging
import os
from datetime import timedelta
from typing import Tuple

from django.utils import timezone

from app.utils.SystemConfigHelper import get_bool, get_int



logger = logging.getLogger(__name__)
def _realpath(path: str) -> str:
    """处理真实路径。"""
    return os.path.realpath(os.path.abspath(path))


def _is_under(path: str, root: str) -> bool:
    """判断低于。"""
    try:
        p = _realpath(path)
        r = _realpath(root)
    except Exception:
        return False
    if p == r:
        return True
    return p.startswith(r.rstrip(os.sep) + os.sep)


def _count_files(root: str) -> int:
    """统计`files`。"""
    if not root or not os.path.isdir(root):
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.isfile(abs_path):
                total += 1
    return int(total)


def _recording_root_from_config(config) -> str:
    """从配置获取录制根目录。"""
    rec_root = str(getattr(config, "recordingStoragePath", "") or "").strip()
    if rec_root:
        return rec_root

    storage_root = str(getattr(config, "storageRootPath", "") or "").strip()
    if storage_root:
        return os.path.join(storage_root, "recordings")

    upload_dir = str(getattr(config, "uploadDir", "") or "").strip()
    if upload_dir:
        return os.path.join(upload_dir, "recordings")

    return ""


def _safe_getmtime(path: str) -> float:
    """处理安全`getmtime`。"""
    try:
        return float(os.path.getmtime(path) or 0.0)
    except Exception:
        return 0.0


def _try_remove_file(path: str) -> bool:
    """处理`try``remove`文件。"""
    try:
        os.remove(path)
    except Exception:
        return False
    return True


def _try_remove_empty_dir(dirpath: str, root: str) -> None:
    """返回`try``remove`空目录。"""
    if dirpath == root:
        return
    try:
        if not os.listdir(dirpath):
            os.rmdir(dirpath)
    except Exception:
        logger.debug("suppressed exception in app/utils/RecordingDataCleaner.py:82", exc_info=True)


def _delete_old_files_in_dir(dirpath: str, filenames, *, rec_root: str, cutoff_ts: float) -> int:
    """返回`delete``old``files``in`目录。"""
    deleted = 0
    for filename in filenames or []:
        abs_path = os.path.join(dirpath, filename)
        if not os.path.isfile(abs_path):
            continue
        if not _is_under(abs_path, rec_root):
            continue
        if _safe_getmtime(abs_path) >= cutoff_ts:
            continue
        if _try_remove_file(abs_path):
            deleted += 1
    return deleted


def _cleanup_recording_tree(rec_root: str, cutoff_ts: float) -> int:
    """清理录制`tree`。"""
    deleted = 0
    for dirpath, _dirnames, filenames in os.walk(rec_root, topdown=False):
        deleted += _delete_old_files_in_dir(dirpath, filenames, rec_root=rec_root, cutoff_ts=cutoff_ts)
        _try_remove_empty_dir(dirpath, rec_root)
    return int(deleted)


def cleanup_recording_data(config) -> Tuple[int, int]:
    """清理录制数据。
    
    Auto cleanup recording files by retention days (industrial delivery).
    
        Returns:
          - deleted_files: number of files deleted
          - remaining_files: number of files remaining
    """
    enabled = get_bool("recordingDataAutoCleanEnabled", False)
    retention_days = get_int("recordingDataRetentionDays", 0, min_value=0, max_value=3650)

    rec_root = _recording_root_from_config(config)
    if not rec_root or not os.path.isdir(rec_root):
        return 0, 0

    if not enabled or retention_days <= 0:
        return 0, _count_files(rec_root)

    cutoff = timezone.now() - timedelta(days=int(retention_days))
    cutoff_ts = cutoff.timestamp()

    deleted = _cleanup_recording_tree(rec_root, cutoff_ts)
    return int(deleted), _count_files(rec_root)
