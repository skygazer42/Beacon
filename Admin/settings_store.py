import json
import os
import time
from typing import Any, Dict

import runtime_paths  # type: ignore


_CACHE: Dict[str, Any] = {
    "mtime": 0.0,
    "data": None,
    "ts": 0.0,
}
_CACHE_TTL_SECONDS = 1.0


def _settings_path() -> str:
    """返回 settings.json 文件路径。"""
    return runtime_paths.resolve_settings_path()


def _read_json_file(filepath: str) -> dict:
    """读取 JSON 配置文件。"""
    if not filepath:
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="gbk") as f:
            raw = f.read()
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _mtime_or_zero(filepath: str) -> float:
    """返回文件修改时间，不存在时返回 0。"""
    if not filepath:
        return 0.0
    return os.path.getmtime(filepath)


def _write_json_file_atomic(filepath: str, data: dict) -> None:
    """原子写入 JSON 配置文件。"""
    dirpath = os.path.dirname(filepath)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        f.write("\n")
    os.replace(tmp, filepath)


def load_settings(*, use_cache: bool = True) -> dict:
    """加载设置。
    
    Load settings.json for UI/branding/external links.
    
        settings.json is intentionally separate from config.json (runtime config).
    """
    path = _settings_path()
    mtime = _mtime_or_zero(path)

    if use_cache:
        now = time.time()
        cached = _CACHE.get("data")
        cached_ts = float(_CACHE.get("ts") or 0.0)
        cached_mtime = float(_CACHE.get("mtime") or 0.0)
        if cached is not None and (now - cached_ts) <= _CACHE_TTL_SECONDS and cached_mtime == mtime:
            return dict(cached)

    data = _read_json_file(path)
    _CACHE["data"] = dict(data)
    _CACHE["mtime"] = mtime
    _CACHE["ts"] = time.time()
    return dict(data)


def get_setting(key: str, default: Any = "") -> Any:
    """获取配置项。"""
    if not key:
        return default
    data = load_settings()
    value = data.get(key)
    return default if value is None else value


def update_settings(values: dict) -> dict:
    """更新设置。
    
    Merge `values` into settings.json (atomic write). Returns the updated dict.
    """
    if not isinstance(values, dict):
        values = {}

    path = _settings_path()
    current = _read_json_file(path)
    if not isinstance(current, dict):
        current = {}

    for k, v in values.items():
        key = str(k or "").strip()
        if not key:
            continue
        current[key] = v

    _write_json_file_atomic(path, current)
    # refresh cache
    _CACHE["data"] = dict(current)
    _CACHE["mtime"] = _mtime_or_zero(path)
    _CACHE["ts"] = time.time()
    return dict(current)
