import base64
import json
import math
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urlencode

import requests  # type: ignore


def _env_bool(name: str, default: bool = False) -> bool:
    """读取环境变量并转换为布尔值。"""
    raw = str(os.environ.get(name, "") or "").strip()
    raw = raw.lower()
    if not raw:
        return bool(default)
    return raw in ("1", "true", "yes", "y", "on")


def _env_str(name: str, default: str = "") -> str:
    """读取环境变量并转换为字符串。"""
    return str(os.environ.get(name, "") or default or "").strip()


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


def is_enabled() -> bool:
    """判断`is`是否启用。
    
    Generic OIDC SSO (authorization code flow) toggle.
    
        This is intentionally env-driven so the same Admin codebase can be used
        for industrial delivery across different customers/providers.
    """
    return _env_bool("BEACON_OIDC_ENABLED", default=False)


_PROVIDERS_CACHE: Dict[str, Any] = {"raw": "", "providers": {}}


def _sanitize_provider_id(raw: Any) -> str:
    """清洗提供方ID。"""
    try:
        v = str(raw or "").strip()
    except Exception:
        v = ""
    if not v:
        return ""
    if len(v) > 64:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", v):
        return ""
    return v


def _providers_cache_hit(raw: str):
    """处理`providers`缓存`hit`。"""
    if str(raw or "") != str(_PROVIDERS_CACHE.get("raw") or ""):
        return None
    cached = _PROVIDERS_CACHE.get("providers") or {}
    return cached if isinstance(cached, dict) else {}


def _load_providers() -> Dict[str, Dict[str, Any]]:
    """加载 OIDC Provider 配置。"""
    raw = _env_str("BEACON_OIDC_PROVIDERS_JSON", "")
    hit = _providers_cache_hit(raw)
    if hit is not None:
        return hit

    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        parsed = {}

    providers: Dict[str, Dict[str, Any]] = {}
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            provider_id = _sanitize_provider_id(key)
            if provider_id and isinstance(value, dict):
                providers[provider_id] = dict(value)
    _PROVIDERS_CACHE["raw"] = raw
    _PROVIDERS_CACHE["providers"] = providers
    return providers


def get_default_provider_id() -> str:
    """获取默认提供方ID。
    
    Default provider id only applies when multi-provider config exists.
    
        For legacy single-provider env config, return empty string so redirect_uri
        and endpoints remain backward compatible.
    """
    providers = _load_providers()
    if not providers:
        return ""

    explicit = _sanitize_provider_id(_env_str("BEACON_OIDC_PROVIDER_DEFAULT", ""))
    if explicit and explicit in providers:
        return explicit

    if "default" in providers:
        return "default"

    if len(providers) == 1:
        return next(iter(providers.keys()))

    return ""


def _provider_get(provider_id: str, key: str, default: Any = None) -> Any:
    """处理提供方`get`。"""
    pid = _sanitize_provider_id(provider_id)
    if not pid:
        return default
    cfg = _load_providers().get(pid)
    if not isinstance(cfg, dict):
        return default
    return cfg.get(key, default)


def _provider_bool(provider_id: str, key: str, default: bool) -> bool:
    """处理提供方布尔值。"""
    v = _provider_get(provider_id, key, None)
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return bool(v)
    s = str(v or "").strip()
    s = s.lower()
    if not s:
        return bool(default)
    return s in ("1", "true", "yes", "y", "on")


def _provider_str(provider_id: str, key: str, default: str) -> str:
    """处理提供方字符串。"""
    v = _provider_get(provider_id, key, None)
    if v is None:
        s = str(default or "").strip()
        return s
    s = str(v or "").strip()
    return s


def get_account_link_mode(provider_id: str = "") -> str:
    """获取`account``link`模式。
    
    Account linking policy for OIDC login.
    
        Values:
        - auto: (legacy) match existing user by username, then by email; otherwise create
        - username: match by username only; otherwise create
        - email: match by email only; otherwise create
        - create: never link to existing users; always create a new local user for new identities
        - deny: only allow login when an identity mapping already exists
    """
    raw = _provider_str(provider_id, "account_link_mode", _env_str("BEACON_OIDC_ACCOUNT_LINK_MODE", "auto"))
    mode = str(raw or "auto").strip().lower()
    if mode in ("auto", "username", "email", "create", "deny"):
        return mode
    return "auto"


