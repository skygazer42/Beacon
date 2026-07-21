import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse


def normalize_secret(secret: str) -> str:
    """执行归一化`secret`。"""
    value = str(secret or "").strip().replace(" ", "").upper()
    return value


def generate_totp_secret(num_bytes: int = 20) -> str:
    """生成TOTP`secret`。"""
    size = int(num_bytes or 20)
    if size < 10:
        size = 10
    if size > 64:
        size = 64
    raw = secrets.token_bytes(size)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    """处理`decode``secret`。"""
    value = normalize_secret(secret)
    if not value:
        raise ValueError("secret is empty")
    padded = value + ("=" * ((8 - (len(value) % 8)) % 8))
    return base64.b32decode(padded, casefold=True)


def generate_hotp_code(secret: str, counter: int, *, digits: int = 6, digest: str = "sha1") -> str:
    """生成`hotp`编码。"""
    try:
        counter_int = int(counter)
    except Exception:
        counter_int = 0
    if counter_int < 0:
        counter_int = 0

    size = int(digits or 6)
    if size < 6:
        size = 6
    if size > 10:
        size = 10

    key = _decode_secret(secret)
    counter_bytes = struct.pack(">Q", counter_int)
    digest_name = str(digest or "sha1").lower()
    if digest_name not in ("sha1", "sha256", "sha512"):
        digest_name = "sha1"
    digest_fn = getattr(hashlib, digest_name)
    h = hmac.new(key, counter_bytes, digest_fn).digest()
    offset = h[-1] & 0x0F
    binary = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    code = binary % (10 ** size)
    return str(code).zfill(size)


def generate_totp_code(secret: str, *, for_time=None, period: int = 30, digits: int = 6, digest: str = "sha1") -> str:
    """生成TOTP编码。"""
    try:
        ts = int(for_time if for_time is not None else time.time())
    except Exception:
        ts = int(time.time())
    step = int(period or 30)
    if step < 15:
        step = 15
    if step > 300:
        step = 300
    counter = ts // step
    return generate_hotp_code(secret, counter, digits=digits, digest=digest)


def verify_totp(secret: str, code: str, *, at_time=None, period: int = 30, window: int = 1, digits: int = 6, digest: str = "sha1") -> bool:
    """验证TOTP。"""
    candidate = str(code or "").strip()
    if not candidate:
        return False
    try:
        ts = int(at_time if at_time is not None else time.time())
    except Exception:
        ts = int(time.time())
    try:
        win = int(window or 0)
    except Exception:
        win = 0
    if win < 0:
        win = 0
    step = int(period or 30)
    if step < 15:
        step = 15
    if step > 300:
        step = 300
    counter = ts // step
    for delta in range(-win, win + 1):
        if generate_hotp_code(secret, counter + delta, digits=digits, digest=digest) == candidate:
            return True
    return False


def build_otpauth_uri(secret: str, *, account_name: str, issuer: str = "Beacon") -> str:
    """构建`otpauth``uri`。"""
    secret_norm = normalize_secret(secret)
    label = urllib.parse.quote(f"{issuer}:{account_name}")
    issuer_q = urllib.parse.quote(str(issuer or "Beacon"))
    return f"otpauth://totp/{label}?secret={secret_norm}&issuer={issuer_q}"
