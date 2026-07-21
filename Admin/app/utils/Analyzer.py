import requests
import json
import time
import logging
import inspect


logger = logging.getLogger(__name__)

STATUS_CODE_PREFIX = "status_code=%d "
MSG_NOT_CHECKED = "not checked"
_UNSET = object()
_DISABLE_ENV_PROXY = {
    "http": "",
    "https": "",
    "all": "",
}


def _request_kwargs_without_env_proxy(kwargs):
    """Analyzer is usually local; do not let system HTTP_PROXY intercept it."""
    kwargs.setdefault("proxies", dict(_DISABLE_ENV_PROXY))
    return kwargs


def _requests_get(**kwargs):
    return requests.get(**_request_kwargs_without_env_proxy(kwargs))


def _requests_post(**kwargs):
    return requests.post(**_request_kwargs_without_env_proxy(kwargs))


def _parse_analyzer_json_response(response, *, service_name="Analyzer"):
    """Return parsed Analyzer JSON or a readable transport error message."""
    status_code = int(getattr(response, "status_code", 0) or 0)
    text = str(getattr(response, "text", "") or "")
    if not text.strip():
        return None, f"{service_name} HTTP {status_code} empty response"
    try:
        return response.json(), ""
    except Exception:
        snippet = text.strip().replace("\n", " ")[:200]
        return None, f"{service_name} HTTP {status_code} non-JSON response: {snippet}"

_CONTROL_ADD_ARGUMENT_NAMES = (
    "code",
    "algorithmCode",
    "streamCode",
    "streamApp",
    "streamName",
    "streamUrl",
    "pushStream",
    "pushStreamUrl",
    "api_url",
    "object_str",
    "objectCode",
    "recognitionRegion",
    "minInterval",
    "classThresh",
    "overlapThresh",
    "alarmVideoType",
    "alarmImageCount",
    "alarmCoverPosition",
    "alarmCoverCustomIndex",
    "alarmImageDrawMode",
    "nmsThresh",
    "confThresh",
    "pushVideoCodec",
    "pushVideoBitrate",
    "pushVideoFps",
    "pushVideoWidth",
    "pushVideoHeight",
    "pushVideoGop",
    "modelPrecision",
    "inputWidth",
    "inputHeight",
    "modelConcurrency",
    "basicAlgoDetectMode",
    "basicAlgoDetectInterval",
    "decodeStride",
    "pullFrequency",
    "psEffectMinFps",
    "forceFrameAlarm",
    "osdEnabled",
    "osdText",
    "osdPosition",
    "osdX",
    "osdY",
    "osdFontSize",
    "osdFontColor",
    "osdBgEnabled",
    "osdFontThickness",
    "osdImagePath",
    "osdImageX",
    "osdImageY",
    "osdImageScale",
    "osdImageAlpha",
    "osdAlgoX",
    "osdAlgoY",
    "osdFpsX",
    "osdFpsY",
    "overlayRegionColor",
    "overlayRegionThickness",
    "overlayLineColor",
    "overlayLineThickness",
    "overlayDetectColor",
    "overlayDetectThickness",
    "overlayDetectFontSize",
    "drawType",
    "lineCoordinates",
    "lineViolationDirection",
    "enableTracking",
    "enableHardwareDecode",
    "enableHardwareEncode",
    "enableHierarchicalAlgorithm",
    "secondaryAlgorithmCode",
    "secondaryApiUrl",
    "secondaryConfThresh",
    "usePipelineMode",
    "pipelineMode",
    "trackingAlgorithmCode",
    "classificationAlgorithmCode",
    "featureAlgorithmCode",
    "behaviorAlgorithmCode",
    "behaviorApiUrl",
    "trackingConfig",
    "classificationConfig",
    "featureConfig",
    "behaviorConfig",
)

_CONTROL_ADD_REQUIRED_ARGUMENT_NAMES = _CONTROL_ADD_ARGUMENT_NAMES[:15]

