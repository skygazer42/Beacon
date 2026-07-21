# ruff: noqa: F403, F405
# This module historically relies on a large set of globals/helpers from ViewsBase.
# Keeping the star import avoids a risky large-scale refactor in this legacy file.
from app.views.ViewsBase import *  # NOSONAR
from app.utils.OSSystem import OSSystem
from app.models import (  # NOSONAR
    Alarm,
    AlgorithmModel,
    Control,
    LicenseLease,
    LicenseState,
    RecordingPlan,
    TaskPlan,
)
import shutil
import requests
import time
import threading
import subprocess
import signal
import json
import re
import os
import base64
import uuid
import logging
from datetime import datetime, timedelta
from django.db import connection, transaction
from django.utils import timezone
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from app.utils.SafeLog import safe_json_dumps
from app.utils.SystemConfigHelper import get_int, get_value
from app.utils.LicenseManager import extract_license_runtime_policy_from_json
from framework.settings import PROJECT_ADMIN_START_TIMESTAMP, PROJECT_BUILT, PROJECT_FLAG, PROJECT_UA, PROJECT_VERSION

_DEVICE_SUFFIXES = ["_gpu", "_cpu", "_auto", "_npu", "_trt"]

logger = logging.getLogger(__name__)

MSG_METHOD_NOT_SUPPORTED = "request method not supported"
MSG_CODE_REQUIRED = "code is required"
MSG_INVALID_API_RESPONSE = "invalid api response"
MSG_IMAGE_TOO_LARGE = "image too large"
DATA_URL_BASE64_MARKER = "base64,"
MSG_INFER_FAILED = "infer failed"
MSG_STREAM_CODE_REQUIRED = "stream_code is required"
MSG_INVALID_REQUEST_PARAMETER = "invalid request parameter"
DEFAULT_CORE_PROCESS_SCHEME = "http"
DEFAULT_CORE_PROCESS_NETLOC = "127.0.0.1:9993"

EVENT_LICENSE_LEASE_ACQUIRE = "license.lease.acquire"
EVENT_LICENSE_LEASE_RENEW = "license.lease.renew"
EVENT_LICENSE_LEASE_RELEASE = "license.lease.release"

ALARM_UPLOAD_PREFIX = "alarm/"
DEFAULT_UPLOAD_URL_PREFIX = "/static/upload/"
DEFAULT_OSD_FONT_COLOR = "255,255,255"
MSG_ALARM_ID_LIST_EMPTY = "告警 ID 列表为空"


def _split_algorithm_code(code):
    """拆分算法编码。"""
    if not code:
        return "", "CPU"
    value = str(code)
    lower = value.lower()
    # Support optional numeric suffix for multi-GPU/TRT, e.g. *_gpu1, *_trt0
    for suffix in ("_gpu", "_trt"):
        if lower.endswith(suffix):
            return value[:-len(suffix)], suffix[1:].upper()
        m = re.search(rf"{re.escape(suffix)}(\d+)$", lower)
        if m:
            return value[: -len(suffix) - len(m.group(1))], suffix[1:].upper()

    for suffix in ("_cpu", "_auto", "_npu"):
        if lower.endswith(suffix):
            return value[:-len(suffix)], suffix[1:].upper()
    return value, "CPU"

_version_cache = {
    # Backward compatible: keep a default cache slot when no extra params provided.
    "timestamp": 0,
    "data": None,
}
_version_cache_items = {}
_version_cache_ttl = 300


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    """处理环境变量浮点数。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        value = float(default)
    else:
        try:
            value = float(raw)
        except Exception:
            value = float(default)
    return max(float(min_value), min(float(max_value), float(value)))


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    """读取环境变量并转换为整数。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception:
            value = int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _index_analyzer_cache_ttl_seconds() -> float:
    # Keep default behavior unchanged while allowing ops tuning in heavy dashboards.
    """返回索引分析器缓存TTL秒数。"""
    return _env_float("BEACON_INDEX_ANALYZER_CACHE_TTL_SECONDS", 10.0, min_value=1.0, max_value=60.0)


def _parse_version(value):
    """解析版本。"""
    if not value:
        return []
    val = str(value).strip()
    if val.lower().startswith("v"):
        val = val[1:]
    parts = re.split(r"[.\-_]", val)
    nums = []
    for part in parts:
        if part.isdigit():
            nums.append(int(part))
        else:
            m = re.match(r"(\d+)", part)
            if m:
                nums.append(int(m.group(1)))
    return nums

def _compare_versions(current, latest):
    """处理`compare``versions`。"""
    cur_parts = _parse_version(current)
    lat_parts = _parse_version(latest)
    length = max(len(cur_parts), len(lat_parts))
    cur_parts += [0] * (length - len(cur_parts))
    lat_parts += [0] * (length - len(lat_parts))
    if cur_parts < lat_parts:
        return -1
    if cur_parts > lat_parts:
        return 1
    return 0

def _version_to_code(version):
    """处理版本`to`编码。"""
    parts = _parse_version(version)
    if not parts:
        return 0
    code_str = ""
    for idx, part in enumerate(parts):
        if idx == 0:
            code_str += str(part)
        else:
            code_str += "%02d" % part
    try:
        return int(code_str)
    except Exception:
        return 0

def _normalize_version_payload(payload):
    """执行归一化版本载荷。"""
    if not isinstance(payload, dict):
        return {}
    version = payload.get("version") or payload.get("latestVersion") or payload.get("tag") or payload.get("tag_name")
    download_url = payload.get("downloadUrl") or payload.get("url") or payload.get("download_url")
    notes = payload.get("notes") or payload.get("releaseNotes") or payload.get("changelog") or payload.get("desc")
    published_at = payload.get("publishedAt") or payload.get("published_at")
    version_code = payload.get("versionCode") or payload.get("version_code")
    if isinstance(version_code, str) and version_code.isdigit():
        version_code = int(version_code)
    return {
        "latestVersion": version,
        "downloadUrl": download_url,
        "releaseNotes": notes,
        "publishedAt": published_at,
        "versionCode": version_code
    }

_VERSION_CHECK_FORWARD_KEYS = (
    "infer_engine",
    "infer_engine_version",
    "arch",
    "os",
    "kernel",
    "device",
    "device_version",
    "openvino",
    "tensorrt",
    "onnxruntime",
    "cann",
    "rknpu",
)


def _version_check_forward_params(request) -> dict:
    # v4.632: 支持上传推理引擎参数等参数（用于升级包兼容性判断）
    # - 参数来源：query string（GET）
    # - 不转发 UI cache-bust 参数 t
    # - 仅 allowlist 转发，避免参数滥用
    """处理版本`check`转发参数。"""
    out = {}
    try:
        for k in _VERSION_CHECK_FORWARD_KEYS:
            v = request.GET.get(k, None)
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            if len(s) > 200:
                s = s[:200]
            out[k] = s
    except Exception:
        out = {}
    return out


def _version_check_cache_key(forward_params: dict) -> str:
    """返回版本`check`缓存键。"""
    if not forward_params:
        return ""
    try:
        return "&".join([f"{k}={forward_params[k]}" for k in sorted(forward_params.keys())])
    except Exception:
        return ""


def _version_check_cache_get(cache_key: str, now: int):
    """处理版本`check`缓存`get`。"""
    if cache_key:
        item = _version_cache_items.get(cache_key)
        cache_data = (item or {}).get("data")
        cache_ts = int((item or {}).get("timestamp") or 0)
    else:
        cache_data = _version_cache.get("data")
        cache_ts = _version_cache.get("timestamp", 0)
    if cache_data and (int(now or 0) - int(cache_ts or 0)) < int(_version_cache_ttl or 0):
        return cache_data
    return None


def _version_check_cache_set(cache_key: str, now: int, data: dict) -> None:
    # Cache per parameter set (best-effort).
    """处理版本`check`缓存`set`。"""
    if cache_key:
        _version_cache_items[cache_key] = {"timestamp": int(now or 0), "data": data}
        return
    _version_cache["timestamp"] = int(now or 0)
    _version_cache["data"] = data


def _version_check_has_update(current_version: str, *, latest_version=None, version_code=None) -> bool:
    """处理版本`check``has``update`。"""
    if isinstance(version_code, int) and version_code > 0:
        current_code = _version_to_code(current_version)
        return int(version_code) > int(current_code)
    if latest_version:
        return _compare_versions(current_version, latest_version) < 0
    return False


def api_discover(request):
    """处理 `discover` 接口请求。"""
    ret = False
    msg = MSG_METHOD_NOT_SUPPORTED
    info = {}

    if request.method == "GET":
        os_system = OSSystem()
        info = {
            "system_name": os_system.getSystemName(),
            "machine_node": os_system.getMachineNode(),
            "project_ua": PROJECT_UA,
            "project_version": PROJECT_VERSION,
            "project_flag": PROJECT_FLAG,
            "project_built": PROJECT_BUILT,
            "project_start_timestamp": PROJECT_ADMIN_START_TIMESTAMP,
            "code":g_config.code,
            "name":g_config.name,
            "describe":g_config.describe,
            "host":g_config.host
        }

        ret = True
        msg = "success"

    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "info": info
    }
    return f_responseJson(res)

def api_check_version(request):
    """处理 `checkVersion` 接口请求。"""
    data = {
        "currentVersion": PROJECT_VERSION,
        "hasUpdate": False
    }
    msg = "success"

    if request.method != 'GET':
        res = {
            "code": 0,
            "msg": MSG_METHOD_NOT_SUPPORTED,
            "data": data
        }
        return f_responseJson(res)

    check_url = getattr(g_config, "versionCheckUrl", "").strip()
    if not check_url:
        msg = "version check url not configured"
        res = {
            "code": 1000,
            "msg": msg,
            "data": data
        }
        return f_responseJson(res)

    forward_params = _version_check_forward_params(request)
    cache_key = _version_check_cache_key(forward_params)
    now = int(time.time())
    cache_data = _version_check_cache_get(cache_key, now)
    if cache_data:
        res = {"code": 1000, "msg": "success", "data": cache_data}
        return f_responseJson(res)

    try:
        # Forward allowlist parameters to upstream version check service.
        resp = requests.get(check_url, timeout=5, params=forward_params or None)
        if resp.status_code != 200:
            raise RuntimeError("status_code=%d" % resp.status_code)
        payload = resp.json()
        latest_info = _normalize_version_payload(payload)
        latest_version = latest_info.get("latestVersion")
        version_code = latest_info.get("versionCode")

        data.update(latest_info)
        data["hasUpdate"] = _version_check_has_update(PROJECT_VERSION, latest_version=latest_version, version_code=version_code)
    except Exception as e:
        msg = str(e)

    _version_check_cache_set(cache_key, now, data)

    res = {
        "code": 1000,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)
api_checkVersion = api_check_version  # pragma: no cover - compatibility alias


class _ImageDetectApiError(Exception):
    def __init__(self, msg: str, *, data=None):
        """处理`init`。"""
        super().__init__(str(msg or ""))
        self.data = data


def _image_detect_error_response(msg: str, *, data=None):
    """返回图片检测错误响应。"""
    body = {"code": 0, "msg": str(msg or "")}
    if data is not None:
        body["data"] = data
    return f_responseJson(body)


def _image_detect_request_params(request):
    """处理图片检测请求参数。"""
    content_type = str(getattr(request, "content_type", "") or "")
    if content_type.startswith("application/json"):
        try:
            return f_parsePostParams(request)
        except Exception:
            raise _ImageDetectApiError("invalid json")
    return {key: request.POST.get(key) for key in request.POST}


def _image_detect_algorithm_codes(raw_code: str, device_param: str):
    """处理图片检测算法编码列表。"""
    device_param = str(device_param or "").strip().upper()
    base_code, inferred_device = _split_algorithm_code(str(raw_code or "").strip())
    base_code = str(base_code or "").strip()
    inferred_device = str(inferred_device or "").strip().upper()
    device = device_param or inferred_device or "CPU"
    suffix = {
        "CPU": "",
        "GPU": "_gpu",
        "TRT": "_trt",
        "AUTO": "_auto",
        "NPU": "_npu",
    }.get(device, "")
    analyzer_code = base_code
    if (raw_code != base_code) and (not device_param) and (inferred_device == device):
        analyzer_code = raw_code
    elif suffix and not str(analyzer_code).lower().endswith(suffix):
        analyzer_code = f"{analyzer_code}{suffix}"
    return base_code, device, analyzer_code


def _image_detect_optional_float(name: str, value, default_value: float):
    """处理图片检测可选浮点数。"""
    if value is None or value == "":
        return float(default_value)
    try:
        f = float(value)
    except Exception:
        raise _ImageDetectApiError(f"{name} must be a number")
    if f < 0.0 or f > 1.0:
        raise _ImageDetectApiError(f"{name} must be between 0 and 1")
    return f


def _image_detect_thresholds(params: dict, algo):
    """处理图片检测`thresholds`。"""
    conf_thresh = _image_detect_optional_float(
        "confThresh",
        params.get("confThresh") if params.get("confThresh") is not None else params.get("conf_thresh"),
        float(getattr(algo, "conf_thresh", 0.25) or 0.25),
    )
    nms_thresh = _image_detect_optional_float(
        "nmsThresh",
        params.get("nmsThresh") if params.get("nmsThresh") is not None else params.get("nms_thresh"),
        float(getattr(algo, "nms_thresh", 0.45) or 0.45),
    )
    return conf_thresh, nms_thresh


def _image_detect_max_image_bytes() -> int:
    """返回图片检测最大值图片字节数。"""
    return _env_int(
        "BEACON_OPENAPI_IMAGE_MAX_BYTES",
        3 * 1024 * 1024,
        min_value=1,
        max_value=50 * 1024 * 1024,
    )


def _image_detect_estimate_base64_decoded_bytes(value: str) -> int:
    """返回图片检测`estimate`Base64`decoded`字节数。"""
    if not value:
        return 0
    clean_value = str(value).strip()
    lower = clean_value.lower()
    if lower.startswith("data:") and DATA_URL_BASE64_MARKER in lower:
        clean_value = clean_value.split(DATA_URL_BASE64_MARKER, 1)[1].strip()
    clean_value = "".join(clean_value.split())
    if len(clean_value) < 8:
        return 0
    padding = _image_detect_base64_padding_bytes(clean_value)
    return max(0, (len(clean_value) // 4) * 3 - padding)


def _image_detect_base64_padding_bytes(clean_value: str) -> int:
    """返回图片检测Base64`padding`字节数。"""
    if clean_value.endswith("=="):
        return 2
    if clean_value.endswith("="):
        return 1
    return 0


def _image_detect_multipart_base64(image_file, max_image_bytes: int) -> str:
    """处理图片检测`multipart`Base64。"""
    declared_size = getattr(image_file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_image_bytes:
        raise _ImageDetectApiError(MSG_IMAGE_TOO_LARGE)

    chunks = []
    total = 0
    try:
        for chunk in image_file.chunks():
            if not chunk:
                continue
            total += len(chunk)
            if total > max_image_bytes:
                raise _ImageDetectApiError(MSG_IMAGE_TOO_LARGE)
            chunks.append(chunk)
    except _ImageDetectApiError:
        raise
    except Exception:
        chunks = []
    image_bytes = b"".join(chunks)
    if not image_bytes:
        raise _ImageDetectApiError("image is empty")
    return base64.b64encode(image_bytes).decode("ascii")


def _image_detect_base64_param(params: dict, max_image_bytes: int) -> str:
    """处理图片检测Base64参数。"""
    image_b64 = params.get("image_base64") or params.get("imageBase64") or ""
    if not isinstance(image_b64, str):
        raise _ImageDetectApiError("image_base64 must be a string")
    image_b64 = image_b64.strip()
    if _image_detect_estimate_base64_decoded_bytes(image_b64) > max_image_bytes:
        raise _ImageDetectApiError(MSG_IMAGE_TOO_LARGE)
    max_b64_chars = ((max_image_bytes + 2) // 3) * 4 + 1024
    if len(image_b64) > max_b64_chars:
        raise _ImageDetectApiError(MSG_IMAGE_TOO_LARGE)
    lower = image_b64.lower()
    if lower.startswith("data:") and DATA_URL_BASE64_MARKER in lower:
        image_b64 = image_b64.split(DATA_URL_BASE64_MARKER, 1)[1].strip()
    return image_b64


def _image_detect_image_base64(request, params: dict) -> str:
    """处理图片检测图片Base64。"""
    max_image_bytes = _image_detect_max_image_bytes()
    image_file = request.FILES.get("image")
    image_b64 = _image_detect_multipart_base64(image_file, max_image_bytes) if image_file is not None else _image_detect_base64_param(params, max_image_bytes)
    if not image_b64:
        raise _ImageDetectApiError("image is required")
    return image_b64


def _image_detect_api_payload(algo, *, base_code: str, image_b64: str, conf_thresh: float, nms_thresh: float, device: str):
    """返回图片检测API载荷。"""
    return {
        "image_base64": image_b64,
        "nodeCode": "openapi",
        "controlCode": "imageDetect",
        "streamCode": "openapi",
        "streamApp": "openapi",
        "streamName": "openapi",
        "flowCode": base_code,
        "algorithmCode": base_code,
        "modelClassNames": str(getattr(algo, "object_str", "") or "").strip(),
        "detectClassNames": str(getattr(algo, "object_str", "") or "").strip(),
        "polygonType": 3,
        "polygon": "0,0,1,0,1,1,0,1",
        "algorithmParams": {
            "confThresh": conf_thresh,
            "nmsThresh": nms_thresh,
            "modelConcurrency": int(getattr(algo, "model_concurrency", 1) or 1),
            "inputWidth": int(getattr(algo, "input_width", 640) or 640),
            "inputHeight": int(getattr(algo, "input_height", 640) or 640),
            "modelPrecision": str(getattr(algo, "model_precision", "FP32") or "FP32"),
        },
        "extensions": {"source": "openapi_image_detect", "device": device},
    }


def _image_detect_api_response(api_url: str, payload: dict):
    """返回图片检测API响应。"""
    try:
        res = requests.post(
            api_url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload, ensure_ascii=False),
            timeout=(2, 10),
        )
    except Exception as exc:
        raise _ImageDetectApiError(str(exc))
    if not res.status_code:
        raise _ImageDetectApiError("request failed")
    try:
        api_data = res.json()
    except Exception:
        raise _ImageDetectApiError(MSG_INVALID_API_RESPONSE)
    if not isinstance(api_data, dict):
        raise _ImageDetectApiError(MSG_INVALID_API_RESPONSE)
    if api_data.get("code") != 1000:
        raise _ImageDetectApiError(str(api_data.get("msg") or MSG_INFER_FAILED), data=api_data)
    return api_data


def _image_detect_api_success_response(*, base_code: str, device: str, api_data):
    """返回图片检测API成功状态响应。"""
    result_obj = api_data.get("result") if isinstance(api_data.get("result"), dict) else {}
    detects = result_obj.get("detects") if isinstance(result_obj.get("detects"), list) else []
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "engine": "api",
                "algorithmCode": base_code,
                "device": device,
                "happen": bool(result_obj.get("happen")) if result_obj else False,
                "happenScore": float(result_obj.get("happenScore") or 0.0) if result_obj else 0.0,
                "count": len(detects),
                "detects": detects,
            },
        }
    )


def _image_detect_builtin_abs_model_path(code: str) -> str:
    """返回图片检测`builtin`绝对路径模型路径。"""
    from app.utils.BuiltinAlgorithms import get_builtin_algorithm_meta
    from app.utils.UploadPath import split_paired_path

    meta = get_builtin_algorithm_meta(code)
    rel_path = str((meta or {}).get("relative_model_path") or "").strip()
    if not rel_path:
        return ""
    parts = split_paired_path(rel_path)
    rel_path = parts[0] if parts else rel_path
    model_dir = str(getattr(g_config, "modelDir", "") or "").strip()
    if not model_dir:
        return ""
    return os.path.normpath(os.path.join(model_dir, rel_path))


def _image_detect_local_model_info(algo):
    """返回图片检测`local`模型信息。"""
    from app.utils.UploadPath import split_paired_path

    if getattr(algo, "algorithm_type", 0) == 0:
        model_path = str(getattr(algo, "model_path", "") or "").strip()
        class_names = [x.strip() for x in str(getattr(algo, "object_str", "") or "").split(",") if x.strip()]
        if not model_path:
            code = str(getattr(algo, "code", "") or "").strip()
            builtin_abs_path = _image_detect_builtin_abs_model_path(code)
            if builtin_abs_path:
                return builtin_abs_path, class_names
            raise _ImageDetectApiError("该算法未配置模型文件")
        parts = split_paired_path(model_path)
        return parts[0] if parts else model_path, class_names

    dll_path = str(getattr(algo, "dll_path", "") or "").strip()
    if not dll_path:
        raise _ImageDetectApiError("该算法未配置动态库（dll/so/dylib）")
    return dll_path, None


def _image_detect_abs_model_path(model_path: str) -> str:
    """返回图片检测绝对路径模型路径。"""
    from app.utils.UploadPath import resolve_upload_url_to_abs_path

    abs_path = resolve_upload_url_to_abs_path(
        model_path,
        upload_dir=getattr(g_config, "uploadDir", ""),
        upload_www_prefix=getattr(g_config, "uploadDir_www", DEFAULT_UPLOAD_URL_PREFIX),
    )
    if not abs_path:
        raise _ImageDetectApiError("无法解析模型文件路径")
    return abs_path


def _image_detect_load_local(algo, *, analyzer_code: str, abs_path: str, class_names, device: str):
    """处理图片检测`load``local`。"""
    model_concurrency = max(1, int(getattr(algo, "model_concurrency", 1) or 1))
    state, msg = g_analyzer.algorithm_load(
        code=analyzer_code,
        modelPath=abs_path,
        classNames=class_names,
        device=device or "CPU",
        modelConcurrency=model_concurrency,
        algorithmSubtype=str(getattr(algo, "algorithm_subtype", "") or "").strip() or None,
    )
    if (not state) and ("already loaded" in str(msg or "").lower()):
        state = True
    if not state:
        raise _ImageDetectApiError(str(msg or "load failed"))


def _image_detect_local_success_response(*, base_code: str, analyzer_code: str, device: str, test_data):
    """返回图片检测`local`成功状态响应。"""
    detects = test_data.get("detects") if isinstance(test_data, dict) else None
    if not isinstance(detects, list):
        detects = []
    try:
        latency_ms = int((test_data or {}).get("latencyMs") or 0)
    except Exception:
        latency_ms = 0
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "engine": "analyzer",
                "algorithmCode": base_code,
                "analyzerCode": analyzer_code,
                "device": device,
                "count": int((test_data or {}).get("count") or len(detects)),
                "latencyMs": latency_ms,
                "detects": detects,
            },
        }
    )


def _image_detect_basic_api_success(algo, *, base_code: str, image_b64: str, conf_thresh: float, nms_thresh: float, device: str):
    """Run a basic API-backed image detection algorithm and return its response."""
    api_url = str(getattr(algo, "api_url", "") or "").strip()
    if not api_url:
        raise _ImageDetectApiError("api_url is required")
    api_data = _image_detect_api_response(
        api_url,
        _image_detect_api_payload(
            algo,
            base_code=base_code,
            image_b64=image_b64,
            conf_thresh=conf_thresh,
            nms_thresh=nms_thresh,
            device=device,
        ),
    )
    return _image_detect_api_success_response(base_code=base_code, device=device, api_data=api_data)