def is_userinfo_enabled() -> bool:
    """判断`is`userinfo是否启用。
    
    Whether to call OIDC userinfo endpoint after token exchange.
    
        Some providers do not include stable/complete identity claims in id_token,
        or customers may require email/group claims from userinfo.
    """
    return _env_bool("BEACON_OIDC_USERINFO_ENABLED", default=False)


def is_nonce_required() -> bool:
    """判断`nonce``required`。"""
    return _env_bool("BEACON_OIDC_REQUIRE_NONCE", default=False)


def is_exp_required() -> bool:
    """判断`exp``required`。"""
    return _env_bool("BEACON_OIDC_REQUIRE_EXP", default=True)


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    """读取环境变量并转换为整数。"""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        value = int(default)
    else:
        try:
            value = int(float(raw))
        except Exception:
            value = int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _get_expected_issuer() -> str:
    """获取`expected``issuer`。"""
    raw = _env_str("BEACON_OIDC_ISSUER", "")
    return raw


def _get_jwks_uri() -> str:
    """获取JWKS`uri`。"""
    raw = _env_str("BEACON_OIDC_JWKS_URI", "")
    return raw


def _get_clock_skew_seconds() -> int:
    """获取`clock``skew`秒数。"""
    return _env_int("BEACON_OIDC_CLOCK_SKEW_SECONDS", 60, min_value=0, max_value=3600)


def _get_jwks_cache_seconds() -> int:
    """获取JWKS缓存秒数。"""
    return _env_int("BEACON_OIDC_JWKS_CACHE_SECONDS", 300, min_value=0, max_value=86400)


def is_userinfo_preferred() -> bool:
    """判断userinfo`preferred`。"""
    return _env_bool("BEACON_OIDC_USERINFO_PREFER", default=True)


def is_userinfo_enabled_for_provider(provider_id: str = "") -> bool:
    """判断userinfo启用`for`提供方。"""
    return _provider_bool(provider_id, "userinfo_enabled", is_userinfo_enabled())


def is_userinfo_preferred_for_provider(provider_id: str = "") -> bool:
    """判断userinfo`preferred``for`提供方。"""
    return _provider_bool(provider_id, "userinfo_prefer", is_userinfo_preferred())


def is_nonce_required_for_provider(provider_id: str = "") -> bool:
    """判断`nonce``required``for`提供方。"""
    return _provider_bool(provider_id, "require_nonce", is_nonce_required())


def is_exp_required_for_provider(provider_id: str = "") -> bool:
    """判断`exp``required``for`提供方。"""
    return _provider_bool(provider_id, "require_exp", is_exp_required())


def _get_max_token_age_seconds() -> int:
    """获取最大值令牌`age`秒数。"""
    return _env_int("BEACON_OIDC_MAX_TOKEN_AGE_SECONDS", 0, min_value=0, max_value=30 * 24 * 3600)


def _get_max_token_age_seconds_for_provider(provider_id: str = "") -> int:
    return _provider_int(
        provider_id,
        "max_token_age_seconds",
        _get_max_token_age_seconds(),
        min_value=0,
        max_value=30 * 24 * 3600,
    )


