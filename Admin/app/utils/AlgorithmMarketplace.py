import json
import os
import zipfile

from app.models import AlgorithmModel


PACKAGE_FORMAT = ".beacon-algo"
METADATA_NAME = "metadata.json"
REQUIRED_METADATA_FIELDS = ("code", "name", "version")


def _clean_text(value, limit: int = 0) -> str:
    """清理算法市场文本。"""
    text = str(value or "").strip()
    if limit > 0:
        return text[:limit]
    return text


def _clean_tags(value) -> list:
    """清理算法包标签。"""
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        text = _clean_text(item, 40)
        if text:
            tags.append(text)
    return tags[:20]


def _metadata_runtime(value) -> dict:
    """清理算法包运行时声明。"""
    runtime = value if isinstance(value, dict) else {}
    return {
        "model": _clean_text(runtime.get("model"), 300),
        "plugin": _clean_text(runtime.get("plugin"), 300),
        "entry": _clean_text(runtime.get("entry"), 120),
    }


def _read_package_metadata(package_path: str) -> dict:
    """读取算法包元数据。"""
    with zipfile.ZipFile(package_path, "r") as zf:
        with zf.open(METADATA_NAME) as fp:
            raw = fp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("metadata.json must be a JSON object")
    return data


def _validate_metadata(metadata: dict) -> None:
    """校验算法包元数据。"""
    for field in REQUIRED_METADATA_FIELDS:
        if not _clean_text(metadata.get(field)):
            raise ValueError(f"{field} is required")


def parse_algorithm_package(package_path: str) -> dict:
    """解析单个算法市场包。"""
    metadata = _read_package_metadata(package_path)
    _validate_metadata(metadata)
    filename = os.path.basename(package_path)

    return {
        "code": _clean_text(metadata.get("code"), 50),
        "name": _clean_text(metadata.get("name"), 100),
        "version": _clean_text(metadata.get("version"), 50),
        "vendor": _clean_text(metadata.get("vendor"), 100),
        "description": _clean_text(metadata.get("description"), 1000),
        "algorithm_type": int(metadata.get("algorithm_type") or 0),
        "algorithm_subtype": _clean_text(metadata.get("algorithm_subtype") or "detection", 20),
        "license_package": _clean_text(metadata.get("license_package") or "core", 50),
        "runtime": _metadata_runtime(metadata.get("runtime")),
        "tags": _clean_tags(metadata.get("tags")),
        "package_file": filename,
        "package_path": package_path,
        "package_format": PACKAGE_FORMAT,
    }


def _iter_package_paths(package_dir: str) -> list:
    """遍历算法市场包路径。"""
    root = _clean_text(package_dir)
    if not root or not os.path.isdir(root):
        return []
    paths = []
    for filename in sorted(os.listdir(root)):
        if filename.endswith(PACKAGE_FORMAT):
            paths.append(os.path.join(root, filename))
    return paths


def _error_package_item(package_path: str, message: str) -> dict:
    """返回算法市场错误包项。"""
    return {
        "code": "",
        "name": os.path.basename(package_path),
        "version": "",
        "vendor": "",
        "description": "",
        "algorithm_type": 0,
        "algorithm_subtype": "",
        "license_package": "",
        "runtime": {},
        "tags": [],
        "package_file": os.path.basename(package_path),
        "package_path": package_path,
        "package_format": PACKAGE_FORMAT,
        "installed": False,
        "valid": False,
        "error": _clean_text(message, 300),
    }


def mark_algorithm_packages_installed(items: list) -> list:
    """标记算法包是否已安装。"""
    codes = [_clean_text(item.get("code"), 50) for item in items if isinstance(item, dict)]
    installed_codes = set(AlgorithmModel.objects.filter(code__in=codes).values_list("code", flat=True))
    marked = []
    for item in items:
        current = dict(item or {})
        current["installed"] = _clean_text(current.get("code"), 50) in installed_codes
        if "valid" not in current:
            current["valid"] = True
        marked.append(current)
    return marked


def list_algorithm_packages(package_dir: str) -> dict:
    """列出算法市场包。"""
    items = []
    for package_path in _iter_package_paths(package_dir):
        try:
            items.append(parse_algorithm_package(package_path))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            items.append(_error_package_item(package_path, str(exc)))

    items = mark_algorithm_packages_installed(items)
    return {
        "package_format": PACKAGE_FORMAT,
        "package_dir": _clean_text(package_dir),
        "items": items,
        "total": len(items),
    }