def _image_detect_model_abs_path(model_path: str) -> str:
    """Resolve an image-detect model path to the Analyzer filesystem path."""
    upload_www_prefix = str(getattr(g_config, "uploadDir_www", DEFAULT_UPLOAD_URL_PREFIX) or DEFAULT_UPLOAD_URL_PREFIX)
    if os.path.isabs(model_path) and not model_path.startswith(upload_www_prefix):
        return model_path
    return _image_detect_abs_model_path(model_path)


def _image_detect_local_infer(algo, *, analyzer_code: str, device: str, image_b64: str, conf_thresh: float, nms_thresh: float):
    """Ensure a local image-detect algorithm is loaded and run one test inference."""
    model_path, class_names = _image_detect_local_model_info(algo)
    _image_detect_load_local(
        algo,
        analyzer_code=analyzer_code,
        abs_path=_image_detect_model_abs_path(model_path),
        class_names=class_names,
        device=device,
    )
    test_state, test_msg, test_data = g_analyzer.algorithm_test_infer(
        analyzer_code,
        image_b64,
        confThresh=conf_thresh,
        nmsThresh=nms_thresh,
        timeout_seconds=30,
    )
    if not test_state:
        raise _ImageDetectApiError(str(test_msg or MSG_INFER_FAILED))
    return test_data


def api_open_image_detect(request):
    """
    OpenAPI: 图片检测接口

    POST /open/algorithm/imageDetect

    Params (json or form):
      - code: algorithm code (required)
      - device: CPU/GPU/TRT/AUTO/NPU (optional; default CPU; may be inferred from code suffix)
      - confThresh / nmsThresh: optional floats in [0,1]
      - image: multipart file (optional)
      - image_base64: base64(JPEG bytes) (optional; required if image is not provided)

    Behavior:
      - basic algorithm + basic_source=api: forward to AlgorithmModel.api_url (protocol v2)
      - local model/plugin: ensure Analyzer loaded, then call Analyzer /api/algorithm/testInfer
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = _image_detect_request_params(request)
        raw_code = str(params.get("code") or "").strip()
        if not raw_code:
            raise _ImageDetectApiError(MSG_CODE_REQUIRED)
        base_code, device, analyzer_code = _image_detect_algorithm_codes(raw_code, params.get("device"))
        algo = AlgorithmModel.objects.filter(code=base_code).first()
        if not algo:
            raise _ImageDetectApiError("算法不存在")
        conf_thresh, nms_thresh = _image_detect_thresholds(params, algo)
        image_b64 = _image_detect_image_base64(request, params)
        is_basic_api = getattr(algo, "algorithm_type", 0) == 0 and getattr(algo, "basic_source", "model") == "api"
        if is_basic_api:
            return _image_detect_basic_api_success(
                algo,
                base_code=base_code,
                image_b64=image_b64,
                conf_thresh=conf_thresh,
                nms_thresh=nms_thresh,
                device=device,
            )

        test_data = _image_detect_local_infer(
            algo,
            analyzer_code=analyzer_code,
            device=device,
            image_b64=image_b64,
            conf_thresh=conf_thresh,
            nms_thresh=nms_thresh,
        )
    except _ImageDetectApiError as exc:
        return _image_detect_error_response(str(exc), data=exc.data)

    return _image_detect_local_success_response(
        base_code=base_code,
        analyzer_code=analyzer_code,
        device=device,
        test_data=test_data,
    )
api_openImageDetect = api_open_image_detect  # pragma: no cover - compatibility alias


def api_open_audio_detect(request):
    """
    OpenAPI: 音频检测 / 语音识别接口（Wave 1）

    POST /open/algorithm/audioDetect
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = _audio_detect_request_params(request)
        base_code = _audio_detect_base_code(params)
        _algo, api_url = _audio_detect_api_algorithm(base_code)
        audio_b64 = _audio_detect_audio_base64(request, params)
        api_data = _audio_detect_api_response(
            api_url,
            _audio_detect_request_payload(base_code=base_code, audio_b64=audio_b64, params=params),
        )
        text, result_language, segments = _audio_detect_result(api_data)
        alarm_info = _audio_detect_alarm_info(
            base_code=base_code,
            params=params,
            text=text,
            result_language=result_language,
            segments=segments,
        )
    except _AudioDetectApiError as exc:
        return _audio_detect_error_response(str(exc), data=exc.data)

    return _audio_detect_success_response(
        base_code=base_code,
        text=text,
        result_language=result_language,
        segments=segments,
        alarm_info=alarm_info,
    )
api_openAudioDetect = api_open_audio_detect  # pragma: no cover - compatibility alias


class _AudioDetectApiError(Exception):
    def __init__(self, msg: str, *, data=None):
        """处理`init`。"""
        super().__init__(str(msg or ""))
        self.data = data


def _parse_optional_json_object(value, field_name: str):
    """解析可选JSON`object`。"""
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except Exception:
            raise ValueError(f"{field_name} must be valid JSON")
        if not isinstance(data, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        return data
    raise ValueError(f"{field_name} must be a JSON object or string")


def _sanitize_audio_event_segments(segments, *, max_items: int = 50):
    """清洗音频事件`segments`。"""
    if not isinstance(segments, list):
        return []
    cleaned = []
    for item in segments[:max_items]:
        if not isinstance(item, dict):
            continue
        row = {}
        for key in ("startMs", "endMs"):
            try:
                row[key] = int(item.get(key))
            except Exception:
                continue
        text = str(item.get("text") or "").strip()
        if text:
            row["text"] = text[:500]
        if row:
            cleaned.append(row)
    return cleaned


def _build_audio_event_alarm_metadata(base_metadata, *, text: str, language: str, segments):
    """构建音频事件告警元数据。"""
    metadata = dict(base_metadata or {})
    user_data = metadata.get("user_data") if isinstance(metadata.get("user_data"), dict) else {}
    if not user_data.get("event"):
        user_data["event"] = "audio_event"
    metadata["user_data"] = user_data
    metadata["audio_event"] = {
        "text": str(text or "")[:2000],
        "language": str(language or "")[:64],
        "source": "openapi_audio_detect",
        "segments": _sanitize_audio_event_segments(segments),
    }
    return metadata


def _normalize_audio_alarm_control_code(value: str, fallback: str) -> str:
    """执行归一化音频告警控制编码。"""
    raw = str(value or "").strip() or str(fallback or "").strip() or "audio_event"
    clean = re.sub(r"[^0-9A-Za-z._:-]+", "_", raw)
    return clean[:50] or "audio_event"


def _parse_audio_alarm_level(params: dict) -> int:
    """解析音频告警`level`。"""
    try:
        alarm_level = int(params.get("alarm_level") or params.get("alarmLevel") or 1)
    except Exception:
        alarm_level = 1
    return max(1, min(4, alarm_level))


def _emit_alarm_created_event_best_effort(*, alarm, legacy_event: str, event_source: str, metadata_obj: dict) -> None:
    """尽力处理`emit`告警`created`事件。"""
    from app.utils.AlarmEventBus import (
        AlarmOutboxEnqueueError,
        build_alarm_created_event_for_alarm,
        enqueue_alarm_event_outbox,
    )
    from app.utils.BackgroundServices import get_alarm_sink_dispatcher

    try:
        payload = build_alarm_created_event_for_alarm(
            g_config,
            alarm=alarm,
            legacy_event=legacy_event,
            event_source=event_source,
            metadata_obj=metadata_obj,
        )
        if getattr(g_config, "alarmOutboxEnabled", True):
            enqueue_alarm_event_outbox(g_config, payload, alarm_id=alarm.id, control_code=alarm.control_code)
            return

        dispatcher = get_alarm_sink_dispatcher()
        if dispatcher:
            dispatcher.enqueue(payload)
    except AlarmOutboxEnqueueError:
        event_id = str(payload.get("event_id", "") or "")
        logger.exception(
            "Alarm outbox enqueue failed event_id=%s alarm_id=%s control_code=%s",
            event_id,
            alarm.id,
            alarm.control_code,
            extra={
                "alarm_event_id": event_id,
                "alarm_id": alarm.id,
                "control_code": alarm.control_code,
            },
        )
        raise
    except Exception:
        return


def _create_audio_review_alarm(*, base_code: str, params: dict, text: str, result_language: str, segments):
    """创建音频`review`告警。"""
    metadata_obj = _parse_optional_json_object(params.get("metadata"), "metadata")
    metadata_obj = _build_audio_event_alarm_metadata(
        metadata_obj,
        text=text,
        language=result_language,
        segments=segments,
    )

    summary_text = str(text or "").strip() or "Audio event detected"
    control_code = _normalize_audio_alarm_control_code(
        params.get("control_code") or params.get("controlCode"),
        fallback=base_code,
    )
    alarm_level = _parse_audio_alarm_level(params)

    alarm = Alarm()
    alarm.sort = 0
    alarm.control_code = control_code
    alarm.desc = str(params.get("desc") or "").strip() or summary_text[:500]
    alarm.detail_desc = summary_text[:2000]
    alarm.alarm_type = "audio_event"
    alarm.alarm_level = alarm_level
    alarm.algorithm_code = str(base_code or "").strip()
    alarm.object_code = "speech"
    alarm.stream_code = str(params.get("stream_code") or params.get("streamCode") or "")[:50]
    alarm.stream_app = str(params.get("stream_app") or params.get("streamApp") or "audio")[:50]
    alarm.stream_name = str(params.get("stream_name") or params.get("streamName") or control_code)[:100]
    alarm.stream_url = str(params.get("stream_url") or params.get("streamUrl") or "")[:300]
    alarm.metadata = json.dumps(metadata_obj, ensure_ascii=False)
    alarm.create_time = datetime.now()
    alarm.state = 0
    alarm.save()

    _emit_alarm_created_event_best_effort(
        alarm=alarm,
        legacy_event="alarm_audio_detect",
        event_source="openAudioDetect",
        metadata_obj=metadata_obj,
    )

    return {
        "id": int(alarm.id),
        "control_code": str(alarm.control_code or ""),
        "alarm_type": str(alarm.alarm_type or ""),
        "detail_url": f"/alarm/detail?id={alarm.id}",
    }


def _parse_boolish(value, default: bool = False) -> bool:
    """解析`boolish`。"""
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        try:
            return int(value) != 0
        except Exception:
            return bool(value)
    raw = str(value or "").strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off", ""):
        return False
    return bool(default)


def _parse_time_hhmm(value, default_h: int = 0, default_m: int = 0):
    """解析时间`hhmm`。
    
    Accept: "HH:MM" / "HH:MM:SS" / datetime.time
        Returns: datetime.time
    """
    from datetime import time as dt_time

    if value is None or value == "":
        return dt_time(default_h, default_m)
    if hasattr(value, "hour") and hasattr(value, "minute"):
        try:
            return dt_time(int(value.hour), int(value.minute))
        except Exception:
            return dt_time(default_h, default_m)
    s = str(value or "").strip()
    if not s:
        return dt_time(default_h, default_m)
    parts = s.split(":")
    if len(parts) < 2:
        return dt_time(default_h, default_m)
    try:
        h = int(parts[0])
        m = int(parts[1])
    except Exception:
        return dt_time(default_h, default_m)
    if h < 0:
        h = 0
    if h > 23:
        h = 23
    if m < 0:
        m = 0
    if m > 59:
        m = 59
    return dt_time(h, m)


def _parse_days_mask_int(params):
    """解析`days`脱敏整数值。"""
    raw_mask = params.get("daysMask")
    if raw_mask is None:
        raw_mask = params.get("days_mask")
    if raw_mask is None or str(raw_mask).strip() == "":
        return None
    try:
        mask = int(raw_mask)
    except Exception:
        return None
    if mask < 0:
        mask = 0
    if mask > 127:
        mask = 127
    return mask


def _parse_days_of_week_values(params) -> list:
    """解析`days``of``week``values`。"""
    raw = params.get("daysOfWeek")
    if raw is None:
        raw = params.get("days_of_week")
    if raw is None:
        return []

    if isinstance(raw, list):
        values = raw
    else:
        s = str(raw or "").strip()
        if not s:
            return []
        values = [x.strip() for x in s.split(",") if x.strip()]

    days = []
    for item in values:
        try:
            days.append(int(item))
        except Exception:
            continue
    return days


def _normalize_days_for_mask(days: list) -> list:
    """获取脱敏的归一化`days`。"""
    if not days:
        return []
    # Normalize:
    # - 1..7 => Mon..Sun
    # - 0..6 => Mon..Sun
    use_1_7 = all(1 <= d <= 7 for d in days)
    use_0_6 = all(0 <= d <= 6 for d in days)
    if use_1_7 and not use_0_6:
        return [d - 1 for d in days]  # 1->0, 7->6
    if use_0_6:
        return days
    return []


def _days_to_mask(days: list) -> int:
    """处理`days``to`脱敏。"""
    mask = 0
    for d in days:
        if 0 <= d <= 6:
            mask |= 1 << d
    return int(mask)


def _parse_days_mask(params) -> int:
    """解析`days`脱敏。
    
    Supports:
          - daysMask / days_mask: int bitmask (bit0=Mon..bit6=Sun)
          - daysOfWeek / days_of_week: list[int] or comma-separated string.
            - If values are 1..7 => treated as Mon=1..Sun=7
            - If values are 0..6 => treated as Mon=0..Sun=6
    """
    mask = _parse_days_mask_int(params)
    if mask is not None:
        return mask

    days = _parse_days_of_week_values(params)
    norm = _normalize_days_for_mask(days)
    mask = _days_to_mask(norm)
    return int(mask) if mask > 0 else 127


def _dir_size_bytes(root: str) -> int:
    """返回目录占用的字节数。"""
    if not root or not os.path.isdir(root):
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            p = os.path.join(dirpath, filename)
            try:
                total += int(os.path.getsize(p) or 0)
            except Exception:
                continue
    return int(total)


def _recording_plan_to_dict(plan: "RecordingPlan") -> dict:
    """处理录制计划`to`字典。"""
    return {
        "id": int(getattr(plan, "id", 0) or 0),
        "code": str(getattr(plan, "code", "") or ""),
        "name": str(getattr(plan, "name", "") or ""),
        "enabled": bool(getattr(plan, "enabled", False)),
        "stream_code": str(getattr(plan, "stream_code", "") or ""),
        "stream_url": str(getattr(plan, "stream_url", "") or ""),
        "start_time": str(getattr(plan, "start_time", "") or ""),
        "end_time": str(getattr(plan, "end_time", "") or ""),
        "days_mask": int(getattr(plan, "days_mask", 127) or 127),
        "record_audio": bool(getattr(plan, "record_audio", False)),
        "format": str(getattr(plan, "format", "mp4") or "mp4"),
        "remark": str(getattr(plan, "remark", "") or ""),
        "create_time": str(getattr(plan, "create_time", "") or ""),
        "update_time": str(getattr(plan, "update_time", "") or ""),
    }


def _normalize_task_type(value: str) -> str:
    """执行归一化任务类型。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    mapping = {
        # external (camelCase) -> internal (snake_case)
        "restartsoftware": "restart_software",
        "restart_software": "restart_software",
        "restartsystem": "restart_system",
        "restart_system": "restart_system",
        "scanofflinestreams": "scan_offline_streams",
        "scan_offline_streams": "scan_offline_streams",
        "controlstart": "control_start",
        "control_start": "control_start",
        "controlstop": "control_stop",
        "control_stop": "control_stop",
        "forwardstart": "forward_start",
        "forward_start": "forward_start",
        "forwardstop": "forward_stop",
        "forward_stop": "forward_stop",
    }
    return mapping.get(lower, lower)


def _normalize_schedule_type(value: str) -> str:
    """执行归一化`schedule`类型。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower in ("daily", "day", "time", "dailytime", "daily_time"):
        return "daily"
    if lower in ("interval", "every", "period", "periodic"):
        return "interval"
    return lower


def _format_hhmm(value) -> str:
    """处理`format``hhmm`。"""
    try:
        return value.strftime("%H:%M") if value else ""
    except Exception:
        return ""


def _str_attr(obj, name: str) -> str:
    """处理字符串`attr`。"""
    try:
        return str(getattr(obj, name, "") or "")
    except Exception:
        return ""


def _int_attr(obj, name: str, default: int = 0) -> int:
    """处理整数值`attr`。"""
    try:
        return int(getattr(obj, name, default) or default)
    except Exception:
        return int(default)


def _bool_attr(obj, name: str, default: bool = False) -> bool:
    """处理布尔值`attr`。"""
    try:
        return bool(getattr(obj, name, default))
    except Exception:
        return bool(default)


def _task_plan_to_dict(plan: "TaskPlan") -> dict:
    """处理任务计划`to`字典。"""
    return {
        "id": _int_attr(plan, "id", 0),
        "code": _str_attr(plan, "code"),
        "name": _str_attr(plan, "name"),
        "enabled": _bool_attr(plan, "enabled", False),
        "task_type": _str_attr(plan, "task_type"),
        "schedule_type": _str_attr(plan, "schedule_type"),
        "run_time": _format_hhmm(getattr(plan, "run_time", None)),
        "days_mask": _int_attr(plan, "days_mask", 127),
        "interval_seconds": _int_attr(plan, "interval_seconds", 0),
        "target_codes": _str_attr(plan, "target_codes"),
        "options_json": _str_attr(plan, "options_json"),
        "last_run_at": _str_attr(plan, "last_run_at"),
        "last_result_code": _int_attr(plan, "last_result_code", 0),
        "last_result_msg": _str_attr(plan, "last_result_msg"),
        "create_time": _str_attr(plan, "create_time"),
        "update_time": _str_attr(plan, "update_time"),
    }


def api_open_basic_info(request):
    """
    OpenAPI: 查询软件基本信息

    GET /open/platform/basicInfo
    """
    try:
        os_info = OSSystem()
        data = {
            "nodeCode": str(getattr(g_config, "code", "") or ""),
            "nodeName": str(getattr(g_config, "name", "") or ""),
            "version": PROJECT_VERSION,
            "built": PROJECT_BUILT,
            "flag": PROJECT_FLAG,
            "adminStartTimestamp": int(PROJECT_ADMIN_START_TIMESTAMP or 0),
            "adminPort": int(getattr(g_config, "adminPort", 0) or 0),
            "analyzerPort": int(getattr(g_config, "analyzerPort", 0) or 0),
            "mediaHttpPort": int(getattr(g_config, "mediaHttpPort", 0) or 0),
            "mediaRtspPort": int(getattr(g_config, "mediaRtspPort", 0) or 0),
            "mediaRtmpPort": int(getattr(g_config, "mediaRtmpPort", 0) or 0),
            "machineNode": os_info.get_machine_node(),
            "osRelease": os_info.get_machine_os_release(),
            "cpu": os_info.get_machine_cpu(),
        }
        return f_responseJson({"code": 1000, "msg": "success", "data": data})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openBasicInfo = api_open_basic_info  # pragma: no cover - compatibility alias


def api_open_storage_info(request):
    """
    OpenAPI: 查询存储信息

    GET /open/platform/storageInfo
    """
    try:
        root = str(getattr(g_config, "storageRootPath", "") or "").strip()
        if not root:
            root = str(getattr(g_config, "uploadDir", "") or "").strip()

        du = None
        try:
            du = shutil.disk_usage(root)
        except Exception:
            du = None

        alarm_root = str(getattr(g_config, "alarmStoragePath", "") or "").strip()
        rec_root = str(getattr(g_config, "recordingStoragePath", "") or "").strip()

        data = {
            "storageRootPath": root,
            "alarmStoragePath": alarm_root,
            "recordingStoragePath": rec_root,
            "disk": {
                "total": int(getattr(du, "total", 0) or 0),
                "used": int(getattr(du, "used", 0) or 0),
                "free": int(getattr(du, "free", 0) or 0),
            },
            "usage": {
                "alarmBytes": _dir_size_bytes(alarm_root),
                "recordingBytes": _dir_size_bytes(rec_root),
            },
            "quota": {
                "alarmMaxStorageMB": int(get_int("alarmDataMaxStorageMB", 0, min_value=0, max_value=1024 * 1024)),
                "recordingMaxStorageMB": int(get_int("recordingDataMaxStorageMB", 0, min_value=0, max_value=1024 * 1024)),
            },
        }
        return f_responseJson({"code": 1000, "msg": "success", "data": data})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openStorageInfo = api_open_storage_info  # pragma: no cover - compatibility alias


def _schedule_admin_restart(delay_seconds: float = 1.0) -> None:
    """处理`schedule`管理员重启。"""
    def _do():
        """处理`do`。"""
        try:
            time.sleep(max(0.0, float(delay_seconds)))
        except Exception:
            time.sleep(1)
        # Best-effort graceful terminate first
        try:
            if hasattr(signal, "SIGTERM"):
                os.kill(os.getpid(), signal.SIGTERM)
                return
        except Exception:
            logger.debug("suppressed exception in app/views/api.py:1363", exc_info=True)
        try:
            os._exit(0)
        except Exception:
            return

    t = threading.Thread(target=_do, name="beacon-openapi-restart-software", daemon=True)
    t.start()


def _schedule_system_restart(delay_seconds: float = 1.0) -> None:
    """处理`schedule`系统重启。"""
    def _do():
        """处理`do`。"""
        try:
            time.sleep(max(0.0, float(delay_seconds)))
        except Exception:
            time.sleep(1)

        try:
            if os.name == "nt":
                # Windows
                subprocess.Popen(["shutdown", "/r", "/t", "1", "/f"])
            else:
                # Linux/macOS (best-effort). "shutdown -r now" may require root.
                subprocess.Popen(["shutdown", "-r", "now"])
        except Exception:
            try:
                if os.name != "nt":
                    subprocess.Popen(["reboot"])
            except Exception:
                logger.debug("suppressed exception in app/views/api.py:1394", exc_info=True)

    t = threading.Thread(target=_do, name="beacon-openapi-restart-system", daemon=True)
    t.start()


def api_open_restart_software(request):
    """
    OpenAPI: 重启软件（重启 Admin 进程；由外部守护进程或容器策略拉起）

    POST /open/platform/restartSoftware
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})
    try:
        _schedule_admin_restart(delay_seconds=1.0)
        return f_responseJson({"code": 1000, "msg": "restarting"})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openRestartSoftware = api_open_restart_software  # pragma: no cover - compatibility alias


def api_open_restart_system(request):
    """
    OpenAPI: 重启系统（best-effort，通常需要管理员权限）

    POST /open/platform/restartSystem
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})
    try:
        _schedule_system_restart(delay_seconds=1.0)
        return f_responseJson({"code": 1000, "msg": "restarting"})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openRestartSystem = api_open_restart_system  # pragma: no cover - compatibility alias


def _normalize_recording_plan_format(value) -> str:
    """执行归一化录制计划`format`。"""
    fmt = str(value or "mp4").strip().lower() or "mp4"
    return fmt if fmt in ("mp4", "ts", "flv") else "mp4"


def _resolve_stream_url_for_recording_plan(stream_code: str, stream_url: str) -> str:
    """解析并返回流URL`for`录制计划。"""
    stream_url = str(stream_url or "").strip()
    if stream_url:
        return stream_url
    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return ""
    return str(getattr(stream, "pull_stream_url", "") or "").strip()