def _provider_int(
    provider_id: str,
    key: str,
    default: int,
    *,
    min_value: int,
    max_value: int,
) -> int:
    raw = _provider_get(provider_id, key, None)
    if raw is None:
        return int(default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(default)
    return max(min_value, min(max_value, value))


def _require_iat_when_max_age_enabled() -> bool:
    """判断需要`iat``when`最大值`age`是否启用。"""
    return _env_bool("BEACON_OIDC_REQUIRE_IAT_WHEN_MAX_AGE", default=True)


def _require_iat_when_max_age_enabled_for_provider(provider_id: str = "") -> bool:
    """获取提供方的需要`iat``when`最大值`age`启用。"""
    return _provider_bool(provider_id, "require_iat_when_max_age", _require_iat_when_max_age_enabled())


def _get_expected_issuer_for_provider(provider_id: str = "") -> str:
    """获取`expected``issuer``for`提供方。"""
    return _provider_str(provider_id, "issuer", _get_expected_issuer())


def _get_jwks_uri_for_provider(provider_id: str = "") -> str:
    """获取JWKS`uri``for`提供方。"""
    return _provider_str(provider_id, "jwks_uri", _get_jwks_uri())


def _get_clock_skew_seconds_for_provider(provider_id: str = "") -> int:
    return _provider_int(
        provider_id,
        "clock_skew_seconds",
        _get_clock_skew_seconds(),
        min_value=0,
        max_value=3600,
    )


def _get_jwks_cache_seconds_for_provider(provider_id: str = "") -> int:
    return _provider_int(
        provider_id,
        "jwks_cache_seconds",
        _get_jwks_cache_seconds(),
        min_value=0,
        max_value=86400,
    )


def _get_http_timeout_seconds_for_provider(provider_id: str = "") -> float:
    raw = _provider_get(provider_id, "http_timeout_seconds", None)
    if raw is None:
        return _env_float("BEACON_OIDC_HTTP_TIMEOUT_SECONDS", 8.0, min_value=1.0, max_value=60.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 8.0
    return max(1.0, min(60.0, value))


def _get_endpoints() -> Dict[str, str]:
    """获取`endpoints`。"""
    return {
        "authorization_endpoint": _env_str("BEACON_OIDC_AUTHORIZATION_ENDPOINT", ""),
        "token_endpoint": _env_str("BEACON_OIDC_TOKEN_ENDPOINT", ""),
        "userinfo_endpoint": _env_str("BEACON_OIDC_USERINFO_ENDPOINT", ""),
        "end_session_endpoint": _env_str("BEACON_OIDC_END_SESSION_ENDPOINT", ""),
    }


def _get_client() -> Dict[str, str]:
    """获取`client`。"""
    return {
        "client_id": _env_str("BEACON_OIDC_CLIENT_ID", ""),
        "client_secret": _env_str("BEACON_OIDC_CLIENT_SECRET", ""),
    }


def get_scope() -> str:
    """获取作用域。"""
    scope = _env_str("BEACON_OIDC_SCOPE", "openid email profile")
    return scope or "openid"


def _get_endpoints_for_provider(provider_id: str = "") -> Dict[str, str]:
    """获取`endpoints``for`提供方。"""
    return {
        "authorization_endpoint": _provider_str(provider_id, "authorization_endpoint", _env_str("BEACON_OIDC_AUTHORIZATION_ENDPOINT", "")),
        "token_endpoint": _provider_str(provider_id, "token_endpoint", _env_str("BEACON_OIDC_TOKEN_ENDPOINT", "")),
        "userinfo_endpoint": _provider_str(provider_id, "userinfo_endpoint", _env_str("BEACON_OIDC_USERINFO_ENDPOINT", "")),
        "end_session_endpoint": _provider_str(provider_id, "end_session_endpoint", _env_str("BEACON_OIDC_END_SESSION_ENDPOINT", "")),
    }


def _get_client_for_provider(provider_id: str = "") -> Dict[str, str]:
    """获取`client``for`提供方。"""
    return {
        "client_id": _provider_str(provider_id, "client_id", _env_str("BEACON_OIDC_CLIENT_ID", "")),
        "client_secret": _provider_str(provider_id, "client_secret", _env_str("BEACON_OIDC_CLIENT_SECRET", "")),
    }


def get_scope_for_provider(provider_id: str = "") -> str:
    """获取作用域`for`提供方。"""
    v = _provider_get(provider_id, "scope", None)
    if v is None:
        return get_scope() or "openid"
    scope = str(v or "").strip()
    if scope:
        return scope
    return get_scope() or "openid"


def _get_prompt_for_provider(provider_id: str = "") -> str:
    """获取`prompt``for`提供方。"""
    prompt = _provider_str(provider_id, "prompt", _env_str("BEACON_OIDC_PROMPT", ""))
    return str(prompt or "").strip()


def build_authorize_url(*, redirect_uri: str, state: str, nonce: str, provider_id: str = "") -> str:
    """构建`authorize`URL。"""
    endpoints = _get_endpoints_for_provider(provider_id)
    auth_endpoint = str(endpoints.get("authorization_endpoint") or "").strip()
    client = _get_client_for_provider(provider_id)
    client_id = str(client.get("client_id") or "").strip()

    if not (auth_endpoint and client_id and str(redirect_uri or "").strip()):
        return ""

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": get_scope_for_provider(provider_id),
        "redirect_uri": str(redirect_uri or "").strip(),
        "state": str(state or "").strip(),
        "nonce": str(nonce or "").strip(),
    }

    # Optional knobs for compatibility.
    prompt = _get_prompt_for_provider(provider_id)
    if prompt:
        params["prompt"] = prompt

    return f"{auth_endpoint}?{urlencode(params)}"


def exchange_code(*, code: str, redirect_uri: str, provider_id: str = "") -> Tuple[bool, Dict[str, Any]]:
    """处理`exchange`编码。
    
    Exchange authorization code to tokens.
    
        Returns: (ok, data)
        - ok=True: data is token response json
        - ok=False: data contains 'reason'
    """
    if not is_enabled():
        return False, {"reason": "disabled"}

    endpoints = _get_endpoints_for_provider(provider_id)
    token_endpoint = str(endpoints.get("token_endpoint") or "").strip()
    client = _get_client_for_provider(provider_id)
    client_id = str(client.get("client_id") or "").strip()
    client_secret = str(client.get("client_secret") or "").strip()

    if not (token_endpoint and client_id and client_secret):
        return False, {"reason": "missing_config"}

    payload = {
        "grant_type": "authorization_code",
        "code": str(code or "").strip(),
        "redirect_uri": str(redirect_uri or "").strip(),
        "client_id": client_id,
        "client_secret": client_secret,
    }
    timeout = _get_http_timeout_seconds_for_provider(provider_id)
    try:
        resp = requests.post(token_endpoint, data=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return False, {"reason": "invalid_token_response"}
        return True, data
    except requests.RequestException as exc:
        return False, {"reason": f"token_exchange_failed:{exc}"}
    except ValueError as exc:
        return False, {"reason": f"token_exchange_failed:{exc}"}


def fetch_userinfo(*, access_token: str, provider_id: str = "") -> Tuple[bool, Dict[str, Any]]:
    """获取userinfo。
    
    Fetch userinfo data from provider (best-effort).
    """
    if not is_enabled():
        return False, {"reason": "disabled"}

    endpoints = _get_endpoints_for_provider(provider_id)
    endpoint = str(endpoints.get("userinfo_endpoint") or "").strip()
    if not endpoint:
        return False, {"reason": "missing_userinfo_endpoint"}

    token = str(access_token or "").strip()
    if not token:
        return False, {"reason": "missing_access_token"}

    timeout = _get_http_timeout_seconds_for_provider(provider_id)
    try:
        resp = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return False, {"reason": "invalid_userinfo_response"}
        return True, data
    except requests.RequestException as exc:
        return False, {"reason": f"userinfo_failed:{exc}"}
    except ValueError as exc:
        return False, {"reason": f"userinfo_failed:{exc}"}


def _b64url_decode(data: str) -> bytes:
    """处理`b64url``decode`。"""
    s = str(data or "").strip()
    if not s:
        return b""
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + padding).encode("ascii"))


