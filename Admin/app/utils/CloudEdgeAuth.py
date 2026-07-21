import hashlib
import os
from typing import Any, Dict


def _get_edge_token_pepper() -> str:
    """获取边缘令牌`pepper`。"""
    return str(os.environ.get("BEACON_CLOUD_EDGE_TOKEN_PEPPER", "") or "").strip()


def hash_edge_token(token: str) -> str:
    """返回哈希边缘令牌。
    
    Hash edge bearer token for storage/compare.
    
        Storage policy:
        - Cloud only stores hash (not plaintext token)
        - hash = sha256(pepper + token)
    """
    pepper = _get_edge_token_pepper()
    raw = (pepper + str(token or "")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def get_bearer_token(request: Any) -> str:
    """获取`bearer`令牌。"""
    auth = str(getattr(request, "META", {}).get("HTTP_AUTHORIZATION", "") or "").strip()
    if not auth:
        return ""
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return ""
    if parts[0].strip().lower() != "bearer":
        return ""
    return str(parts[1] or "").strip()


def authenticate_edge_request(request: Any) -> Dict[str, Any]:
    """处理`authenticate`边缘请求。
    
    Authenticate an EdgeCluster request using Authorization: Bearer <edge_token>.
    
        Returns:
          {
            "ok": bool,
            "cluster": CloudEdgeCluster|None,
            "error": str,
            "status_code": int,
          }
    """
    token = get_bearer_token(request)
    if not token:
        return {"ok": False, "cluster": None, "error": "missing bearer token", "status_code": 401}

    pepper = _get_edge_token_pepper()
    if not pepper:
        return {
            "ok": False,
            "cluster": None,
            "error": "server misconfigured: missing BEACON_CLOUD_EDGE_TOKEN_PEPPER",
            "status_code": 500,
        }

    from app.models import CloudEdgeCluster

    token_hash = hash_edge_token(token)
    try:
        cluster = CloudEdgeCluster.objects.filter(edge_token_hash=token_hash).first()
    except Exception:
        cluster = None

    if not cluster:
        return {"ok": False, "cluster": None, "error": "invalid bearer token", "status_code": 401}

    if not bool(getattr(cluster, "enabled", False)):
        return {"ok": False, "cluster": cluster, "error": "cluster disabled", "status_code": 403}

    return {"ok": True, "cluster": cluster, "error": "", "status_code": 200}