def _create_recording_plan_from_params(params):
    """创建录制计划`from`参数。"""
    from app.utils.Security import validate_control_code

    code = str(params.get("code") or params.get("planCode") or params.get("plan_code") or "").strip()
    name = str(params.get("name") or "").strip()
    stream_code = str(params.get("stream_code") or params.get("streamCode") or "").strip()
    stream_url = str(params.get("stream_url") or params.get("streamUrl") or "").strip()
    enabled = _parse_boolish(params.get("enabled"), default=True)
    record_audio = _parse_boolish(params.get("record_audio") or params.get("recordAudio"), default=False)
    fmt = _normalize_recording_plan_format(params.get("format"))
    remark = str(params.get("remark") or "").strip()

    try:
        code = validate_control_code(code)
    except Exception as e:
        return None, str(e)

    if not stream_code:
        return None, MSG_STREAM_CODE_REQUIRED

    stream_url = _resolve_stream_url_for_recording_plan(stream_code, stream_url)
    start_time = _parse_time_hhmm(params.get("start_time") or params.get("startTime"), 0, 0)
    end_time = _parse_time_hhmm(params.get("end_time") or params.get("endTime"), 23, 59)
    days_mask = _parse_days_mask(params)

    if RecordingPlan.objects.filter(code=code).exists():
        return None, "recording plan code already exists"

    plan = RecordingPlan.objects.create(
        code=code,
        name=name,
        enabled=enabled,
        stream_code=stream_code,
        stream_url=stream_url,
        start_time=start_time,
        end_time=end_time,
        days_mask=days_mask,
        record_audio=record_audio,
        format=fmt,
        remark=remark,
    )
    return plan, ""


def api_open_add_recording_plan(request):
    """
    OpenAPI: 添加录像计划

    POST /open/recordingPlan/add
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)

    plan, err = _create_recording_plan_from_params(params)
    if not plan:
        return f_responseJson({"code": 0, "msg": err or "invalid params"})
    return f_responseJson({"code": 1000, "msg": "success", "data": _recording_plan_to_dict(plan)})
api_openAddRecordingPlan = api_open_add_recording_plan  # pragma: no cover - compatibility alias


def _first_present_param_value(params: dict, *keys: str):
    """返回首个`present`参数值。"""
    for key in keys:
        if key in params:
            return params.get(key)
    return None


def _has_any_param_key(params: dict, *keys: str) -> bool:
    """检查`any`参数键。"""
    return any(k in params for k in keys)


def _update_recording_plan_name_enabled(plan: "RecordingPlan", params: dict) -> None:
    """判断`update`录制计划名称是否启用。"""
    if "name" in params:
        plan.name = str(params.get("name") or "").strip()
    if "enabled" in params:
        plan.enabled = _parse_boolish(params.get("enabled"), default=bool(plan.enabled))


def _update_recording_plan_stream(plan: "RecordingPlan", params: dict) -> None:
    """更新录制计划流。"""
    if _has_any_param_key(params, "stream_code", "streamCode"):
        plan.stream_code = str(_first_present_param_value(params, "stream_code", "streamCode") or "").strip()
    if _has_any_param_key(params, "stream_url", "streamUrl"):
        plan.stream_url = str(_first_present_param_value(params, "stream_url", "streamUrl") or "").strip()


def _update_recording_plan_time(plan: "RecordingPlan", params: dict) -> None:
    """更新录制计划时间。"""
    if _has_any_param_key(params, "start_time", "startTime"):
        plan.start_time = _parse_time_hhmm(_first_present_param_value(params, "start_time", "startTime"), 0, 0)
    if _has_any_param_key(params, "end_time", "endTime"):
        plan.end_time = _parse_time_hhmm(_first_present_param_value(params, "end_time", "endTime"), 23, 59)


def _update_recording_plan_days_mask(plan: "RecordingPlan", params: dict) -> None:
    """更新录制计划`days`脱敏。"""
    if _has_any_param_key(params, "daysMask", "days_mask", "daysOfWeek", "days_of_week"):
        plan.days_mask = _parse_days_mask(params)


def _update_recording_plan_audio(plan: "RecordingPlan", params: dict) -> None:
    """更新录制计划音频。"""
    if _has_any_param_key(params, "record_audio", "recordAudio"):
        plan.record_audio = _parse_boolish(
            _first_present_param_value(params, "record_audio", "recordAudio"), default=bool(plan.record_audio)
        )


def _update_recording_plan_format(plan: "RecordingPlan", params: dict) -> None:
    """更新录制计划`format`。"""
    if "format" not in params:
        return
    fmt = str(params.get("format") or "").strip().lower()
    if fmt in ("mp4", "ts", "flv"):
        plan.format = fmt


def _update_recording_plan_remark(plan: "RecordingPlan", params: dict) -> None:
    """更新录制计划`remark`。"""
    if "remark" in params:
        plan.remark = str(params.get("remark") or "").strip()


def api_open_edit_recording_plan(request):
    """
    OpenAPI: 编辑录像计划

    POST /open/recordingPlan/edit
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)

    code = str(params.get("code") or params.get("planCode") or params.get("plan_code") or "").strip()
    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    plan = RecordingPlan.objects.filter(code=code).first()
    if not plan:
        return f_responseJson({"code": 0, "msg": "recording plan not found"})

    _update_recording_plan_name_enabled(plan, params)
    _update_recording_plan_stream(plan, params)
    _update_recording_plan_time(plan, params)
    _update_recording_plan_days_mask(plan, params)
    _update_recording_plan_audio(plan, params)
    _update_recording_plan_format(plan, params)
    _update_recording_plan_remark(plan, params)

    plan.save()
    return f_responseJson({"code": 1000, "msg": "success", "data": _recording_plan_to_dict(plan)})
api_openEditRecordingPlan = api_open_edit_recording_plan  # pragma: no cover - compatibility alias


def api_open_delete_recording_plan(request):
    """
    OpenAPI: 删除录像计划

    POST /open/recordingPlan/delete
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or params.get("planCode") or params.get("plan_code") or "").strip()
    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    plan = RecordingPlan.objects.filter(code=code).first()
    if not plan:
        return f_responseJson({"code": 1000, "msg": "success", "data": {"deleted": 0}})

    try:
        plan.delete()
        return f_responseJson({"code": 1000, "msg": "success", "data": {"deleted": 1}})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openDeleteRecordingPlan = api_open_delete_recording_plan  # pragma: no cover - compatibility alias


def api_open_list_recording_plans(request):
    """
    OpenAPI: 查询录像计划

    POST /open/recordingPlan/list
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or params.get("planCode") or params.get("plan_code") or "").strip()

    qs = RecordingPlan.objects.all().order_by("-id")
    if code:
        qs = qs.filter(code=code)

    data = [_recording_plan_to_dict(p) for p in qs]
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openListRecordingPlans = api_open_list_recording_plans  # pragma: no cover - compatibility alias


def _param_first_str(params: dict, *keys: str) -> str:
    """处理参数首个字符串。"""
    for key in keys:
        if key not in params:
            continue
        value = params.get(key)
        s = str(value or "").strip()
        if s:
            return s
    return ""


def _task_plan_target_codes_from_params(params: dict) -> str:
    """从参数获取任务计划`target`编码列表。"""
    value = params.get("target_codes")
    if value is None:
        value = params.get("targetCodes")
    if value is None:
        value = params.get("targets")
    return str(value or "").strip()


def _task_plan_options_json_from_params(params: dict) -> str:
    """从参数获取任务计划`options`JSON。"""
    value = params.get("options_json")
    if value is None:
        value = params.get("optionsJson")
    if value is None:
        value = params.get("options")

    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return ""
    return str(value or "").strip()


def _parse_task_plan_schedule_from_params(params: dict, schedule_type: str):
    """解析任务计划`schedule``from`参数。"""
    if schedule_type == "daily":
        run_time = _parse_time_hhmm(_param_first_str(params, "run_time", "runTime"), 0, 0)
        return run_time, 0

    raw = _param_first_str(params, "interval_seconds", "intervalSeconds")
    try:
        interval_seconds = int(raw or 0)
    except Exception:
        interval_seconds = 0
    if interval_seconds < 1:
        interval_seconds = 60
    return None, interval_seconds


def _create_task_plan_from_params(params: dict):
    """创建任务计划`from`参数。"""
    from app.utils.Security import validate_control_code

    code = _param_first_str(params, "code", "planCode", "plan_code")
    name = str(params.get("name") or "").strip()
    enabled = _parse_boolish(params.get("enabled"), default=True)

    task_type = _normalize_task_type(_param_first_str(params, "task_type", "taskType"))
    schedule_type = _normalize_schedule_type(_param_first_str(params, "schedule_type", "scheduleType"))

    try:
        code = validate_control_code(code)
    except Exception as e:
        return None, str(e)

    if TaskPlan.objects.filter(code=code).exists():
        return None, "task plan code already exists"

    if not task_type:
        task_type = "restart_software"
    if schedule_type not in ("daily", "interval"):
        schedule_type = "daily"

    run_time, interval_seconds = _parse_task_plan_schedule_from_params(params, schedule_type)
    days_mask = _parse_days_mask(params)
    target_codes = _task_plan_target_codes_from_params(params)
    options_json = _task_plan_options_json_from_params(params)

    plan = TaskPlan.objects.create(
        code=code,
        name=name,
        enabled=enabled,
        task_type=task_type,
        schedule_type=schedule_type,
        run_time=run_time,
        days_mask=days_mask,
        interval_seconds=interval_seconds,
        target_codes=target_codes,
        options_json=options_json,
    )
    return plan, ""


def api_open_add_task_plan(request):
    """
    OpenAPI: 添加任务计划

    POST /open/taskPlan/add
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    plan, err = _create_task_plan_from_params(params)
    if not plan:
        return f_responseJson({"code": 0, "msg": err or "invalid params"})
    return f_responseJson({"code": 1000, "msg": "success", "data": _task_plan_to_dict(plan)})
api_openAddTaskPlan = api_open_add_task_plan  # pragma: no cover - compatibility alias


def _param_first_present(params: dict, *keys: str):
    """处理参数首个`present`。"""
    for key in keys:
        if key in params:
            return True, params.get(key)
    return False, None


def _has_any_param_key(params: dict, *keys: str) -> bool:
    """检查`any`参数键。"""
    return any(k in params for k in keys)


def _apply_task_plan_partial_update(plan, params: dict) -> None:
    """处理应用任务计划`partial``update`。"""
    if "name" in params:
        plan.name = str(params.get("name") or "").strip()

    if "enabled" in params:
        plan.enabled = _parse_boolish(params.get("enabled"), default=bool(plan.enabled))

    task_type = _normalize_task_type(_param_first_str(params, "task_type", "taskType"))
    if task_type:
        plan.task_type = task_type

    schedule_type = _normalize_schedule_type(_param_first_str(params, "schedule_type", "scheduleType"))
    if schedule_type in ("daily", "interval"):
        plan.schedule_type = schedule_type

    has_run_time, run_time_value = _param_first_present(params, "run_time", "runTime")
    if has_run_time:
        plan.run_time = _parse_time_hhmm(run_time_value, 0, 0)

    has_interval_seconds, interval_value = _param_first_present(params, "interval_seconds", "intervalSeconds")
    if has_interval_seconds:
        try:
            v = int(interval_value or 0)
        except Exception:
            v = 0
        if v < 0:
            v = 0
        plan.interval_seconds = v

    if _has_any_param_key(params, "daysMask", "days_mask", "daysOfWeek", "days_of_week"):
        plan.days_mask = _parse_days_mask(params)

    if _has_any_param_key(params, "target_codes", "targetCodes", "targets"):
        plan.target_codes = _task_plan_target_codes_from_params(params)

    if _has_any_param_key(params, "options_json", "optionsJson", "options"):
        plan.options_json = _task_plan_options_json_from_params(params)



def api_open_edit_task_plan(request):
    """
    OpenAPI: 编辑任务计划（部分更新）

    POST /open/taskPlan/edit
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = _param_first_str(params, "code", "planCode", "plan_code")
    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    plan = TaskPlan.objects.filter(code=code).first()
    if not plan:
        return f_responseJson({"code": 0, "msg": "task plan not found"})

    _apply_task_plan_partial_update(plan, params)
    plan.save()
    return f_responseJson({"code": 1000, "msg": "success", "data": _task_plan_to_dict(plan)})
api_openEditTaskPlan = api_open_edit_task_plan  # pragma: no cover - compatibility alias


def api_open_delete_task_plan(request):
    """
    OpenAPI: 删除任务计划

    POST /open/taskPlan/delete
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or params.get("planCode") or params.get("plan_code") or "").strip()
    if not code:
        return f_responseJson({"code": 0, "msg": MSG_CODE_REQUIRED})

    plan = TaskPlan.objects.filter(code=code).first()
    if not plan:
        return f_responseJson({"code": 1000, "msg": "success", "data": {"deleted": 0}})

    try:
        plan.delete()
        return f_responseJson({"code": 1000, "msg": "success", "data": {"deleted": 1}})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openDeleteTaskPlan = api_open_delete_task_plan  # pragma: no cover - compatibility alias


def api_open_list_task_plans(request):
    """
    OpenAPI: 查询任务计划

    POST /open/taskPlan/list
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    code = str(params.get("code") or params.get("planCode") or params.get("plan_code") or "").strip()

    qs = TaskPlan.objects.all().order_by("-id")
    if code:
        qs = qs.filter(code=code)

    data = [_task_plan_to_dict(p) for p in qs]
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openListTaskPlans = api_open_list_task_plans  # pragma: no cover - compatibility alias


def _sanitize_stream_code_for_path(value: str) -> str:
    """清洗流编码`for`路径。
    
    Best-effort sanitize stream code used as a folder name under recordings/.
    
        Notes:
        - This is NOT used for DB writes (StreamView handles that).
        - For listing files, we only need to avoid path traversal and bad chars.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    safe_pattern = re.compile(r"[^\w\u4e00-\u9fff\-]", re.UNICODE)
    cleaned = safe_pattern.sub("_", raw)
    # collapse slashes just in case
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    return cleaned


def _recording_storage_root_dir(config) -> str:
    """返回录制存储根目录目录。"""
    raw = getattr(config, "recordingStoragePath", "")
    if not raw:
        return ""
    return str(raw).strip()


def _iter_recording_stream_dirs(root: str, stream_code: str):
    """遍历录制流目录列表。"""
    if stream_code:
        yield stream_code, os.path.join(root, stream_code)
        return

    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        yield str(entry.name), str(entry.path)
                except Exception:
                    continue
    except Exception:
        return


def _iter_recording_file_items(root: str, stream_code: str):
    """遍历录制文件条目。"""
    for sc, stream_dir in _iter_recording_stream_dirs(root, stream_code):
        try:
            with os.scandir(stream_dir) as it:
                for entry in it:
                    try:
                        if not entry.is_file():
                            continue
                        try:
                            st = entry.stat()
                            size_bytes = int(getattr(st, "st_size", 0))
                            mtime = int(getattr(st, "st_mtime", 0))
                        except Exception:
                            size_bytes = 0
                            mtime = 0

                        filename = str(entry.name)
                        yield {
                            "stream_code": sc,
                            "filename": filename,
                            "rel_path": f"recordings/{sc}/{filename}".replace("\\", "/"),
                            "size_bytes": size_bytes,
                            "mtime": mtime,
                        }
                    except Exception:
                        continue
        except Exception:
            continue


def api_open_list_recording_files(request):
    """
    OpenAPI: 查询录像文件列表

    POST /open/recording/file/list
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    stream_code = _sanitize_stream_code_for_path(_first_non_empty_param(params, "stream_code", "streamCode"))
    page = _clamp_int(_first_non_empty_param(params, "page", "p"), default=1, min_value=1, max_value=1_000_000)
    page_size = _clamp_int(_first_non_empty_param(params, "page_size", "pageSize", "ps"), default=50, min_value=1, max_value=200)

    root = _recording_storage_root_dir(g_config)
    if not root or not os.path.isdir(root):
        return f_responseJson({"code": 1000, "msg": "success", "data": [], "total": 0})

    items = list(_iter_recording_file_items(root, stream_code))
    items.sort(key=lambda x: int(x.get("mtime", 0)), reverse=True)

    total = len(items)
    start = (page - 1) * page_size
    data = items[start : start + page_size]

    return f_responseJson({"code": 1000, "msg": "success", "data": data, "total": total})
api_openListRecordingFiles = api_open_list_recording_files  # pragma: no cover - compatibility alias


def api_open_recording_file_play_url(request):
    """
    OpenAPI: 查询录像文件播放地址（基于 FileService）

    POST /open/recording/file/playUrl
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    rel_path = _first_non_empty_param(params, "rel_path", "relPath")
    if not rel_path:
        return f_responseJson({"code": 0, "msg": "rel_path is required"})

    from app.utils.Security import validate_upload_rel_path, resolve_under_base

    try:
        rel = validate_upload_rel_path(rel_path, required_prefix="recordings/")
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    root = _file_service_root_dir(g_config)
    if not root:
        return f_responseJson({"code": 0, "msg": "file service is disabled"})

    try:
        abs_path = resolve_under_base(root, rel)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    if not os.path.isfile(abs_path):
        return f_responseJson({"code": 0, "msg": "recording file not found"})

    try:
        play_url = _file_service_play_url(request, rel)
        return f_responseJson({"code": 1000, "msg": "success", "data": {"rel_path": rel, "play_url": play_url}})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_openRecordingFilePlayUrl = api_open_recording_file_play_url  # pragma: no cover - compatibility alias


def _first_non_empty_param(params: dict, *keys: str) -> str:
    """处理首个非空参数。"""
    for key in keys:
        value = str(params.get(key) or "").strip()
        if value:
            return value
    return ""


def _file_service_root_dir(config) -> str:
    """返回文件`service`根目录目录。"""
    if not bool(getattr(config, "fileServiceEnabled", False)):
        return ""
    return str(getattr(config, "fileServiceRootDir", "") or "").strip()


def _file_service_play_url(request, rel: str) -> str:
    """返回文件`service`播放URL。"""
    from urllib.parse import quote
    from app.views import FileServiceView

    scheme = "https" if bool(getattr(request, "is_secure", lambda: False)()) else "http"
    host = str(getattr(request, "get_host", lambda: "")() or "").strip() or "127.0.0.1"
    path = str(getattr(request, "path", "") or "").strip()
    if path.startswith("/api/app-shell/recording/action/"):
        return FileServiceView.build_recording_session_proxy_url(request, rel)
    return f"{scheme}://{host}/open/fileService/{quote(rel, safe='/')}"


def _storage_root_dir() -> str:
    """返回存储根目录目录。"""
    root = str(getattr(g_config, "storageRootPath", "") or "").strip()
    if root:
        return root
    upload_dir = str(getattr(g_config, "uploadDir", "") or "").strip()
    return upload_dir or "upload"


def _clamp_int(raw_value, *, default: int, min_value: int, max_value: int) -> int:
    """限制整数值。"""
    try:
        value = int(raw_value if raw_value is not None else default)
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


def _normalize_recording_format(raw_value) -> str:
    """执行归一化录制`format`。"""
    fmt = str(raw_value or "mp4").strip().lower() or "mp4"
    return fmt if fmt in ("mp4", "ts", "flv") else "mp4"


def _resolve_stream_url_from_params(params: dict) -> str:
    """解析并返回流URL`from`参数。"""
    return _first_non_empty_param(params, "stream_url", "streamUrl")


def _resolve_stream_code_from_params(params: dict) -> str:
    """解析并返回流编码`from`参数。"""
    return _first_non_empty_param(params, "stream_code", "streamCode")


def _resolve_record_audio_param(params: dict):
    """解析并返回`record`音频参数。"""
    if "record_audio" in params:
        return params.get("record_audio")
    return params.get("recordAudio")


def _resolve_stream_url_if_missing(stream_code: str, stream_url: str) -> str:
    """解析并返回流URL`if``missing`。"""
    if stream_url:
        return stream_url
    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return ""
    return str(getattr(stream, "pull_stream_url", "") or "").strip()


def api_open_start_recording(request):
    """
    OpenAPI: 手动开始录像

    POST /open/recording/startRecording
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    stream_code = _resolve_stream_code_from_params(params)
    stream_url = _resolve_stream_url_from_params(params)
    duration = _clamp_int(params.get("duration", 60), default=60, min_value=0, max_value=3600)
    fmt = _normalize_recording_format(params.get("format", "mp4"))
    record_audio = _parse_boolish(_resolve_record_audio_param(params), default=True)

    if not stream_code:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_REQUIRED})

    stream_url = _resolve_stream_url_if_missing(stream_code, stream_url)

    if not stream_url:
        return f_responseJson({"code": 0, "msg": "stream_url is required"})

    from app.utils.StreamRecording import get_stream_recorder

    recorder = get_stream_recorder(_storage_root_dir())
    result = recorder.start_recording(
        stream_code=stream_code,
        stream_url=stream_url,
        duration=int(duration),
        format=fmt,
        include_audio=bool(record_audio),
    )

    if result.get("success"):
        data = {
            "record_id": result.get("record_id"),
            "save_path": result.get("save_path"),
        }
        return f_responseJson({"code": 1000, "msg": str(result.get("message") or "success"), "data": data})
    return f_responseJson({"code": 0, "msg": str(result.get("message") or "failed")})
api_openStartRecording = api_open_start_recording  # pragma: no cover - compatibility alias


def api_open_stop_recording(request):
    """
    OpenAPI: 手动停止录像

    POST /open/recording/stopRecording
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    stream_code = str(params.get("stream_code") or params.get("streamCode") or "").strip()
    if not stream_code:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_REQUIRED})

    from app.utils.StreamRecording import get_stream_recorder

    recorder = get_stream_recorder(_storage_root_dir())
    result = recorder.stop_recording(stream_code)
    if result.get("success"):
        data = {"save_path": result.get("save_path"), "duration": result.get("duration")}
        return f_responseJson({"code": 1000, "msg": str(result.get("message") or "success"), "data": data})
    return f_responseJson({"code": 0, "msg": str(result.get("message") or "failed")})
api_openStopRecording = api_open_stop_recording  # pragma: no cover - compatibility alias


def api_open_capture_snapshot(request):
    """
    OpenAPI: 手动抓拍截图

    POST /open/recording/captureSnapshot
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    stream_code = str(params.get("stream_code") or params.get("streamCode") or "").strip()
    method = str(params.get("method") or "ffmpeg").strip()
    if method not in ("ffmpeg", "opencv"):
        method = "ffmpeg"

    if not stream_code:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_REQUIRED})

    stream = Stream.objects.filter(code=stream_code).first()
    stream_url = str(getattr(stream, "pull_stream_url", "") or "").strip() if stream else ""
    if not stream_url:
        return f_responseJson({"code": 0, "msg": "stream not found"})

    from app.utils.StreamRecording import get_stream_snapshotter

    snapshotter = get_stream_snapshotter(_storage_root_dir())
    result = snapshotter.capture_snapshot(stream_code=stream_code, stream_url=stream_url, method=method)
    if result.get("success"):
        image_path = str(result.get("image_path") or "").strip()
        image_url = ""
        if image_path:
            base = str(getattr(g_config, "uploadDir_www", DEFAULT_UPLOAD_URL_PREFIX) or DEFAULT_UPLOAD_URL_PREFIX)
            image_url = base.rstrip("/") + "/" + image_path.lstrip("/")
        data = {
            "image_path": image_path,
            "image_url": image_url,
        }
        return f_responseJson({"code": 1000, "msg": str(result.get("message") or "success"), "data": data})
    return f_responseJson({"code": 0, "msg": str(result.get("message") or "failed")})