_CONTROL_ADD_OPTIONAL_FIELD_GROUPS = (
    (
        ("alarmCoverPosition", str),
        ("alarmCoverCustomIndex", int),
        ("alarmImageDrawMode", str),
    ),
    (
        ("nmsThresh", str),
        ("confThresh", str),
    ),
    (
        ("pushVideoCodec", str),
        ("pushVideoBitrate", int),
        ("pushVideoFps", int),
        ("pushVideoWidth", int),
        ("pushVideoHeight", int),
        ("pushVideoGop", int),
    ),
    (
        ("modelPrecision", str),
        ("inputWidth", int),
        ("inputHeight", int),
        ("modelConcurrency", int),
    ),
    (
        ("basicAlgoDetectMode", int),
        ("basicAlgoDetectInterval", int),
        ("decodeStride", int),
        ("pullFrequency", int),
        ("psEffectMinFps", int),
        ("forceFrameAlarm", bool),
    ),
    (
        ("osdEnabled", bool),
        ("osdText", str),
        ("osdPosition", str),
        ("osdX", int),
        ("osdY", int),
        ("osdFontSize", int),
        ("osdFontColor", str),
        ("osdBgEnabled", bool),
        ("osdFontThickness", int),
    ),
    (
        ("osdImagePath", str),
        ("osdImageX", int),
        ("osdImageY", int),
        ("osdImageScale", float),
        ("osdImageAlpha", float),
    ),
    (
        ("osdAlgoX", int),
        ("osdAlgoY", int),
        ("osdFpsX", int),
        ("osdFpsY", int),
    ),
    (
        ("overlayRegionColor", str),
        ("overlayRegionThickness", int),
        ("overlayLineColor", str),
        ("overlayLineThickness", int),
        ("overlayDetectColor", str),
        ("overlayDetectThickness", int),
        ("overlayDetectFontSize", int),
    ),
    (
        ("drawType", str),
        ("lineCoordinates", str),
        ("lineViolationDirection", str),
        ("enableTracking", bool),
    ),
    (
        ("enableHardwareDecode", bool),
        ("enableHardwareEncode", bool),
    ),
    (
        ("enableHierarchicalAlgorithm", bool),
        ("secondaryAlgorithmCode", str),
        ("secondaryApiUrl", str),
        ("secondaryConfThresh", str),
    ),
    (
        ("usePipelineMode", bool),
        ("pipelineMode", int),
        ("trackingAlgorithmCode", str),
        ("classificationAlgorithmCode", str),
        ("featureAlgorithmCode", str),
        ("behaviorAlgorithmCode", str),
        ("behaviorApiUrl", str),
        ("trackingConfig", str),
        ("classificationConfig", str),
        ("featureConfig", str),
        ("behaviorConfig", str),
    ),
)


def _apply_control_add_optional_fields(payload, control_kwargs, field_specs) -> None:
    """返回应用控制新增可选字段。"""
    for field_name, caster in field_specs:
        value = control_kwargs.get(field_name)
        if value is None:
            continue
        payload[field_name] = caster(value)


def _make_control_add_signature():
    """生成控制新增签名。"""
    parameters = [inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    required_count = len(_CONTROL_ADD_REQUIRED_ARGUMENT_NAMES)
    for index, field_name in enumerate(_CONTROL_ADD_ARGUMENT_NAMES):
        default = inspect._empty if index < required_count else None
        parameters.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
            )
        )
    return inspect.Signature(parameters)


def _resolve_legacy_kwarg(kwargs, legacy_name, value, *, default=_UNSET, required=False, display_name=None):
    if legacy_name in kwargs:
        if value is not _UNSET:
            raise TypeError(f"got multiple values for argument '{display_name or legacy_name}'")
        value = kwargs.pop(legacy_name)
    if value is _UNSET:
        if required:
            raise TypeError(f"missing required argument: '{display_name or legacy_name}'")
        return default
    return value


def _raise_unexpected_kwargs(kwargs):
    if kwargs:
        unexpected = next(iter(kwargs))
        raise TypeError(f"got an unexpected keyword argument '{unexpected}'")


