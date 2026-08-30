import os
from collections.abc import Mapping


BACKGROUND_ROLE_ENV = "BEACON_BACKGROUND_ROLE"
VALID_BACKGROUND_ROLES = frozenset({"all", "web", "worker", "init", "disabled"})


def get_background_role(environ: Mapping[str, str] = None) -> str:
    """Return the explicit background-service role for the current process.

    ``all`` preserves the single-process Edge runtime. Cloud deployments use
    ``web`` for request-local helpers, ``worker`` for singleton schedulers, and
    ``init`` for schema/bootstrap jobs. Invalid values fail closed so a typo
    cannot silently duplicate schedulers across Web replicas.
    """
    source = os.environ if environ is None else environ
    if str(source.get("BEACON_DISABLE_BACKGROUND", "") or "").strip() == "1":
        return "disabled"

    role = str(source.get(BACKGROUND_ROLE_ENV, "all") or "all").strip().lower()
    if role not in VALID_BACKGROUND_ROLES:
        allowed = ", ".join(sorted(VALID_BACKGROUND_ROLES))
        raise ValueError(f"{BACKGROUND_ROLE_ENV} must be one of: {allowed}")
    return role