api_openCaptureSnapshot = api_open_capture_snapshot  # pragma: no cover - compatibility alias


def api_open_face_list(request):
    """
    OpenAPI: 查询人脸库列表（转发到 Analyzer FaceDb）

    POST /open/face/list
    """
    if request.method not in ("POST", "GET"):
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    ok, msg, data = g_analyzer.face_list()
    if not ok:
        return f_responseJson({"code": 0, "msg": str(msg or "face_list failed")})
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openFaceList = api_open_face_list  # pragma: no cover - compatibility alias


def _get_default_face_feature_algorithm_code() -> str:
    """获取默认`face``feature`算法编码。"""
    configured = str(
        get_value(
            "faceDefaultFeatureAlgorithmCode",
            getattr(g_config, "faceDefaultFeatureAlgorithmCode", ""),
        )
        or ""
    ).strip()
    return configured


def _normalize_face_feature_algorithm_code(params: dict, *, require_for_image: bool) -> dict:
    """执行归一化`face``feature`算法编码。"""
    payload = dict(params or {})
    explicit = str(payload.get("featureAlgorithmCode") or payload.get("feature_algorithm_code") or "").strip()
    if explicit:
        payload["featureAlgorithmCode"] = explicit
        return payload

    has_embedding = False
    if isinstance(payload.get("embedding"), list) and payload.get("embedding"):
        has_embedding = True
    if str(payload.get("embedding_base64") or "").strip():
        has_embedding = True

    has_image = bool(str(payload.get("image_base64") or "").strip())
    if not has_image or has_embedding:
        return payload

    default_code = _get_default_face_feature_algorithm_code()
    if default_code:
        payload["featureAlgorithmCode"] = default_code
        return payload

    if require_for_image:
        raise ValueError(
            "featureAlgorithmCode is required for image-based face add/search when no default face feature algorithm is configured"
        )
    return payload


def api_open_face_add(request):
    """
    OpenAPI: 添加/更新人脸（转发到 Analyzer FaceDb）

    POST /open/face/add
    Payload (example):
      { "id": "alice", "name": "Alice", "embedding": [..] }
      or { "id": "alice", "name": "Alice", "image_base64": "...", "featureAlgorithmCode": "on_facenet_cpu" }
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    face_id = str(params.get("id") or params.get("faceId") or "").strip()
    if not face_id:
        return f_responseJson({"code": 0, "msg": "id is required"})
    params["id"] = face_id
    try:
        params = _normalize_face_feature_algorithm_code(params, require_for_image=True)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    ok, msg, data = g_analyzer.face_add(params)
    if not ok:
        return f_responseJson({"code": 0, "msg": str(msg or (data or {}).get("msg") or "face_add failed")})
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openFaceAdd = api_open_face_add  # pragma: no cover - compatibility alias


def api_open_face_delete(request):
    """
    OpenAPI: 删除人脸（转发到 Analyzer FaceDb）

    POST /open/face/delete
    Payload: { "id": "alice" }
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    face_id = str(params.get("id") or params.get("faceId") or "").strip()
    if not face_id:
        return f_responseJson({"code": 0, "msg": "id is required"})

    ok, msg, data = g_analyzer.face_delete({"id": face_id})
    if not ok:
        return f_responseJson({"code": 0, "msg": str(msg or (data or {}).get("msg") or "face_delete failed")})
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openFaceDelete = api_open_face_delete  # pragma: no cover - compatibility alias


def api_open_face_search(request):
    """
    OpenAPI: 根据图片/特征向量查询最相似的人脸（转发到 Analyzer FaceDb）

    POST /open/face/search
    Payload:
      - embedding: [..] or embedding_base64: "..."
      - or image_base64 + featureAlgorithmCode
      - minScore: float (optional)
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parsePostParams(request)
    try:
        params = _normalize_face_feature_algorithm_code(params, require_for_image=True)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    ok, msg, data = g_analyzer.face_search(params)
    if not ok:
        return f_responseJson({"code": 0, "msg": str(msg or (data or {}).get("msg") or "face_search failed")})
    # Analyzer may return code=1001 (not found). For OpenAPI, treat it as a successful query.
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openFaceSearch = api_open_face_search  # pragma: no cover - compatibility alias


def api_open_face_enable(request):
    """
    OpenAPI: 开启人脸搜索（转发到 Analyzer FaceDb）

    POST /open/face/enable
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    ok, msg, data = g_analyzer.face_enable()
    if not ok:
        return f_responseJson({"code": 0, "msg": str(msg or (data or {}).get("msg") or "face_enable failed")})
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openFaceEnable = api_open_face_enable  # pragma: no cover - compatibility alias


def api_open_face_disable(request):
    """
    OpenAPI: 关闭人脸搜索（转发到 Analyzer FaceDb）

    POST /open/face/disable
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    ok, msg, data = g_analyzer.face_disable()
    if not ok:
        return f_responseJson({"code": 0, "msg": str(msg or (data or {}).get("msg") or "face_disable failed")})
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openFaceDisable = api_open_face_disable  # pragma: no cover - compatibility alias

def api_license_info(request):
    """
    查询授权状态与机器码
    """
    ltype = str(getattr(g_config, "licenseType", "community") or "community").strip().lower()
    if ltype in ("machine", "dongle"):
        ok, msg, data = g_analyzer.license_info()
        if not ok:
            return f_responseJson({"code": 0, "msg": str(msg or "license_info failed")})
        info = (data or {}).get("data") or {}
    else:
        info = g_license.check()
    res = {
        "code": 1000,
        "msg": "success",
        "data": info
    }
    return f_responseJson(res)
api_licenseInfo = api_license_info  # pragma: no cover - compatibility alias


def api_alarm_poll(request):
    """处理 `alarmPoll` 接口请求。
    
    GET /api/alarm/poll
    
        Lightweight incremental poll endpoint for the alarm list page.
    
        Query:
          - after_id: int (only count alarms with id > after_id)
          - start/end (datetime-local), control_code, algorithm_code, unread, has_video
    
        Response:
          { code: 1000, msg: "success", data: { new_count, newest_id, sound_url } }
    """
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parseGetParams(request)
    from app.utils.AlarmPoll import build_alarm_poll_summary, parse_after_id

    after_id = parse_after_id(params.get("after_id", 0))

    try:
        data = build_alarm_poll_summary(params, after_id=after_id)
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    res = {
        "code": 1000,
        "msg": "success",
        "data": data,
    }
    return f_responseJson(res)
api_alarmPoll = api_alarm_poll  # pragma: no cover - compatibility alias


def api_cross_camera_search(request):
    """处理 `crossCameraSearch` 接口请求。
    
    GET /alarm/api/crossCameraSearch
    
        Find nearby alarms from other cameras that appear to reference the same object.
    """
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    params = f_parseGetParams(request)
    try:
        alarm_id = int(str(params.get("alarm_id") or params.get("alarmId") or "0").strip())
    except Exception:
        alarm_id = 0
    if alarm_id <= 0:
        return f_responseJson({"code": 0, "msg": "alarm_id is required"})

    reference_alarm = Alarm.objects.filter(id=alarm_id).first()
    if reference_alarm is None:
        return f_responseJson({"code": 0, "msg": "alarm not found"})

    try:
        window_minutes = int(str(params.get("window_minutes") or params.get("windowMinutes") or "30").strip())
    except Exception:
        window_minutes = 30

    try:
        limit = int(str(params.get("limit") or "20").strip())
    except Exception:
        limit = 20

    object_code = str(params.get("object_code") or params.get("objectCode") or "").strip()
    track_id = str(params.get("track_id") or params.get("trackId") or "").strip()

    from app.utils.AlarmPoll import build_cross_camera_timeline, find_cross_camera_matches

    try:
        items = find_cross_camera_matches(
            reference_alarm,
            window_minutes=window_minutes,
            object_code=object_code,
            track_id=track_id,
            limit=limit,
        )
        timeline = build_cross_camera_timeline(
            reference_alarm,
            items,
            object_code=object_code,
            track_id=track_id,
        )
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "alarm_id": int(reference_alarm.id),
                "window_minutes": max(1, min(int(window_minutes or 30), 24 * 60)),
                "items": items,
                "timeline": timeline,
                "total": len(items),
            },
        }
    )
api_crossCameraSearch = api_cross_camera_search  # pragma: no cover - compatibility alias


def _get_latest_license_state(for_update=False):
    """获取`latest`授权状态。"""
    try:
        qs = LicenseState.objects.order_by("-update_time", "-id")
        if for_update and connection.vendor != "sqlite":
            qs = qs.select_for_update()
        return qs.first()
    except Exception:
        return None


def _parse_packages_json(value):
    """解析`packages`JSON。"""
    if not value:
        return []
    try:
        packages = json.loads(value)
        if isinstance(packages, list):
            return [str(p).strip() for p in packages if str(p).strip()]
    except Exception:
        logger.debug("suppressed exception in app/views/api.py:2555", exc_info=True)
    return []

def _parse_package_limits_json(value):
    """解析打包`limits`JSON。"""
    if not value:
        return {}
    try:
        limits = json.loads(value)
        if isinstance(limits, dict):
            out = {}
            for pkg, obj in limits.items():
                pkg_name = str(pkg or "").strip()
                if not pkg_name:
                    continue
                if isinstance(obj, dict):
                    out[pkg_name] = obj
            return out
    except Exception:
        logger.debug("suppressed exception in app/views/api.py:2574", exc_info=True)
    return {}


def _get_license_runtime_policy(state) -> dict:
    """获取授权运行时策略。"""
    if not state:
        return extract_license_runtime_policy_from_json("")
    return extract_license_runtime_policy_from_json(getattr(state, "license_json", "") or "")


def _ordered_active_stream_keys(qs):
    """返回`ordered`活动流键列表。"""
    ordered = []
    seen = set()
    try:
        rows = qs.order_by("create_time", "id").values_list("node_id", "stream_code", "control_code")
    except Exception:
        return ordered

    for node_id, stream_code, control_code in rows:
        node = str(node_id or "").strip()
        stream = _normalize_lease_stream_code(stream_code, control_code)
        if not node or not stream:
            continue
        key = (node, stream)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _get_active_stream_rank(qs, node_id: str, stream_code: str) -> int:
    """获取活动流`rank`。"""
    target = (str(node_id or "").strip(), _normalize_lease_stream_code(stream_code, ""))
    if not target[0] or not target[1]:
        return 0
    for idx, key in enumerate(_ordered_active_stream_keys(qs), start=1):
        if key == target:
            return idx
    return 0


def _build_thread_priority_hint(state, active_qs, *, node_id: str, stream_code: str) -> dict:
    """构建`thread``priority``hint`。"""
    runtime_policy = _get_license_runtime_policy(state)
    policy = runtime_policy.get("thread_priority_policy") if isinstance(runtime_policy, dict) else {}
    if not isinstance(policy, dict):
        policy = {}
    first_n = int(policy.get("first_n_active_streams", 0) or 0)
    rank = _get_active_stream_rank(active_qs, node_id=node_id, stream_code=stream_code)
    enabled = bool(policy.get("enabled")) and first_n > 0 and rank > 0 and rank <= first_n
    return {
        "enabled": bool(enabled),
        "stream_rank": int(rank),
        "first_n_active_streams": int(first_n),
        "nice_value": int(policy.get("nice_value", 0) or 0) if enabled else 0,
    }


def _active_lease_qs(now=None):
    """处理活动`lease``qs`。"""
    now = now or timezone.now()
    return LicenseLease.objects.filter(released_at__isnull=True, expires_at__gt=now)


def _normalize_lease_stream_code(stream_code, control_code=""):
    """执行归一化`lease`流编码。"""
    value = str(stream_code or "").strip()
    if value:
        return value
    return str(control_code or "").strip()


def _distinct_active_stream_keys(qs):
    """返回`distinct`活动流键列表。"""
    try:
        rows = qs.values_list("node_id", "stream_code", "control_code")
    except Exception:
        return set()

    keys = set()
    for node_id, stream_code, control_code in rows:
        node = str(node_id or "").strip()
        stream = _normalize_lease_stream_code(stream_code, control_code)
        if not node or not stream:
            continue
        keys.add((node, stream))
    return keys


def _sanitize_trace_id(value: str, *, max_len: int = 128) -> str:
    """清洗链路追踪ID。"""
    try:
        s = str(value or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    s = s.replace("\r", "").replace("\n", "")
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _safe_getattr(obj, name: str, default=None):
    """处理安全`getattr`。"""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _first_non_empty(values):
    """处理首个非空。"""
    for value in values:
        if value:
            return value
    return ""


def _get_ops_request_meta(request) -> dict:
    """获取运维请求元数据。"""
    meta = _safe_getattr(request, "META", {}) or {}
    if not isinstance(meta, dict):
        return {}
    return meta


def _get_ops_trace_ids(request) -> tuple[str, str]:
    """获取运维链路追踪`ids`。"""
    meta = _get_ops_request_meta(request)

    request_id = _first_non_empty(
        [
            _sanitize_trace_id(_safe_getattr(request, "beacon_request_id", "")),
            _sanitize_trace_id(meta.get("HTTP_X_REQUEST_ID", "")),
            _sanitize_trace_id(meta.get("HTTP_X_BEACON_REQUEST_ID", "")),
        ]
    )
    correlation_id = _first_non_empty(
        [
            _sanitize_trace_id(_safe_getattr(request, "beacon_correlation_id", "")),
            _sanitize_trace_id(meta.get("HTTP_X_CORRELATION_ID", "")),
            _sanitize_trace_id(meta.get("HTTP_X_BEACON_CORRELATION_ID", "")),
        ]
    )
    if not correlation_id:
        correlation_id = request_id
    return request_id, correlation_id


def _get_ops_source_ip(request) -> str:
    """获取运维来源IP。"""
    meta = _get_ops_request_meta(request)
    return str(meta.get("REMOTE_ADDR", "") or "").strip()


def _build_ops_audit_detail_json(detail: Optional[dict], request_id: str, correlation_id: str) -> str:
    """构建运维审计详情JSON。"""
    detail_obj = dict(detail) if isinstance(detail, dict) else {}
    if request_id:
        detail_obj.setdefault("request_id", request_id)
    if correlation_id:
        detail_obj.setdefault("correlation_id", correlation_id)
    if not detail_obj:
        return ""
    try:
        return json.dumps(detail_obj, ensure_ascii=False, default=str)
    except Exception:
        return ""


def _write_ops_audit_log(
    request,
    *,
    event_type: str,
    ok: bool,
    operator: str = "",
    node_id: str = "",
    control_code: str = "",
    algorithm_code: str = "",
    lease_id: str = "",
    error_code: str = "",
    error_message: str = "",
    detail: Optional[dict] = None,
):
    """写入运维审计`log`。"""
    from app.models import OpsAuditLog

    try:
        source_ip = _get_ops_source_ip(request)
        request_id, correlation_id = _get_ops_trace_ids(request)
        detail_json = _build_ops_audit_detail_json(detail, request_id, correlation_id)

        OpsAuditLog.objects.create(
            event_type=str(event_type or "").strip()[:50],
            ok=bool(ok),
            operator=str(operator or "").strip()[:100],
            source_ip=source_ip[:64],
            node_id=str(node_id or "").strip()[:100],
            control_code=str(control_code or "").strip()[:50],
            algorithm_code=str(algorithm_code or "").strip()[:50],
            lease_id=str(lease_id or "").strip()[:64],
            error_code=str(error_code or "").strip()[:50],
            error_message=str(error_message or ""),
            detail_json=detail_json,
        )
    except Exception:
        return


class _LicenseLeaseAcquireError(Exception):
    def __init__(
        self,
        error_code: str,
        msg: str,
        *,
        node_id: str = "",
        control_code: str = "",
        algorithm_code: str = "",
        lease_id: str = "",
        detail: Optional[dict] = None,
    ):
        """处理`init`。"""
        super().__init__(str(msg or ""))
        self.error_code = str(error_code or "").strip()
        self.msg = str(msg or "")
        self.node_id = str(node_id or "").strip()
        self.control_code = str(control_code or "").strip()
        self.algorithm_code = str(algorithm_code or "").strip()
        self.lease_id = str(lease_id or "").strip()
        self.detail = detail


def _license_lease_ttl_seconds(raw_value) -> int:
    """返回授权`lease`TTL秒数。"""
    try:
        ttl_seconds = int(raw_value)
    except Exception:
        ttl_seconds = 120
    return max(30, min(600, ttl_seconds))


def _license_lease_package_max_active_controls(package_limits, package: str) -> int:
    """处理授权`lease`打包最大值活动`controls`。"""
    try:
        obj = package_limits.get(package)
        if isinstance(obj, dict):
            return int(obj.get("max_active_controls", 0) or 0)
    except Exception:
        logger.debug("suppressed exception in app/views/api.py:2826", exc_info=True)
    return 0


def _license_lease_over_quota(limit: int, active_stream_keys, stream_key) -> bool:
    """处理授权`lease``over`配额。"""
    return limit > 0 and stream_key not in active_stream_keys and len(active_stream_keys) >= limit


def _license_lease_raise_error(fields: dict, error_code: str, msg: str, *, lease_id: str = "", detail: Optional[dict] = None):
    """处理授权`lease`抛出错误。"""
    raise _LicenseLeaseAcquireError(
        error_code,
        msg,
        node_id=fields.get("node_id", ""),
        control_code=fields.get("control_code", ""),
        algorithm_code=fields.get("algorithm_code", ""),
        lease_id=lease_id,
        detail=detail,
    )


def _license_lease_acquire_fields(params) -> dict:
    """返回授权`lease``acquire`字段。"""
    fields = {
        "node_id": str(params.get("node_id", "") or "").strip(),
        "stream_code": _normalize_lease_stream_code(params.get("stream_code", ""), params.get("control_code", "")),
        "control_code": str(params.get("control_code", "") or "").strip(),
        "algorithm_code": str(params.get("algorithm_code", "") or "").strip(),
        "ttl_seconds": _license_lease_ttl_seconds(params.get("ttl_seconds", 120)),
    }
    if fields["node_id"] and fields["control_code"] and fields["algorithm_code"]:
        return fields
    _license_lease_raise_error(
        fields,
        "missing_required_fields",
        "missing required fields",
        detail={"ttl_seconds": fields["ttl_seconds"]},
    )


def _license_lease_acquire_fail_response(request, exc: _LicenseLeaseAcquireError):
    """返回授权`lease``acquire`失败响应。"""
    _write_ops_audit_log(
        request,
        event_type=EVENT_LICENSE_LEASE_ACQUIRE,
        ok=False,
        operator="openapi",
        node_id=exc.node_id,
        control_code=exc.control_code,
        algorithm_code=exc.algorithm_code,
        lease_id=exc.lease_id,
        error_code=exc.error_code,
        detail=exc.detail,
    )
    return f_responseJson({"code": 0, "msg": exc.msg})


def _license_lease_thread_priority(state, *, now, node_id: str, stream_code: str):
    """处理授权`lease``thread``priority`。"""
    refreshed_active_qs = _active_lease_qs(now=now)
    return _build_thread_priority_hint(state, refreshed_active_qs, node_id=node_id, stream_code=stream_code)


def _license_lease_acquire_success_response(request, fields: dict, *, lease_id: str, expires_at, state, now, idempotent: bool):
    """返回授权`lease``acquire`成功状态响应。"""
    _write_ops_audit_log(
        request,
        event_type=EVENT_LICENSE_LEASE_ACQUIRE,
        ok=True,
        operator="openapi",
        node_id=fields["node_id"],
        control_code=fields["control_code"],
        algorithm_code=fields["algorithm_code"],
        lease_id=lease_id,
        detail={"ttl_seconds": fields["ttl_seconds"], "idempotent": idempotent, "stream_code": fields["stream_code"]},
    )
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "lease_id": lease_id,
                "expires_at": expires_at,
                "thread_priority": _license_lease_thread_priority(
                    state,
                    now=now,
                    node_id=fields["node_id"],
                    stream_code=fields["stream_code"],
                ),
            },
        }
    )


def _license_lease_state(fields: dict):
    """返回授权`lease`状态。"""
    state = _get_latest_license_state(for_update=True)
    if not state or not bool(state.valid):
        _license_lease_raise_error(fields, "license_invalid", "license_invalid", detail={"ttl_seconds": fields["ttl_seconds"]})

    now = timezone.now()
    if state.not_before and now < state.not_before:
        _license_lease_raise_error(fields, "license_not_active", "license_not_active", detail={"ttl_seconds": fields["ttl_seconds"]})
    if state.not_after and now > state.not_after:
        _license_lease_raise_error(fields, "license_expired", "license_expired", detail={"ttl_seconds": fields["ttl_seconds"]})
    return state, now


def _license_lease_package(fields: dict, state):
    """处理授权`lease`打包。"""
    packages = _parse_packages_json(getattr(state, "packages_json", "") or "")
    package_limits = _parse_package_limits_json(getattr(state, "package_limits_json", "") or "")
    base_code, _device = _split_algorithm_code(fields["algorithm_code"])
    algorithm = AlgorithmModel.objects.filter(code=base_code).first()
    builtin_package = None
    if not algorithm:
        from app.utils.BuiltinAlgorithms import get_builtin_algorithm_license_package

        try:
            builtin_package = get_builtin_algorithm_license_package(base_code)
        except Exception:
            builtin_package = None
        if not builtin_package:
            _license_lease_raise_error(fields, "algorithm_not_found", "algorithm_not_found", detail={"ttl_seconds": fields["ttl_seconds"]})

    package = (
        str(getattr(algorithm, "license_package", "") or "").strip() if algorithm else str(builtin_package or "").strip()
    ) or "core"
    if packages and package not in packages:
        _license_lease_raise_error(
            fields,
            "license_package_denied",
            "license_package_denied",
            detail={"ttl_seconds": fields["ttl_seconds"], "package": package, "builtin": bool(builtin_package) and (algorithm is None)},
        )
    return package, package_limits


def _license_lease_raise_control_quota(fields: dict, *, lease_id: str = "", active_streams: int, stream_change: Optional[bool] = None, idempotent: Optional[bool] = None):
    """处理授权`lease`抛出控制配额。"""
    detail = {"ttl_seconds": fields["ttl_seconds"], "stream_code": fields["stream_code"], "active_streams": active_streams}
    if stream_change is not None:
        detail["stream_change"] = bool(stream_change)
    if idempotent is not None:
        detail["idempotent"] = bool(idempotent)
    _license_lease_raise_error(fields, "license_over_quota_controls", "license_over_quota_controls", lease_id=lease_id, detail=detail)


def _license_lease_raise_nodes_quota(fields: dict):
    """处理授权`lease`抛出`nodes`配额。"""
    _license_lease_raise_error(
        fields,
        "license_over_quota_nodes",
        "license_over_quota_nodes",
        detail={"ttl_seconds": fields["ttl_seconds"]},
    )


def _license_lease_raise_package_quota(
    fields: dict,
    *,
    package: str,
    package_limit: int,
    active_in_package: int,
    lease_id: str = "",
    package_change: Optional[bool] = None,
    idempotent: Optional[bool] = None,
):
    """处理授权`lease`抛出打包配额。"""
    detail = {
        "ttl_seconds": fields["ttl_seconds"],
        "package": package,
        "max_active_controls": package_limit,
        "active_in_package": active_in_package,
        "stream_code": fields["stream_code"],
    }
    if package_change is not None:
        detail["package_change"] = bool(package_change)
    if idempotent is not None:
        detail["idempotent"] = bool(idempotent)
    _license_lease_raise_error(fields, "license_over_quota_package", "license_over_quota_package", lease_id=lease_id, detail=detail)


def _license_lease_update_existing(existing, *, fields: dict, package: str, package_limits, max_active_controls: int, now):
    """处理授权`lease``update`现有。"""
    old_package = str(getattr(existing, "package", "") or "core").strip() or "core"
    old_stream_code = _normalize_lease_stream_code(getattr(existing, "stream_code", ""), getattr(existing, "control_code", ""))
    old_stream_key = (str(getattr(existing, "node_id", "") or "").strip(), old_stream_code)
    new_stream_key = (fields["node_id"], fields["stream_code"])
    other_active_qs = _active_lease_qs(now=now).exclude(lease_id=existing.lease_id)
    other_stream_keys = _distinct_active_stream_keys(other_active_qs)
    if _license_lease_over_quota(max_active_controls, other_stream_keys, new_stream_key):
        _license_lease_raise_control_quota(
            fields,
            lease_id=existing.lease_id,
            active_streams=len(other_stream_keys),
            stream_change=old_stream_key != new_stream_key,
            idempotent=True,
        )

    package_limit = _license_lease_package_max_active_controls(package_limits, package)
    active_pkg_keys = _distinct_active_stream_keys(other_active_qs.filter(package=package)) if package_limit > 0 else set()
    if _license_lease_over_quota(package_limit, active_pkg_keys, new_stream_key):
        _license_lease_raise_package_quota(
            fields,
            package=package,
            package_limit=package_limit,
            active_in_package=len(active_pkg_keys),
            lease_id=existing.lease_id,
            package_change=old_package != package,
            idempotent=True,
        )

    existing.algorithm_code = fields["algorithm_code"]
    existing.package = package
    existing.stream_code = fields["stream_code"]
    if old_stream_key != new_stream_key:
        existing.create_time = now
    existing.expires_at = now + timedelta(seconds=fields["ttl_seconds"])
    existing.save()
    return existing.lease_id, existing.expires_at


def _license_lease_create_new(*, fields: dict, package: str, package_limits, max_active_controls: int, max_nodes: int, now):
    """处理授权`lease``create``new`。"""
    active_qs = _active_lease_qs(now=now)
    active_stream_keys = _distinct_active_stream_keys(active_qs)
    stream_key = (fields["node_id"], fields["stream_code"])
    if _license_lease_over_quota(max_active_controls, active_stream_keys, stream_key):
        _license_lease_raise_control_quota(fields, active_streams=len(active_stream_keys))

    node_already_active = active_qs.filter(node_id=fields["node_id"]).exists()
    active_nodes = active_qs.values("node_id").distinct().count()
    if max_nodes > 0 and (not node_already_active) and active_nodes >= max_nodes:
        _license_lease_raise_nodes_quota(fields)

    package_limit = _license_lease_package_max_active_controls(package_limits, package)
    active_pkg_keys = _distinct_active_stream_keys(active_qs.filter(package=package)) if package_limit > 0 else set()
    if _license_lease_over_quota(package_limit, active_pkg_keys, stream_key):
        _license_lease_raise_package_quota(
            fields,
            package=package,
            package_limit=package_limit,
            active_in_package=len(active_pkg_keys),
        )

    lease = LicenseLease.objects.create(
        lease_id=uuid.uuid4().hex,
        node_id=fields["node_id"],
        stream_code=fields["stream_code"],
        control_code=fields["control_code"],
        algorithm_code=fields["algorithm_code"],
        package=package,
        expires_at=now + timedelta(seconds=fields["ttl_seconds"]),
    )
    return lease.lease_id, lease.expires_at


def api_license_lease_acquire(request):
    """
    申请租约（占用 1 路 Control）
    POST /open/license/lease/acquire
    body: {node_id, control_code, algorithm_code, ttl_seconds?}
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
    except Exception:
        _write_ops_audit_log(
            request,
            event_type=EVENT_LICENSE_LEASE_ACQUIRE,
            ok=False,
            operator="openapi",
            error_code="invalid_request_parameter",
        )
        return f_responseJson({"code": 0, "msg": MSG_INVALID_REQUEST_PARAMETER})

    try:
        fields = _license_lease_acquire_fields(params)
        with transaction.atomic():
            state, now = _license_lease_state(fields)
            max_active_controls = int(getattr(state, "max_active_controls", 0) or 0)
            max_nodes = int(getattr(state, "max_nodes", 0) or 0)
            package, package_limits = _license_lease_package(fields, state)
            LicenseLease.objects.filter(released_at__isnull=True, expires_at__lte=now).delete()
            existing = _active_lease_qs(now=now).filter(node_id=fields["node_id"], control_code=fields["control_code"]).first()
            if existing:
                lease_id, expires_at = _license_lease_update_existing(
                    existing,
                    fields=fields,
                    package=package,
                    package_limits=package_limits,
                    max_active_controls=max_active_controls,
                    now=now,
                )
                return _license_lease_acquire_success_response(
                    request,
                    fields,
                    lease_id=lease_id,
                    expires_at=expires_at,
                    state=state,
                    now=now,
                    idempotent=True,
                )

            lease_id, expires_at = _license_lease_create_new(
                fields=fields,
                package=package,
                package_limits=package_limits,
                max_active_controls=max_active_controls,
                max_nodes=max_nodes,
                now=now,
            )
    except _LicenseLeaseAcquireError as exc:
        return _license_lease_acquire_fail_response(request, exc)

    return _license_lease_acquire_success_response(
        request,
        fields,
        lease_id=lease_id,
        expires_at=expires_at,
        state=state,
        now=now,
        idempotent=False,
    )
