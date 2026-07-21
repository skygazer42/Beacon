# ========== 日志导出 ==========
# 工业交付：一键导出关键配置 + 运行数据 + 日志，便于离线排障与工单流转

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import redirect, render

from app.views.ViewsBase import getUser


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


def _get_db_user(request):
    """获取数据库用户。"""
    session_user = getUser(request) or {}
    try:
        user_id = int(session_user.get("id") or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return None
    return User.objects.filter(id=user_id).first()


def _require_admin(request):
    """为视图增加管理员权限校验。
    
    Export logs include config.json/settings.json and may contain sensitive fields.
        Industrial delivery: restrict to admin only.
    """
    user = getUser(request)
    if not user:
        return False, redirect("/login")

    db_user = _get_db_user(request)
    if not db_user or (not db_user.is_staff and not db_user.is_superuser):
        return False, render(
            request,
            "app/message.html",
            {"msg": "权限不足，仅管理员可导出日志", "is_success": False, "redirect_url": "/"},
        )
    return True, None


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
                    # seek might fail for some filesystems; fallback to full read
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
):
    """处理压缩包`write`文件。"""
    if not fs_path.exists() or not fs_path.is_file():
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
    # skip obvious binaries
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
        zip_path = f"{zip_prefix.rstrip('/')}/{_zip_rel_path(dir_path, p)}"
        _zip_write_file(zf, zip_path=zip_path, fs_path=p, max_bytes=max_bytes, manifest_items=manifest_items)


def api_export_logs(request):
    """处理 `export_logs` 接口请求。"""
    ok, resp = _require_admin(request)
    if not ok:
        return resp

    include_stream_logs = _is_truthy(request.GET.get("include_stream_logs"))
    include_media_logs = include_stream_logs  # alias naming (release note)

    try:
        max_tail_bytes = int(request.GET.get("max_tail_bytes", 2 * 1024 * 1024) or (2 * 1024 * 1024))
    except Exception:
        max_tail_bytes = 2 * 1024 * 1024
    max_tail_bytes = max(64 * 1024, min(20 * 1024 * 1024, max_tail_bytes))

    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    filename = f"beacon_logs_{ts}.zip"

    repo_root = _get_repo_root()

    manifest = {
        "export_time": now.isoformat(timespec="seconds"),
        "include_stream_logs": bool(include_stream_logs),
        "max_tail_bytes": int(max_tail_bytes),
        "repo_root": str(repo_root),
        "items": [],
        "notes": [
            "config.json/settings.json 可能包含敏感字段（token/密钥等），请注意保存与传输安全。",
            "日志文件默认只打包末尾 tail（避免超大文件导致导出失败）。",
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # ==== config files ====
        _zip_write_file(
            zf,
            zip_path="config/config.json",
            fs_path=repo_root / "config.json",
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        _zip_write_file(
            zf,
            zip_path="config/settings.json",
            fs_path=repo_root / "settings.json",
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        _zip_write_file(
            zf,
            zip_path="config/config.ini",
            fs_path=repo_root / "config.ini",
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )

        # ==== DB snapshot (best-effort) ====
        from app.models import Stream, Control, AlgorithmModel, OpsAuditLog

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

            algorithms = []
            for a in AlgorithmModel.objects.filter(state=1).order_by("-id")[:10000]:
                algorithms.append(
                    {
                        "id": a.id,
                        "code": a.code,
                        "name": a.name,
                        "algorithm_type": a.algorithm_type,
                        "basic_source": a.basic_source,
                        "api_url": a.api_url,
                        "model_path": a.model_path,
                        "dll_path": a.dll_path,
                        "builtin_behavior": a.builtin_behavior,
                        "remark": a.remark,
                    }
                )
            _zip_write_json(zf, "db/algorithms.json", algorithms)

            audits = []
            for r in OpsAuditLog.objects.all().order_by("-id")[:5000]:
                audits.append(
                    {
                        "id": r.id,
                        "create_time": getattr(r, "create_time", None),
                        "event_type": getattr(r, "event_type", ""),
                        "ok": bool(getattr(r, "ok", False)),
                        "operator": getattr(r, "operator", ""),
                        "source_ip": getattr(r, "source_ip", ""),
                        "node_id": getattr(r, "node_id", ""),
                        "control_code": getattr(r, "control_code", ""),
                        "algorithm_code": getattr(r, "algorithm_code", ""),
                        "lease_id": getattr(r, "lease_id", ""),
                        "error_code": getattr(r, "error_code", ""),
                        "error_message": getattr(r, "error_message", ""),
                        "detail_json": getattr(r, "detail_json", ""),
                    }
                )
            _zip_write_json(zf, "db/ops_audit.json", audits)
        except Exception as e:
            _zip_write_json(zf, "db/error.json", {"error": str(e)})

        # ==== log dirs ====
        _zip_add_log_dir(
            zf,
            dir_path=repo_root / "log",
            zip_prefix="logs/root",
            max_files=200,
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        _zip_add_log_dir(
            zf,
            dir_path=repo_root / "Admin" / "log",
            zip_prefix="logs/admin",
            max_files=200,
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )
        _zip_add_log_dir(
            zf,
            dir_path=repo_root / "Analyzer" / "log",
            zip_prefix="logs/analyzer",
            max_files=200,
            max_bytes=max_tail_bytes,
            manifest_items=manifest["items"],
        )

        if include_media_logs:
            _zip_add_log_dir(
                zf,
                dir_path=repo_root / "MediaServer" / "log",
                zip_prefix="logs/mediaserver",
                max_files=500,
                max_bytes=max_tail_bytes,
                manifest_items=manifest["items"],
            )

        # manifest last
        _zip_write_json(zf, "manifest.json", manifest)

    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["Cache-Control"] = "no-store"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp
