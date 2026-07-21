"""
Offline upgrade package management (industrial delivery).

Roadmap:
  #90 离线升级包：上传/校验/应用/回滚

Endpoints (OpenAPI ops scope):
  - POST /open/ops/upgrade/upload
  - GET  /open/ops/upgrade/validate?package_id=...
  - POST /open/ops/upgrade/apply
  - POST /open/ops/upgrade/rollback

Notes:
  This implementation focuses on a safe, testable on-disk workflow:
  - Upload zip and persist under <root>/upgrade/packages/<id>/package.zip
  - Validate manifest compatibility (min/max/from_versions)
  - Apply extracts into <root>/upgrade/staging/<id>/ and updates state.json
  - Rollback swaps applied_package_id back to previous_package_id (best-effort)
"""

import hashlib
import json
import logging
import os
import re
import shutil
import zipfile
import runtime_paths  # type: ignore
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.http import HttpResponse
from django.shortcuts import redirect, render

from app.views.ViewsBase import getUser
from framework.settings import PROJECT_VERSION

CONTENT_TYPE_JSON = "application/json"
MSG_METHOD_NOT_ALLOWED = "method not allowed"
MSG_PACKAGE_NOT_FOUND = "package not found"
logger = logging.getLogger(__name__)


class UpgradeExtractLimitError(Exception):
    pass


def _json_response(payload: Dict[str, Any], *, status: int = 200) -> HttpResponse:
    """返回JSON响应。"""
    resp = HttpResponse(json.dumps(payload, ensure_ascii=False, default=str), status=status, content_type=CONTENT_TYPE_JSON)
    resp["Cache-Control"] = "no-store"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def index(request):
    """渲染默认页面。"""
    from app.views import OpsApiKeyView

    user = getUser(request)
    if not user:
        return redirect("/login")

    db_user = OpsApiKeyView._get_db_user(request)
    if not OpsApiKeyView._is_admin(db_user):
        return OpsApiKeyView._deny(request, json_mode=False)

    return render(request, "app/ops/upgrade.html", {"user": user})


def _root_dir() -> str:
    """返回根目录目录。"""
    try:
        return str(runtime_paths.resolve_root_dir() or "").strip()
    except Exception:
        logger.debug("runtime_paths root resolution failed; using file-relative fallback", exc_info=True)
    # Fallback (dev only): repo root inferred from this file.
    # Admin/app/views -> Admin/app -> Admin -> repo root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _upgrade_dir() -> str:
    """返回`upgrade`目录。"""
    return os.path.join(_root_dir(), "upgrade")


def _packages_dir() -> str:
    """返回`packages`目录。"""
    return os.path.join(_upgrade_dir(), "packages")


def _staging_dir() -> str:
    """返回`staging`目录。"""
    return os.path.join(_upgrade_dir(), "staging")


def _state_path() -> str:
    """返回状态路径。"""
    return os.path.join(_upgrade_dir(), "state.json")


def _write_json_atomic(path: str, data: dict) -> None:
    """写入JSON`atomic`。"""
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        f.write("\n")
    os.replace(tmp, path)


def _read_json_file(path: str) -> dict:
    """读取 JSON 配置文件。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="gbk") as f:
            raw = f.read()
    except Exception:
        return {}

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_version(value: Any) -> List[int]:
    """解析版本。"""
    s = str(value or "").strip()
    if not s:
        return []
    if len(s) > 1 and s[0] in ("v", "V") and s[1].isdigit():
        s = s[1:]
    parts = re.split(r"[.\-_]", s)
    nums: List[int] = []
    for part in parts:
        if part.isdigit():
            nums.append(int(part))
            continue
        m = re.match(r"(\d+)", part)
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                continue
    return nums


def _compare_versions(a: str, b: str) -> int:
    """处理`compare``versions`。"""
    pa = _parse_version(a)
    pb = _parse_version(b)
    length = max(len(pa), len(pb))
    pa += [0] * (length - len(pa))
    pb += [0] * (length - len(pb))
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def _validate_package_id(value: Any) -> str:
    """校验打包ID。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > 64:
        return ""
    if raw[0] == ".":
        return ""
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", raw):
        return ""
    return raw