api_licenseLeaseAcquire = api_license_lease_acquire  # pragma: no cover - compatibility alias


def _license_lease_renew_fail(
    request,
    *,
    lease=None,
    lease_id: str = "",
    error_code: str,
    msg: str,
    detail: Optional[dict] = None,
):
    """处理授权`lease``renew`失败。"""
    node_id = str(getattr(lease, "node_id", "") or "") if lease else ""
    control_code = str(getattr(lease, "control_code", "") or "") if lease else ""
    algorithm_code = str(getattr(lease, "algorithm_code", "") or "") if lease else ""
    _write_ops_audit_log(
        request,
        event_type=EVENT_LICENSE_LEASE_RENEW,
        ok=False,
        operator="openapi",
        node_id=node_id,
        control_code=control_code,
        algorithm_code=algorithm_code,
        lease_id=lease_id,
        error_code=error_code,
        detail=detail,
    )
    return f_responseJson({"code": 0, "msg": msg})


def _license_lease_renew_parse_params(request):
    """处理授权`lease``renew``parse`参数。"""
    try:
        params = f_parsePostParams(request)
    except Exception:
        return "", 0, _license_lease_renew_fail(
            request,
            error_code="invalid_request_parameter",
            msg=MSG_INVALID_REQUEST_PARAMETER,
        )

    lease_id = str(params.get("lease_id", "") or "").strip()
    ttl_seconds = _clamp_int(params.get("ttl_seconds", 120), default=120, min_value=30, max_value=600)
    if not lease_id:
        return "", ttl_seconds, _license_lease_renew_fail(
            request,
            error_code="missing_lease_id",
            msg="missing lease_id",
        )

    return lease_id, ttl_seconds, None


def _license_lease_renew_get_lease(request, *, lease_id: str, ttl_seconds: int, now):
    """处理授权`lease``renew``get``lease`。"""
    lease = LicenseLease.objects.filter(lease_id=lease_id, released_at__isnull=True).first()
    if not lease:
        return None, _license_lease_renew_fail(
            request,
            lease_id=lease_id,
            error_code="lease_not_found",
            msg="lease_not_found",
            detail={"ttl_seconds": ttl_seconds},
        )
    if lease.expires_at and lease.expires_at <= now:
        return None, _license_lease_renew_fail(
            request,
            lease=lease,
            lease_id=lease_id,
            error_code="lease_expired",
            msg="lease_expired",
            detail={"ttl_seconds": ttl_seconds},
        )
    return lease, None


def _license_lease_renew_get_valid_state(request, *, lease, lease_id: str, ttl_seconds: int, now):
    """返回授权`lease``renew``get``valid`状态。"""
    state = _get_latest_license_state()
    if not state or not bool(state.valid):
        return None, _license_lease_renew_fail(
            request,
            lease=lease,
            lease_id=lease_id,
            error_code="license_invalid",
            msg="license_invalid",
            detail={"ttl_seconds": ttl_seconds},
        )
    if state.not_before and now < state.not_before:
        return None, _license_lease_renew_fail(
            request,
            lease=lease,
            lease_id=lease_id,
            error_code="license_not_active",
            msg="license_not_active",
            detail={"ttl_seconds": ttl_seconds},
        )
    if state.not_after and now > state.not_after:
        return None, _license_lease_renew_fail(
            request,
            lease=lease,
            lease_id=lease_id,
            error_code="license_expired",
            msg="license_expired",
            detail={"ttl_seconds": ttl_seconds},
        )
    return state, None


def _license_lease_renew_check_package(request, *, lease, lease_id: str, ttl_seconds: int, state):
    """处理授权`lease``renew``check`打包。"""
    packages = _parse_packages_json(getattr(state, "packages_json", "") or "")
    if not packages:
        return None

    lease_package = str(getattr(lease, "package", "") or "core").strip() or "core"
    if lease_package in packages:
        return None

    return _license_lease_renew_fail(
        request,
        lease=lease,
        lease_id=lease_id,
        error_code="license_package_denied",
        msg="license_package_denied",
        detail={"ttl_seconds": ttl_seconds, "package": lease_package},
    )


def api_license_lease_renew(request):
    """
    续租
    POST /open/license/lease/renew
    body: {lease_id, ttl_seconds?}
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    lease_id, ttl_seconds, error = _license_lease_renew_parse_params(request)
    if error:
        return error

    now = timezone.now()
    lease, error = _license_lease_renew_get_lease(request, lease_id=lease_id, ttl_seconds=ttl_seconds, now=now)
    if error:
        return error

    state, error = _license_lease_renew_get_valid_state(request, lease=lease, lease_id=lease_id, ttl_seconds=ttl_seconds, now=now)
    if error:
        return error

    error = _license_lease_renew_check_package(request, lease=lease, lease_id=lease_id, ttl_seconds=ttl_seconds, state=state)
    if error:
        return error

    lease.expires_at = now + timedelta(seconds=ttl_seconds)
    lease.save()
    refreshed_active_qs = _active_lease_qs(now=now)
    thread_priority = _build_thread_priority_hint(
        state,
        refreshed_active_qs,
        node_id=str(getattr(lease, "node_id", "") or "").strip(),
        stream_code=_normalize_lease_stream_code(getattr(lease, "stream_code", ""), getattr(lease, "control_code", "")),
    )
    _write_ops_audit_log(
        request,
        event_type=EVENT_LICENSE_LEASE_RENEW,
        ok=True,
        operator="openapi",
        node_id=getattr(lease, "node_id", "") or "",
        control_code=getattr(lease, "control_code", "") or "",
        algorithm_code=getattr(lease, "algorithm_code", "") or "",
        lease_id=lease_id,
        detail={"ttl_seconds": ttl_seconds},
    )
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "expires_at": lease.expires_at,
                "thread_priority": thread_priority,
            },
        }
    )
api_licenseLeaseRenew = api_license_lease_renew  # pragma: no cover - compatibility alias


def api_license_lease_release(request):
    """
    释放租约
    POST /open/license/lease/release
    body: {lease_id}
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
    except Exception:
        _write_ops_audit_log(request, event_type=EVENT_LICENSE_LEASE_RELEASE, ok=False, operator="openapi", error_code="invalid_request_parameter")
        return f_responseJson({"code": 0, "msg": MSG_INVALID_REQUEST_PARAMETER})

    lease_id = str(params.get("lease_id", "") or "").strip()
    if not lease_id:
        _write_ops_audit_log(request, event_type=EVENT_LICENSE_LEASE_RELEASE, ok=False, operator="openapi", error_code="missing_lease_id")
        return f_responseJson({"code": 0, "msg": "missing lease_id"})

    now = timezone.now()
    lease = LicenseLease.objects.filter(lease_id=lease_id, released_at__isnull=True).first()
    if not lease:
        # idempotent: releasing an already-released lease is ok
        _write_ops_audit_log(request, event_type=EVENT_LICENSE_LEASE_RELEASE, ok=True, operator="openapi", lease_id=lease_id, detail={"idempotent": True})
        return f_responseJson({"code": 1000, "msg": "success"})

    lease.released_at = now
    lease.save()
    _write_ops_audit_log(
        request,
        event_type=EVENT_LICENSE_LEASE_RELEASE,
        ok=True,
        operator="openapi",
        node_id=getattr(lease, "node_id", "") or "",
        control_code=getattr(lease, "control_code", "") or "",
        algorithm_code=getattr(lease, "algorithm_code", "") or "",
        lease_id=lease_id,
        detail={"idempotent": False},
    )
    return f_responseJson({"code": 1000, "msg": "success"})
api_licenseLeaseRelease = api_license_lease_release  # pragma: no cover - compatibility alias


def _get_license_package_usage(active_qs):
    """获取授权打包`usage`。"""
    try:
        packages_in_use = [
            str(p or "core").strip() or "core" for p in active_qs.values_list("package", flat=True).distinct()
        ]
        usage = {}
        for pkg in packages_in_use:
            usage[pkg] = len(_distinct_active_stream_keys(active_qs.filter(package=pkg)))
        return usage
    except Exception:
        return {}


def _dict_or_empty(value):
    """Return a dict value or an empty dict."""
    return value if isinstance(value, dict) else {}


def _build_local_license_usage_payload(info: dict):
    """构建`local`授权`usage`载荷。"""
    info = _dict_or_empty(info)
    extra = _dict_or_empty(info.get("extra"))
    usage = _dict_or_empty(extra.get("usage"))
    limits = _dict_or_empty(extra.get("limits"))
    thread_priority_policy = _dict_or_empty(extra.get("thread_priority_policy"))
    package_usage = _dict_or_empty(extra.get("package_usage"))

    return {
        "license_id": str(extra.get("license_id", "") or ""),
        "customer": str(extra.get("customer", "") or ""),
        "cluster_id": str(extra.get("cluster_id", "") or ""),
        "valid": bool(info.get("ok")),
        "not_after": extra.get("not_after"),
        "limits": {
            "max_active_controls": int(limits.get("max_active_controls", 0) or 0),
            "max_nodes": int(limits.get("max_nodes", 0) or 0),
        },
        "packages": [],
        "package_limits": {},
        "package_usage": package_usage,
        "active_controls": int(usage.get("active_controls", 0) or 0),
        "active_streams": int(usage.get("active_streams", 0) or 0),
        "active_nodes": int(usage.get("active_nodes", 0) or 0),
        "edition": str(extra.get("edition", "") or ""),
        "thread_priority_policy": thread_priority_policy,
        "type": str(info.get("type", "") or ""),
        "machine_code": str(info.get("machine_code", "") or ""),
    }


def _local_license_info_payload() -> dict:
    """Return local license info from Analyzer with local fallback."""
    try:
        ok, _, data = g_analyzer.license_info(
            timeout_seconds=2,
            cache_ttl_seconds=_index_analyzer_cache_ttl_seconds(),
        )
        if ok:
            return (data or {}).get("data") or {}
        return g_license.check() or {}
    except Exception:
        try:
            return g_license.check() or {}
        except Exception:
            return {}


def _local_license_usage_response():
    """Return the license usage response for local machine/dongle license modes."""
    ltype = str(getattr(g_config, "licenseType", "community") or "community").strip().lower()
    if ltype not in ("community", "machine", "dongle"):
        return f_responseJson({"code": 0, "msg": "license_not_installed", "data": {}})
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": _build_local_license_usage_payload(_local_license_info_payload()),
        }
    )


def _license_state_validity(state, now) -> bool:
    """Return whether a license state is currently valid."""
    not_started = bool(state.not_before and now < state.not_before)
    expired = bool(state.not_after and now > state.not_after)
    return bool(state.valid) and (not not_started) and (not expired)


def _license_usage_data_for_state(state, active_qs, now) -> dict:
    """Build usage payload data for an installed license state."""
    packages = _parse_packages_json(getattr(state, "packages_json", "") or "")
    package_limits = _parse_package_limits_json(getattr(state, "package_limits_json", "") or "")
    package_usage = _get_license_package_usage(active_qs)
    active_streams = len(_distinct_active_stream_keys(active_qs))
    runtime_policy = _get_license_runtime_policy(state)

    return {
        "license_id": getattr(state, "license_id", "") or "",
        "customer": getattr(state, "customer", "") or "",
        "cluster_id": getattr(state, "cluster_id", "") or "",
        "valid": _license_state_validity(state, now),
        "not_after": state.not_after,
        "limits": {
            "max_active_controls": int(getattr(state, "max_active_controls", 0) or 0),
            "max_nodes": int(getattr(state, "max_nodes", 0) or 0),
        },
        "packages": packages,
        "package_limits": package_limits,
        "edition": str(runtime_policy.get("edition", "") or ""),
        "thread_priority_policy": runtime_policy.get("thread_priority_policy") if isinstance(runtime_policy, dict) else {},
        "package_usage": package_usage,
        "active_controls": active_qs.count(),
        "active_streams": active_streams,
        "active_nodes": active_qs.values("node_id").distinct().count(),
    }


def api_license_usage(request):
    """
    查询授权使用量（运维观测）
    GET /open/license/usage
    """
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    state = _get_latest_license_state()
    if not state:
        return _local_license_usage_response()

    now = timezone.now()
    active_qs = _active_lease_qs(now=now)
    data = _license_usage_data_for_state(state, active_qs, now)
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_licenseUsage = api_license_usage  # pragma: no cover - compatibility alias
def api_get_all_stream_data(request):
    """处理 `getAllStreamData` 接口请求。"""
    data = g_djangoSql.select("select code,nickname from av_stream order by id desc")
    res = {
        "code": 1000,
        "msg": "success",
        "data": data
    }
    return f_responseJson(res)
api_getAllStreamData = api_get_all_stream_data  # pragma: no cover - compatibility alias

def api_get_all_algroithm_flow_data(request):
    """处理 `getAllAlgroithmFlowData` 接口请求。"""
    data = g_djangoSql.select("select code,name from av_algorithm order by id desc")

    res = {
        "code": 1000,
        "msg": "success",
        "data": data
    }
    return f_responseJson(res)
api_getAllAlgroithmFlowData = api_get_all_algroithm_flow_data  # pragma: no cover - compatibility alias
def _core_process_host(raw_host) -> str:
    """处理核心进程主机。"""
    host = str(raw_host or "").strip()
    if not host:
        return ""
    if urlsplit(host).scheme not in ("http", "https"):
        host = urlunsplit((DEFAULT_CORE_PROCESS_SCHEME, host, "", "", ""))
    return host


def _core_process_hosts():
    """处理核心进程`hosts`。"""
    raw_hosts = str(os.environ.get("BEACON_ANALYZER_HOSTS") or "").strip()
    hosts = [_core_process_host(part) for part in raw_hosts.split(",")] if raw_hosts else []
    hosts = [host for host in hosts if host]
    if hosts:
        return hosts
    return [
        _core_process_host(getattr(g_config, "analyzerHost", ""))
        or urlunsplit((DEFAULT_CORE_PROCESS_SCHEME, DEFAULT_CORE_PROCESS_NETLOC, "", "", ""))
    ]


def _core_process_analyzer_class():
    """处理核心进程分析器`class`。"""
    from app.utils.Analyzer import Analyzer

    return Analyzer


def _core_process_analyzer(host, analyzer_class):
    """处理核心进程分析器。"""
    if str(getattr(g_analyzer, "analyzer_host", "") or "") == host:
        return g_analyzer
    if analyzer_class is None:
        return None
    return analyzer_class(host, openApiToken=str(getattr(g_config, "openApiToken", "") or ""))


def _core_process_probe(analyzer, *, cache_ttl_seconds=0):
    """处理核心进程探测。"""
    if analyzer is None:
        return False, False, {}, {}, "Analyzer client not available"

    ok_resource = False
    ok_sched = False
    resource = {}
    sched = {}
    err = ""
    try:
        ok_resource, _m, resource = analyzer.resource_info(timeout_seconds=2, cache_ttl_seconds=cache_ttl_seconds)
    except Exception as e:
        err = str(e)
    try:
        ok_sched, _m, sched = analyzer.scheduler_info(timeout_seconds=2, cache_ttl_seconds=cache_ttl_seconds)
    except Exception as e:
        if not err:
            err = str(e)
    return ok_resource, ok_sched, resource if ok_resource else {}, sched if ok_sched else {}, err or "success"


def _core_process_entry(idx: int, host: str, analyzer_class, *, cache_ttl_seconds=0):
    """处理核心进程条目。"""
    ok_resource, ok_sched, resource, sched, msg = _core_process_probe(
        _core_process_analyzer(host, analyzer_class),
        cache_ttl_seconds=cache_ttl_seconds,
    )
    return {
        "process_index": int(idx),
        "analyzer_host": host,
        "ok": bool(ok_resource and ok_sched),
        "resource": resource,
        "scheduler": sched,
        "msg": msg,
    }


def _core_process_response(*, ret: bool, msg: str, data=None, info=None):
    """返回核心进程响应。"""
    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "data": data or [],
        "info": info or {},
    }
    logger.debug("api_getAllCoreProcessData() res=%s", safe_json_dumps(res, max_len=1024))
    return f_responseJson(res)


def api_get_all_core_process_data(request):
    """处理 `getAllCoreProcessData` 接口请求。"""
    if request.method != "GET":
        return _core_process_response(ret=False, msg=MSG_METHOD_NOT_SUPPORTED)

    logger.debug("api_getAllCoreProcessData()")
    hosts = _core_process_hosts()
    analyzer_class = _core_process_analyzer_class()
    data = [_core_process_entry(idx, host, analyzer_class) for idx, host in enumerate(hosts)]
    info = {
        "processNum": int(len(hosts)),
        "processMode": 1 if len(hosts) > 1 else 0,
    }
    return _core_process_response(ret=True, msg="success", data=data, info=info)
api_getAllCoreProcessData = api_get_all_core_process_data  # pragma: no cover - compatibility alias

