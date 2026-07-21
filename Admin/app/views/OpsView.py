import csv
import io
import json
import logging
import os
import time
import threading
from typing import Any, Dict

from django.http import HttpResponse
from django.db import connection
from django.utils import timezone

from app.utils.DeploymentMode import get_deployment_mode
from framework.settings import PROJECT_BUILT, PROJECT_FLAG, PROJECT_VERSION, PROJECT_ADMIN_START_TIMESTAMP


CONTENT_TYPE_JSON = "application/json"
MSG_METHOD_NOT_ALLOWED = "method not allowed"
logger = logging.getLogger(__name__)


def _json_response(payload: Dict[str, Any], *, status: int = 200) -> HttpResponse:
    """返回JSON响应。"""
    resp = HttpResponse(json.dumps(payload, ensure_ascii=False, default=str), status=status, content_type=CONTENT_TYPE_JSON)
    # Health/ready endpoints must not be cached by proxies/clients.
    resp["Cache-Control"] = "no-store"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def _get_repo_root() -> str:
    # Admin/app/views/OpsView.py -> Admin/app/views -> Admin/app -> Admin -> repo root
    """获取仓库根目录。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _prom_escape_label_value(value: str) -> str:
    """返回`prom`转义标签值。"""
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


def _prom_format_labels(labels: Dict[str, Any]) -> str:
    """处理`prom``format`标签。"""
    if not labels:
        return ""
    parts = []
    for k, v in labels.items():
        key = str(k).strip()
        if not key:
            continue
        parts.append(f'{key}="{_prom_escape_label_value(str(v))}"')
    if not parts:
        return ""
    return "{" + ",".join(parts) + "}"


def _prom_metric_line(name: str, value: Any, *, labels: Dict[str, Any] = None) -> str:
    """处理`prom``metric``line`。"""
    labels_str = _prom_format_labels(labels or {})
    return f"{name}{labels_str} {value}"


_METRICS_COUNT_CACHE: Dict[str, Dict[str, Any]] = {}
_METRICS_COUNT_CACHE_LOCK = threading.Lock()


def _now_seconds() -> float:
    """返回当前时间秒数。"""
    try:
        return float(time.time())
    except Exception:
        return 0.0


def _cached_value(key: str, ttl_seconds: float, compute_fn):
    """返回`cached`值。"""
    if not key:
        return compute_fn()

    try:
        ttl = float(ttl_seconds or 0)
    except Exception:
        ttl = 0.0

    if ttl <= 0:
        return compute_fn()

    now = _now_seconds()
    if now > 0:
        with _METRICS_COUNT_CACHE_LOCK:
            item = _METRICS_COUNT_CACHE.get(key) or {}
            try:
                ts = float(item.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if ts > 0 and (now - ts) < ttl:
                return item.get("value")

    value = compute_fn()
    if now > 0:
        with _METRICS_COUNT_CACHE_LOCK:
            _METRICS_COUNT_CACHE[key] = {"ts": now, "value": value}
    return value


def _metrics_count_cache_ttl_seconds() -> float:
    """返回指标统计缓存TTL秒数。"""
    raw = str(os.environ.get("BEACON_OPS_METRICS_COUNT_CACHE_TTL_SECONDS", "") or "").strip()
    if not raw:
        return 10.0
    try:
        value = float(raw)
    except Exception:
        value = 10.0
    if value < 0:
        value = 0.0
    if value > 300:
        value = 300.0
    return float(value)


def healthz(request):
    """处理`healthz`。"""
    from app.utils.BackgroundServices import get_background_services_status

    now = int(time.time())
    try:
        started = int(PROJECT_ADMIN_START_TIMESTAMP or 0)
    except Exception:
        started = 0
    uptime = max(0, now - started) if started > 0 else 0

    return _json_response(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "status": "ok",
                "deployment_mode": get_deployment_mode(),
                "version": PROJECT_VERSION,
                "flag": PROJECT_FLAG,
                "built": PROJECT_BUILT,
                "start_timestamp": started,
                "uptime_seconds": uptime,
                "background_services": get_background_services_status(),
            },
        }
    )


def readyz(request):
    """处理`readyz`。"""
    checks: Dict[str, Any] = {}

    db = _check_db()
    checks["db"] = db

    if get_deployment_mode() == "cloud":
        checks["cloud_required_config"] = _check_cloud_required_config()

    ok = True
    for item in checks.values():
        if isinstance(item, dict) and item.get("ok") is False:
            ok = False
            break

    if ok:
        return _json_response({"code": 1000, "msg": "success", "data": {"status": "ok", "checks": checks}})
    return _json_response({"code": 0, "msg": "not ready", "data": {"status": "fail", "checks": checks}}, status=503)


def _uptime_seconds() -> int:
    """返回`uptime`秒数。"""
    now = int(time.time())
    try:
        started = int(PROJECT_ADMIN_START_TIMESTAMP or 0)
    except Exception:
        started = 0
    return max(0, now - started) if started > 0 else 0


def _append_build_metrics(lines, *, uptime: int) -> None:
    """追加构建指标。"""
    lines.append(
        _prom_metric_line(
            "beacon_admin_build_info",
            1,
            labels={
                "version": PROJECT_VERSION,
                "flag": PROJECT_FLAG,
            },
        )
    )
    lines.append(_prom_metric_line("beacon_admin_uptime_seconds", uptime))


def _append_db_metrics(lines) -> None:
    """追加数据库指标。"""
    db = _check_db()
    db_vendor = str(db.get("vendor") or "") or str(getattr(connection, "vendor", "") or "")
    lines.append(_prom_metric_line("beacon_admin_db_up", 1 if db.get("ok") else 0, labels={"vendor": db_vendor}))
    if isinstance(db.get("latency_ms"), int):
        lines.append(_prom_metric_line("beacon_admin_db_latency_ms", int(db.get("latency_ms") or 0), labels={"vendor": db_vendor}))


def _append_system_resource_metrics(lines) -> None:
    """追加系统`resource`指标。"""
    from app.utils.OSSystem import OSSystem

    try:
        info = OSSystem().get_os_info()
    except Exception:
        return

    cpu = info.get("os_cpu_used_rate")
    mem = info.get("os_virtual_mem_used_rate")
    disk = info.get("os_disk_used_rate")
    if isinstance(cpu, (int, float)):
        lines.append(_prom_metric_line("beacon_admin_system_cpu_used_ratio", float(cpu)))
    if isinstance(mem, (int, float)):
        lines.append(_prom_metric_line("beacon_admin_system_mem_used_ratio", float(mem)))
    if isinstance(disk, (int, float)):
        lines.append(_prom_metric_line("beacon_admin_system_disk_used_ratio", float(disk)))


def _append_alarm_outbox_metrics(lines) -> None:
    """追加告警`outbox`指标。"""
    from app.models import AlarmEventOutbox

    ttl = _metrics_count_cache_ttl_seconds()
    pending = _cached_value("alarm_outbox_pending", ttl, lambda: AlarmEventOutbox.objects.filter(status="pending").count())
    failed = _cached_value("alarm_outbox_failed", ttl, lambda: AlarmEventOutbox.objects.filter(status="failed").count())
    lines.append(_prom_metric_line("beacon_admin_alarm_outbox_pending", pending))
    lines.append(_prom_metric_line("beacon_admin_alarm_outbox_failed", failed))


def _append_login_lockout_metrics(lines) -> None:
    """追加登录锁定指标。"""
    from app.models import LoginLockout

    ttl = _metrics_count_cache_ttl_seconds()
    now_ts = timezone.now()
    active = _cached_value("login_lockout_active", ttl, lambda: LoginLockout.objects.filter(locked_until__gt=now_ts).count())
    principals = _cached_value("login_lockout_principals", ttl, lambda: LoginLockout.objects.values("username").distinct().count())
    lines.append(_prom_metric_line("beacon_admin_login_lockout_active", active))
    lines.append(_prom_metric_line("beacon_admin_login_lockout_principals", principals))


def _append_license_metrics(lines) -> None:
    """追加授权指标。"""
    from app.models import LicenseLease

    ttl = _metrics_count_cache_ttl_seconds()

    def _active_qs():
        """处理活动`qs`。"""
        now_ts = timezone.now()
        return LicenseLease.objects.filter(released_at__isnull=True, expires_at__gt=now_ts)

    active_leases = _cached_value("license_active_leases", ttl, lambda: _active_qs().count())
    active_nodes = _cached_value("license_active_nodes", ttl, lambda: _active_qs().values("node_id").distinct().count())
    lines.append(_prom_metric_line("beacon_admin_license_active_leases", active_leases))
    lines.append(_prom_metric_line("beacon_admin_license_active_nodes", active_nodes))


def _append_cloud_metrics(lines) -> None:
    """追加云端指标。"""
    if get_deployment_mode() != "cloud":
        return
    from app.models import CloudAlarmEvent
    total = _cached_value("cloud_alarm_events_total", 30, lambda: CloudAlarmEvent.objects.count())
    lines.append(_prom_metric_line("beacon_admin_cloud_alarm_events_total", total))


def metrics(request):
    """处理指标。"""
    uptime = _uptime_seconds()
    lines = []

    _append_build_metrics(lines, uptime=uptime)
    _append_db_metrics(lines)
    _append_system_resource_metrics(lines)
    _append_alarm_outbox_metrics(lines)
    _append_login_lockout_metrics(lines)
    _append_license_metrics(lines)
    _append_cloud_metrics(lines)

    body = "\n".join(lines) + "\n"
    resp = HttpResponse(body, content_type="text/plain; version=0.0.4; charset=utf-8")
    resp["Cache-Control"] = "no-store"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def audit_export(request):
    """处理审计`export`。"""
    if request.method != "GET":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    from app.views.OpsAuditLogView import _apply_filters, _serialize_audit_row

    export_format = str(request.GET.get("format", "") or "").strip().lower() or "json"
    if export_format not in ("json", "csv"):
        export_format = "json"

    try:
        limit = int(request.GET.get("limit", 1000) or 1000)
    except Exception:
        limit = 1000
    limit = max(1, min(2000, limit))

    from app.models import OpsAuditLog

    qs = OpsAuditLog.objects.all().order_by("-id")
    qs = _apply_filters(qs, request.GET)

    rows = list(qs[:limit])
    serialized_rows = [_serialize_audit_row(r) for r in rows]

    if export_format == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        header = [
            "create_time",
            "event_type",
            "action_label",
            "ok",
            "operator",
            "actor_label",
            "object_label",
            "record_url",
            "source_ip",
            "node_id",
            "control_code",
            "algorithm_code",
            "lease_id",
            "error_code",
            "error_message",
        ]
        writer.writerow(header)
        for item in serialized_rows:
            writer.writerow(
                [
                    item.get("create_time", ""),
                    item.get("event_type", ""),
                    item.get("action_label", ""),
                    "1" if bool(item.get("ok")) else "0",
                    item.get("operator", ""),
                    item.get("actor_label", ""),
                    item.get("object_label", ""),
                    item.get("record_url", ""),
                    item.get("source_ip", ""),
                    item.get("node_id", ""),
                    item.get("control_code", ""),
                    item.get("algorithm_code", ""),
                    item.get("lease_id", ""),
                    item.get("error_code", ""),
                    item.get("error_message", ""),
                ]
            )
        data = out.getvalue()
        resp = HttpResponse(data, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="beacon-audit.csv"'
        return resp

    return _json_response({"code": 1000, "msg": "success", "data": serialized_rows})


def cleanup(request):
    """清理相关数据。
    
    Manual ops cleanup endpoint (industrial delivery).
    
        POST /open/ops/cleanup
        body: { "targets": ["metrics_cache", "alarm_compose_cache"], "dry_run": true }
    
        Notes:
        - Protected by OpenAPI token policy in middleware (when no logged-in session).
        - Supports dry_run for verification before deletion.
    """
    if request.method != "POST":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    payload = _parse_request_payload_dict(request)
    cleanup_options = _cleanup_request_options(payload)
    dry_run = bool(cleanup_options["dry_run"])
    targets = cleanup_options["targets"]

    results: Dict[str, Any] = {}

    if "metrics_cache" in targets:
        results["metrics_cache"] = _cleanup_metrics_cache()

    if "alarm_compose_cache" in targets:
        results["alarm_compose_cache"] = _cleanup_alarm_compose_cache(dry_run=dry_run)

    if "transcode_cache" in targets:
        results["transcode_cache"] = _cleanup_transcode_cache()

    if "logs" in targets:
        results["logs"] = _cleanup_logs(payload, dry_run=dry_run)

    if "tmp_files" in targets:
        results["tmp_files"] = _cleanup_tmp_files(payload, dry_run=dry_run)

    return _json_response(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "dry_run": bool(dry_run),
                "targets": results,
            },
        }
    )


def _safe_str_falsy(value: Any) -> str:
    """判断安全字符串是否为空。"""
    if not value:
        return ""
    return str(value)


def _safe_int(value: Any, default: int) -> int:
    """处理安全整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _parse_bool_default(value: Any, default: bool) -> bool:
    """解析布尔值默认。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return bool(value)
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return default


def _parse_request_payload_dict(request) -> Dict[str, Any]:
    """解析请求载荷字典。"""
    ct = _request_content_type_lower(request)
    if CONTENT_TYPE_JSON in ct:
        try:
            raw = getattr(request, "body", b"")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            parsed = json.loads(str(raw).strip() or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    try:
        parsed = dict(getattr(request, "POST", {}) or {})
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _parse_int_clamped(value: Any, default: int, *, min_value: int = None, max_value: int = None) -> int:
    """解析整数值`clamped`。"""
    try:
        iv = int(value if value is not None else default)
    except Exception:
        iv = int(default)
    if min_value is not None:
        iv = max(int(min_value), iv)
    if max_value is not None:
        iv = min(int(max_value), iv)
    return int(iv)


def _normalize_cleanup_targets(targets: Any):
    """执行归一化清理目标。"""
    raw_targets = targets
    if isinstance(raw_targets, str):
        raw_targets = [t.strip() for t in raw_targets.split(",") if str(t or "").strip()]
    if not isinstance(raw_targets, list):
        raw_targets = []
    normalized = [str(t or "").strip() for t in raw_targets if str(t or "").strip()]
    if not normalized:
        normalized = ["all"]
    if "all" in normalized:
        return ["metrics_cache", "alarm_compose_cache"]
    return normalized


def _cleanup_request_options(payload: Dict[str, Any]) -> Dict[str, Any]:
    """清理请求`options`。"""
    data = payload if isinstance(payload, dict) else {}
    return {
        "dry_run": _parse_bool_default(data.get("dry_run"), True),
        "targets": _normalize_cleanup_targets(data.get("targets")),
    }


def _cleanup_metrics_cache() -> Dict[str, Any]:
    """清理指标缓存。"""
    cleared = 0
    try:
        with _METRICS_COUNT_CACHE_LOCK:
            cleared = len(_METRICS_COUNT_CACHE)
            _METRICS_COUNT_CACHE.clear()
    except Exception:
        cleared = 0
    return {"cleared_keys": int(cleared)}


def _cleanup_alarm_compose_cache(*, dry_run: bool) -> Dict[str, Any]:
    """清理告警`compose`缓存。"""
    from app.views.ViewsBase import g_config
    from app.utils.AlarmCacheCleaner import cleanup_alarm_compose_cache

    try:
        deleted, kept = cleanup_alarm_compose_cache(g_config, dry_run=dry_run)
        return {
            "dry_run": bool(dry_run),
            "deleted": int(deleted),
            "kept": int(kept),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _cleanup_transcode_cache() -> Dict[str, Any]:
    """清理转码缓存。"""
    from app.utils.BackgroundServices import get_transcode_manager

    try:
        tm = get_transcode_manager()
        if tm and hasattr(tm, "flush_all"):
            return tm.flush_all()
        return {"ok": False, "error": "transcode manager not running"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _existing_dirs(paths):
    """返回现有目录列表。"""
    seen = set()
    out = []
    for path in paths or []:
        normalized = os.path.normpath(str(path or "").strip())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isdir(normalized):
            out.append(normalized)
    return out


def _delete_old_file(path: str, *, cutoff: float, dry_run: bool, counters: Dict[str, int], count_bytes: bool = False) -> None:
    """处理`delete``old`文件。"""
    try:
        if not os.path.isfile(path):
            return
        try:
            st = os.stat(path)
        except Exception:
            return
        if float(getattr(st, "st_mtime", 0) or 0) >= cutoff:
            counters["kept_files"] += 1
            return

        file_size = int(getattr(st, "st_size", 0) or 0)
        if dry_run:
            counters["deleted_files"] += 1
            if count_bytes:
                counters["deleted_bytes"] += file_size
            return

        try:
            os.remove(path)
            counters["deleted_files"] += 1
            if count_bytes:
                counters["deleted_bytes"] += file_size
        except Exception:
            counters["kept_files"] += 1
    except Exception:
        return


def _cleanup_empty_dirs(roots) -> None:
    """清理空目录。"""
    for root in roots or []:
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            _ = dirnames
            if filenames or dirpath == root:
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except Exception:
                logger.debug("remove empty cleanup directory failed path=%s", dirpath, exc_info=True)


def _walk_cleanup_dirs(roots, *, cutoff: float, dry_run: bool, count_bytes: bool = False) -> Dict[str, int]:
    """返回`walk`清理目录列表。"""
    counters = {"deleted_files": 0, "kept_files": 0, "deleted_bytes": 0}
    for root in roots or []:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                _delete_old_file(
                    os.path.join(dirpath, filename),
                    cutoff=cutoff,
                    dry_run=dry_run,
                    counters=counters,
                    count_bytes=count_bytes,
                )
    _cleanup_empty_dirs(roots)
    return counters


def _cleanup_logs(payload: Dict[str, Any], *, dry_run: bool) -> Dict[str, Any]:
    """清理`logs`。"""
    try:
        retention_days = _parse_int_clamped(payload.get("log_retention_days"), 7, min_value=1, max_value=3650)
        cutoff = _now_seconds() - retention_days * 86400

        repo_root = _get_repo_root()
        candidates = []
        env_dir = str(os.environ.get("BEACON_LOG_DIR", "") or "").strip()
        if env_dir:
            candidates.append(env_dir)
        candidates.extend(
            [
                os.path.join(repo_root, "log"),
                os.path.join(repo_root, "Admin", "log"),
                os.path.join(repo_root, "Analyzer", "log"),
                os.path.join(repo_root, "MediaServer", "log"),
            ]
        )

        log_dirs = _existing_dirs(candidates)
        counters = _walk_cleanup_dirs(log_dirs, cutoff=cutoff, dry_run=dry_run, count_bytes=True)
        return {
            "dry_run": bool(dry_run),
            "retention_days": int(retention_days),
            "deleted_files": int(counters["deleted_files"]),
            "kept_files": int(counters["kept_files"]),
            "deleted_bytes": int(counters["deleted_bytes"]),
            "log_dirs": log_dirs,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _cleanup_tmp_files(payload: Dict[str, Any], *, dry_run: bool) -> Dict[str, Any]:
    """清理`tmp``files`。"""
    from app.views.ViewsBase import g_config

    try:
        max_age_hours = _parse_int_clamped(payload.get("tmp_max_age_hours"), 24, min_value=1, max_value=24 * 365)
        cutoff = _now_seconds() - max_age_hours * 3600

        repo_root = _get_repo_root()
        candidates = [
            os.path.join(repo_root, "tmp"),
            os.path.join(repo_root, "temp"),
        ]

        try:
            upload_dir = str(getattr(g_config, "uploadDir", "") or "").strip()
            if upload_dir:
                candidates.append(os.path.join(upload_dir, "tmp"))

            storage_root = str(getattr(g_config, "storageRootPath", "") or "").strip()
            if storage_root:
                candidates.append(os.path.join(storage_root, "tmp"))
        except Exception:
            logger.debug("collect cleanup candidate dirs from config failed", exc_info=True)

        tmp_dirs = _existing_dirs(candidates)
        counters = _walk_cleanup_dirs(tmp_dirs, cutoff=cutoff, dry_run=dry_run)
        try:
            for name in os.listdir(repo_root):
                if str(name).endswith(".tmp"):
                    _delete_old_file(
                        os.path.join(repo_root, name),
                        cutoff=cutoff,
                        dry_run=dry_run,
                        counters=counters,
                    )
        except Exception:
            logger.debug("cleanup repo tmp files failed root=%s", repo_root, exc_info=True)

        return {
            "dry_run": bool(dry_run),
            "max_age_hours": int(max_age_hours),
            "deleted_files": int(counters["deleted_files"]),
            "kept_files": int(counters["kept_files"]),
            "tmp_dirs": tmp_dirs,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _outbox_replay_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    """处理`outbox``replay`参数。"""
    return {
        "event_id": _safe_str_falsy(payload.get("event_id")).strip(),
        "sink_type": _safe_str_falsy(payload.get("sink_type")).strip(),
        "reset_attempts": _parse_bool_default(payload.get("reset_attempts"), False),
        "outbox_id": _safe_int(payload.get("outbox_id"), 0),
    }


def _outbox_replay_queryset(qs, *, outbox_id: int, event_id: str, sink_type: str):
    """返回`outbox``replay`查询集。"""
    if outbox_id > 0:
        return qs.filter(id=outbox_id)
    qs = qs.filter(event_id=event_id)
    if sink_type:
        qs = qs.filter(sink_type=sink_type)
    return qs


def _outbox_replay_update_fields(*, reset_attempts: bool) -> Dict[str, Any]:
    """返回`outbox``replay``update`字段。"""
    now = timezone.now()
    update_fields: Dict[str, Any] = {
        "status": "pending",
        "next_retry_at": None,
        "update_time": now,
    }
    if reset_attempts:
        update_fields["attempts"] = 0
    return update_fields


def outbox_replay(request):
    """处理`outbox``replay`。
    
    Manual outbox replay endpoint (DLQ / failed replay).
    
        POST /open/ops/outbox/replay
        body:
          - { "event_id": "evt-xxx", "sink_type": "webhook?", "reset_attempts": false? }
          - { "outbox_id": 123, "reset_attempts": false? }
    
        Behavior:
        - Only affects rows with status=failed.
        - Sets status back to pending and clears next_retry_at for immediate dispatch.
    """
    if request.method != "POST":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    payload = _parse_request_payload_dict(request)
    params = _outbox_replay_params(payload)
    event_id = str(params.get("event_id") or "")
    sink_type = str(params.get("sink_type") or "")
    reset_attempts = bool(params.get("reset_attempts"))
    outbox_id = int(params.get("outbox_id") or 0)

    if outbox_id <= 0 and not event_id:
        return _json_response({"code": 0, "msg": "missing outbox_id or event_id"}, status=400)

    from app.models import AlarmEventOutbox

    try:
        qs = AlarmEventOutbox.objects.filter(status="failed").order_by("id")
        qs = _outbox_replay_queryset(qs, outbox_id=outbox_id, event_id=event_id, sink_type=sink_type)
        updated = int(qs.update(**_outbox_replay_update_fields(reset_attempts=reset_attempts)) or 0)

        return _json_response(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "updated": updated,
                },
            }
        )
    except Exception as e:
        return _json_response({"code": 0, "msg": str(e) or "error"}, status=500)


def _request_content_type_lower(request) -> str:
    """处理请求`content`类型`lower`。"""
    try:
        return str(getattr(request, "content_type", "") or "").lower()
    except Exception:
        return ""


def _parse_logging_json_body(request) -> Dict[str, Any]:
    """解析`logging`JSON响应体。"""
    try:
        raw = getattr(request, "body", b"") or b""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        parsed = json.loads(str(raw or "").strip() or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _parse_logging_post_payload(request) -> Dict[str, Any]:
    """解析`logging``post`载荷。"""
    try:
        return dict(getattr(request, "POST", {}) or {})
    except Exception:
        return {}


def _parse_logging_payload(request) -> Dict[str, Any]:
    """解析`logging`载荷。"""
    ct = _request_content_type_lower(request)
    if CONTENT_TYPE_JSON in ct:
        return _parse_logging_json_body(request)
    return _parse_logging_post_payload(request)


def _normalize_logging_level_name(value: Any) -> str:
    """执行归一化`logging``level`名称。"""
    level_raw = str(value or "").strip().upper()
    return "WARNING" if level_raw == "WARN" else level_raw


def _resolve_logging_level_value(level_name: str) -> Any:
    """解析并返回`logging``level`值。"""
    level_value = getattr(logging, str(level_name or ""), None)
    return level_value if isinstance(level_value, int) else None


def _parse_logging_logger_names(payload: Dict[str, Any]) -> list:
    """解析`logging``logger``names`。"""
    loggers: Any = payload.get("loggers")
    if not isinstance(loggers, list):
        loggers = [payload.get("logger", "")]

    names = []
    for item in loggers:
        if item == "":
            names.append("")
            continue
        token = str(item or "").strip()
        if token:
            names.append(token)
    return names or [""]


def _apply_logging_levels(logger_names: list, level_value: int) -> list:
    """处理应用`logging``levels`。"""
    updated = []
    for name in logger_names:
        try:
            logging.getLogger(name).setLevel(level_value)
            updated.append(name)
        except Exception:
            continue
    return updated


def logging_set_level(request):
    """处理`logging``set``level`。
    
    Runtime logging level switch (industrial delivery).
    
        POST /open/ops/logging/level
        body: { "level": "INFO", "logger": "app.middleware" }
    
        Notes:
        - Best-effort: only adjusts Python logging levels in-process.
        - Intended for on-site troubleshooting without restart.
    """
    if request.method != "POST":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    payload = _parse_logging_payload(request)
    level_raw = _normalize_logging_level_name(payload.get("level"))
    if not level_raw:
        return _json_response({"code": 0, "msg": "missing level"}, status=400)

    level_value = _resolve_logging_level_value(level_raw)
    if level_value is None:
        return _json_response({"code": 0, "msg": "invalid level"}, status=400)

    logger_names = _parse_logging_logger_names(payload)
    updated = _apply_logging_levels(logger_names, level_value)

    return _json_response({"code": 1000, "msg": "success", "data": {"level": level_raw, "loggers": updated}})


def _check_db() -> Dict[str, Any]:
    """检查数据库。"""
    start = time.time()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {
            "ok": True,
            "vendor": str(getattr(connection, "vendor", "") or ""),
            "latency_ms": int((time.time() - start) * 1000),
        }
    except Exception as e:
        return {
            "ok": False,
            "vendor": str(getattr(connection, "vendor", "") or ""),
            "latency_ms": int((time.time() - start) * 1000),
            "error": str(e),
        }


def _check_cloud_required_config() -> Dict[str, Any]:
    """检查云端`required`配置。"""
    missing = []
    bucket = str(os.environ.get("BEACON_CLOUD_S3_BUCKET", "") or "").strip()
    pepper = str(os.environ.get("BEACON_CLOUD_EDGE_TOKEN_PEPPER", "") or "").strip()

    if not pepper:
        missing.append("BEACON_CLOUD_EDGE_TOKEN_PEPPER")
    if not bucket:
        missing.append("BEACON_CLOUD_S3_BUCKET")

    return {"ok": len(missing) == 0, "missing": missing}