def _load_manifest_from_zip(zip_path: str) -> Tuple[bool, str, dict]:
    """加载`manifest``from`压缩包。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            try:
                data = zf.read("manifest.json")
            except KeyError:
                return False, "manifest.json is missing", {}
    except zipfile.BadZipFile:
        return False, "invalid zip file", {}
    except Exception as e:
        return False, str(e) or "error", {}

    try:
        text = data.decode("utf-8", errors="replace")
        manifest = json.loads(text)
        if not isinstance(manifest, dict):
            return False, "manifest.json must be an object", {}
        return True, "success", manifest
    except Exception:
        return False, "manifest.json is not valid json", {}


def _compat_get(compat: dict, snake_key: str, camel_key: str):
    """处理`compat``get`。"""
    v = compat.get(snake_key, None)
    if v is None:
        v = compat.get(camel_key, None)
    return v


def _validate_from_versions(from_versions) -> Tuple[List[str], List[str]]:
    """校验`from``versions`。"""
    if from_versions is None:
        return [], []
    if not isinstance(from_versions, list):
        return [], ["compatible.from_versions must be a list"]
    allowed = [str(x or "").strip() for x in from_versions if str(x or "").strip()]
    errors = []
    for v in allowed:
        if not _parse_version(v):
            errors.append(f"compatible.from_versions contains invalid version: {v}")
    return allowed, errors


def _validate_min_max_versions(min_v, max_v) -> Tuple[str, str, List[str]]:
    """校验`min`最大值`versions`。"""
    errors: List[str] = []
    min_s = str(min_v or "").strip()
    max_s = str(max_v or "").strip()
    if min_s and not _parse_version(min_s):
        errors.append("compatible.min_version is invalid")
    if max_s and not _parse_version(max_s):
        errors.append("compatible.max_version is invalid")
    return min_s, max_s, errors


def _extract_compat_rule(manifest: dict) -> Tuple[bool, List[str], dict]:
    """提取`compat``rule`。
    
    Validate and normalize the compatibility rule in manifest.json.
    
        This is a schema-level validation only (does NOT compare with current version).
    """
    errors: List[str] = []
    if not isinstance(manifest, dict):
        return False, ["manifest must be an object"], {}

    compat = manifest.get("compatible")
    if compat is None:
        return False, ["compatible metadata is required"], {}
    if not isinstance(compat, dict):
        return False, ["compatible must be an object"], {}

    # Accept both snake_case and camelCase for package authors.
    from_versions = _compat_get(compat, "from_versions", "fromVersions")
    min_v = _compat_get(compat, "min_version", "minVersion")
    max_v = _compat_get(compat, "max_version", "maxVersion")

    allowed, list_errors = _validate_from_versions(from_versions)
    min_s, max_s, range_errors = _validate_min_max_versions(min_v, max_v)
    errors.extend(list_errors)
    errors.extend(range_errors)

    if (not allowed) and (not min_s) and (not max_s):
        errors.append("compatible must define from_versions or min_version/max_version")

    rule = {
        "from_versions": allowed,
        "min_version": min_s,
        "max_version": max_s,
    }
    return len(errors) == 0, errors, rule


def _validate_manifest_compat_for_current(manifest: dict) -> Tuple[bool, List[str]]:
    """校验`manifest``compat``for``current`。
    
    Validate that the package is compatible with the *current* running version.
    """
    ok, errors, rule = _extract_compat_rule(manifest)
    if not ok:
        return False, errors

    current = str(PROJECT_VERSION or "").strip()
    if not current:
        # If current version is unknown, do not allow "blind" upgrades.
        return False, ["current version is unknown"]

    allowed = rule.get("from_versions") or []
    if allowed and current not in allowed:
        return False, [f"current version {current} not in from_versions"]

    min_v = str(rule.get("min_version") or "").strip()
    max_v = str(rule.get("max_version") or "").strip()
    errs: List[str] = []
    if min_v and _compare_versions(current, min_v) < 0:
        errs.append(f"current version {current} < min_version {min_v}")
    if max_v and _compare_versions(current, max_v) > 0:
        errs.append(f"current version {current} > max_version {max_v}")
    return len(errs) == 0, errs


def _package_dir(package_id: str) -> str:
    """返回打包目录。"""
    return os.path.join(_packages_dir(), package_id)


def _zip_path(package_id: str) -> str:
    """返回压缩包路径。"""
    return os.path.join(_package_dir(package_id), "package.zip")


def _meta_path(package_id: str) -> str:
    """返回元数据路径。"""
    return os.path.join(_package_dir(package_id), "meta.json")


def _ensure_dirs() -> None:
    """返回`ensure`目录列表。"""
    os.makedirs(_packages_dir(), exist_ok=True)
    os.makedirs(_staging_dir(), exist_ok=True)


def _load_state() -> dict:
    """加载状态。"""
    return _read_json_file(_state_path()) or {}


def _save_state(state: dict) -> None:
    """保存状态。"""
    _write_json_atomic(_state_path(), state or {})


def _extract_env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    """提取环境变量整数值。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception:
            value = int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _get_extract_limits() -> Dict[str, int]:
    """获取提取`limits`。"""
    return {
        "max_files": _extract_env_int("BEACON_UPGRADE_EXTRACT_MAX_FILES", 5000, min_value=1, max_value=200_000),
        "max_total_bytes": _extract_env_int(
            "BEACON_UPGRADE_EXTRACT_MAX_TOTAL_BYTES",
            2 * 1024 * 1024 * 1024,
            min_value=1,
            max_value=200 * 1024 * 1024 * 1024,
        ),
        "max_file_bytes": _extract_env_int(
            "BEACON_UPGRADE_EXTRACT_MAX_FILE_BYTES",
            512 * 1024 * 1024,
            min_value=1,
            max_value=50 * 1024 * 1024 * 1024,
        ),
    }


