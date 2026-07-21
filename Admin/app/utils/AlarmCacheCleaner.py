import os
import shutil
import time

from django.db import close_old_connections


def _iter_alarm_leaf_dirs(alarm_root: str):
    """遍历告警`leaf`目录列表。"""
    if not os.path.isdir(alarm_root):
        return
    for control_code in os.listdir(alarm_root):
        p1 = os.path.join(alarm_root, control_code)
        if not os.path.isdir(p1):
            continue
        for leaf in os.listdir(p1):
            p2 = os.path.join(p1, leaf)
            if os.path.isdir(p2):
                yield control_code, leaf, p2


def cleanup_alarm_compose_cache(config, *, dry_run: bool = False):
    """
    清理报警视频合成产生的目录缓存：
    - 只删除超过保留时间的目录
    - 若数据库中有 Alarm 记录引用该目录（video_path/image_path 前缀匹配），则不删

    When dry_run=True:
    - Does NOT delete any directories
    - Returns counts as "(would_delete, kept)" for audit/verification purposes.
    """
    retention_hours = int(getattr(config, "alarmComposeCacheRetentionHours", 72) or 72)
    if retention_hours < 1:
        retention_hours = 1
    cutoff = time.time() - retention_hours * 3600

    alarm_root = os.path.join(config.uploadDir, "alarm")
    if not os.path.isdir(alarm_root):
        return 0, 0

    close_old_connections()
    from app.models import Alarm

    deleted = 0
    kept = 0

    for control_code, leaf, path in _iter_alarm_leaf_dirs(alarm_root):
        try:
            st = os.stat(path)
        except Exception:
            continue
        if st.st_mtime > cutoff:
            kept += 1
            continue

        rel_prefix = f"alarm/{control_code}/{leaf}/"
        rel_prefix_win = rel_prefix.replace("/", "\\")
        # JSON strings will escape backslashes, so we also try a doubled variant for contains checks.
        rel_prefix_win_json = rel_prefix.replace("/", "\\\\")

        has_ref = (
            Alarm.objects.filter(video_path__startswith=rel_prefix).exists()
            or Alarm.objects.filter(video_path__startswith=rel_prefix_win).exists()
            or Alarm.objects.filter(image_path__startswith=rel_prefix).exists()
            or Alarm.objects.filter(image_path__startswith=rel_prefix_win).exists()
            or Alarm.objects.filter(extra_images__contains=rel_prefix).exists()
            or Alarm.objects.filter(extra_images__contains=rel_prefix_win_json).exists()
            or Alarm.objects.filter(metadata__contains=rel_prefix).exists()
            or Alarm.objects.filter(metadata__contains=rel_prefix_win_json).exists()
        )
        if has_ref:
            kept += 1
            continue

        if dry_run:
            deleted += 1
            continue

        try:
            shutil.rmtree(path)
            deleted += 1
        except Exception:
            kept += 1

    return deleted, kept
