import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.utils.OSSystem import OSSystem


def _now_utc() -> datetime:
    """处理当前时间`utc`。"""
    return datetime.now(timezone.utc)


def _parse_iso8601(value: Any) -> Optional[datetime]:
    """解析`iso8601`。"""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Support "...Z"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """处理`to``utc``naive`。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive as UTC by convention for license payload.
        return dt
    try:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return dt.replace(tzinfo=None)


def _normalize_license_edition(value: Any) -> str:
    """执行归一化授权`edition`。"""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if re.match(r"^[a-z0-9][a-z0-9_-]{0,49}$", raw):
        return raw
    return ""


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """处理`coerce`布尔值。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if not text:
        return default
    if text in ("1", "true", "yes", "on", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disabled"):
        return False
    return default


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """限制整数值。"""
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def extract_license_runtime_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """提取授权运行时策略。"""
    if not isinstance(payload, dict):
        payload = {}

    edition = _normalize_license_edition(payload.get("edition"))
    raw_policy = payload.get("thread_priority_policy")

    if edition == "ordinary":
        policy = {"enabled": True, "first_n_active_streams": 20, "nice_value": -5}
    else:
        policy = {"enabled": False, "first_n_active_streams": 0, "nice_value": 0}

    if isinstance(raw_policy, dict):
        policy["enabled"] = _coerce_bool(raw_policy.get("enabled"), default=policy["enabled"])
        policy["first_n_active_streams"] = _clamp_int(
            raw_policy.get("first_n_active_streams"),
            default=policy["first_n_active_streams"],
            minimum=0,
            maximum=1024,
        )
        policy["nice_value"] = _clamp_int(
            raw_policy.get("nice_value"),
            default=policy["nice_value"],
            minimum=-20,
            maximum=19,
        )

    if policy["first_n_active_streams"] <= 0 or not bool(policy["enabled"]):
        policy["enabled"] = False
        policy["first_n_active_streams"] = max(0, int(policy["first_n_active_streams"] or 0))
        policy["nice_value"] = 0

    return {"edition": edition, "thread_priority_policy": policy}


def extract_license_runtime_policy_from_json(raw: Any) -> Dict[str, Any]:
    """提取授权运行时策略`from`JSON。"""
    if not raw:
        return extract_license_runtime_policy({})
    try:
        payload = json.loads(str(raw))
    except Exception:
        payload = {}
    return extract_license_runtime_policy(payload)


def canonical_license_message(payload: Dict[str, Any]) -> bytes:
    """返回`canonical`授权`message`。
    
    Canonicalize license payload for signature verification:
        - Remove `signature` field
        - JSON: sort keys, no whitespace, UTF-8
    """
    if not isinstance(payload, dict):
        payload = {}

    data = dict(payload)
    data.pop("signature", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def get_current_cluster_id() -> str:
    """获取`current`集群ID。
    
    Get the cluster binding id for this deployment.
        Priority:
        1) BEACON_CLUSTER_ID (explicit; recommended for K8s via Secret/PVC)
        2) Derived fingerprint (best-effort) from host characteristics
    """
    env_value = str(os.environ.get("BEACON_CLUSTER_ID", "") or "").strip()
    if env_value:
        return env_value

    os_system = OSSystem()
    parts = [
        os_system.get_machine_node(),
        os_system.get_machine_cpu(),
        "%012x" % uuid.getnode(),
        os_system.get_machine_os_release(),
    ]
    raw = "|".join([str(p or "") for p in parts])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _license_fail(result: Dict[str, Any], error_code: str, error_message: str) -> Dict[str, Any]:
    """处理授权失败。"""
    result["error_code"] = str(error_code or "")
    result["error_message"] = str(error_message or "")
    return result


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """处理`ensure``utc`。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def _validate_license_signature(payload: Dict[str, Any], *, public_key_b64: str) -> tuple[str, str]:
    """校验授权签名。"""
    signature = payload.get("signature")
    if not isinstance(signature, dict):
        return "missing_signature", "signature is required"

    alg = str(signature.get("alg", "") or "").strip().lower()
    if alg != "ed25519":
        return "unsupported_signature", "unsupported signature alg"

    sig_b64 = str(signature.get("sig", "") or "").strip()
    if not sig_b64:
        return "bad_signature", "signature is empty"

    try:
        sig_bytes = base64.b64decode(sig_b64, validate=True)
    except Exception:
        return "bad_signature", "signature base64 decode failed"

    try:
        pub_bytes = base64.b64decode(str(public_key_b64 or ""), validate=True)
    except Exception:
        return "bad_public_key", "public key base64 decode failed"

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
        message = canonical_license_message(payload)
        pub.verify(sig_bytes, message)
    except Exception:
        return "bad_signature", "signature verify failed"

    return "", ""


def _validate_license_time_window(payload: Dict[str, Any], *, now_dt: datetime) -> tuple[Optional[datetime], Optional[datetime], str, str]:
    """校验授权时间窗口。"""
    not_before = _ensure_utc(_parse_iso8601(payload.get("not_before")))
    not_after = _ensure_utc(_parse_iso8601(payload.get("not_after")))

    if not_before and now_dt < not_before:
        return not_before, not_after, "license_not_yet_valid", "license not yet valid"

    if not_after and now_dt > not_after:
        return not_before, not_after, "license_expired", "license expired"

    return not_before, not_after, "", ""


def _parse_license_package_limits(payload: Dict[str, Any]) -> Dict[str, Any]:
    """解析授权打包`limits`。"""
    raw_package_limits = payload.get("package_limits")
    if not isinstance(raw_package_limits, dict):
        return {}

    package_limits: Dict[str, Any] = {}
    for pkg, limits in raw_package_limits.items():
        pkg_name = str(pkg or "").strip()
        if not pkg_name:
            continue
        if not isinstance(limits, dict):
            continue
        max_active_controls = limits.get("max_active_controls", 0)
        try:
            max_active_controls = int(max_active_controls)
        except Exception:
            max_active_controls = 0
        package_limits[pkg_name] = {"max_active_controls": max_active_controls}

    return package_limits


def validate_license_payload(
    payload: Dict[str, Any],
    *,
    public_key_b64: str,
    expected_cluster_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """校验授权载荷。
    
    Validate a license payload:
        - signature present and valid (Ed25519)
        - cluster_id matches expected_cluster_id (if provided)
        - not_before / not_after time window
    
        Returns a dict:
        - ok: bool
        - error_code: str (empty when ok)
        - error_message: str
        - parsed fields (best-effort)
    """
    result: Dict[str, Any] = {
        "ok": False,
        "error_code": "",
        "error_message": "",
    }

    if not isinstance(payload, dict):
        return _license_fail(result, "malformed", "payload must be a dict")

    error_code, error_message = _validate_license_signature(payload, public_key_b64=public_key_b64)
    if error_code:
        return _license_fail(result, error_code, error_message)

    cluster_id = str(payload.get("cluster_id", "") or "").strip()
    if expected_cluster_id is not None and cluster_id != str(expected_cluster_id):
        return _license_fail(result, "cluster_mismatch", "cluster_id mismatch")

    now_dt = now or _now_utc()
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    not_before, not_after, error_code, error_message = _validate_license_time_window(payload, now_dt=now_dt)
    if error_code:
        return _license_fail(result, error_code, error_message)

    package_limits = _parse_license_package_limits(payload)

    result.update(
        {
            "ok": True,
            "license_id": str(payload.get("license_id", "") or "").strip(),
            "customer": str(payload.get("customer", "") or "").strip(),
            "cluster_id": cluster_id,
            "not_before": _to_utc_naive(not_before),
            "not_after": _to_utc_naive(not_after),
            "limits": payload.get("limits") if isinstance(payload.get("limits"), dict) else {},
            "packages": payload.get("packages") if isinstance(payload.get("packages"), list) else [],
            "package_limits": package_limits,
        }
    )
    result.update(extract_license_runtime_policy(payload))
    return result