def api_get_all_core_process_data2(request):
    """处理 `getAllCoreProcessData2` 接口请求。"""
    ret = False
    msg = MSG_METHOD_NOT_SUPPORTED
    info = {}

    if request.method == "GET":

        logger.debug("api_getAllCoreProcessData2()")
        stream_set = set()  # 数据库中所有布控code的set
        control_count = 0
        at_db_controls = g_djangoSql.select("select code,stream_app,stream_name from av_control where state=1")
        for at_db_control in at_db_controls:
            app_name = "%s_%s" % (at_db_control["stream_app"], at_db_control["stream_name"])
            stream_set.add(app_name)
            control_count += 1

        raw_hosts = str(os.environ.get("BEACON_ANALYZER_HOSTS") or "").strip()
        hosts = []
        if raw_hosts:
            hosts = [h.strip() for h in raw_hosts.split(",") if h and str(h).strip()]
        info["processNum"] = int(len(hosts) if hosts else 1)
        info["processMode"] = 1 if info["processNum"] > 1 else 0
        info["controlCount"] = control_count
        info["streamCount"] = len(stream_set)

        ret = True
        msg = "success"

    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "info": info
    }
    logger.debug("api_getAllCoreProcessData2() res=%s", safe_json_dumps(res, max_len=1024))

    return f_responseJson(res)
api_getAllCoreProcessData2 = api_get_all_core_process_data2  # pragma: no cover - compatibility alias


def _upload_alarm_get_str(params: dict, field_name: str) -> str:
    """执行上传告警`get`字符串。"""
    value = params.get(field_name) or ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value.strip()


def _upload_alarm_validate_control_code(control_code: str) -> str:
    """执行上传告警`validate`控制编码。"""
    from app.utils.Security import validate_control_code

    try:
        return validate_control_code(control_code)
    except Exception as e:
        raise ValueError(str(e))


def _upload_alarm_validate_existing_rel_path(rel_path: str) -> str:
    """执行上传告警`validate`现有相对路径路径。"""
    from app.utils.Security import validate_upload_rel_path, resolve_under_base

    try:
        rel_path = validate_upload_rel_path(rel_path, required_prefix=ALARM_UPLOAD_PREFIX)
        resolve_under_base(g_config.uploadDir, rel_path)
        return rel_path
    except Exception as e:
        raise ValueError(str(e))


def _upload_alarm_validate_str_len(field_name: str, value, *, max_len: int) -> str:
    """执行上传告警`validate`字符串`len`。"""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if len(value) > int(max_len):
        raise ValueError(f"{field_name} too long")
    return value


def _upload_alarm_parse_region_index(raw_value) -> int:
    # Optional; 0-based; -1 means unknown/not applicable.
    """执行上传告警`parse`区域索引。"""
    if raw_value is None or raw_value == "":
        return -1
    try:
        idx = int(raw_value)
    except Exception:
        raise ValueError("region_index must be an integer")
    if idx < -1:
        raise ValueError("region_index must be >= -1")
    if idx > 100000:
        raise ValueError("region_index too large")
    return idx


def _upload_alarm_parse_optional_float(field_name: str, value):
    """执行上传告警`parse`可选浮点数。"""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except Exception:
        raise ValueError(f"{field_name} must be a number")
    if f < 0.0 or f > 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return f


def _upload_alarm_parse_optional_int(field_name: str, value):
    """执行上传告警`parse`可选整数值。"""
    if value is None or value == "":
        return None
    try:
        i = int(value)
    except Exception:
        raise ValueError(f"{field_name} must be an integer")
    if i < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return i


def _upload_alarm_parse_metadata(value):
    """执行上传告警`parse`元数据。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            obj = json.loads(text)
        except Exception:
            raise ValueError("metadata must be valid JSON")
        if not isinstance(obj, dict):
            raise ValueError("metadata must be a JSON object")
        return obj
    raise ValueError("metadata must be a JSON object or string")


def _upload_alarm_parse_extra_images(value):
    """执行上传告警`parse`额外`images`。"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            obj = json.loads(text)
        except Exception:
            raise ValueError("extra_images must be valid JSON")
        if not isinstance(obj, list):
            raise ValueError("extra_images must be a JSON array")
        return obj
    raise ValueError("extra_images must be a JSON array or string")


def _upload_alarm_clean_extra_images(extra_images_list):
    """执行上传告警清理额外`images`。"""
    from app.utils.Security import validate_upload_rel_path, resolve_under_base

    if extra_images_list is None:
        return None
    cleaned = []
    for idx, item in enumerate(extra_images_list):
        if item is None:
            continue
        if not isinstance(item, str):
            raise ValueError(f"extra_images[{idx}] must be a string")
        p = item.strip()
        if not p:
            continue
        try:
            p = validate_upload_rel_path(p, required_prefix=ALARM_UPLOAD_PREFIX)
            resolve_under_base(g_config.uploadDir, p)
        except Exception as e:
            raise ValueError(str(e))
        cleaned.append(p)
    return cleaned


def _upload_alarm_save_uploaded_file(*, file_obj, control_code: str, prefix: str, default_ext: str, allowed_exts) -> str:
    """执行上传告警`save``uploaded`文件。"""
    from app.utils.Security import validate_upload_rel_path, resolve_under_base

    if not file_obj:
        return ""
    filename = str(getattr(file_obj, "name", "") or "")
    ext = ""
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].strip().lower()
    ext = (ext or str(default_ext or "")).strip(".").lower()
    if ext not in allowed_exts:
        raise ValueError(f"{prefix}_file extension not allowed: {ext}")

    day = datetime.now().strftime("%Y%m%d")
    filename = f"{prefix}_{int(time.time()*1000)}.{ext}"
    rel_path = f"alarm/{control_code}/{day}/{filename}"
    rel_path = validate_upload_rel_path(rel_path, required_prefix=ALARM_UPLOAD_PREFIX)
    abs_path = resolve_under_base(g_config.uploadDir, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    with open(abs_path, "wb") as f:
        try:
            for chunk in file_obj.chunks():
                f.write(chunk)
        except Exception:
            # fallback for non-standard file objects
            f.write(file_obj.read())
    return rel_path


def _upload_alarm_save_base64(*, b64_str: str, control_code: str, prefix: str, ext: str) -> str:
    """执行上传告警`save`Base64。"""
    from app.utils.Security import validate_upload_rel_path, resolve_under_base

    if not b64_str:
        return ""
    try:
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        data_bytes = base64.b64decode(b64_str)
        day = datetime.now().strftime("%Y%m%d")
        filename = f"{prefix}_{int(time.time()*1000)}.{ext}"
        rel_path = f"alarm/{control_code}/{day}/{filename}"
        rel_path = validate_upload_rel_path(rel_path, required_prefix=ALARM_UPLOAD_PREFIX)
        abs_path = resolve_under_base(g_config.uploadDir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(data_bytes)
        return rel_path
    except Exception as e:
        # Industrial default policy: prechecks/auxiliary storage should not block the main alarm pipeline.
        logger.warning("api_uploadAlarm save_base64 error: %s", e)
        return ""


def _upload_alarm_resolve_image_abs_path_best_effort(values: dict, resolve_under_base) -> str:
    """尽力执行上传告警`resolve`图片绝对路径路径。"""
    image_rel = str(values.get("image_path") or "").strip()
    if not image_rel:
        return ""
    try:
        return str(resolve_under_base(g_config.uploadDir, image_rel))
    except Exception:
        return ""


def _upload_alarm_run_precheck_best_effort(values: dict):
    # v4.725: optional LLM precheck (fail-open)
    """尽力执行上传告警`run`预检。"""
    from app.utils.AlarmPrecheck import should_store_alarm
    from app.utils.Security import resolve_under_base

    try:
        image_abs_path = _upload_alarm_resolve_image_abs_path_best_effort(values, resolve_under_base)
        allow_store, precheck_reason = should_store_alarm(
            g_config,
            control_code=values.get("control_code", ""),
            desc=values.get("desc", ""),
            alarm_type=values.get("alarm_type", ""),
            alarm_level=values.get("alarm_level", 1),
            algorithm_code=values.get("algorithm_code", ""),
            object_code=values.get("object_code", ""),
            recognition_region=values.get("recognition_region", ""),
            stream_code=values.get("stream_code", ""),
            stream_app=values.get("stream_app", ""),
            stream_name=values.get("stream_name", ""),
            stream_url=values.get("stream_url", ""),
            image_path=values.get("image_path", ""),
            image_abs_path=image_abs_path,
            image_base64=values.get("image_base64", ""),
            metadata=values.get("metadata_obj") or {},
        )
        return bool(allow_store), precheck_reason
    except Exception:
        return None


def _upload_alarm_remove_relpath_best_effort(rel_path: str) -> None:
    """尽力执行上传告警`remove``relpath`。"""
    if not rel_path:
        return
    from app.utils.Security import resolve_under_base

    try:
        abs_path = resolve_under_base(g_config.uploadDir, rel_path)
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception:
        return


def _upload_alarm_cleanup_created_files_best_effort(request, values: dict) -> None:
    # best-effort cleanup only when we created local files from request data
    """尽力执行上传告警清理`created``files`。"""
    created_image = bool(values.get("image_base64")) or (hasattr(request, "FILES") and request.FILES.get("image_file"))
    created_video = bool(values.get("video_base64")) or (hasattr(request, "FILES") and request.FILES.get("video_file"))
    if created_image:
        _upload_alarm_remove_relpath_best_effort(str(values.get("image_path") or "").strip())
    if created_video:
        _upload_alarm_remove_relpath_best_effort(str(values.get("video_path") or "").strip())


def _upload_alarm_precheck_or_filtered_response(request, values: dict):
    """执行上传告警预检`or``filtered`响应。"""
    precheck = _upload_alarm_run_precheck_best_effort(values)
    if precheck is None:
        return None

    allow_store, precheck_reason = precheck
    if allow_store:
        return None

    _upload_alarm_cleanup_created_files_best_effort(request, values)
    return f_responseJson(
        {
            "code": 1000,
            "msg": "filtered",
            "data": {
                "stored": False,
                "reason": str(precheck_reason or "blocked"),
            },
        }
    )


def _upload_alarm_save_alarm(values: dict):
    """执行上传告警`save`告警。"""
    now_date = datetime.now()
    alarm = Alarm()
    alarm.sort = 0
    alarm.control_code = values.get("control_code", "")
    alarm.desc = values.get("desc", "")
    alarm.detail_desc = values.get("desc", "")
    alarm.alarm_type = values.get("alarm_type", "")
    alarm.alarm_level = int(values.get("alarm_level", 1) or 1)
    alarm.algorithm_code = values.get("algorithm_code", "")
    alarm.object_code = values.get("object_code", "")
    alarm.recognition_region = values.get("recognition_region", "")
    alarm.region_index = int(values.get("region_index", -1) or -1)

    if values.get("class_thresh") is not None:
        alarm.class_thresh = values.get("class_thresh")
    if values.get("overlap_thresh") is not None:
        alarm.overlap_thresh = values.get("overlap_thresh")
    if values.get("min_interval") is not None:
        alarm.min_interval = values.get("min_interval")

    alarm.stream_code = values.get("stream_code", "")
    alarm.stream_app = values.get("stream_app", "")
    alarm.stream_name = values.get("stream_name", "")
    alarm.stream_url = values.get("stream_url", "")
    alarm.video_path = values.get("video_path", "")
    alarm.image_path = values.get("image_path", "")

    metadata_obj = values.get("metadata_obj")
    if bool(getattr(g_config, "alarmAiReviewEnabled", False)):
        from app.utils.AlarmAiReview import apply_alarm_ai_review

        metadata_obj = apply_alarm_ai_review(alarm, values, metadata_obj)
        values["metadata_obj"] = metadata_obj

    if metadata_obj is not None:
        alarm.metadata = json.dumps(metadata_obj, ensure_ascii=False)
    if values.get("extra_images_list") is not None:
        alarm.extra_images = json.dumps(values.get("extra_images_list"), ensure_ascii=False)

    alarm.create_time = now_date
    alarm.state = 0
    alarm.save()

    data = {
        "id": alarm.id,
        "control_code": alarm.control_code,
        "alarm_type": alarm.alarm_type,
        "alarm_level": alarm.alarm_level,
        "algorithm_code": alarm.algorithm_code,
        "object_code": alarm.object_code,
        "recognition_region": alarm.recognition_region,
        "region_index": alarm.region_index,
        "class_thresh": alarm.class_thresh,
        "overlap_thresh": alarm.overlap_thresh,
        "min_interval": alarm.min_interval,
        "stream_code": alarm.stream_code,
        "stream_app": alarm.stream_app,
        "stream_name": alarm.stream_name,
        "stream_url": alarm.stream_url,
        "metadata": values.get("metadata_obj"),
        "extra_images": values.get("extra_images_list") or [],
        "image_path": alarm.image_path,
        "video_path": alarm.video_path,
        "image_url": (g_config.uploadDir_www + alarm.image_path) if alarm.image_path else "",
        "video_url": (g_config.uploadDir_www + alarm.video_path) if alarm.video_path else "",
    }
    return alarm, data


def _upload_alarm_emit_event(*, alarm, values: dict):
    """执行上传告警`emit`事件。"""
    from app.utils.AlarmEventBus import (
        AlarmOutboxEnqueueError,
        build_alarm_created_event_for_alarm,
        enqueue_alarm_event_outbox,
    )
    from app.utils.BackgroundServices import get_alarm_sink_dispatcher

    try:
        payload = build_alarm_created_event_for_alarm(
            g_config,
            alarm=alarm,
            legacy_event="alarm_upload",
            event_source="uploadAlarm",
            metadata_obj=values.get("metadata_obj") or {},
            extra_images=values.get("extra_images_list") or [],
        )
        if getattr(g_config, "alarmOutboxEnabled", True):
            enqueue_alarm_event_outbox(g_config, payload, alarm_id=alarm.id, control_code=values.get("control_code", ""))
        else:
            dispatcher = get_alarm_sink_dispatcher()
            if dispatcher:
                dispatcher.enqueue(payload)
    except AlarmOutboxEnqueueError:
        event_id = str(payload.get("event_id", "") or "")
        control_code = str(values.get("control_code", "") or getattr(alarm, "control_code", "") or "")
        logger.exception(
            "Alarm outbox enqueue failed event_id=%s alarm_id=%s control_code=%s",
            event_id,
            alarm.id,
            control_code,
            extra={"alarm_event_id": event_id, "alarm_id": alarm.id, "control_code": control_code},
        )
        raise
    except Exception:
        logger.debug("suppressed exception in app/views/api.py:4079", exc_info=True)


def _upload_alarm_parse_core_fields(params: dict) -> dict:
    """执行上传告警`parse`核心字段。"""
    control_code = _upload_alarm_get_str(params, "control_code")
    if not control_code:
        raise ValueError("control_code is required")
    control_code = _upload_alarm_validate_control_code(control_code)

    image_path = _upload_alarm_get_str(params, "image_path")
    video_path = _upload_alarm_get_str(params, "video_path")
    image_base64 = _upload_alarm_get_str(params, "image_base64")
    video_base64 = _upload_alarm_get_str(params, "video_base64")

    allowed_image_exts = {"jpg", "jpeg", "png"}
    allowed_video_exts = {"mp4", "ts", "flv"}
    image_ext = str(params.get("image_ext") or "jpg").strip(".").lower()
    video_ext = str(params.get("video_ext") or "mp4").strip(".").lower()
    if image_ext not in allowed_image_exts:
        raise ValueError("image_ext is invalid")
    if video_ext not in allowed_video_exts:
        raise ValueError("video_ext is invalid")

    if image_path and not image_base64:
        image_path = _upload_alarm_validate_existing_rel_path(image_path)
    if video_path and not video_base64:
        video_path = _upload_alarm_validate_existing_rel_path(video_path)

    return {
        "control_code": control_code,
        "desc": _upload_alarm_get_str(params, "desc"),
        "image_path": image_path,
        "video_path": video_path,
        "image_base64": image_base64,
        "video_base64": video_base64,
        "image_ext": image_ext,
        "video_ext": video_ext,
        "allowed_image_exts": allowed_image_exts,
        "allowed_video_exts": allowed_video_exts,
    }


def _upload_alarm_parse_extended_fields(params: dict) -> dict:
    """执行上传告警`parse``extended`字段。"""
    alarm_type = params.get("alarm_type") or params.get("alarmType") or "detection"
    if not isinstance(alarm_type, str):
        raise ValueError("alarm_type must be a string")
    alarm_type = alarm_type.strip() or "detection"
    if len(alarm_type) > 50:
        raise ValueError("alarm_type too long")

    alarm_level = params.get("alarm_level") or params.get("alarmLevel") or 1
    try:
        alarm_level = int(alarm_level)
    except Exception:
        raise ValueError("alarm_level must be an integer")
    if alarm_level < 1 or alarm_level > 4:
        raise ValueError("alarm_level must be 1-4")

    algorithm_code = _upload_alarm_validate_str_len(
        "algorithm_code",
        params.get("algorithm_code") or params.get("algorithmCode") or "",
        max_len=50,
    )
    object_code = _upload_alarm_validate_str_len(
        "object_code",
        params.get("object_code") or params.get("objectCode") or "",
        max_len=50,
    )
    recognition_region = _upload_alarm_validate_str_len(
        "recognition_region",
        params.get("recognition_region") or params.get("recognitionRegion") or "",
        max_len=200,
    )
    region_index = _upload_alarm_parse_region_index(params.get("region_index") or params.get("regionIndex"))

    return {
        "alarm_type": alarm_type,
        "alarm_level": alarm_level,
        "algorithm_code": algorithm_code,
        "object_code": object_code,
        "recognition_region": recognition_region,
        "region_index": region_index,
    }


def _upload_alarm_parse_threshold_fields(params: dict) -> dict:
    """执行上传告警`parse``threshold`字段。"""
    class_thresh = _upload_alarm_parse_optional_float("class_thresh", params.get("class_thresh") or params.get("classThresh"))
    overlap_thresh = _upload_alarm_parse_optional_float(
        "overlap_thresh", params.get("overlap_thresh") or params.get("overlapThresh")
    )
    min_interval = _upload_alarm_parse_optional_int("min_interval", params.get("min_interval") or params.get("minInterval"))
    return {
        "class_thresh": class_thresh,
        "overlap_thresh": overlap_thresh,
        "min_interval": min_interval,
    }


def _upload_alarm_parse_stream_fields(params: dict) -> dict:
    """执行上传告警`parse`流字段。"""
    stream_code = _upload_alarm_validate_str_len(
        "stream_code", params.get("stream_code") or params.get("streamCode") or "", max_len=50
    )
    stream_app = _upload_alarm_validate_str_len(
        "stream_app", params.get("stream_app") or params.get("streamApp") or "", max_len=50
    )
    stream_name = _upload_alarm_validate_str_len(
        "stream_name", params.get("stream_name") or params.get("streamName") or "", max_len=100
    )
    stream_url = _upload_alarm_validate_str_len(
        "stream_url", params.get("stream_url") or params.get("streamUrl") or "", max_len=300
    )
    return {
        "stream_code": stream_code,
        "stream_app": stream_app,
        "stream_name": stream_name,
        "stream_url": stream_url,
    }


def _upload_alarm_parse_metadata_fields(params: dict) -> dict:
    """执行上传告警`parse`元数据字段。"""
    metadata_obj = _upload_alarm_parse_metadata(params.get("metadata"))
    extra_images = params.get("extra_images") or params.get("extraImages")
    extra_images_list = _upload_alarm_clean_extra_images(_upload_alarm_parse_extra_images(extra_images))
    return {
        "metadata_obj": metadata_obj,
        "extra_images_list": extra_images_list,
    }


def _upload_alarm_apply_multipart_files(request, values: dict) -> dict:
    # multipart upload: image_file / video_file
    """执行上传告警应用`multipart``files`。"""
    try:
        if hasattr(request, "FILES"):
            if request.FILES.get("image_file") and (not values.get("image_base64")):
                values["image_path"] = _upload_alarm_save_uploaded_file(
                    file_obj=request.FILES.get("image_file"),
                    control_code=values.get("control_code", ""),
                    prefix="img",
                    default_ext=values.get("image_ext", "jpg"),
                    allowed_exts=values.get("allowed_image_exts") or {"jpg", "jpeg", "png"},
                )
            if request.FILES.get("video_file") and (not values.get("video_base64")):
                values["video_path"] = _upload_alarm_save_uploaded_file(
                    file_obj=request.FILES.get("video_file"),
                    control_code=values.get("control_code", ""),
                    prefix="video",
                    default_ext=values.get("video_ext", "mp4"),
                    allowed_exts=values.get("allowed_video_exts") or {"mp4", "ts", "flv"},
                )
    except Exception as e:
        raise ValueError(str(e))
    return values


def _upload_alarm_apply_base64(values: dict) -> dict:
    # base64 upload takes precedence (fail-open on decode errors)
    """执行上传告警应用Base64。"""
    if values.get("image_base64"):
        values["image_path"] = _upload_alarm_save_base64(
            b64_str=values.get("image_base64") or "",
            control_code=values.get("control_code", ""),
            prefix="img",
            ext=values.get("image_ext", "jpg"),
        )
    if values.get("video_base64"):
        values["video_path"] = _upload_alarm_save_base64(
            b64_str=values.get("video_base64") or "",
            control_code=values.get("control_code", ""),
            prefix="video",
            ext=values.get("video_ext", "mp4"),
        )
    return values


def _upload_alarm_handle_post(request, params: dict):
    """执行上传告警`handle``post`。"""
    try:
        values = {}
        values.update(_upload_alarm_parse_core_fields(params))
        values.update(_upload_alarm_parse_extended_fields(params))
        values.update(_upload_alarm_parse_threshold_fields(params))
        values.update(_upload_alarm_parse_stream_fields(params))
        values.update(_upload_alarm_parse_metadata_fields(params))
        values = _upload_alarm_apply_multipart_files(request, values)
        values = _upload_alarm_apply_base64(values)

        filtered = _upload_alarm_precheck_or_filtered_response(request, values)
        if filtered is not None:
            return filtered

        alarm, data = _upload_alarm_save_alarm(values)
        _upload_alarm_emit_event(alarm=alarm, values=values)
        return f_responseJson({"code": 1000, "msg": "success", "data": data})
    except ValueError as e:
        return f_responseJson({"code": 0, "msg": str(e)})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e), "data": {}})


