"""
Ops diagnostics bundle export and web diagnostics center.

Endpoints:
  GET  /open/ops/diagnostics/export
  GET  /ops/diagnostics
  POST /ops/diagnostics

Notes:
  - OpenAPI export remains scope-protected by middleware (`ops` scope).
  - Web diagnostics page requires a logged-in session user.
  - Bundle generation is best-effort and keeps logs as tail bytes.
"""

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from django.http import HttpResponse
from django.shortcuts import redirect, render

from app.utils.DeploymentMode import get_deployment_mode
from app.utils.OSSystem import OSSystem
from app.views.ViewsBase import getUser
from framework.settings import PROJECT_BUILT, PROJECT_FLAG, PROJECT_VERSION


def _is_truthy(value) -> bool:
    """判断`truthy`。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _get_repo_root() -> Path:
    # Admin/app/views -> Admin/app -> Admin -> repo root
    """获取仓库根目录。"""
    return Path(__file__).resolve().parents[3]


def _read_tail_bytes(filepath: Path, max_bytes: int):
    """读取`tail`字节数。"""
    try:
        size = int(filepath.stat().st_size)
    except Exception:
        size = 0
    truncated = False

    try:
        with open(filepath, "rb") as f:
            if size > max_bytes and max_bytes > 0:
                try:
                    f.seek(-max_bytes, os.SEEK_END)
                    truncated = True
                except Exception:
                    truncated = False
            data = f.read()
        return data, truncated, size
    except Exception as e:
        return (f"[beacon] failed to read file: {filepath.name}: {str(e)}\n").encode("utf-8"), True, size


def _zip_write_json(zf: zipfile.ZipFile, zip_path: str, obj) -> None:
    """返回压缩包`write`JSON。"""
    data = json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n"
    zf.writestr(zip_path, data.encode("utf-8"))


def _zip_write_file(
    zf: zipfile.ZipFile,
    *,
    zip_path: str,
    fs_path: Path,
    max_bytes: int,
    manifest_items: list,
    stub_when_missing: bool = False,
):
    """处理压缩包`write`文件。"""
    if not fs_path.exists() or not fs_path.is_file():
        if stub_when_missing:
            zf.writestr(zip_path, b"[beacon] missing\n")
        manifest_items.append({"zip_path": zip_path, "fs_path": str(fs_path), "included": False, "reason": "missing"})
        return

    data, truncated, size = _read_tail_bytes(fs_path, max_bytes=max_bytes)
    zf.writestr(zip_path, data)
    manifest_items.append(
        {
            "zip_path": zip_path,
            "fs_path": str(fs_path),
            "included": True,
            "size_bytes": size,
            "tail_truncated": bool(truncated),
            "tail_bytes": int(max_bytes),
        }
    )


def _is_exportable_log_file(path: Path) -> bool:
    """判断`exportable``log`文件。"""
    if not path.is_file():
        return False
    lower = path.name.lower()
    return not lower.endswith((".so", ".dll", ".exe", ".bin"))


def _collect_exportable_files(dir_path: Path) -> list[Path]:
    """处理`collect``exportable``files`。"""
    files: list[Path] = []
    for root, _, filenames in os.walk(str(dir_path)):
        for name in filenames:
            p = Path(root) / name
            if _is_exportable_log_file(p):
                files.append(p)
    return files


def _zip_rel_path(dir_path: Path, file_path: Path) -> str:
    """返回压缩包相对路径路径。"""
    try:
        return str(file_path.relative_to(dir_path)).replace("\\", "/")
    except Exception:
        return file_path.name


def _zip_add_log_dir(
    zf: zipfile.ZipFile,
    *,
    dir_path: Path,
    zip_prefix: str,
    max_files: int,
    max_bytes: int,
    manifest_items: list,
):
    """返回压缩包新增`log`目录。"""
    if not dir_path.exists() or not dir_path.is_dir():
        manifest_items.append({"zip_path": zip_prefix.rstrip("/") + "/", "fs_path": str(dir_path), "included": False, "reason": "missing_dir"})
        return

    try:
        files = _collect_exportable_files(dir_path)
    except Exception as e:
        manifest_items.append({"zip_path": zip_prefix.rstrip("/") + "/", "fs_path": str(dir_path), "included": False, "reason": str(e)})
        return

    files = sorted(files, key=lambda p: str(p))
    if max_files > 0:
        files = files[:max_files]

    for p in files:
        _zip_write_file(
            zf,
            zip_path=f"{zip_prefix.rstrip('/')}/{_zip_rel_path(dir_path, p)}",
            fs_path=p,
            max_bytes=max_bytes,
            manifest_items=manifest_items,
        )


def _parse_max_tail_bytes(raw_value) -> int:
    """解析最大值`tail`字节数。"""
    try:
        value = int(raw_value or (2 * 1024 * 1024))
    except Exception:
        value = 2 * 1024 * 1024
    return max(64 * 1024, min(20 * 1024 * 1024, value))


def _parse_max_files(raw_value) -> int:
    """解析最大值`files`。"""
    try:
        value = int(raw_value or 200)
    except Exception:
        value = 200
    return max(0, min(2000, value))


def _build_empty_summary() -> Dict[str, Any]:
    """构建空`summary`。"""
    return {
        "host": "-",
        "system_name": "-",
        "os_release": "-",
        "cpu": "-",
        "cpu_usage": "-",
        "memory_usage": "-",
        "disk_usage": "-",
        "uptime": "-",
        "summary_ok": False,
    }


def _load_diagnostics_summary() -> Dict[str, Any]:
    """加载`diagnostics``summary`。"""
    summary = _build_empty_summary()
    probe = OSSystem().getDiagnosticsSummary()
    if isinstance(probe, dict):
        summary.update(probe)
    summary["summary_ok"] = bool(summary.get("summary_ok"))
    return summary


def _build_export_response(
    *,
    include_media_logs: bool,
    max_tail_bytes: int,
    max_files: int,
) -> HttpResponse:
    """构建`export`响应。"""
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    filename = f"beacon_diagnostics_{ts}.zip"

    repo_root = _get_repo_root()

    manifest: Dict[str, Any] = {
        "export_time": now.isoformat(timespec="seconds"),
        "diagnostics": True,
        "include_media_logs": bool(include_media_logs),
        "max_tail_bytes": int(max_tail_bytes),
        "max_files": int(max_files),
        "repo_root": str(repo_root),
        "build": {
            "version": PROJECT_VERSION,
            "flag": PROJECT_FLAG,
            "built": PROJECT_BUILT,
            "deployment_mode": get_deployment_mode(),
        },
        "items": [],
        "notes": [
            "Logs are exported as tail bytes by default to avoid oversized bundles.",
            "config.json and settings.json may include sensitive fields; store the bundle securely.",
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _zip_write_file(
            zf,
            zip_path="config/config.json",
            fs_path=repo_root / "config.json",
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
            stub_when_missing=True,
        )
        _zip_write_file(
            zf,
            zip_path="config/settings.json",
            fs_path=repo_root / "settings.json",
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
            stub_when_missing=True,
        )
        _zip_write_file(
            zf,
            zip_path="config/config.ini",
            fs_path=repo_root / "config.ini",
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
            stub_when_missing=False,
        )

        from app.models import ApiKey, Control, LoginLockout, OpsAuditLog, Stream

        try:
            streams = []
            for s in Stream.objects.all().order_by("-id")[:10000]:
                streams.append(
                    {
                        "id": s.id,
                        "code": s.code,
                        "app": s.app,
                        "name": s.name,
                        "pull_stream_url": s.pull_stream_url,
                        "pull_stream_type": s.pull_stream_type,
                        "nickname": s.nickname,
                        "remark": s.remark,
                        "forward_state": getattr(s, "forward_state", 0),
                        "state": getattr(s, "state", 0),
                        "last_update_time": getattr(s, "last_update_time", None),
                    }
                )
            _zip_write_json(zf, "db/streams.json", streams)

            controls = []
            for c in Control.objects.all().order_by("-id")[:10000]:
                controls.append(
                    {
                        "id": c.id,
                        "code": c.code,
                        "stream_app": c.stream_app,
                        "stream_name": c.stream_name,
                        "algorithm_code": c.algorithm_code,
                        "object_code": c.object_code,
                        "state": getattr(c, "state", 0),
                        "remark": c.remark,
                        "polygon": getattr(c, "polygon", ""),
                        "behaviorConfig": getattr(c, "behaviorConfig", ""),
                    }
                )
            _zip_write_json(zf, "db/controls.json", controls)

            keys = []
            for k in ApiKey.objects.all().order_by("-id")[:5000]:
                keys.append(
                    {
                        "id": k.id,
                        "name": k.name,
                        "token_prefix": getattr(k, "token_prefix", ""),
                        "scopes_json": getattr(k, "scopes_json", ""),
                        "enabled": bool(getattr(k, "enabled", False)),
                        "expires_at": getattr(k, "expires_at", None),
                        "revoked_at": getattr(k, "revoked_at", None),
                        "last_used_at": getattr(k, "last_used_at", None),
                        "created_by": getattr(k, "created_by", ""),
                        "remark": getattr(k, "remark", ""),
                        "create_time": getattr(k, "create_time", None),
                    }
                )
            _zip_write_json(zf, "db/api_keys.json", keys)

            lockouts = []
            for row in LoginLockout.objects.all().order_by("-id")[:5000]:
                lockouts.append(
                    {
                        "id": row.id,
                        "username": getattr(row, "username", ""),
                        "source_ip": getattr(row, "source_ip", ""),
                        "failures": int(getattr(row, "failures", 0) or 0),
                        "first_failure_at": getattr(row, "first_failure_at", None),
                        "last_failure_at": getattr(row, "last_failure_at", None),
                        "locked_until": getattr(row, "locked_until", None),
                        "create_time": getattr(row, "create_time", None),
                    }
                )
            _zip_write_json(zf, "db/login_lockout.json", lockouts)

            audits = []
            for r in OpsAuditLog.objects.all().order_by("-id")[:2000]:
                audits.append(
                    {
                        "id": r.id,
                        "create_time": getattr(r, "create_time", None),
                        "event_type": getattr(r, "event_type", ""),
                        "ok": bool(getattr(r, "ok", False)),
                        "operator": getattr(r, "operator", ""),
                        "source_ip": getattr(r, "source_ip", ""),
                        "error_message": getattr(r, "error_message", ""),
                        "detail_json": getattr(r, "detail_json", ""),
                    }
                )
            _zip_write_json(zf, "db/ops_audit.json", audits)
        except Exception as e:
            _zip_write_json(zf, "db/error.json", {"error": str(e)})

        _zip_add_log_dir(
            zf,
            dir_path=repo_root / "log",
            zip_prefix="logs/root",
            max_files=max_files,
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        _zip_add_log_dir(
            zf,
            dir_path=repo_root / "Admin" / "log",
            zip_prefix="logs/admin",
            max_files=max_files,
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        _zip_add_log_dir(
            zf,
            dir_path=repo_root / "Analyzer" / "log",
            zip_prefix="logs/analyzer",
            max_files=max_files,
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        if include_media_logs:
            _zip_add_log_dir(
                zf,
                dir_path=repo_root / "MediaServer" / "log",
                zip_prefix="logs/mediaserver",
                max_files=max_files,
                max_bytes=max_tail_bytes,
                manifest_items=manifest["items"],
            )

        _zip_write_json(zf, "manifest.json", manifest)

    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["Cache-Control"] = "no-store"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def index(request):
    """渲染默认页面。"""
    user = getUser(request)
    if not user:
        return redirect("/login")

    if request.method == "POST":
        action = str(request.POST.get("action", "") or "").strip().lower()
        if action == "export":
            include_media_logs = _is_truthy(request.POST.get("include_media_logs")) or _is_truthy(request.POST.get("include_stream_logs"))
            return _build_export_response(
                include_media_logs=include_media_logs,
                max_tail_bytes=_parse_max_tail_bytes(request.POST.get("max_tail_bytes")),
                max_files=_parse_max_files(request.POST.get("max_files")),
            )

    try:
        diagnostics_summary = _load_diagnostics_summary()
    except Exception:
        diagnostics_summary = _build_empty_summary()

    return render(
        request,
        "app/ops/diagnostics.html",
        {
            "user": user,
            "diagnostics_summary": diagnostics_summary,
        },
    )


def export(request):
    """执行`export`。"""
    if request.method != "GET":
        return HttpResponse(
            json.dumps({"code": 0, "msg": "method not allowed"}, ensure_ascii=False),
            status=405,
            content_type="application/json",
        )

    include_media_logs = _is_truthy(request.GET.get("include_media_logs"))
    include_stream_logs = _is_truthy(request.GET.get("include_stream_logs"))
    include_media_logs = include_media_logs or include_stream_logs

    return _build_export_response(
        include_media_logs=include_media_logs,
        max_tail_bytes=_parse_max_tail_bytes(request.GET.get("max_tail_bytes")),
        max_files=_parse_max_files(request.GET.get("max_files")),
    )