class Analyzer():

    def __init__(self, analyzer_host=_UNSET, open_api_token=_UNSET, **legacy_kwargs):
        """处理`init`。"""
        analyzer_host = _resolve_legacy_kwarg(
            legacy_kwargs,
            "analyzerHost",
            analyzer_host,
            required=True,
            display_name="analyzer_host",
        )
        open_api_token = _resolve_legacy_kwarg(
            legacy_kwargs,
            "openApiToken",
            open_api_token,
            default="",
            display_name="open_api_token",
        )
        _raise_unexpected_kwargs(legacy_kwargs)
        self.analyzer_host = analyzer_host
        self.open_api_token = str(open_api_token or "").strip()
        self.timeout = 60
        # 运维/看板类接口：需要“快速失败”，避免 Analyzer 不可用时拖垮 Admin UI。
        self.ops_timeout = 2
        self.analyzer_server_state = False  # 流媒体服务状态
        self._scheduler_info_cache = {
            "ts": 0.0,
            "state": False,
            "msg": MSG_NOT_CHECKED,
            "stats": {},
        }
        self._device_info_cache = {
            "ts": 0.0,
            "state": False,
            "msg": MSG_NOT_CHECKED,
            "data": {},
        }
        self._license_info_cache = {
            "ts": 0.0,
            "state": False,
            "msg": MSG_NOT_CHECKED,
            "data": {},
        }
        self._resource_info_cache = {
            "ts": 0.0,
            "state": False,
            "msg": MSG_NOT_CHECKED,
            "data": {},
        }
        self._algorithm_list_cache = {
            "ts": 0.0,
            "state": False,
            "msg": MSG_NOT_CHECKED,
            "items": [],
        }

    def _build_headers(self):
        """构建请求头。"""
        headers = {
            "Content-Type": "application/json;"
        }
        if self.open_api_token:
            headers["X-Beacon-Token"] = self.open_api_token
        return headers

    def controls(self):
        """处理`controls`。"""
        __state = False
        __msg = "error"
        __data = []

        try:
            headers = self._build_headers()

            data = {
            }

            data_json = json.dumps(data)

            res = _requests_post(url='%s/api/controls' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=self.timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result["msg"]
                if res_result["code"] == 1000:

                    res_result_data = res_result.get("data")
                    if res_result_data:
                        __data = res_result_data
                    __state = True
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    def control(self, code):
        """
        @code   布控编号    [str]  xxxxxxxxx
        """
        __state = False
        __msg = "error"
        __control = {}
        try:
            headers = self._build_headers()
            data = {
                "code": code,
            }

            data_json = json.dumps(data)
            res = _requests_post(url='%s/api/control' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=self.timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result["msg"]
                if res_result["code"] == 1000:
                    __control = res_result.get("control")
                    __state = True

            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg, __control

    def algorithm_load(
        self,
        code,
        model_path=_UNSET,
        class_names=_UNSET,
        device="CPU",
        model_concurrency=_UNSET,
        algorithm_subtype=_UNSET,
        **legacy_kwargs,
    ):
        """
        动态加载算法（ONNX/OpenVINO/插件动态库）
        @code: 算法编号（建议与布控使用的 algorithmCode 一致，可包含 _gpu/_cpu 等后缀）
        @modelPath: 模型/插件路径（.onnx/.xml/.dll/.so/.dylib）
        @classNames: 类别名称数组（ONNX/OpenVINO 需要；插件可不传）
        @device: CPU/GPU/TRT/AUTO/NPU（ONNX/OpenVINO 使用）
        @modelConcurrency: 并发实例数（可选）
        @algorithmSubtype: 算法子类型（可选：detection/classification/tracking/behavior）
        """
        model_path = _resolve_legacy_kwarg(
            legacy_kwargs,
            "modelPath",
            model_path,
            required=True,
            display_name="model_path",
        )
        class_names = _resolve_legacy_kwarg(
            legacy_kwargs,
            "classNames",
            class_names,
            default=None,
            display_name="class_names",
        )
        model_concurrency = _resolve_legacy_kwarg(
            legacy_kwargs,
            "modelConcurrency",
            model_concurrency,
            default=None,
            display_name="model_concurrency",
        )
        algorithm_subtype = _resolve_legacy_kwarg(
            legacy_kwargs,
            "algorithmSubtype",
            algorithm_subtype,
            default=None,
            display_name="algorithm_subtype",
        )
        _raise_unexpected_kwargs(legacy_kwargs)
        __state = False
        __msg = "error"

        try:
            headers = self._build_headers()
            data = {
                "code": code,
                "modelPath": model_path,
                "device": device or "CPU",
            }
            if algorithm_subtype is not None:
                subtype = str(algorithm_subtype or "").strip()
                if subtype:
                    data["algorithmSubtype"] = subtype
            if class_names is not None:
                data["classNames"] = class_names
            if model_concurrency is not None:
                data["modelConcurrency"] = int(model_concurrency)

            data_json = json.dumps(data, ensure_ascii=False)
            res = _requests_post(url='%s/api/algorithm/load' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=self.timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __state = True
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg

    def algorithm_unload(self, code):
        """
        卸载算法
        """
        __state = False
        __msg = "error"

        try:
            headers = self._build_headers()
            data = {"code": code}
            data_json = json.dumps(data, ensure_ascii=False)
            res = _requests_post(url='%s/api/algorithm/unload' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=self.timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __state = True
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg

    def _safe_time_now(self) -> float:
        """处理安全时间当前时间。"""
        try:
            return float(time.time())
        except Exception:
            return 0.0

    def _safe_cache_ttl_seconds(self, cache_ttl_seconds) -> float:
        """返回安全缓存TTL秒数。"""
        try:
            return float(cache_ttl_seconds or 0)
        except Exception:
            return 0.0

    def _ops_probe_from_cache(self, cache_obj: dict, *, now: float, ttl: float):
        """从缓存中读取运维探测结果。"""
        if ttl <= 0 or now <= 0:
            return None

        cached = cache_obj or {}
        try:
            ts = float(cached.get("ts") or 0.0)
        except Exception:
            ts = 0.0

        if ts > 0 and (now - ts) < ttl:
            return bool(cached.get("state")), str(cached.get("msg") or "cached"), cached.get("data") or {}
        return None

    def _ops_probe_update_cache(self, cache_name: str, state: bool, msg: str, data: dict) -> None:
        """返回运维探测`update`缓存。"""
        try:
            setattr(
                self,
                cache_name,
                {
                    "ts": float(time.time()),
                    "state": bool(state),
                    "msg": str(msg or ""),
                    "data": data or {},
                },
            )
        except Exception:
            logger.debug("suppressed exception in app/utils/Analyzer.py:527", exc_info=True)

    def _algorithm_list_from_cache(self, *, now: float, ttl: float):
        """从缓存获取算法列表。"""
        if ttl <= 0 or now <= 0:
            return None

        cached = self._algorithm_list_cache or {}
        try:
            ts = float(cached.get("ts") or 0.0)
        except Exception:
            ts = 0.0

        if ts > 0 and (now - ts) < ttl:
            return bool(cached.get("state")), str(cached.get("msg") or "cached"), cached.get("items") or []
        return None

    def _algorithm_list_timeout_tuple(self, timeout_seconds):
        """处理算法列表超时时间`tuple`。"""
        try:
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
        except Exception:
            t = 2.0
        t = max(0.2, min(t, 10.0))
        return min(0.5, t), max(0.2, t - 0.5)

    def _algorithm_list_items_from_result(self, res_result):
        """从结果中提取算法列表条目。"""
        items = res_result.get("items")
        if isinstance(items, list):
            return items

        # backward-compatible fallback
        algos = res_result.get("algorithms") or []
        if isinstance(algos, list):
            return [{"code": str(x)} for x in algos if x]
        return []

    def _algorithm_list_fetch(self, *, timeout_seconds=None):
        """处理算法列表拉取。"""
        __state = False
        __msg = "error"
        __items = []

        try:
            headers = self._build_headers()
            timeout = self._algorithm_list_timeout_tuple(timeout_seconds)

            res = _requests_get(url='%s/api/algorithm/list' % self.analyzer_host, headers=headers, timeout=timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __items = self._algorithm_list_items_from_result(res_result)
                    __state = True
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg, __items

    def _algorithm_list_update_cache(self, __state, __msg, __items) -> None:
        """返回算法列表`update`缓存。"""
        try:
            self._algorithm_list_cache = {
                "ts": float(time.time()),
                "state": bool(__state),
                "msg": str(__msg or ""),
                "items": __items or [],
            }
        except Exception:
            logger.debug("suppressed exception in app/utils/Analyzer.py:601", exc_info=True)

    def algorithm_list(self, *, timeout_seconds=None, cache_ttl_seconds=2):
        """
        获取 Analyzer 已加载算法列表（带 refCount 等运维信息）
        返回：(__state, __msg, __items_list)
        """
        cached = self._algorithm_list_from_cache(now=self._safe_time_now(), ttl=self._safe_cache_ttl_seconds(cache_ttl_seconds))
        if cached is not None:
            return cached

        __state, __msg, __items = self._algorithm_list_fetch(timeout_seconds=timeout_seconds)
        self._algorithm_list_update_cache(__state, __msg, __items)
        return __state, __msg, __items

    def algorithm_test_infer(
        self,
        code,
        image_base64,
        *,
        conf_thresh=_UNSET,
        nms_thresh=_UNSET,
        timeout_seconds=None,
        **legacy_kwargs,
    ):
        """
        v4.18: 一次性推理测试（用于后台“算法接入验收”）。
        Analyzer endpoint: POST /api/algorithm/testInfer

        Returns: (__state, __msg, __data_dict)
        """
        conf_thresh = _resolve_legacy_kwarg(
            legacy_kwargs,
            "confThresh",
            conf_thresh,
            default=0.25,
            display_name="conf_thresh",
        )
        nms_thresh = _resolve_legacy_kwarg(
            legacy_kwargs,
            "nmsThresh",
            nms_thresh,
            default=0.45,
            display_name="nms_thresh",
        )
        _raise_unexpected_kwargs(legacy_kwargs)
        __state = False
        __msg = "error"
        __data = {}

        try:
            headers = self._build_headers()

            payload = {
                "code": str(code or "").strip(),
                "image_base64": str(image_base64 or ""),
                "confThresh": float(conf_thresh),
                "nmsThresh": float(nms_thresh),
            }

            try:
                t = float(timeout_seconds) if timeout_seconds is not None else float(self.timeout or 60)
            except Exception:
                t = 60.0
            t = max(1.0, min(t, 120.0))
            timeout = (min(2.0, t), max(1.0, t - 2.0))

            data_json = json.dumps(payload, ensure_ascii=False)
            res = _requests_post(
                url="%s/api/algorithm/testInfer" % self.analyzer_host,
                headers=headers,
                data=data_json,
                timeout=timeout,
            )
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __state = True
                    __data = res_result
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg, __data

    def device_info(self, *, timeout_seconds=None, cache_ttl_seconds=0):
        """返回设备信息。
        
        Get Analyzer inference device/providers info.
        
                Analyzer endpoint: GET /api/device/info
                Returns: (__state, __msg, __data_dict)
        """
        now = self._safe_time_now()
        ttl = self._safe_cache_ttl_seconds(cache_ttl_seconds)
        cached = self._ops_probe_from_cache(self._device_info_cache, now=now, ttl=ttl)
        if cached is not None:
            return cached

        __state = False
        __msg = "error"
        __data = {}

        try:
            headers = self._build_headers()
            try:
                t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            except Exception:
                t = 2.0
            # Device/provider probing can be materially slower than other ops endpoints
            # because Analyzer may enumerate OpenVINO devices and ONNX providers.
            t = max(5.0, t)
            t = max(0.2, min(t, 10.0))
            timeout = (min(0.5, t), max(0.2, t - 0.5))

            res = _requests_get(url="%s/api/device/info" % self.analyzer_host, headers=headers, timeout=timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __state = True
                    __data = res_result
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        self._ops_probe_update_cache("_device_info_cache", __state, __msg, __data)
        return __state, __msg, __data

    def license_info(self, *, timeout_seconds=None, cache_ttl_seconds=0):
        """返回授权信息。
        
        Get Analyzer local license info.
        
                Analyzer endpoint: GET /api/license/info
                Returns: (__state, __msg, __data_dict)
        """
        now = self._safe_time_now()
        ttl = self._safe_cache_ttl_seconds(cache_ttl_seconds)
        cached = self._ops_probe_from_cache(self._license_info_cache, now=now, ttl=ttl)
        if cached is not None:
            return cached

        __state = False
        __msg = "error"
        __data = {}

        try:
            headers = self._build_headers()
            try:
                t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            except Exception:
                t = 2.0
            t = max(0.2, min(t, 10.0))
            timeout = (min(0.5, t), max(0.2, t - 0.5))

            res = _requests_get(url="%s/api/license/info" % self.analyzer_host, headers=headers, timeout=timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __state = True
                    __data = res_result
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        self._ops_probe_update_cache("_license_info_cache", __state, __msg, __data)
        return __state, __msg, __data

    def resource_info(self, *, timeout_seconds=None, cache_ttl_seconds=0):
        """返回`resource`信息。
        
        Get Analyzer resource info (cpu/mem/quotas/stats).
        
                Analyzer endpoint: GET /api/resource/info
                Returns: (__state, __msg, __data_dict)
        """
        now = self._safe_time_now()
        ttl = self._safe_cache_ttl_seconds(cache_ttl_seconds)
        cached = self._ops_probe_from_cache(self._resource_info_cache, now=now, ttl=ttl)
        if cached is not None:
            return cached

        __state = False
        __msg = "error"
        __data = {}

        try:
            headers = self._build_headers()
            try:
                t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            except Exception:
                t = 2.0
            t = max(0.2, min(t, 10.0))
            timeout = (min(0.5, t), max(0.2, t - 0.5))

            res = _requests_get(url="%s/api/resource/info" % self.analyzer_host, headers=headers, timeout=timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __state = True
                    __data = res_result
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        self._ops_probe_update_cache("_resource_info_cache", __state, __msg, __data)
        return __state, __msg, __data

    def _scheduler_info_from_cache(self, *, now: float, ttl: float):
        """从缓存获取调度器信息。"""
        if not (ttl > 0 and now > 0):
            return None
        cached = self._scheduler_info_cache or {}
        try:
            ts = float(cached.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if ts > 0 and (now - ts) < ttl:
            return bool(cached.get("state")), str(cached.get("msg") or "cached"), cached.get("stats") or {}
        return None

    def _fetch_scheduler_info(self, *, timeout_seconds=None):
        """获取调度器信息。"""
        __state = False
        __msg = "error"
        __stats = {}

        try:
            headers = self._build_headers()
            try:
                t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            except Exception:
                t = 2.0
            t = max(0.2, min(t, 10.0))
            # Use split connect/read timeouts to prevent long TCP hangs.
            timeout = (min(0.5, t), max(0.2, t - 0.5))

            res = _requests_get(url='%s/api/scheduler/info' % self.analyzer_host, headers=headers, timeout=timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result.get("msg", "error")
                if res_result.get("code") == 1000:
                    __stats = res_result.get("stats") or {}
                    __state = True
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg, __stats

    def _store_scheduler_info_cache(self, *, now: float, state: bool, msg: str, stats: dict) -> None:
        """缓存调度器信息缓存。"""
        try:
            self._scheduler_info_cache = {
                "ts": now or float(time.time()),
                "state": bool(state),
                "msg": str(msg or ""),
                "stats": stats or {},
            }
        except Exception:
            logger.debug("suppressed exception in app/utils/Analyzer.py:880", exc_info=True)

    def scheduler_info(self, *, timeout_seconds=None, cache_ttl_seconds=2):
        """
        获取 Analyzer 调度统计（用于运维可观测性 / UI 展示）
        返回：(__state, __msg, __stats_dict)
        """
        try:
            now = float(time.time())
        except Exception:
            now = 0.0

        try:
            ttl = float(cache_ttl_seconds or 0)
        except Exception:
            ttl = 0.0

        cached = self._scheduler_info_from_cache(now=now, ttl=ttl)
        if cached is not None:
            return cached

        __state, __msg, __stats = self._fetch_scheduler_info(timeout_seconds=timeout_seconds)
        self._store_scheduler_info_cache(now=now, state=__state, msg=__msg, stats=__stats)
        return __state, __msg, __stats

    def _control_add_kwargs_from_call(self, args, kwargs):
        """从`call`获取控制新增参数。"""
        if len(args) > len(_CONTROL_ADD_ARGUMENT_NAMES):
            raise TypeError("control_add() received too many positional arguments")

        control_kwargs = dict(kwargs or {})
        for field_name, value in zip(_CONTROL_ADD_ARGUMENT_NAMES, args):
            if field_name in control_kwargs:
                raise TypeError("control_add() got multiple values for argument '%s'" % field_name)
            control_kwargs[field_name] = value

        unexpected_names = sorted(set(control_kwargs.keys()) - set(_CONTROL_ADD_ARGUMENT_NAMES))
        if unexpected_names:
            raise TypeError("control_add() got unexpected keyword arguments: %s" % ", ".join(unexpected_names))

        missing_names = [name for name in _CONTROL_ADD_REQUIRED_ARGUMENT_NAMES if name not in control_kwargs]
        if missing_names:
            raise TypeError("control_add() missing required arguments: %s" % ", ".join(missing_names))

        return control_kwargs

    def _build_control_add_payload(self, control_kwargs):
        """构建控制新增载荷。"""
        payload = {
            "code": control_kwargs["code"],
            "algorithmCode": control_kwargs["algorithmCode"],
            "streamCode": control_kwargs["streamCode"],
            "streamApp": control_kwargs["streamApp"],
            "streamName": control_kwargs["streamName"],
            "streamUrl": control_kwargs["streamUrl"],
            "pushStream": control_kwargs["pushStream"],
            "pushStreamUrl": control_kwargs["pushStreamUrl"],
            "api_url": control_kwargs["api_url"],
            "object_str": control_kwargs["object_str"],
            "objectCode": control_kwargs["objectCode"],
            "recognitionRegion": control_kwargs["recognitionRegion"],
            "minInterval": str(control_kwargs["minInterval"]),
            "classThresh": str(control_kwargs["classThresh"]),
            "overlapThresh": str(control_kwargs["overlapThresh"]),
            "alarmVideoType": control_kwargs.get("alarmVideoType"),
            "alarmImageCount": control_kwargs.get("alarmImageCount"),
        }

        for field_specs in _CONTROL_ADD_OPTIONAL_FIELD_GROUPS:
            _apply_control_add_optional_fields(payload, control_kwargs, field_specs)

        return payload

    def control_add(self, *args, **kwargs):
        """处理控制新增。"""
        __state = False
        __msg = "error"

        try:
            headers = self._build_headers()
            control_kwargs = self._control_add_kwargs_from_call(args, kwargs)
            data = self._build_control_add_payload(control_kwargs)
            data_json = json.dumps(data)
            res = _requests_post(url='%s/api/control/add' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=self.timeout)
            if res.status_code:
                res_result, parse_msg = _parse_analyzer_json_response(res)
                if parse_msg:
                    __msg = parse_msg
                else:
                    __msg = res_result["msg"]
                if res_result and res_result["code"] == 1000:
                    __state = True

            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg

    control_add.__signature__ = _make_control_add_signature()

    def large_model_calcu(self, prompt, image_path):


        """处理大模型计算。"""
        __state = False
        __msg = "error"
        __content = ""

        try:
            headers = self._build_headers()

            data = {
                "prompt": prompt,
                "imagePath": image_path
            }

            data_json = json.dumps(data)

            try:
                prompt_len = len(str(prompt or ""))
            except Exception:
                prompt_len = -1
            logger.debug("Analyzer.large_model_calcu() prompt_len=%s image_path=%s", prompt_len, image_path)

            res = _requests_post(url='%s/api/largeModelCalcu' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=600)
            if res.status_code:
                res_result = res.json()
                __msg = res_result["msg"]
                if res_result["code"] == 1000:
                    __content = res_result.get("content")
                    __state = True

            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg, __content

    # ========== Face DB / Face recognition primitives ==========

    def face_list(self, *, timeout_seconds=None):
        """返回`face`列表。
        
        List faces stored in Analyzer face DB.
        
                Analyzer endpoint: GET /api/face/list
                Returns: (__state, __msg, __data_dict)
        """
        __state = False
        __msg = "error"
        __data = {}
        try:
            headers = self._build_headers()
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            t = max(0.2, min(t, 10.0))
            timeout = (min(0.5, t), max(0.2, t - 0.5))
            res = _requests_get(url="%s/api/face/list" % self.analyzer_host, headers=headers, timeout=timeout)
            if res.status_code:
                __data = res.json()
                __msg = str(__data.get("msg") or "error")
                __state = bool(__data.get("code") in (1000, 1001))
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    def face_add(self, payload: dict, *, timeout_seconds=None):
        """处理`face`新增。
        
        Add/update face in Analyzer face DB.
        
                Analyzer endpoint: POST /api/face/add
        """
        __state = False
        __msg = "error"
        __data = {}
        try:
            headers = self._build_headers()
            data_json = json.dumps(payload or {}, ensure_ascii=False)
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.timeout or 60)
            res = _requests_post(url="%s/api/face/add" % self.analyzer_host, headers=headers, data=data_json, timeout=t)
            if res.status_code:
                __data = res.json()
                __msg = str(__data.get("msg") or "error")
                __state = bool(__data.get("code") == 1000)
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    def face_delete(self, payload: dict, *, timeout_seconds=None):
        """处理`face``delete`。
        
        Delete face from Analyzer face DB.
        
                Analyzer endpoint: POST /api/face/delete
        """
        __state = False
        __msg = "error"
        __data = {}
        try:
            headers = self._build_headers()
            data_json = json.dumps(payload or {}, ensure_ascii=False)
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.timeout or 60)
            res = _requests_post(url="%s/api/face/delete" % self.analyzer_host, headers=headers, data=data_json, timeout=t)
            if res.status_code:
                __data = res.json()
                __msg = str(__data.get("msg") or "error")
                __state = bool(__data.get("code") == 1000)
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    def face_search(self, payload: dict, *, timeout_seconds=None):
        """处理`face`搜索。
        
        Search nearest face in Analyzer face DB.
        
                Analyzer endpoint: POST /api/face/search
                Returns: (__state, __msg, __data_dict)
        """
        __state = False
        __msg = "error"
        __data = {}
        try:
            headers = self._build_headers()
            data_json = json.dumps(payload or {}, ensure_ascii=False)
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.timeout or 60)
            res = _requests_post(url="%s/api/face/search" % self.analyzer_host, headers=headers, data=data_json, timeout=t)
            if res.status_code:
                __data = res.json()
                __msg = str(__data.get("msg") or "error")
                __state = bool(__data.get("code") in (1000, 1001))
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    def face_enable(self, *, timeout_seconds=None):
        """处理`face``enable`。
        
        Enable face search.
        
                Analyzer endpoint: POST /api/face/enable
        """
        __state = False
        __msg = "error"
        __data = {}
        try:
            headers = self._build_headers()
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            t = max(0.2, min(t, 10.0))
            timeout = (min(0.5, t), max(0.2, t - 0.5))
            res = _requests_post(url="%s/api/face/enable" % self.analyzer_host, headers=headers, data=json.dumps({}), timeout=timeout)
            if res.status_code:
                __data = res.json()
                __msg = str(__data.get("msg") or "error")
                __state = bool(__data.get("code") == 1000)
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    def face_disable(self, *, timeout_seconds=None):
        """处理`face``disable`。
        
        Disable face search.
        
                Analyzer endpoint: POST /api/face/disable
        """
        __state = False
        __msg = "error"
        __data = {}
        try:
            headers = self._build_headers()
            t = float(timeout_seconds) if timeout_seconds is not None else float(self.ops_timeout or 2)
            t = max(0.2, min(t, 10.0))
            timeout = (min(0.5, t), max(0.2, t - 0.5))
            res = _requests_post(url="%s/api/face/disable" % self.analyzer_host, headers=headers, data=json.dumps({}), timeout=timeout)
            if res.status_code:
                __data = res.json()
                __msg = str(__data.get("msg") or "error")
                __state = bool(__data.get("code") == 1000)
            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)
        return __state, __msg, __data

    # ============================================================

    def control_cancel(self, code):
        """
        @code   布控编号    [str]  xxxxxxxxx
        """
        __state = False
        __msg = "error"

        try:
            headers = self._build_headers()
            data = {
                "code": code,
            }

            data_json = json.dumps(data)
            res = _requests_post(url='%s/api/control/cancel' % self.analyzer_host, headers=headers,
                                data=data_json, timeout=self.timeout)
            if res.status_code:
                res_result = res.json()
                __msg = res_result["msg"]
                if res_result["code"] == 1000:
                    __state = True

            else:
                __msg = STATUS_CODE_PREFIX % (res.status_code)
            self.analyzer_server_state = True
        except Exception as e:
            self.analyzer_server_state = False
            __msg = str(e)

        return __state, __msg