def _b64url_decode_json(data: str) -> Dict[str, Any]:
    """返回`b64url``decode`JSON。"""
    raw = _b64url_decode(data)
    if not raw:
        return {}
    try:
        loaded = json.loads(raw.decode("utf-8", errors="replace"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


_JWKS_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_cached_jwks(jwks_uri: str) -> Dict[str, Any]:
    """获取`cached`JWKS。"""
    uri = str(jwks_uri or "").strip()
    if not uri:
        return {}
    entry = _JWKS_CACHE.get(uri) or {}
    try:
        expires_at = float(entry.get("expires_at") or 0.0)
    except Exception:
        expires_at = 0.0
    if expires_at > time.time():
        jwks = entry.get("jwks") or {}
        return jwks if isinstance(jwks, dict) else {}
    return {}


def _fetch_jwks(jwks_uri: str, *, provider_id: str = "") -> Tuple[bool, Dict[str, Any]]:
    """获取JWKS。"""
    uri = str(jwks_uri or "").strip()
    if not uri:
        return False, {"reason": "missing_jwks_uri"}

    cached = _get_cached_jwks(uri)
    if cached:
        return True, cached

    timeout = _get_http_timeout_seconds_for_provider(provider_id)
    try:
        resp = requests.get(uri, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return False, {"reason": "invalid_jwks_response"}
        keys = data.get("keys")
        if not isinstance(keys, list):
            return False, {"reason": "invalid_jwks_keys"}
        ttl = float(_get_jwks_cache_seconds_for_provider(provider_id))
        _JWKS_CACHE[uri] = {"expires_at": time.time() + ttl, "jwks": data}
        return True, data
    except requests.RequestException as exc:
        return False, {"reason": f"jwks_fetch_failed:{exc}"}
    except ValueError as exc:
        return False, {"reason": f"jwks_fetch_failed:{exc}"}


def _select_jwk(jwks: Dict[str, Any], *, kid: str) -> Dict[str, Any]:
    """选择`jwk`。"""
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        return {}
    if kid:
        for k in keys:
            if isinstance(k, dict) and str(k.get("kid") or "") == kid:
                return k
        return {}
    # No kid: try single-key jwks.
    if len(keys) == 1 and isinstance(keys[0], dict):
        return keys[0]
    return {}


def _public_key_from_jwk(jwk: Dict[str, Any]):
    """从`jwk`获取公共键。
    
    Convert a JWK (RSA) to a cryptography public key.
        Supports:
        - n/e public numbers
        - x5c leaf certificate
    """
    if not isinstance(jwk, dict):
        return None
    if str(jwk.get("kty") or "").upper() != "RSA":
        return None

    n = str(jwk.get("n") or "").strip()
    e = str(jwk.get("e") or "").strip()
    if n and e:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

        try:
            n_int = int.from_bytes(_b64url_decode(n), "big")
            e_int = int.from_bytes(_b64url_decode(e), "big")
            return RSAPublicNumbers(e_int, n_int).public_key()
        except Exception:
            return None

    x5c = jwk.get("x5c")
    if isinstance(x5c, list) and x5c:
        from cryptography import x509

        try:
            cert_der = base64.b64decode(str(x5c[0] or "").encode("ascii"))
            cert = x509.load_der_x509_certificate(cert_der)
            return cert.public_key()
        except Exception:
            # Some providers might return PEM-like values; ignore.
            return None

    return None


def _group_values(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _unique_strings(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def _oidc_validate_issuer_claim(claims: Dict[str, Any], *, provider_id: str = "") -> str:
    """处理OIDC`validate``issuer`声明。"""
    expected_issuer = _get_expected_issuer_for_provider(provider_id)
    if not expected_issuer:
        return ""
    if str(claims.get("iss") or "").strip() == expected_issuer:
        return ""
    return "iss_mismatch"


def _oidc_validate_audience_claim(claims: Dict[str, Any], *, provider_id: str = "") -> str:
    client_id = str(_get_client_for_provider(provider_id).get("client_id") or "").strip()
    if not client_id:
        return ""

    audience = claims.get("aud")
    if isinstance(audience, str):
        return "" if audience == client_id else "aud_mismatch"
    if isinstance(audience, list):
        return "" if client_id in audience else "aud_mismatch"
    return "aud_missing"


def _oidc_claim_timestamp(claims: Dict[str, Any], name: str) -> int:
    raw = claims.get(name)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    if not math.isfinite(float(raw)):
        return 0
    return int(raw)


def _oidc_validate_exp_claim(exp: int, *, provider_id: str = "", now_ts: int, skew: int) -> str:
    """处理OIDC`validate``exp`声明。"""
    if exp <= 0 and is_exp_required_for_provider(provider_id):
        return "jwt_exp_missing"
    if exp and now_ts > int(exp) + int(skew):
        return "jwt_expired"
    return ""


def _oidc_validate_nbf_claim(nbf: int, *, exp: int, now_ts: int, skew: int) -> str:
    """处理OIDC`validate``nbf`声明。"""
    if not nbf:
        return ""
    if exp and int(nbf) > int(exp):
        return "jwt_nbf_after_exp"
    if now_ts + int(skew) < int(nbf):
        return "jwt_not_yet_valid"
    return ""


def _oidc_validate_iat_claim(iat: int, *, exp: int, provider_id: str = "", now_ts: int, skew: int) -> str:
    """处理OIDC`validate``iat`声明。"""
    max_age = int(_get_max_token_age_seconds_for_provider(provider_id) or 0)
    if (not iat) and max_age > 0 and _require_iat_when_max_age_enabled_for_provider(provider_id):
        return "jwt_iat_missing_for_max_age"
    if not iat:
        return ""
    if exp and int(iat) > int(exp):
        return "jwt_iat_after_exp"
    if now_ts + int(skew) < int(iat):
        return "jwt_issued_in_future"
    if max_age > 0 and now_ts > int(iat) + int(max_age) + int(skew):
        return "jwt_too_old"
    return ""


def _oidc_validate_time_claims(claims: Dict[str, Any], *, provider_id: str = "") -> str:
    """处理OIDC`validate`时间`claims`。"""
    skew = int(_get_clock_skew_seconds_for_provider(provider_id) or 0)
    now_ts = int(time.time())
    exp = _oidc_claim_timestamp(claims, "exp")
    exp_reason = _oidc_validate_exp_claim(
        exp,
        provider_id=provider_id,
        now_ts=now_ts,
        skew=skew,
    )
    if exp_reason:
        return exp_reason

    nbf = _oidc_claim_timestamp(claims, "nbf")
    nbf_reason = _oidc_validate_nbf_claim(
        nbf,
        exp=exp,
        now_ts=now_ts,
        skew=skew,
    )
    if nbf_reason:
        return nbf_reason

    iat = _oidc_claim_timestamp(claims, "iat")
    return _oidc_validate_iat_claim(
        iat,
        exp=exp,
        provider_id=provider_id,
        now_ts=now_ts,
        skew=skew,
    )


def _oidc_validate_nonce_claim(claims: Dict[str, Any], *, expected_nonce: str = "", provider_id: str = "") -> str:
    expected = str(expected_nonce or "").strip()
    nonce = claims.get("nonce") if isinstance(claims.get("nonce"), str) else ""
    if is_nonce_required_for_provider(provider_id):
        return "" if expected and nonce == expected else "nonce_mismatch"
    if expected and nonce and nonce != expected:
        return "nonce_mismatch"
    return ""


def _oidc_token_parts(id_token: str) -> Tuple[List[str], str]:
    """处理OIDC令牌`parts`。"""
    token = str(id_token or "").strip()
    parts = token.split(".")
    if len(parts) != 3:
        return [], "invalid_jwt_format"
    return parts, ""


def _oidc_validate_jwt_header(parts: List[str]) -> Tuple[Dict[str, Any], str]:
    """处理OIDC`validate``jwt`请求头。"""
    header = _b64url_decode_json(parts[0])
    alg = str(header.get("alg") or "").strip()
    if not alg or alg.lower() == "none":
        return {}, "jwt_alg_not_allowed"
    if alg.upper() != "RS256":
        return {}, "jwt_alg_unsupported"
    return header, ""


def _oidc_verify_jwt_signature(parts: List[str], *, provider_id: str = "", kid: str = "") -> Tuple[bool, Dict[str, Any]]:
    """返回OIDC`verify``jwt`签名。"""
    signature = _b64url_decode(parts[2])
    if not signature:
        return False, {"reason": "jwt_signature_missing"}

    jwks_uri = _get_jwks_uri_for_provider(provider_id)
    ok, jwks = _fetch_jwks(jwks_uri, provider_id=provider_id)
    if not ok:
        return False, jwks

    jwk = _select_jwk(jwks, kid=kid)
    if not jwk:
        return False, {"reason": "jwk_not_found"}

    public_key = _public_key_from_jwk(jwk)
    if not public_key:
        return False, {"reason": "jwk_unsupported"}

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return False, {"reason": "jwt_signature_invalid"}
    return True, {}


def verify_and_parse_id_token(id_token: str, *, expected_nonce: str = "", provider_id: str = "") -> Tuple[bool, Dict[str, Any]]:
    """验证`and``parse`ID令牌。
    
    Verify id_token signature against provider JWKS (RS256) and parse claims.
    
        Returns: (ok, claims_or_error_info)
    """
    parts, parts_reason = _oidc_token_parts(id_token)
    if parts_reason:
        return False, {"reason": parts_reason}

    header, header_reason = _oidc_validate_jwt_header(parts)
    if header_reason:
        return False, {"reason": header_reason}

    kid = str(header.get("kid") or "").strip()
    signature_ok, signature_error = _oidc_verify_jwt_signature(
        parts,
        provider_id=provider_id,
        kid=kid,
    )
    if not signature_ok:
        return False, signature_error

    claims = _b64url_decode_json(parts[1])
    if not claims:
        return False, {"reason": "invalid_jwt_payload"}

    issuer_reason = _oidc_validate_issuer_claim(claims, provider_id=provider_id)
    if issuer_reason:
        return False, {"reason": issuer_reason}

    audience_reason = _oidc_validate_audience_claim(claims, provider_id=provider_id)
    if audience_reason:
        return False, {"reason": audience_reason}

    time_reason = _oidc_validate_time_claims(claims, provider_id=provider_id)
    if time_reason:
        return False, {"reason": time_reason}

    nonce_reason = _oidc_validate_nonce_claim(
        claims,
        expected_nonce=expected_nonce,
        provider_id=provider_id,
    )
    if nonce_reason:
        return False, {"reason": nonce_reason}

    return True, claims


def extract_user_from_claims(claims: Dict[str, Any]) -> Dict[str, str]:
    """提取用户`from``claims`。
    
    Map OIDC claims/userinfo payload to local user identity fields.
    """
    def _norm_text(v: Any, *, max_len: int) -> str:
        """处理`norm`文本。"""
        try:
            s = str(v or "")
        except Exception:
            s = ""
        try:
            s = unicodedata.normalize("NFKC", s)
        except Exception:
            s = str(s or "")
        s = s.strip().replace("\r", "").replace("\n", "")
        if len(s) > int(max_len):
            s = s[: int(max_len)]
        return s

    claims = claims if isinstance(claims, dict) else {}
    email = _norm_text(claims.get("email"), max_len=254).lower()
    preferred_username = _norm_text(claims.get("preferred_username"), max_len=150)
    sub = _norm_text(claims.get("sub"), max_len=255)

    username = preferred_username
    if not username and email and "@" in email:
        username = email.split("@", 1)[0]
    if not username:
        username = sub
    username = _norm_text(username, max_len=150)

    return {
        "username": username,
        "email": email,
        "sub": sub,
    }


def extract_groups_from_claims(claims: Dict[str, Any]) -> List[str]:
    """Extract standard group claims and Keycloak role claims."""
    if not isinstance(claims, dict):
        return []

    groups: List[str] = []
    for key in ("groups", "roles", "role", "cognito:groups"):
        groups.extend(_group_values(claims.get(key)))

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        groups.extend(_group_values(realm_access.get("roles")))

    resource_access = claims.get("resource_access")
    if isinstance(resource_access, dict):
        for entry in resource_access.values():
            if isinstance(entry, dict):
                groups.extend(_group_values(entry.get("roles")))

    return _unique_strings(groups)


def _csv_set(raw: str) -> Set[str]:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def get_staff_groups(provider_id: str = "") -> Set[str]:
    """获取`staff``groups`。"""
    raw = _provider_get(provider_id, "staff_groups", None)
    if isinstance(raw, list):
        return {str(x or "").strip().lower() for x in raw if str(x or "").strip()}
    if isinstance(raw, str):
        return {str(x or "").strip().lower() for x in _csv_set(raw)}
    return {str(x or "").strip().lower() for x in _csv_set(_env_str("BEACON_OIDC_STAFF_GROUPS", ""))}


def get_superuser_groups(provider_id: str = "") -> Set[str]:
    """获取`superuser``groups`。"""
    raw = _provider_get(provider_id, "superuser_groups", None)
    if isinstance(raw, list):
        return {str(x or "").strip().lower() for x in raw if str(x or "").strip()}
    if isinstance(raw, str):
        return {str(x or "").strip().lower() for x in _csv_set(raw)}
    return {str(x or "").strip().lower() for x in _csv_set(_env_str("BEACON_OIDC_SUPERUSER_GROUPS", ""))}


def get_required_groups(provider_id: str = "") -> Set[str]:
    """获取`required``groups`。
    
    Optional hard gate for OIDC SSO.
    
        If configured, the user must have at least one group in this set,
        otherwise the callback should deny the login (403).
    
        Env: BEACON_OIDC_REQUIRED_GROUPS=group1,group2
        Provider override: required_groups (string CSV or list)
    """
    raw = _provider_get(provider_id, "required_groups", None)
    if isinstance(raw, list):
        return {str(x or "").strip().lower() for x in raw if str(x or "").strip()}
    if isinstance(raw, str):
        return {str(x or "").strip().lower() for x in _csv_set(raw)}
    return {str(x or "").strip().lower() for x in _csv_set(_env_str("BEACON_OIDC_REQUIRED_GROUPS", ""))}


def sync_user_flags_enabled(provider_id: str = "") -> bool:
    """判断`sync`用户标记集合是否启用。"""
    return _provider_bool(provider_id, "sync_user_flags", _env_bool("BEACON_OIDC_SYNC_USER_FLAGS", default=True))


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """解析 JSON 对象。"""
    s = str(raw or "").strip()
    if not s:
        return {}
    try:
        loaded = json.loads(s)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def get_permissions_by_group(provider_id: str = "") -> Dict[str, Dict[str, Any]]:
    """获取`permissions``by`分组。"""
    v = _provider_get(provider_id, "permissions_by_group", None)
    if isinstance(v, dict):
        out: Dict[str, Dict[str, Any]] = {}
        for k, item in v.items():
            if not k or not isinstance(item, dict):
                continue
            out[str(k).strip().lower()] = dict(item)
        return out

    loaded = _parse_json_object(_env_str("BEACON_OIDC_PERMISSIONS_BY_GROUP_JSON", ""))
    out2: Dict[str, Dict[str, Any]] = {}
    for k, item in loaded.items():
        if not k or not isinstance(item, dict):
            continue
        out2[str(k).strip().lower()] = dict(item)
    return out2


def sync_user_permissions_enabled(provider_id: str = "") -> bool:
    """判断`sync`用户`permissions`是否启用。"""
    return _provider_bool(provider_id, "sync_user_permissions", _env_bool("BEACON_OIDC_SYNC_USER_PERMISSIONS", default=False))


def build_permissions_from_groups(groups: List[str], *, provider_id: str = "") -> Dict[str, bool]:
    """构建`permissions``from``groups`。
    
    Build a permission allowlist (UserPermission.permissions_json) from groups.
    
        Merge strategy:
        - treat each group mapping as a "grant list"
        - merge grants with OR (true wins)
        - absence means deny (when a non-empty permission record is present)
    """
    groups = groups if isinstance(groups, list) else []
    mapping = get_permissions_by_group(provider_id)
    out: Dict[str, bool] = {}

    for g in groups:
        rule = mapping.get(str(g or "").strip().lower())
        if not isinstance(rule, dict):
            continue
        for k, v in rule.items():
            key = str(k or "").strip()
            if not key:
                continue
            if v is True:
                out[key] = True
    return out


def build_end_session_url(*, id_token_hint: str, post_logout_redirect_uri: str = "", provider_id: str = "") -> str:
    """构建`end`会话URL。"""
    endpoints = _get_endpoints_for_provider(provider_id)
    end_session = str(endpoints.get("end_session_endpoint") or "").strip()
    if not end_session:
        return ""
    params = {"id_token_hint": str(id_token_hint or "").strip()}
    if str(post_logout_redirect_uri or "").strip():
        params["post_logout_redirect_uri"] = str(post_logout_redirect_uri or "").strip()
    return f"{end_session}?{urlencode(params)}"