def api_upload_alarm(request):
    """
    开放报警上报接口：支持直接传入相对路径或 base64 数据。
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED, "data": {}})

    try:
        params = f_parsePostParams(request)
    except Exception:
        params = None
    if not isinstance(params, dict):
        return f_responseJson({"code": 0, "msg": "invalid request body"})

    return _upload_alarm_handle_post(request, params)
api_uploadAlarm = api_upload_alarm  # pragma: no cover - compatibility alias


def api_get_control_data(request):
    """
    开放接口：查询布控任务列表
    """
    params = {}
    try:
        if request.method == "POST":
            params = f_parsePostParams(request)
        elif request.method == "GET":
            params = f_parseGetParams(request)
    except Exception:
        params = {}

    code = str(params.get("code") or params.get("controlCode") or params.get("control_code") or "").strip()

    qs = Control.objects.all().order_by("-id")
    if code:
        qs = qs.filter(code=code)

    data = []
    for control in qs:
        data.append(
            {
                "code": getattr(control, "code", ""),
                "stream_app": getattr(control, "stream_app", ""),
                "stream_name": getattr(control, "stream_name", ""),
                "algorithm_code": getattr(control, "algorithm_code", ""),
                "object_code": getattr(control, "object_code", ""),
                "push_stream": 1 if bool(getattr(control, "push_stream", False)) else 0,
                "min_interval": int(getattr(control, "min_interval", 0) or 0),
                "class_thresh": float(getattr(control, "class_thresh", 0.0) or 0.0),
                "overlap_thresh": float(getattr(control, "overlap_thresh", 0.0) or 0.0),
                "state": int(getattr(control, "state", 0) or 0),
                "remark": getattr(control, "remark", ""),
            }
        )
    res = {
        "code": 1000,
        "msg": "success",
        "data": data
    }
    return f_responseJson(res)
api_getControlData = api_get_control_data  # pragma: no cover - compatibility alias


def api_get_stream_data(request):
    """
    开放接口：查询视频流列表，附带播放地址
    """
    params = {}
    try:
        if request.method == "POST":
            params = f_parsePostParams(request)
        elif request.method == "GET":
            params = f_parseGetParams(request)
    except Exception:
        params = {}

    code = str(params.get("code") or params.get("streamCode") or params.get("stream_code") or "").strip()

    qs = Stream.objects.all().order_by("-id")
    if code:
        qs = qs.filter(code=code)

    public_host = get_public_host_for_urls(request)
    data = []
    for stream in qs:
        app = getattr(stream, "app", "")
        name = getattr(stream, "name", "")
        data.append({
            "code": getattr(stream, "code", ""),
            "app": app,
            "name": name,
            "nickname": getattr(stream, "nickname", ""),
            "remark": getattr(stream, "remark", ""),
            "pull_stream_url": getattr(stream, "pull_stream_url", ""),
            "forward_state": int(getattr(stream, "forward_state", 0) or 0),
            "ws_flv": g_zlm.get_wsFlvUrl(app, name, public_host),
            "http_flv": g_zlm.get_httpFlvUrl(app, name, public_host),
            "ws_mp4": g_zlm.get_wsMp4Url(app, name, public_host),
            "http_mp4": g_zlm.get_httpMp4Url(app, name, public_host),
            "rtsp": g_zlm.get_rtspUrl(app, name, public_host)
        })
    res = {
        "code": 1000,
        "msg": "success",
        "data": data
    }
    return f_responseJson(res)
api_getStreamData = api_get_stream_data  # pragma: no cover - compatibility alias



def _control_flag(params: dict, key: str, *, default: bool = False) -> bool:
    """处理控制标记。
    
    Parse legacy "1"/"0" style flags used by OpenAPI endpoints.
        Note: when the key exists, only "1" is treated as True (to preserve behavior).
    """
    if key not in params:
        return bool(default)
    return str(params.get(key) or "").strip() == "1"


def _control_parse_int_default(params: dict, key: str, default: int) -> int:
    """处理控制`parse`整数值默认。"""
    raw = params.get(key, None) if key in params else None
    try:
        return int(raw) if raw not in (None, "") else int(default)
    except Exception:
        return int(default)


def _control_parse_float_default(params: dict, key: str, default: float) -> float:
    """处理控制`parse`浮点数默认。"""
    raw = params.get(key, None) if key in params else None
    try:
        return float(raw) if raw not in (None, "") else float(default)
    except Exception:
        return float(default)


def _control_parse_int_optional(params: dict, key: str, default: int, *, min_value: int, max_value: int):
    """处理控制`parse`整数值可选。"""
    if key not in params:
        return None
    v = _control_parse_int_default(params, key, default)
    if v < min_value:
        v = min_value
    if v > max_value:
        v = max_value
    return v


def _control_parse_str_optional(params: dict, key: str):
    """处理控制`parse`字符串可选。"""
    if key not in params:
        return None
    s = str(params.get(key) or "").strip()
    return s or None


def _control_has_any_key(params: dict, keys: tuple) -> bool:
    """返回控制`has``any`键。"""
    for k in keys:
        if k in params:
            return True
    return False


def _control_parse_alias_int_optional(params: dict, keys: tuple, default: int, *, min_value: int, max_value: int):
    """处理控制`parse``alias`整数值可选。
    
    Parse int params that may come under multiple legacy key spellings.
    
        Returns:
          - None when none of the keys exist in params
          - clamped int value when any key exists (invalid values fall back to default)
    """
    for key in keys:
        if key not in params:
            continue
        raw = params.get(key, None)
        try:
            v = int(raw) if raw not in (None, "") else int(default)
        except Exception:
            v = int(default)
        if v < min_value:
            v = min_value
        if v > max_value:
            v = max_value
        return v
    return None


def _control_parse_analysis_prompt_value(params: dict):
    """返回控制`parse``analysis``prompt`值。"""
    raw = params.get("analysisPrompt", params.get("analysis_prompt", params.get("promptZh", None)))
    if raw is None:
        return None
    s = str(raw or "")
    if len(s) > 8000:
        s = s[:8000]
    return s


def _control_parse_force_frame_alarm_value(params: dict):
    """返回控制`parse``force``frame`告警值。"""
    raw = params.get("forceFrameAlarm", None)
    if raw is None:
        return None

    v = str(raw or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return False
    return False


def _control_patch_set_str_attr(control, params: dict, param_key: str, attr: str, *, strip: bool) -> None:
    """处理控制补丁`set`字符串`attr`。"""
    if param_key not in params:
        return
    val = params.get(param_key)
    if strip:
        val = str(val or "").strip()
    else:
        val = str(val or "")
    setattr(control, attr, val)


def _control_patch_set_bool_token(control, params: dict, param_key: str, attr: str, *, strip: bool, none_value: str) -> None:
    """返回控制补丁`set`布尔值令牌。"""
    if param_key not in params:
        return
    raw = params.get(param_key)
    s = str(raw if raw is not None else none_value)
    if strip:
        s = s.strip()
    setattr(control, attr, s == "1")


def _control_patch_set_int_keep(control, params: dict, param_key: str, attr: str) -> None:
    """处理控制补丁`set`整数值`keep`。"""
    if param_key not in params:
        return
    raw = params.get(param_key)
    try:
        setattr(control, attr, int(raw or getattr(control, attr)))
    except Exception:
        return


def _control_patch_set_float_keep(control, params: dict, param_key: str, attr: str) -> None:
    """处理控制补丁`set`浮点数`keep`。"""
    if param_key not in params:
        return
    raw = params.get(param_key)
    try:
        setattr(control, attr, float(raw or getattr(control, attr)))
    except Exception:
        return


def _control_apply_patch_update(control, params: dict) -> None:
    # Basic config fields
    """处理控制应用补丁`update`。"""
    _control_patch_set_str_attr(control, params, "algorithmCode", "algorithm_code", strip=True)
    _control_patch_set_str_attr(control, params, "objectCode", "object_code", strip=True)
    _control_patch_set_str_attr(control, params, "polygon", "polygon", strip=False)
    _control_patch_set_bool_token(control, params, "pushStream", "push_stream", strip=True, none_value="")

    # Threshold fields (keep existing values on invalid input)
    _control_patch_set_int_keep(control, params, "minInterval", "min_interval")
    _control_patch_set_float_keep(control, params, "classThresh", "class_thresh")
    _control_patch_set_float_keep(control, params, "overlapThresh", "overlap_thresh")

    _control_patch_set_str_attr(control, params, "remark", "remark", strip=False)

    decode_stride = _control_parse_int_optional(params, "decodeStride", 1, min_value=1, max_value=60)
    if decode_stride is not None:
        control.decode_stride = decode_stride

    pull_frequency = _control_parse_alias_int_optional(params, ("pullFrequency", "pull_frequency"), 0, min_value=0, max_value=60)
    if pull_frequency is not None:
        control.pull_frequency = pull_frequency

    ps_effect_min_fps = _control_parse_alias_int_optional(params, ("psEffectMinFps", "ps_effect_min_fps"), 0, min_value=0, max_value=60)
    if ps_effect_min_fps is not None:
        control.ps_effect_min_fps = ps_effect_min_fps

    push_video_fps = _control_parse_alias_int_optional(params, ("pushVideoFps", "push_video_fps"), 25, min_value=13, max_value=60)
    if push_video_fps is not None:
        control.push_video_fps = push_video_fps

    # Only update when explicitly provided (patch semantics).
    if _control_has_any_key(params, ("analysisPrompt", "analysis_prompt", "promptZh")):
        raw = params.get("analysisPrompt", params.get("analysis_prompt", params.get("promptZh", "")))
        s = str(raw or "")
        if len(s) > 8000:
            s = s[:8000]
        control.analysis_prompt = s


def _control_parse_json_config(params: dict, key: str, *, default_text: str = "{}") -> str:
    """返回控制`parse`JSON配置。"""
    text = str(params.get(key, "") or "").strip()
    if not text:
        text = default_text
    try:
        json.loads(text)
    except Exception:
        raise ValueError(f"{key} JSON格式错误")
    return text


def _control_parse_alarm_fields(params: dict) -> dict:
    """返回控制`parse`告警字段。"""
    alarm_sound_id = int(params.get("alarmSoundId", 0))
    alarm_video_type = params.get("alarmVideoType", "mp4")
    alarm_image_count = int(params.get("alarmImageCount", 3))
    alarm_cover_position = str(params.get("alarmCoverPosition", "back") or "back").strip()
    if alarm_cover_position not in ("front", "middle", "back", "custom"):
        alarm_cover_position = "back"
    try:
        alarm_cover_custom_index = int(params.get("alarmCoverCustomIndex", 0) or 0)
    except Exception:
        alarm_cover_custom_index = 0
    if alarm_cover_custom_index < 0:
        alarm_cover_custom_index = 0
    alarm_image_draw_mode = str(params.get("alarmImageDrawMode", "boxed") or "boxed").strip().lower()
    if alarm_image_draw_mode not in ("boxed", "clean", "both"):
        alarm_image_draw_mode = "boxed"

    return {
        "alarmSoundId": alarm_sound_id,
        "alarmVideoType": alarm_video_type,
        "alarmImageCount": alarm_image_count,
        "alarmCoverPosition": alarm_cover_position,
        "alarmCoverCustomIndex": alarm_cover_custom_index,
        "alarmImageDrawMode": alarm_image_draw_mode,
    }


def _control_parse_pipeline_fields(params: dict) -> dict:
    """返回控制`parse``pipeline`字段。"""
    use_pipeline_mode = _control_flag(params, "usePipelineMode", default=False)
    try:
        pipeline_mode = int(params.get("pipelineMode", 1) or 1)
    except Exception:
        pipeline_mode = 1
    if pipeline_mode < 1:
        pipeline_mode = 1
    if pipeline_mode > 9:
        pipeline_mode = 9

    enable_tracking = _control_flag(params, "enableTracking", default=False)

    tracking_algorithm_code = str(params.get("trackingAlgorithmCode", "") or "").strip()
    tracking_config = _control_parse_json_config(params, "trackingConfig", default_text="{}")

    classification_algorithm_code = str(params.get("classificationAlgorithmCode", "") or "").strip()
    classification_config = _control_parse_json_config(params, "classificationConfig", default_text="{}")

    feature_algorithm_code = str(params.get("featureAlgorithmCode", "") or "").strip()
    feature_config = _control_parse_json_config(params, "featureConfig", default_text="{}")

    behavior_algorithm_code = str(params.get("behaviorAlgorithmCode", "") or "").strip()
    behavior_api_url = str(params.get("behaviorApiUrl", "") or "").strip()
    behavior_config = _control_parse_json_config(params, "behaviorConfig", default_text="{}")

    if use_pipeline_mode and pipeline_mode in (3, 4, 6, 7) and not classification_algorithm_code:
        raise ValueError("classificationAlgorithmCode 不能为空（流程模式3/4/6/7需要分类算法）")
    if use_pipeline_mode and pipeline_mode == 5 and not behavior_api_url:
        raise ValueError("behaviorApiUrl 不能为空（流程模式5需要行为API地址）")
    if use_pipeline_mode and pipeline_mode in (7, 9) and not feature_algorithm_code:
        raise ValueError("featureAlgorithmCode 不能为空（流程模式7/9需要特征算法）")

    return {
        "usePipelineMode": use_pipeline_mode,
        "pipelineMode": pipeline_mode,
        "enableTracking": enable_tracking,
        "trackingAlgorithmCode": tracking_algorithm_code,
        "trackingConfig": tracking_config,
        "classificationAlgorithmCode": classification_algorithm_code,
        "classificationConfig": classification_config,
        "featureAlgorithmCode": feature_algorithm_code,
        "featureConfig": feature_config,
        "behaviorAlgorithmCode": behavior_algorithm_code,
        "behaviorApiUrl": behavior_api_url,
        "behaviorConfig": behavior_config,
    }


def _control_parse_draw_fields(params: dict) -> dict:
    """返回控制`parse``draw`字段。"""
    draw_type = str(params.get("drawType", "polygon") or "polygon").strip()
    if draw_type not in ("polygon", "line"):
        raise ValueError("drawType 参数不合法")
    line_coordinates = str(params.get("lineCoordinates", "") or "").strip()
    line_violation_direction = str(params.get("lineViolationDirection", "both") or "both").strip()
    if line_violation_direction not in ("both", "forward", "backward"):
        raise ValueError("lineViolationDirection 参数不合法")
    return {
        "drawType": draw_type,
        "lineCoordinates": line_coordinates,
        "lineViolationDirection": line_violation_direction,
    }


def _control_parse_hw_fields(params: dict) -> dict:
    """返回控制`parse``hw`字段。"""
    enable_hardware_decode = _control_flag(params, "enableHardwareDecode", default=False)
    enable_hardware_encode = _control_flag(params, "enableHardwareEncode", default=False)
    return {
        "enableHardwareDecode": enable_hardware_decode,
        "enableHardwareEncode": enable_hardware_encode,
    }


def _control_parse_hierarchical_fields(
    params: dict, *, use_pipeline_mode: bool, pipeline_mode: int, behavior_config: str
) -> dict:
    """返回控制`parse``hierarchical`字段。"""
    enable_hierarchical_algorithm = _control_flag(params, "enableHierarchicalAlgorithm", default=False)
    secondary_algorithm_code = str(params.get("secondaryAlgorithmCode", "") or "").strip()
    secondary_api_url = str(params.get("secondaryApiUrl", "") or "").strip()
    try:
        secondary_conf_thresh = float(params.get("secondaryConfThresh", 0.25) or 0.25)
    except Exception:
        raise ValueError("secondaryConfThresh 参数不合法")
    if secondary_conf_thresh <= 0:
        secondary_conf_thresh = 0.25
    if enable_hierarchical_algorithm and not secondary_algorithm_code:
        raise ValueError("secondaryAlgorithmCode 不能为空（启用层级算法时需要二级算法）")

    _control_validate_pipeline_detect2_constraints(
        use_pipeline_mode=use_pipeline_mode,
        pipeline_mode=pipeline_mode,
        behavior_config=behavior_config,
        enable_hierarchical_algorithm=enable_hierarchical_algorithm,
        secondary_algorithm_code=secondary_algorithm_code,
        secondary_api_url=secondary_api_url,
    )

    return {
        "enableHierarchicalAlgorithm": enable_hierarchical_algorithm,
        "secondaryAlgorithmCode": secondary_algorithm_code,
        "secondaryApiUrl": secondary_api_url,
        "secondaryConfThresh": secondary_conf_thresh,
    }


def _control_parse_osd_fields(params: dict) -> dict:
    """返回控制`parse`OSD字段。"""
    osd_enabled = _control_flag(params, "osdEnabled", default=False)
    osd_text = str(params.get("osdText", "") or "")
    osd_position = str(params.get("osdPosition", "top-left") or "top-left")
    osd_x = int(params.get("osdX", 10) or 10)
    osd_y = int(params.get("osdY", 30) or 30)
    osd_font_size = int(params.get("osdFontSize", 24) or 24)
    osd_font_color = str(params.get("osdFontColor", DEFAULT_OSD_FONT_COLOR) or DEFAULT_OSD_FONT_COLOR)
    osd_bg_enabled = _control_flag(params, "osdBgEnabled", default=True)

    payload = {
        "osdEnabled": osd_enabled,
        "osdText": osd_text,
        "osdPosition": osd_position,
        "osdX": osd_x,
        "osdY": osd_y,
        "osdFontSize": osd_font_size,
        "osdFontColor": osd_font_color,
        "osdBgEnabled": osd_bg_enabled,
    }
    payload.update(_control_parse_osd_image_fields(params))
    payload.update(_control_parse_osd_overlay_coords(params))
    return payload


def _control_parse_osd_font_thickness(params: dict):
    """处理控制`parse`OSD`font``thickness`。"""
    osd_font_thickness = params.get("osdFontThickness", None)
    if osd_font_thickness is None:
        return None
    try:
        osd_font_thickness = int(osd_font_thickness or 2)
    except Exception:
        osd_font_thickness = 2
    if osd_font_thickness < 1:
        osd_font_thickness = 2
    return osd_font_thickness


def _control_parse_overlay_fields(params: dict) -> dict:
    """返回控制`parse``overlay`字段。"""
    overlay_region_color = _control_parse_str_optional(params, "overlayRegionColor")
    overlay_line_color = _control_parse_str_optional(params, "overlayLineColor")
    overlay_detect_color = _control_parse_str_optional(params, "overlayDetectColor")

    overlay_region_thickness = _control_parse_int_optional(params, "overlayRegionThickness", 4, min_value=1, max_value=100)
    overlay_line_thickness = _control_parse_int_optional(params, "overlayLineThickness", 4, min_value=1, max_value=100)
    overlay_detect_thickness = _control_parse_int_optional(params, "overlayDetectThickness", 2, min_value=1, max_value=100)
    overlay_detect_font_size = _control_parse_int_optional(params, "overlayDetectFontSize", 48, min_value=1, max_value=512)

    return {
        "overlayRegionColor": overlay_region_color,
        "overlayRegionThickness": overlay_region_thickness,
        "overlayLineColor": overlay_line_color,
        "overlayLineThickness": overlay_line_thickness,
        "overlayDetectColor": overlay_detect_color,
        "overlayDetectThickness": overlay_detect_thickness,
        "overlayDetectFontSize": overlay_detect_font_size,
    }


def _control_parse_perf_fields(params: dict) -> dict:
    """返回控制`parse``perf`字段。"""
    decode_stride = _control_parse_int_optional(params, "decodeStride", 1, min_value=1, max_value=60)
    pull_frequency = _control_parse_alias_int_optional(params, ("pullFrequency", "pull_frequency"), 0, min_value=0, max_value=60)
    ps_effect_min_fps = _control_parse_alias_int_optional(params, ("psEffectMinFps", "ps_effect_min_fps"), 0, min_value=0, max_value=60)
    push_video_fps = _control_parse_alias_int_optional(params, ("pushVideoFps", "push_video_fps"), 25, min_value=13, max_value=60)

    analysis_prompt = _control_parse_analysis_prompt_value(params)
    force_frame_alarm = _control_parse_force_frame_alarm_value(params)

    return {
        "decodeStride": decode_stride,
        "pullFrequency": pull_frequency,
        "psEffectMinFps": ps_effect_min_fps,
        "pushVideoFps": push_video_fps,
        "analysisPrompt": analysis_prompt,
        "forceFrameAlarm": force_frame_alarm,
    }


def _control_validate_pipeline_detect2_constraints(
    *,
    use_pipeline_mode: bool,
    pipeline_mode: int,
    behavior_config: str,
    enable_hierarchical_algorithm: bool,
    secondary_algorithm_code: str,
    secondary_api_url: str,
) -> None:
    # 模式 8/9：第二步检测来自“层级算法（二级检测）”，且当前仅支持本地模型
    """处理控制`validate``pipeline``detect2``constraints`。"""
    if not use_pipeline_mode:
        return
    if pipeline_mode not in (8, 9):
        return

    try:
        bc = json.loads(behavior_config) if str(behavior_config or "").strip() else {}
    except Exception:
        bc = {}

    pipeline = bc.get("pipeline") if isinstance(bc, dict) else None
    if not isinstance(pipeline, dict):
        pipeline = {}

    detect2_enabled = pipeline.get("detect2Enabled", True)
    if not bool(detect2_enabled):
        return

    if not enable_hierarchical_algorithm:
        raise ValueError("流程模式8/9开启第二步检测时，必须启用层级算法（二级检测）")
    if not secondary_algorithm_code:
        raise ValueError("流程模式8/9开启第二步检测时，secondaryAlgorithmCode 不能为空")
    if secondary_api_url:
        raise ValueError("流程模式8/9的第二步检测暂不支持 secondaryApiUrl（请使用本地模型）")


def _control_parse_osd_image_fields(params: dict) -> dict:
    # OSD 贴图
    """返回控制`parse`OSD图片字段。"""
    osd_image_path = str(params.get("osdImagePath", "") or "")
    osd_image_x = int(params.get("osdImageX", 10) or 10)
    osd_image_y = int(params.get("osdImageY", 10) or 10)
    osd_image_scale = float(params.get("osdImageScale", 1.0) or 1.0)
    osd_image_alpha = float(params.get("osdImageAlpha", 1.0) or 1.0)
    if osd_image_scale <= 0:
        osd_image_scale = 1.0
    if osd_image_alpha < 0:
        osd_image_alpha = 0.0
    if osd_image_alpha > 1:
        osd_image_alpha = 1.0

    return {
        "osdImagePath": osd_image_path,
        "osdImageX": osd_image_x,
        "osdImageY": osd_image_y,
        "osdImageScale": osd_image_scale,
        "osdImageAlpha": osd_image_alpha,
    }


def _control_parse_osd_overlay_coords(params: dict) -> dict:
    # Algo/FPS overlay coordinates (画面左侧算法名与FPS)
    """处理控制`parse`OSD`overlay``coords`。"""
    osd_algo_x = int(params.get("osdAlgoX", 20) or 20)
    osd_algo_y = int(params.get("osdAlgoY", 80) or 80)
    osd_fps_x = int(params.get("osdFpsX", 20) or 20)
    osd_fps_y = int(params.get("osdFpsY", 140) or 140)
    return {
        "osdAlgoX": osd_algo_x,
        "osdAlgoY": osd_algo_y,
        "osdFpsX": osd_fps_x,
        "osdFpsY": osd_fps_y,
    }


def _control_parse_stream_fields(params: dict) -> dict:
    """返回控制`parse`流字段。"""
    stream_app = str(params.get("streamApp") or "").strip()
    stream_name = str(params.get("streamName") or "").strip()
    stream_video = str(params.get("streamVideo") or "").strip() or "video"
    stream_audio = str(params.get("streamAudio") or "").strip() or "audio"
    return {
        "streamApp": stream_app,
        "streamName": stream_name,
        "streamVideo": stream_video,
        "streamAudio": stream_audio,
    }


def _parse_control_upsert_payload(params: dict) -> dict:
    """解析控制`upsert`载荷。"""
    control_code = str(params.get("controlCode") or "").strip()
    algorithm_code = str(params.get("algorithmCode") or "").strip()
    object_code = str(params.get("objectCode") or "").strip()
    polygon = str(params.get("polygon") or "")

    # v4.709: Allow cluster/machine callers to omit optional fields to reduce payload size.
    # Defaults align with ControlView.add UI defaults.
    push_stream = _control_flag(params, "pushStream", default=True)

    min_interval = _control_parse_int_default(params, "minInterval", 180)
    class_thresh = _control_parse_float_default(params, "classThresh", 0.5)
    overlap_thresh = _control_parse_float_default(params, "overlapThresh", 0.5)

    remark = str(params.get("remark") or "")
    payload = {
        "controlCode": control_code,
        "algorithmCode": algorithm_code,
        "objectCode": object_code,
        "polygon": polygon,
        "pushStream": push_stream,
        "minInterval": min_interval,
        "classThresh": class_thresh,
        "overlapThresh": overlap_thresh,
        "remark": remark,
    }
    payload.update(_control_parse_stream_fields(params))
    payload.update(_control_parse_alarm_fields(params))
    payload.update(_control_parse_pipeline_fields(params))
    payload.update(_control_parse_draw_fields(params))
    payload.update(_control_parse_hw_fields(params))
    payload.update(
        _control_parse_hierarchical_fields(
            params,
            use_pipeline_mode=payload["usePipelineMode"],
            pipeline_mode=payload["pipelineMode"],
            behavior_config=payload["behaviorConfig"],
        )
    )
    payload.update(_control_parse_osd_fields(params))
    payload["osdFontThickness"] = _control_parse_osd_font_thickness(params)
    payload.update(_control_parse_overlay_fields(params))
    payload.update(_control_parse_perf_fields(params))
    return payload


def _apply_control_config_fields(control, payload: dict, *, include_stream_fields: bool) -> None:
    """返回应用控制配置字段。"""
    if include_stream_fields:
        control.stream_app = payload["streamApp"]
        control.stream_name = payload["streamName"]
        control.stream_video = payload["streamVideo"]
        control.stream_audio = payload["streamAudio"]

    control.algorithm_code = payload["algorithmCode"]
    control.object_code = payload["objectCode"]
    control.polygon = payload["polygon"]
    control.min_interval = payload["minInterval"]
    control.class_thresh = payload["classThresh"]
    control.overlap_thresh = payload["overlapThresh"]
    control.remark = payload["remark"]
    control.push_stream = payload["pushStream"]

    # 报警配置
    control.alarm_sound_id = payload["alarmSoundId"]
    control.alarm_video_type = payload["alarmVideoType"]
    control.alarm_image_count = payload["alarmImageCount"]
    control.alarm_cover_position = payload["alarmCoverPosition"]
    control.alarm_cover_custom_index = payload["alarmCoverCustomIndex"]
    control.alarm_image_draw_mode = payload["alarmImageDrawMode"]

    # 流程模式/追踪配置
    control.use_pipeline_mode = payload["usePipelineMode"]
    control.algorithm_pipeline_mode = payload["pipelineMode"]
    control.enable_tracking = payload["enableTracking"]
    control.tracking_algorithm_code = payload["trackingAlgorithmCode"]
    control.tracking_config = payload["trackingConfig"]
    control.classification_algorithm_code = payload["classificationAlgorithmCode"]
    control.classification_config = payload["classificationConfig"]
    control.feature_algorithm_code = payload["featureAlgorithmCode"]
    control.feature_config = payload["featureConfig"]
    control.behavior_algorithm_code = payload["behaviorAlgorithmCode"]
    control.behavior_api_url = payload["behaviorApiUrl"]
    control.behavior_config = payload["behaviorConfig"]
    if payload.get("analysisPrompt") is not None:
        control.analysis_prompt = payload["analysisPrompt"]

    # 绘制/越线配置
    control.draw_type = payload["drawType"]
    control.line_coordinates = payload["lineCoordinates"]
    control.line_violation_direction = payload["lineViolationDirection"]

    # 硬件编解码配额开关
    control.enable_hw_decode = payload["enableHardwareDecode"]
    control.enable_hw_encode = payload["enableHardwareEncode"]

    # 层级算法（二级检测）配置
    control.enable_hierarchical_algorithm = payload["enableHierarchicalAlgorithm"]
    control.secondary_algorithm_code = payload["secondaryAlgorithmCode"]
    control.secondary_api_url = payload["secondaryApiUrl"]
    control.secondary_conf_thresh = payload["secondaryConfThresh"]

    # OSD 配置
    control.osd_enabled = payload["osdEnabled"]
    control.osd_text = payload["osdText"]
    control.osd_position = payload["osdPosition"]
    control.osd_x = payload["osdX"]
    control.osd_y = payload["osdY"]
    control.osd_font_size = payload["osdFontSize"]
    control.osd_font_color = payload["osdFontColor"]
    control.osd_bg_enabled = payload["osdBgEnabled"]
    control.osd_image_path = payload["osdImagePath"]
    control.osd_image_x = payload["osdImageX"]
    control.osd_image_y = payload["osdImageY"]
    control.osd_image_scale = payload["osdImageScale"]
    control.osd_image_alpha = payload["osdImageAlpha"]
    control.osd_algo_x = payload["osdAlgoX"]
    control.osd_algo_y = payload["osdAlgoY"]
    control.osd_fps_x = payload["osdFpsX"]
    control.osd_fps_y = payload["osdFpsY"]

    if payload.get("osdFontThickness") is not None:
        control.osd_font_thickness = payload["osdFontThickness"]
    if payload.get("decodeStride") is not None:
        control.decode_stride = payload["decodeStride"]
    if payload.get("pullFrequency") is not None:
        control.pull_frequency = payload["pullFrequency"]
    if payload.get("psEffectMinFps") is not None:
        control.ps_effect_min_fps = payload["psEffectMinFps"]
    if payload.get("pushVideoFps") is not None:
        control.push_video_fps = payload["pushVideoFps"]
    if payload.get("forceFrameAlarm") is not None:
        control.force_frame_alarm = bool(payload["forceFrameAlarm"])

    # 算法流绘制样式
    if payload.get("overlayRegionColor") is not None:
        control.overlay_region_color = payload["overlayRegionColor"]
    if payload.get("overlayRegionThickness") is not None:
        control.overlay_region_thickness = payload["overlayRegionThickness"]
    if payload.get("overlayLineColor") is not None:
        control.overlay_line_color = payload["overlayLineColor"]
    if payload.get("overlayLineThickness") is not None:
        control.overlay_line_thickness = payload["overlayLineThickness"]
    if payload.get("overlayDetectColor") is not None:
        control.overlay_detect_color = payload["overlayDetectColor"]
    if payload.get("overlayDetectThickness") is not None:
        control.overlay_detect_thickness = payload["overlayDetectThickness"]
    if payload.get("overlayDetectFontSize") is not None:
        control.overlay_detect_font_size = payload["overlayDetectFontSize"]


def _upsert_control_from_payload(request, payload: dict):
    """从载荷获取`upsert`控制。"""
    control_code = payload.get("controlCode") or ""

    control = None
    try:
        control = Control.objects.get(code=control_code)
    except (Control.DoesNotExist, Control.MultipleObjectsReturned):
        control = None

    if control:
        _apply_control_config_fields(control, payload, include_stream_fields=True)
        control.last_update_time = datetime.now()
        control.save()
        if control.id:
            return True, "更新布控成功(a)"
        return False, "更新布控失败(a)"

    control = Control()
    # OpenAPI / cluster callers may not have a logged-in web session.
    session_user = getUser(request) or {}
    try:
        control.user_id = int(session_user.get("id") or 0)
    except Exception:
        control.user_id = 0
    control.sort = 0
    control.code = control_code

    _apply_control_config_fields(control, payload, include_stream_fields=True)

    # Push stream destination is always under the Analyzer's app/name convention.
    control.push_stream_app = g_zlm.default_push_stream_app
    control.push_stream_name = control_code

    control.create_time = datetime.now()
    control.last_update_time = datetime.now()
    control.save()

    if control.id:
        return True, "添加布控成功"
    return False, "添加布控失败"


def api_post_add_control(request):
    """处理 `postAddControl` 接口请求。"""
    code = 0
    msg = "error"

    if request.method == 'POST':
        params = f_parsePostParams(request)
        try:
            payload = _parse_control_upsert_payload(params)
            if (
                payload.get("controlCode")
                and payload.get("algorithmCode")
                and payload.get("streamApp")
                and payload.get("streamName")
                and payload.get("streamVideo")
            ):
                save_state, save_msg = _upsert_control_from_payload(request, payload)
                if save_state:
                    code = 1000
                msg = save_msg
            else:
                msg = "布控请求参数不完整！"
        except Exception as e:
            msg = "布控请求参数存在错误: %s" % str(e)
    else:
        msg = "请求方法不合法！"

    return f_responseJson({"code": code, "msg": msg})
api_postAddControl = api_post_add_control  # pragma: no cover - compatibility alias


def _control_edit_is_legacy_full_update(params: dict) -> bool:
    """处理控制编辑`is`旧版`full``update`。"""
    legacy_required = (
        "algorithmCode",
        "objectCode",
        "polygon",
        "pushStream",
        "minInterval",
        "classThresh",
        "overlapThresh",
    )
    return all(k in params for k in legacy_required)


def _control_edit_patch(control_code: str, params: dict) -> dict:
    """处理控制编辑补丁。"""
    control = Control.objects.filter(code=control_code).first()
    if not control:
        raise ValueError("该布控不存在")

    _control_apply_patch_update(control, params)

    control.last_update_time = datetime.now()
    control.save()

    if control.id:
        return {"code": 1000, "msg": "更新布控成功"}
    return {"code": 0, "msg": "更新布控失败"}


def _control_edit_full(control_code: str, params: dict) -> dict:
    """处理控制编辑`full`。"""
    algorithm_code = params.get("algorithmCode")
    object_code = params.get("objectCode")
    polygon = params.get("polygon")
    push_stream = True if '1' == params.get("pushStream") else False
    min_interval = int(params.get("minInterval"))
    class_thresh = float(params.get("classThresh"))
    overlap_thresh = float(params.get("overlapThresh"))
    remark = params.get("remark")
    payload = {
        "controlCode": control_code,
        "algorithmCode": algorithm_code,
        "objectCode": object_code,
        "polygon": polygon,
        "pushStream": push_stream,
        "minInterval": min_interval,
        "classThresh": class_thresh,
        "overlapThresh": overlap_thresh,
        "remark": remark,
    }
    payload.update(_control_parse_alarm_fields(params))
    payload.update(_control_parse_pipeline_fields(params))
    payload.update(_control_parse_draw_fields(params))
    payload.update(_control_parse_hw_fields(params))
    payload.update(
        _control_parse_hierarchical_fields(
            params,
            use_pipeline_mode=payload["usePipelineMode"],
            pipeline_mode=payload["pipelineMode"],
            behavior_config=payload["behaviorConfig"],
        )
    )
    payload.update(_control_parse_osd_fields(params))
    payload["osdFontThickness"] = _control_parse_osd_font_thickness(params)
    payload.update(_control_parse_overlay_fields(params))
    payload.update(_control_parse_perf_fields(params))

    if not (control_code and algorithm_code and object_code):
        return {"code": 0, "msg": "更新布控请求参数不完整！"}

    try:
        control = Control.objects.get(code=control_code)
        _apply_control_config_fields(control, payload, include_stream_fields=False)
        control.last_update_time = datetime.now()
        control.save()
        if control.id:
            return {"code": 1000, "msg": "更新布控成功"}
        return {"code": 0, "msg": "更新布控失败"}
    except Exception as e:
        return {"code": 0, "msg": "更新布控数据失败：" + str(e)}


def api_post_edit_control(request):
    """处理 `postEditControl` 接口请求。"""
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": "请求方法不合法！"})

    params = f_parsePostParams(request)
    try:
        control_code = str(params.get("controlCode") or "").strip()
        if not control_code:
            raise ValueError("controlCode 不能为空")

        if not _control_edit_is_legacy_full_update(params):
            return f_responseJson(_control_edit_patch(control_code, params))
        return f_responseJson(_control_edit_full(control_code, params))
    except Exception as e:
        return f_responseJson({"code": 0, "msg": "布控请求参数存在错误: %s" % str(e)})
api_postEditControl = api_post_edit_control  # pragma: no cover - compatibility alias


def _alarm_parse_alarm_ids(value: str):
    """返回告警`parse`告警`ids`。"""
    try:
        alarm_ids = [int(x.strip()) for x in str(value or "").split(",") if x.strip()]
    except ValueError:
        return None, "告警 ID 格式错误，必须是数字"
    if not alarm_ids:
        return None, MSG_ALARM_ID_LIST_EMPTY
    return alarm_ids, ""


def _alarm_handle_mark_read(alarm_ids: list) -> tuple:
    """处理告警`handle``mark`读取。"""
    if Alarm.objects.filter(id__in=alarm_ids).update(state=1) > 0:
        return 1000, "已读操作成功"
    return 0, "已读操作失败"


def _alarm_handle_mark_handled(alarm_ids: list, params: dict, session_user: dict) -> tuple:
    """处理告警`handle``mark``handled`。"""
    handled_by = str(session_user.get("username") or session_user.get("email") or "").strip()
    now = timezone.now()

    # remark is optional; only update when explicitly provided
    remark_provided = "handled_remark" in params or "remark" in params
    handled_remark = str(params.get("handled_remark", params.get("remark", "")) or "").strip()

    update_fields = {
        "handled": True,
        "handled_time": now,
        "handled_by": handled_by,
    }
    if remark_provided:
        update_fields["handled_remark"] = handled_remark

    updated = int(Alarm.objects.filter(id__in=alarm_ids).update(**update_fields) or 0)
    return 1000, f"标记已处理成功 {updated} 条"


def _alarm_handle_mark_unhandled(alarm_ids: list) -> tuple:
    """处理告警`handle``mark``unhandled`。"""
    updated = int(
        Alarm.objects.filter(id__in=alarm_ids).update(
            handled=False,
            handled_time=None,
            handled_by="",
            handled_remark="",
        )
        or 0
    )
    return 1000, f"取消处理成功 {updated} 条"


def _alarm_handle_delete(alarm_ids_raw: str) -> tuple:
    """处理告警`handle``delete`。"""
    alarm_ids, err = _alarm_parse_alarm_ids(alarm_ids_raw)
    if not alarm_ids:
        return 0, err or MSG_ALARM_ID_LIST_EMPTY

    handle_success_count = 0
    handle_error_count = 0
    for alarm_id in alarm_ids:
        try:
            removed = f_removeAlarmAndStorage(alarm_id)
        except Exception as e:
            logger.warning(
                "manual alarm delete failed: alarm_id=%s err=%s",
                safe_json_dumps(str(alarm_id), max_len=128),
                safe_json_dumps(str(e), max_len=512),
            )
            removed = False
        if removed is True:
            handle_success_count += 1
        else:
            handle_error_count += 1
    code = 1000 if handle_error_count == 0 else 0
    return code, "删除成功%d条，删除失败%d条" % (handle_success_count, handle_error_count)


def api_post_handle_alarm(request):
    """处理 `postHandleAlarm` 接口请求。"""
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": "请求方法不支持"})

    params = f_parsePostParams(request)
    alarm_ids_str = params.get("alarm_ids_str", "")
    handle = params.get("handle")
    session_user = getUser(request) or {}

    if handle == "delete":
        code, msg = _alarm_handle_delete(alarm_ids_str)
        return f_responseJson({"code": code, "msg": msg})

    alarm_ids, err = _alarm_parse_alarm_ids(alarm_ids_str)
    if not alarm_ids:
        return f_responseJson({"code": 0, "msg": err or MSG_ALARM_ID_LIST_EMPTY})

    handlers = {
        "read": lambda: _alarm_handle_mark_read(alarm_ids),
        "handled": lambda: _alarm_handle_mark_handled(alarm_ids, params, session_user),
        "unhandled": lambda: _alarm_handle_mark_unhandled(alarm_ids),
    }
    fn = handlers.get(handle)
    if not fn:
        return f_responseJson({"code": 0, "msg": "不支持的处理类型"})

    code, msg = fn()
    return f_responseJson({"code": code, "msg": msg})
api_postHandleAlarm = api_post_handle_alarm  # pragma: no cover - compatibility alias


def api_alarm_sinks_test_send(request):
    """
    测试当前启用的 Webhook/Cloud 告警出口。

    - best-effort：不会抛异常，不影响主流程
    - 返回每个 sink 的 publish 结果（ok/retriable/error）
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    from app.utils.AlarmSinks import publish_alarm_event_to_sink

    # Build a minimal test event.
    event_id = "test-" + uuid.uuid4().hex
    try:
        ts_ms = int(time.time() * 1000)
    except Exception:
        ts_ms = 0

    event = {
        "schema": "beacon.alarm.test",
        "event_id": event_id,
        "ts_ms": ts_ms,
        "control_code": "test",
        "alarm_level": 1,
        "desc": "alarm sink test event",
    }

    sink_specs = [
        (
            "webhook",
            bool(getattr(g_config, "alarmWebhookEnabled", False))
            and any(str(url or "").strip() for url in (getattr(g_config, "alarmWebhookUrls", []) or [])),
        ),
        (
            "cloud",
            bool(getattr(g_config, "cloudEnabled", False))
            and bool(str(getattr(g_config, "cloudBaseUrl", "") or "").strip())
            and bool(str(getattr(g_config, "cloudEdgeToken", "") or "").strip()),
        ),
    ]
    sinks = [name for name, enabled in sink_specs if enabled]

    if not sinks:
        return f_responseJson({"code": 0, "msg": "未启用 Webhook 或 Cloud 告警出口", "results": {}, "event_id": event_id})

    results = {}
    for sink in sinks:
        try:
            results[sink] = publish_alarm_event_to_sink(g_config, sink, dict(event))
        except Exception as e:
            results[sink] = {"ok": False, "retriable": True, "http_status": 0, "error": str(e)}

    return f_responseJson({"code": 1000, "msg": "success", "event_id": event_id, "results": results})
