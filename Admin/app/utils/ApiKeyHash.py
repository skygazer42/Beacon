import hashlib
import hmac
import os


def _api_key_pepper() -> bytes:
    return str(os.environ.get("BEACON_API_KEY_PEPPER", "") or "").encode("utf-8")


def require_api_key_pepper_for_production() -> None:
    """Fail closed before issuing keys when production pepper is missing or weak."""

    debug_raw = str(os.environ.get("BEACON_DJANGO_DEBUG", "1") or "").strip().lower()
    if debug_raw in ("1", "true", "yes", "y", "on"):
        return
    if len(_api_key_pepper()) < 32:
        raise ValueError("API key pepper is not configured for production")


def hash_api_key_token(token: str) -> str:
    """Return the current keyed digest for a high-entropy API token."""

    raw_token = str(token or "").encode("utf-8")
    return hmac.new(_api_key_pepper(), raw_token, hashlib.sha256).hexdigest()


def legacy_hash_api_key_token(token: str) -> str:
    """Return the pre-v1.1 digest so existing rows can be migrated on use."""

    raw = _api_key_pepper() + str(token or "").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
