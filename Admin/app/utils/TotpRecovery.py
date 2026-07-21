import base64
import secrets
from datetime import datetime
from typing import List

from django.contrib.auth.hashers import check_password, make_password

from app import models as app_models


def normalize_recovery_code(code: str) -> str:
    """执行归一化`recovery`编码。
    
    Normalize user input / generated recovery codes for storage & comparison.
    
        - strip spaces/separators
        - uppercase
        - keep only alnum
    """
    raw = str(code or "").strip().upper()
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isalnum())


def generate_recovery_codes(*, count: int = 10, bytes_per_code: int = 10, group: int = 4) -> List[str]:
    """生成`recovery`编码列表。
    
    Generate display-friendly recovery codes.
    
        Default params yield base32 codes with enough entropy for one-time fallback
        (and are still typeable for humans).
    """
    try:
        n = int(count)
    except Exception:
        n = 10
    n = max(1, min(50, n))

    try:
        size = int(bytes_per_code)
    except Exception:
        size = 10
    size = max(8, min(32, size))

    try:
        group_size = int(group)
    except Exception:
        group_size = 4
    group_size = max(0, min(8, group_size))

    out: List[str] = []
    for _ in range(n):
        raw = secrets.token_bytes(size)
        base = base64.b32encode(raw).decode("ascii").rstrip("=")
        normalized = normalize_recovery_code(base)
        if group_size > 0:
            parts = [normalized[i : i + group_size] for i in range(0, len(normalized), group_size)]
            out.append("-".join([p for p in parts if p]))
        else:
            out.append(normalized)
    return out


def replace_recovery_codes_for_user(user, *, count: int = 10) -> List[str]:
    """获取用户的`replace``recovery`编码列表。
    
    Replace (delete + generate) recovery codes for user.
    
        Returns plaintext codes (display-only). Persisted records store hashes only.
    """
    model = getattr(app_models, "UserTotpRecoveryCode", None)
    if not model:
        return []

    model.objects.filter(user=user).delete()
    codes = generate_recovery_codes(count=count)
    objs = []
    for c in codes:
        normalized = normalize_recovery_code(c)
        if not normalized:
            continue
        objs.append(model(user=user, code_hash=make_password(normalized)))
    if objs:
        model.objects.bulk_create(objs)
    return codes


def consume_recovery_code_for_user(user, code: str) -> bool:
    """获取用户的`consume``recovery`编码。
    
    If `code` matches an unused recovery code, mark it used and return True.
    """
    normalized = normalize_recovery_code(code)
    if not normalized:
        return False

    model = getattr(app_models, "UserTotpRecoveryCode", None)
    if not model:
        return False

    # Small, bounded list (typically 10 codes); linear scan is fine.
    rows = model.objects.filter(user=user, used_at__isnull=True)
    for row in rows:
        try:
            if check_password(normalized, str(getattr(row, "code_hash", "") or "")):
                row.used_at = datetime.now()
                try:
                    row.save(update_fields=["used_at", "update_time"])
                except Exception:
                    row.save()
                return True
        except Exception:
            continue
    return False

