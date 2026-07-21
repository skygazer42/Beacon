import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple


logger = logging.getLogger(__name__)

OTLP_HTTP_TRACES_PATH = "/v1/traces"

_INIT_LOCK = threading.Lock()
_INIT_DONE = False
_INIT_RESULT: Optional[Dict[str, Any]] = None


def _env_bool(name: str, default: bool = False) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_float(name: str, default: float) -> float:
    """处理环境变量浮点数。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _normalize_otlp_http_traces_endpoint(endpoint: str) -> str:
    """执行归一化OTLPHTTP`traces``endpoint`。
    
    Normalize OTLP/HTTP traces endpoint.
    
        Accept:
        - base: http://host:4318
        - full: http://host:4318/v1/traces
    """
    raw = str(endpoint or "").strip()
    if not raw:
        return ""
    if raw.endswith(OTLP_HTTP_TRACES_PATH):
        return raw
    if OTLP_HTTP_TRACES_PATH in raw:
        return raw
    if raw.endswith("/"):
        return raw + "v1/traces"
    return raw + OTLP_HTTP_TRACES_PATH


def _get_otlp_traces_endpoint() -> str:
    # Beacon-preferred override (keeps repo docs stable and avoids surprising behavior
    # when OTEL_* env vars are used for something else).
    """获取OTLP`traces``endpoint`。"""
    endpoint = str(os.environ.get("BEACON_OTEL_OTLP_ENDPOINT", "") or "").strip()
    if endpoint:
        return _normalize_otlp_http_traces_endpoint(endpoint)

    # Standard OTel env vars compatibility (optional).
    endpoint = str(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "") or "").strip()
    if endpoint:
        return _normalize_otlp_http_traces_endpoint(endpoint)

    endpoint = str(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "") or "").strip()
    if endpoint:
        return _normalize_otlp_http_traces_endpoint(endpoint)

    return ""


def _load_otel_deps() -> Dict[str, Any]:
    """加载`otel``deps`。"""
    try:
        from opentelemetry import trace  # type: ignore
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
        from opentelemetry.instrumentation.django import DjangoInstrumentor  # type: ignore
        from opentelemetry.instrumentation.requests import RequestsInstrumentor  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased  # type: ignore
    except ImportError as e:
        return {"ok": False, "error": e}

    return {
        "ok": True,
        "trace": trace,
        "OTLPSpanExporter": OTLPSpanExporter,
        "DjangoInstrumentor": DjangoInstrumentor,
        "RequestsInstrumentor": RequestsInstrumentor,
        "Resource": Resource,
        "TracerProvider": TracerProvider,
        "BatchSpanProcessor": BatchSpanProcessor,
        "ParentBased": ParentBased,
        "TraceIdRatioBased": TraceIdRatioBased,
    }


def _get_service_version() -> str:
    """获取`service`版本。"""
    from django.conf import settings  # type: ignore

    try:
        return str(getattr(settings, "PROJECT_VERSION", "") or "").strip()
    except Exception:
        return ""


def _get_deployment_mode() -> str:
    """获取`deployment`模式。"""
    from app.utils.DeploymentMode import get_deployment_mode

    try:
        return str(get_deployment_mode() or "").strip()
    except Exception:
        return ""


def _clamp_ratio(value: float) -> float:
    """限制`ratio`。"""
    try:
        ratio = float(value)
    except Exception:
        ratio = 0.0
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


def _build_resource_attrs(*, service_name: str) -> Dict[str, Any]:
    """构建`resource``attrs`。"""
    service_version = _get_service_version()
    deployment_mode = _get_deployment_mode()
    return {
        "service.name": service_name,
        **({"service.version": service_version} if service_version else {}),
        **({"deployment.mode": deployment_mode} if deployment_mode else {}),
        "beacon.component": "admin",
    }


def _configure_otel(deps: Dict[str, Any], *, resource: Any, ratio: float) -> Tuple[bool, str, str]:
    """处理`configure``otel`。"""
    ok = True
    error = ""
    endpoint = ""
    try:
        sampler = deps["ParentBased"](deps["TraceIdRatioBased"](ratio))
        provider = deps["TracerProvider"](resource=resource, sampler=sampler)
        try:
            deps["trace"].set_tracer_provider(provider)
        except Exception:
            # If the provider is already set (another instrumentation), keep going.
            logger.debug("suppressed exception in app/utils/Otel.py:161", exc_info=True)

        endpoint = _get_otlp_traces_endpoint()
        exporter_kwargs: Dict[str, Any] = {}
        if endpoint:
            exporter_kwargs["endpoint"] = endpoint
        exporter = deps["OTLPSpanExporter"](**exporter_kwargs)
        provider.add_span_processor(deps["BatchSpanProcessor"](exporter))

        # Instrument incoming/outgoing HTTP.
        deps["DjangoInstrumentor"]().instrument()
        deps["RequestsInstrumentor"]().instrument()
    except Exception as e:
        ok = False
        error = str(e)
        logger.warning("opentelemetry init failed: %s", e)
    return bool(ok), error, endpoint


def init_otel() -> Dict[str, Any]:
    """处理`init``otel`。
    
    Best-effort OpenTelemetry init for Admin (Django).
    
        - Disabled by default (BEACON_OTEL_ENABLED=0).
        - If deps missing or init fails, startup continues (no crash).
        - Idempotent (safe to call multiple times).
    """
    global _INIT_DONE, _INIT_RESULT
    with _INIT_LOCK:
        enabled = _env_bool("BEACON_OTEL_ENABLED", default=False)
        if _INIT_DONE and isinstance(_INIT_RESULT, dict):
            # If the previous init result matches the current enable flag, treat as idempotent.
            # This keeps startup safe while allowing tests (or advanced callers) to toggle the
            # enable flag between calls.
            if bool(_INIT_RESULT.get("enabled")) == bool(enabled):
                return dict(_INIT_RESULT)

        if not enabled:
            _INIT_DONE = True
            _INIT_RESULT = {"ok": True, "enabled": False}
            return dict(_INIT_RESULT)

        deps = _load_otel_deps()
        if not deps.get("ok"):
            # Missing deps or incompatible environment. Keep best-effort behavior:
            # do not break startup.
            logger.warning("opentelemetry init skipped: %s", deps.get("error"))
            _INIT_DONE = True
            _INIT_RESULT = {"ok": False, "enabled": True, "error": "missing_deps"}
            return dict(_INIT_RESULT)

        # Build resource attributes.
        service_name = (
            str(os.environ.get("BEACON_OTEL_SERVICE_NAME", "") or "").strip()
            or str(os.environ.get("OTEL_SERVICE_NAME", "") or "").strip()
            or "beacon-admin"
        )

        resource = deps["Resource"].create(_build_resource_attrs(service_name=service_name))

        ratio = _clamp_ratio(_env_float("BEACON_OTEL_SAMPLE_RATIO", default=0.1))
        ok, error, endpoint = _configure_otel(deps, resource=resource, ratio=ratio)

        _INIT_DONE = True
        _INIT_RESULT = {
            "ok": bool(ok),
            "enabled": True,
            "service_name": service_name,
            "sample_ratio": float(ratio),
            "otlp_traces_endpoint": endpoint or _get_otlp_traces_endpoint(),
            **({"error": error} if error else {}),
        }
        return dict(_INIT_RESULT)
