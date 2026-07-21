import os


def get_deployment_mode() -> str:
    """获取`deployment`模式。"""
    raw = str(os.environ.get("BEACON_DEPLOYMENT_MODE", "") or "").strip().lower()
    if raw in ("cloud", "saas"):
        return "cloud"
    return "edge"


def is_cloud_mode() -> bool:
    """判断云端模式。"""
    return get_deployment_mode() == "cloud"


def is_edge_mode() -> bool:
    """判断边缘模式。"""
    return get_deployment_mode() == "edge"
