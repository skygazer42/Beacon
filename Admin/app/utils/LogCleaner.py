import logging
import os
import time
from typing import Any, Dict, List, Optional
import runtime_paths  # type: ignore


logger = logging.getLogger(__name__)


def _now_seconds() -> float:
    """返回当前时间秒数。"""
    try:
        return float(time.time())
    except Exception:
        return 0.0


def _root_dir() -> str:
    """返回根目录目录。
    
    Resolve Beacon product root directory (best-effort).
    
        When running from source tree, this falls back to repo root.
    """
    try:
        root = str(runtime_paths.resolve_root_dir() or "").strip()
        if root:
            return root
    except Exception:
        logger.debug("suppressed exception in app/utils/LogCleaner.py:32", exc_info=True)

    # Admin/app/utils/LogCleaner.py -> Admin/app/utils -> Admin/app -> Admin -> repo root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def list_candidate_log_dirs(root_dir: Optional[str] = None) -> List[str]:
    """返回列表`candidate``log`目录列表。
    
    Return existing log directories that should be considered for cleanup.
    
        Notes:
        - Prefer env `BEACON_LOG_DIR` when set.
        - Include common component log dirs under the product root.
    """
    dirs: List[str] = []

    env_dir = str(os.environ.get("BEACON_LOG_DIR", "") or "").strip()
    if env_dir:
        dirs.append(env_dir)

    root = os.path.normpath(str(root_dir or _root_dir() or "").strip())
    if root:
        rels = [
            "log",
            "logs",
            os.path.join("Admin", "log"),
            os.path.join("Admin", "logs"),
            os.path.join("Analyzer", "log"),
            os.path.join("Analyzer", "logs"),
            os.path.join("MediaServer", "log"),
            os.path.join("MediaServer", "logs"),
        ]
        for rel in rels:
            dirs.append(os.path.join(root, rel))

    # De-dup and keep only existing directories.
    seen = set()
    out: List[str] = []
    for d in dirs:
        d = os.path.normpath(str(d or "").strip())
        if not d or d in seen:
            continue
        seen.add(d)
        if os.path.isdir(d):
            out.append(d)
    return out


def _normalize_retention_days(retention_days: Any) -> int:
    """执行归一化`retention``days`。"""
    try:
        days = int(retention_days or 0)
    except Exception:
        days = 0
    return max(0, min(3650, days))


def _normalize_cleanup_log_dirs(log_dirs: Optional[List[str]]) -> List[str]:
    """执行归一化清理`log`目录列表。"""
    out: List[str] = []
    seen = set()
    for path in log_dirs or []:
        raw_path = str(path or "").strip()
        if not raw_path:
            continue
        normalized = os.path.normpath(raw_path)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _cleanup_file(path: str, *, cutoff: float, dry_run: bool) -> Dict[str, int]:
    """清理文件。"""
    try:
        if not os.path.isfile(path):
            return {"deleted_files": 0, "kept_files": 0, "deleted_bytes": 0}
        try:
            st = os.stat(path)
        except Exception:
            return {"deleted_files": 0, "kept_files": 0, "deleted_bytes": 0}

        if float(getattr(st, "st_mtime", 0) or 0) >= cutoff:
            return {"deleted_files": 0, "kept_files": 1, "deleted_bytes": 0}

        file_size = int(getattr(st, "st_size", 0) or 0)
        if dry_run:
            return {"deleted_files": 1, "kept_files": 0, "deleted_bytes": file_size}

        try:
            os.remove(path)
            return {"deleted_files": 1, "kept_files": 0, "deleted_bytes": file_size}
        except Exception:
            return {"deleted_files": 0, "kept_files": 1, "deleted_bytes": 0}
    except Exception:
        return {"deleted_files": 0, "kept_files": 0, "deleted_bytes": 0}


def _cleanup_empty_dirs(root: str) -> None:
    """清理空目录。"""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        _ = dirnames
        if filenames or dirpath == root:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except Exception:
            logger.debug("suppressed exception in app/utils/LogCleaner.py:142", exc_info=True)


def _build_cleanup_result(*, dry_run: bool, retention_days: int, deleted_files: int, kept_files: int, deleted_bytes: int, log_dirs: List[str]) -> Dict[str, Any]:
    """构建清理结果。"""
    return {
        "dry_run": bool(dry_run),
        "retention_days": int(retention_days),
        "deleted_files": int(deleted_files),
        "kept_files": int(kept_files),
        "deleted_bytes": int(deleted_bytes),
        "log_dirs": log_dirs,
    }


def cleanup_log_dirs(
    log_dirs: List[str],
    *,
    retention_days: int,
    dry_run: bool = False,
    now_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """清理`log`目录列表。
    
    Cleanup files under log_dirs older than retention_days.
    
        This is a filesystem operation. It is best-effort: errors are ignored.
    """
    days = _normalize_retention_days(retention_days)
    log_dirs = _normalize_cleanup_log_dirs(log_dirs)

    if days <= 0:
        return _build_cleanup_result(
            dry_run=dry_run,
            retention_days=days,
            deleted_files=0,
            kept_files=0,
            deleted_bytes=0,
            log_dirs=log_dirs,
        )

    now = float(now_seconds) if isinstance(now_seconds, (int, float)) else _now_seconds()
    cutoff = now - days * 86400

    deleted_files = 0
    kept_files = 0
    deleted_bytes = 0

    for root in log_dirs:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                stats = _cleanup_file(os.path.join(dirpath, filename), cutoff=cutoff, dry_run=dry_run)
                deleted_files += stats["deleted_files"]
                kept_files += stats["kept_files"]
                deleted_bytes += stats["deleted_bytes"]

        _cleanup_empty_dirs(root)

    return _build_cleanup_result(
        dry_run=dry_run,
        retention_days=days,
        deleted_files=deleted_files,
        kept_files=kept_files,
        deleted_bytes=deleted_bytes,
        log_dirs=log_dirs,
    )


def cleanup_default_log_dirs(*, retention_days: int, dry_run: bool = False) -> Dict[str, Any]:
    """清理默认`log`目录列表。"""
    return cleanup_log_dirs(list_candidate_log_dirs(), retention_days=retention_days, dry_run=dry_run)