def _resolve_extract_dir_path(name: str, dest_dir: str, *, validate_upload_rel_path, resolve_under_base) -> Optional[str]:
    """解析并返回提取目录路径。"""
    try:
        rel = validate_upload_rel_path(name.rstrip("/"))
        return resolve_under_base(dest_dir, rel)
    except Exception:
        return None


def _resolve_extract_file_path(name: str, dest_dir: str, *, validate_upload_rel_path, resolve_under_base) -> Optional[str]:
    """解析并返回提取文件路径。"""
    try:
        rel = validate_upload_rel_path(name)
        return resolve_under_base(dest_dir, rel)
    except Exception:
        return None


def _declared_zip_file_size(info) -> int:
    """处理`declared`压缩包文件大小。"""
    try:
        return int(getattr(info, "file_size", 0) or 0)
    except Exception:
        return 0


def _cleanup_partial_extract(abs_path: str) -> None:
    """清理`partial`提取。"""
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        logger.debug("cleanup partial extract failed path=%s", abs_path, exc_info=True)


def _extract_file_entry(zf, info, abs_path: str, *, max_file_bytes: int, max_total_bytes: int, extracted_bytes: int) -> int:
    """提取文件条目。"""
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    declared_size = _declared_zip_file_size(info)
    name = str(getattr(info, "filename", "") or "")
    if declared_size > 0 and declared_size > max_file_bytes:
        raise UpgradeExtractLimitError(
            f"file too large in package: {name} (size={declared_size}, max_file_bytes={max_file_bytes})"
        )

    wrote = 0
    total_bytes = int(extracted_bytes)
    try:
        with zf.open(info, "r") as src, open(abs_path, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                chunk_len = int(len(chunk))
                wrote += chunk_len
                total_bytes += chunk_len
                if wrote > max_file_bytes:
                    raise UpgradeExtractLimitError(f"file too large in package: {name} (max_file_bytes={max_file_bytes})")
                if total_bytes > max_total_bytes:
                    raise UpgradeExtractLimitError(f"package extract too large (max_total_bytes={max_total_bytes})")
        return wrote
    except Exception:
        _cleanup_partial_extract(abs_path)
        raise


def _raise_if_extract_file_limit_reached(extracted_files: int, max_files: int) -> None:
    """处理抛出`if`提取文件`limit``reached`。"""
    if extracted_files >= max_files:
        raise UpgradeExtractLimitError(f"too many files in package (max_files={max_files})")


def _extract_dir_entry(name: str, dest_dir: str, *, validate_upload_rel_path, resolve_under_base) -> Dict[str, int]:
    """提取目录条目。"""
    abs_dir = _resolve_extract_dir_path(
        name,
        dest_dir,
        validate_upload_rel_path=validate_upload_rel_path,
        resolve_under_base=resolve_under_base,
    )
    if not abs_dir:
        return {"files": 0, "bytes": 0, "skipped": 1}
    os.makedirs(abs_dir, exist_ok=True)
    return {"files": 0, "bytes": 0, "skipped": 0}


def _extract_regular_entry(
    zf,
    info,
    name: str,
    dest_dir: str,
    *,
    validate_upload_rel_path,
    resolve_under_base,
    limits: Dict[str, int],
    extracted_bytes: int,
) -> Dict[str, int]:
    """提取`regular`条目。"""
    abs_path = _resolve_extract_file_path(
        name,
        dest_dir,
        validate_upload_rel_path=validate_upload_rel_path,
        resolve_under_base=resolve_under_base,
    )
    if not abs_path:
        return {"files": 0, "bytes": 0, "skipped": 1}

    try:
        wrote = _extract_file_entry(
            zf,
            info,
            abs_path,
            max_file_bytes=limits["max_file_bytes"],
            max_total_bytes=limits["max_total_bytes"],
            extracted_bytes=extracted_bytes,
        )
    except UpgradeExtractLimitError:
        raise
    except Exception:
        return {"files": 0, "bytes": 0, "skipped": 1}

    return {"files": 1, "bytes": wrote, "skipped": 0}


def _extract_zip_member(
    zf,
    info,
    dest_dir: str,
    *,
    validate_upload_rel_path,
    resolve_under_base,
    limits: Dict[str, int],
    extracted_bytes: int,
) -> Dict[str, int]:
    """提取压缩包`member`。"""
    name = str(getattr(info, "filename", "") or "")
    if not name:
        return {"files": 0, "bytes": 0, "skipped": 1}
    if name.endswith("/"):
        return _extract_dir_entry(
            name,
            dest_dir,
            validate_upload_rel_path=validate_upload_rel_path,
            resolve_under_base=resolve_under_base,
        )
    return _extract_regular_entry(
        zf,
        info,
        name,
        dest_dir,
        validate_upload_rel_path=validate_upload_rel_path,
        resolve_under_base=resolve_under_base,
        limits=limits,
        extracted_bytes=extracted_bytes,
    )


def _extract_zip_safely(zip_path: str, dest_dir: str) -> Dict[str, Any]:
    """提取压缩包`safely`。
    
    Extract zip to dest_dir while preventing path traversal.
    """
    from app.utils.Security import resolve_under_base, validate_upload_rel_path

    limits = _get_extract_limits()

    extracted_files = 0
    extracted_bytes = 0
    skipped = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            _raise_if_extract_file_limit_reached(extracted_files, limits["max_files"])
            result = _extract_zip_member(
                zf,
                info,
                dest_dir,
                validate_upload_rel_path=validate_upload_rel_path,
                resolve_under_base=resolve_under_base,
                limits=limits,
                extracted_bytes=extracted_bytes,
            )
            extracted_files += int(result["files"])
            extracted_bytes += int(result["bytes"])
            skipped += int(result["skipped"])

    return {
        "extracted_files": int(extracted_files),
        "extracted_bytes": int(extracted_bytes),
        "skipped": int(skipped),
    }


def _is_truthy_text(value: Any) -> bool:
    """判断`truthy`文本。"""
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _is_candidate_package_dir_name(pkg_id: str) -> bool:
    """判断`candidate`打包目录名称。"""
    token = str(pkg_id or "").strip()
    if not token:
        return False
    if token.startswith("."):
        return False
    # Ignore temp upload dirs.
    if token.startswith("._upload_"):
        return False
    return True


def _list_package_ids() -> List[str]:
    """返回列表打包`ids`。"""
    try:
        entries = os.listdir(_packages_dir())
    except Exception:
        return []

    items: List[str] = []
    for name in entries:
        pkg_id = str(name or "").strip()
        if not _is_candidate_package_dir_name(pkg_id):
            continue
        items.append(pkg_id)
    return items


def _load_package_meta_and_manifest(pkg_id: str) -> Tuple[dict, dict]:
    """加载打包元数据`and``manifest`。"""
    meta = _read_json_file(_meta_path(pkg_id))
    manifest = meta.get("manifest")
    if isinstance(manifest, dict):
        return meta, manifest

    ok, _msg, m = _load_manifest_from_zip(_zip_path(pkg_id))
    if ok and isinstance(m, dict):
        return meta, m
    return meta, {}


def _package_list_item(
    *,
    pkg_id: str,
    meta: dict,
    manifest: dict,
    compat_ok: bool,
    compat_errors: List[str],
) -> Dict[str, Any]:
    """处理打包列表`item`。"""
    target_version = str(manifest.get("target_version") or manifest.get("targetVersion") or "")
    return {
        "package_id": pkg_id,
        "uploaded_at": str(meta.get("uploaded_at") or ""),
        "size_bytes": int(meta.get("size_bytes") or 0),
        "sha256": str(meta.get("sha256") or ""),
        "target_version": target_version,
        "compatible_ok": bool(compat_ok),
        "compatible_errors": compat_errors,
    }


def _sort_packages_best_effort(items: List[Dict[str, Any]]) -> None:
    # Newest first (best-effort). Missing/invalid timestamps fall back to string sort.
    """尽力处理`sort``packages`。"""
    try:
        items.sort(key=lambda it: str(it.get("uploaded_at") or ""), reverse=True)
    except Exception:
        logger.debug("sort upgrade packages failed", exc_info=True)


def list_packages(request):
    """处理列表`packages`。
    
    GET /open/ops/upgrade/list
          - optional: only_compatible=1
    """
    if request.method != "GET":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    only_compatible = _is_truthy_text(request.GET.get("only_compatible", "") or "")

    _ensure_dirs()

    items: List[Dict[str, Any]] = []
    for pkg_id in _list_package_ids():
        meta, manifest = _load_package_meta_and_manifest(pkg_id)
        compat_ok, compat_errors = _validate_manifest_compat_for_current(manifest) if isinstance(manifest, dict) else (False, ["manifest missing"])
        if only_compatible and not compat_ok:
            continue
        items.append(
            _package_list_item(
                pkg_id=pkg_id,
                meta=meta if isinstance(meta, dict) else {},
                manifest=manifest if isinstance(manifest, dict) else {},
                compat_ok=bool(compat_ok),
                compat_errors=compat_errors,
            )
        )

    _sort_packages_best_effort(items)

    return _json_response({"code": 1000, "msg": "success", "data": items})


def _persist_upload_to_tmp_zip(uploaded_file, *, tmp_zip_path: str) -> Tuple[int, str]:
    """处理`persist`上传`to``tmp`压缩包。"""
    size = 0
    h = hashlib.sha256()
    with open(tmp_zip_path, "wb") as out:
        for chunk in uploaded_file.chunks():
            if not chunk:
                continue
            out.write(chunk)
            h.update(chunk)
            size += int(len(chunk))
    return int(size), h.hexdigest()


def upload(request):
    """执行上传。
    
    POST /open/ops/upgrade/upload
        multipart: file=<zip>
    """
    if request.method != "POST":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    try:
        f = request.FILES.get("file") or request.FILES.get("package")
    except Exception:
        f = None
    if f is None:
        return _json_response({"code": 0, "msg": "missing file"}, status=400)

    _ensure_dirs()

    # Write zip to a temp location first to avoid leaving corrupt artifacts.
    tmp_id = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
    tmp_dir = os.path.join(_packages_dir(), f"._upload_{tmp_id}")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_zip_path = os.path.join(tmp_dir, "package.zip")

    try:
        try:
            size, sha256 = _persist_upload_to_tmp_zip(f, tmp_zip_path=tmp_zip_path)
        except Exception as e:
            return _json_response({"code": 0, "msg": str(e) or "upload failed"}, status=500)

        ok, msg, manifest = _load_manifest_from_zip(tmp_zip_path)
        if not ok:
            return _json_response({"code": 0, "msg": msg or "invalid package"}, status=400)

        # Roadmap #91: upgrade packages MUST declare compatibility range metadata,
        # otherwise operators could accidentally apply an incompatible package.
        ok_rule, errs, _rule = _extract_compat_rule(manifest)
        if not ok_rule:
            return _json_response({"code": 0, "msg": "invalid manifest", "data": {"errors": errs}}, status=400)

        manifest_pkg_id = _validate_package_id(manifest.get("package_id"))
        package_id = manifest_pkg_id or (hashlib.sha256((sha256 + str(size)).encode("utf-8")).hexdigest()[:12])

        # Avoid collisions (best-effort).
        if os.path.exists(_package_dir(package_id)):
            package_id = f"{package_id}_{tmp_id[:6]}"

        pkg_dir = _package_dir(package_id)
        os.makedirs(pkg_dir, exist_ok=True)
        final_zip_path = _zip_path(package_id)

        try:
            os.replace(tmp_zip_path, final_zip_path)
        except Exception as e:
            return _json_response({"code": 0, "msg": str(e) or "persist failed"}, status=500)
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            logger.debug("cleanup uploaded temp dir failed path=%s", tmp_dir, exc_info=True)

    meta = {
        "package_id": package_id,
        "filename": str(getattr(f, "name", "") or ""),
        "size_bytes": int(size),
        "sha256": sha256,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": manifest,
    }
    _write_json_atomic(_meta_path(package_id), meta)

    return _json_response({"code": 1000, "msg": "success", "data": {"package_id": package_id, "sha256": sha256, "size_bytes": int(size)}})


def validate(request):
    """校验相关数据。
    
    GET /open/ops/upgrade/validate?package_id=...
    """
    if request.method != "GET":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    raw_package_id = str(request.GET.get("package_id", "") or "").strip()
    if not raw_package_id:
        return _json_response({"code": 0, "msg": "missing package_id"}, status=400)
    # Avoid path traversal / injection when mapping id -> on-disk package paths.
    package_id = _validate_package_id(raw_package_id)
    if not package_id:
        return _json_response({"code": 0, "msg": "invalid package_id"}, status=400)

    meta = _read_json_file(_meta_path(package_id))
    manifest = meta.get("manifest") if isinstance(meta, dict) else None
    if not isinstance(manifest, dict):
        # fallback: read from zip (if meta missing)
        zip_path = _zip_path(package_id)
        if not os.path.exists(zip_path):
            return _json_response({"code": 0, "msg": MSG_PACKAGE_NOT_FOUND}, status=404)
        ok, msg, manifest = _load_manifest_from_zip(zip_path)
        if not ok:
            return _json_response({"code": 0, "msg": msg or MSG_PACKAGE_NOT_FOUND}, status=404)

    ok, errors = _validate_manifest_compat_for_current(manifest)

    data = {
        "ok": bool(ok),
        "errors": errors,
        "current_version": str(PROJECT_VERSION or ""),
        "target_version": str(manifest.get("target_version") or manifest.get("targetVersion") or ""),
        "package_id": package_id,
    }
    return _json_response({"code": 1000, "msg": "success", "data": data})


def _request_payload_dict(request) -> Dict[str, Any]:
    """处理请求载荷字典。"""
    try:
        ct = str(getattr(request, "content_type", "") or "").lower()
    except Exception:
        ct = ""

    if CONTENT_TYPE_JSON in ct:
        try:
            raw = getattr(request, "body", b"") or b""
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(str(raw or "").strip() or "{}")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    try:
        payload = dict(getattr(request, "POST", {}) or {})
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _payload_truthy(payload: Dict[str, Any], key: str) -> bool:
    """处理载荷`truthy`。"""
    return str(payload.get(key, "") or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _load_manifest_for_package_id(package_id: str) -> Tuple[bool, str, dict]:
    """加载`manifest``for`打包ID。"""
    meta = _read_json_file(_meta_path(package_id))
    manifest = meta.get("manifest") if isinstance(meta, dict) else None
    if isinstance(manifest, dict):
        return True, "success", manifest
    return _load_manifest_from_zip(_zip_path(package_id))


def _prepare_staging_dir(stage_dir: str) -> None:
    # Clean staging dir before extraction.
    """返回`prepare``staging`目录。"""
    try:
        if os.path.isdir(stage_dir):
            shutil.rmtree(stage_dir)
    except Exception:
        logger.debug("cleanup staging dir failed path=%s", stage_dir, exc_info=True)
    os.makedirs(stage_dir, exist_ok=True)


def _update_upgrade_state_after_apply(*, package_id: str, manifest: dict) -> str:
    # Update state (best-effort)
    """更新`upgrade`状态`after`应用。"""
    state = _load_state()
    prev = str(state.get("applied_package_id") or "").strip()
    state["previous_package_id"] = prev
    state["applied_package_id"] = package_id
    state["applied_at"] = datetime.now().isoformat(timespec="seconds")
    state["current_version"] = str(PROJECT_VERSION or "")
    state["target_version"] = str(manifest.get("target_version") or manifest.get("targetVersion") or "")
    _save_state(state)
    return prev


def apply(request):
    """处理应用。
    
    POST /open/ops/upgrade/apply
        body: { "package_id": "...", "dry_run": false? }
    
        This extracts the package under staging and updates state.json.
    """
    if request.method != "POST":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    payload = _request_payload_dict(request)

    raw_package_id = str(payload.get("package_id", "") or "").strip()
    if not raw_package_id:
        return _json_response({"code": 0, "msg": "missing package_id"}, status=400)
    # Avoid path traversal / injection when mapping id -> on-disk package paths.
    package_id = _validate_package_id(raw_package_id)
    if not package_id:
        return _json_response({"code": 0, "msg": "invalid package_id"}, status=400)

    dry_run = _payload_truthy(payload, "dry_run")

    ok, msg, manifest = _load_manifest_for_package_id(package_id)
    if not ok:
        return _json_response({"code": 0, "msg": msg or MSG_PACKAGE_NOT_FOUND}, status=404)

    ok, errors = _validate_manifest_compat_for_current(manifest)
    if not ok:
        return _json_response({"code": 0, "msg": "incompatible package", "data": {"errors": errors}}, status=400)

    zip_path = _zip_path(package_id)
    if not os.path.exists(zip_path):
        return _json_response({"code": 0, "msg": MSG_PACKAGE_NOT_FOUND}, status=404)

    stage_dir = os.path.join(_staging_dir(), package_id)

    if dry_run:
        return _json_response(
            {
                "code": 1000,
                "msg": "success",
                "data": {
                    "dry_run": True,
                    "package_id": package_id,
                    "staging_dir": stage_dir,
                },
            }
        )

    _prepare_staging_dir(stage_dir)

    try:
        extract_info = _extract_zip_safely(zip_path, stage_dir)
    except Exception as e:
        return _json_response({"code": 0, "msg": str(e) or "extract failed"}, status=500)

    prev = _update_upgrade_state_after_apply(package_id=package_id, manifest=manifest)

    data = {
        "dry_run": False,
        "package_id": package_id,
        "previous_package_id": prev,
        "applied_package_id": package_id,
        "staging_dir": stage_dir,
        "extract": extract_info,
    }
    return _json_response({"code": 1000, "msg": "success", "data": data})


def rollback(request):
    """处理`rollback`。
    
    POST /open/ops/upgrade/rollback
        body: {} (rollback to previous_package_id)
    """
    if request.method != "POST":
        return _json_response({"code": 0, "msg": MSG_METHOD_NOT_ALLOWED}, status=405)

    state = _load_state()
    applied = str(state.get("applied_package_id") or "").strip()
    prev = str(state.get("previous_package_id") or "").strip()

    # Best-effort swap back.
    state["applied_package_id"] = prev
    state["previous_package_id"] = ""
    state["rolled_back_from"] = applied
    state["rolled_back_at"] = datetime.now().isoformat(timespec="seconds")
    _save_state(state)

    return _json_response(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "applied_package_id": prev,
                "rolled_back_from": applied,
            },
        }
    )