api_alarmSinksTestSend = api_alarm_sinks_test_send  # pragma: no cover - compatibility alias


def _audio_detect_error_response(msg: str, *, data=None):
    """返回音频检测错误响应。"""
    body = {"code": 0, "msg": str(msg or "")}
    if data is not None:
        body["data"] = data
    return f_responseJson(body)


def _audio_detect_request_params(request):
    """处理音频检测请求参数。"""
    content_type = str(getattr(request, "content_type", "") or "")
    if content_type.startswith("application/json"):
        try:
            return f_parsePostParams(request)
        except Exception:
            raise _AudioDetectApiError("invalid json")
    return {key: request.POST.get(key) for key in request.POST}


def _audio_detect_base_code(params):
    """处理音频检测基础编码。"""
    raw_code = str(params.get("code") or "").strip()
    if not raw_code:
        raise _AudioDetectApiError(MSG_CODE_REQUIRED)
    base_code, _ = _split_algorithm_code(raw_code)
    return str(base_code or "").strip()


def _audio_detect_api_algorithm(base_code):
    """处理音频检测API算法。"""
    algo = AlgorithmModel.objects.filter(code=base_code).first()
    if not algo:
        raise _AudioDetectApiError("算法不存在")

    algorithm_subtype = str(getattr(algo, "algorithm_subtype", "") or "").strip().lower()
    if algorithm_subtype != "speech":
        raise _AudioDetectApiError("audioDetect requires a speech algorithm")

    is_basic_api = getattr(algo, "algorithm_type", 0) == 0 and getattr(algo, "basic_source", "model") == "api"
    if not is_basic_api:
        raise _AudioDetectApiError(
            "Wave 1 only supports API-backed speech algorithms; local/model speech inference is not supported yet"
        )

    api_url = str(getattr(algo, "api_url", "") or "").strip()
    if not api_url:
        raise _AudioDetectApiError("api_url is required")
    return algo, api_url


def _audio_detect_audio_base64(request, params):
    """处理音频检测音频Base64。"""
    audio_file = request.FILES.get("audio")
    if audio_file is not None:
        try:
            audio_bytes = audio_file.read()
        except Exception:
            audio_bytes = b""
        if not audio_bytes:
            raise _AudioDetectApiError("audio is empty")
        return base64.b64encode(audio_bytes).decode("ascii")

    audio_b64 = params.get("audio_base64") or params.get("audioBase64") or ""
    if not isinstance(audio_b64, str):
        raise _AudioDetectApiError("audio_base64 must be a string")
    audio_b64 = audio_b64.strip()
    if not audio_b64:
        raise _AudioDetectApiError("audio is required")
    return audio_b64


def _audio_detect_language(params):
    """处理音频检测`language`。"""
    language = params.get("language")
    if not isinstance(language, str):
        return ""
    return language.strip()


def _audio_detect_hotwords(params):
    """处理音频检测`hotwords`。"""
    hotwords = params.get("hotwords")
    if isinstance(hotwords, str):
        return [item.strip() for item in hotwords.split(",") if item.strip()]
    if isinstance(hotwords, list):
        return hotwords
    return []


def _audio_detect_request_payload(*, base_code: str, audio_b64: str, params: dict):
    """返回音频检测请求载荷。"""
    payload = {
        "audio_base64": audio_b64,
        "algorithmCode": base_code,
        "language": _audio_detect_language(params) or None,
        "hotwords": _audio_detect_hotwords(params) or None,
        "extensions": {"source": "openapi_audio_detect"},
    }
    return {key: value for key, value in payload.items() if value is not None}


def _audio_detect_api_response(api_url: str, payload: dict):
    """返回音频检测API响应。"""
    try:
        res = requests.post(
            api_url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload, ensure_ascii=False),
            timeout=(2, 20),
        )
    except Exception as exc:
        raise _AudioDetectApiError(str(exc))

    if not res.status_code:
        raise _AudioDetectApiError("request failed")

    try:
        api_data = res.json()
    except Exception:
        raise _AudioDetectApiError(MSG_INVALID_API_RESPONSE)

    if not isinstance(api_data, dict):
        raise _AudioDetectApiError(MSG_INVALID_API_RESPONSE)
    if api_data.get("code") != 1000:
        raise _AudioDetectApiError(str(api_data.get("msg") or MSG_INFER_FAILED), data=api_data)
    return api_data


def _audio_detect_result(api_data):
    """返回音频检测结果。"""
    result_obj = api_data.get("result") if isinstance(api_data.get("result"), dict) else {}
    text = result_obj.get("text") if isinstance(result_obj.get("text"), str) else ""
    result_language = result_obj.get("language") if isinstance(result_obj.get("language"), str) else ""
    segments = result_obj.get("segments") if isinstance(result_obj.get("segments"), list) else []
    return text, result_language, segments


def _audio_detect_alarm_info(*, base_code: str, params: dict, text: str, result_language: str, segments):
    """返回音频检测告警信息。"""
    if not _parse_boolish(params.get("create_alarm") or params.get("createAlarm"), default=False):
        return {}
    try:
        return _create_audio_review_alarm(
            base_code=base_code,
            params=params,
            text=text,
            result_language=result_language,
            segments=segments,
        )
    except ValueError as exc:
        raise _AudioDetectApiError(str(exc))
    except Exception as exc:
        raise _AudioDetectApiError(str(exc))


def _audio_detect_success_response(*, base_code: str, text: str, result_language: str, segments, alarm_info):
    """返回音频检测成功状态响应。"""
    return f_responseJson(
        {
            "code": 1000,
            "msg": "success",
            "data": {
                "engine": "api",
                "algorithmCode": base_code,
                "text": text,
                "language": result_language,
                "segments": segments,
                "alarm": alarm_info,
            },
        }
    )
