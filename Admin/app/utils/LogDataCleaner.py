from typing import Any, Dict

from app.utils.SystemConfigHelper import get_bool, get_int


def cleanup_logs(*, dry_run: bool = False) -> Dict[str, Any]:
    """清理`logs`。
    
    Cleanup log directories based on SystemConfig:
          - logAutoCleanEnabled: 1/0
          - logRetentionDays: int days
    
        Returns a best-effort summary dict (never raises).
    """
    enabled = bool(get_bool("logAutoCleanEnabled", False))
    days = int(get_int("logRetentionDays", 0, min_value=0, max_value=3650))

    if (not enabled) or days <= 0:
        return {
            "ok": True,
            "skipped": True,
            "enabled": bool(enabled),
            "retention_days": int(days),
            "dry_run": bool(dry_run),
            "deleted_files": 0,
            "kept_files": 0,
            "deleted_bytes": 0,
            "log_dirs": [],
        }

    from app.utils.LogCleaner import cleanup_default_log_dirs

    try:
        result = cleanup_default_log_dirs(retention_days=days, dry_run=dry_run)
        result["ok"] = True
        result["skipped"] = False
        result["enabled"] = True
        return result
    except Exception as e:
        return {
            "ok": False,
            "skipped": False,
            "enabled": True,
            "retention_days": int(days),
            "dry_run": bool(dry_run),
            "error": str(e),
        }
