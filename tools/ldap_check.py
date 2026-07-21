#!/usr/bin/env python3
"""
LDAP/AD connectivity + auth verification helper.

This is intended for industrial delivery acceptance:
- validate env config quickly
- prove at least one LDAP bind path works

Usage example:
  export BEACON_LDAP_ENABLED=1
  export BEACON_LDAP_URL="ldaps://ad.example.com:636"
  export BEACON_LDAP_BIND_DN="CN=svc,OU=Users,DC=example,DC=com"
  export BEACON_LDAP_BIND_PASSWORD="***"
  export BEACON_LDAP_BASE_DN="DC=example,DC=com"
  export BEACON_LDAP_USER_FILTER="(|(sAMAccountName={username})(userPrincipalName={username}))"
  python3 tools/ldap_check.py --username alice
"""

import argparse
import getpass
import os
import sys
from pathlib import Path


def _import_ldap_auth():
    """执行导入LDAP认证。"""
    repo_root = Path(__file__).resolve().parents[1]
    admin_dir = repo_root / "Admin"
    sys.path.insert(0, str(admin_dir))
    from app.utils import LdapAuth  # type: ignore

    return LdapAuth


def _resolve_password(args) -> str:
    """解析并返回`password`。"""
    password = str(getattr(args, "password", "") or "")
    if password:
        return password

    password = str(os.environ.get("BEACON_LDAP_TEST_PASSWORD") or "")
    if password:
        return password

    try:
        return getpass.getpass("LDAP password: ")
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(130)


def _run_check(*, username: str, password: str) -> int:
    """执行`check`。"""
    try:
        ldap_auth = _import_ldap_auth()
    except Exception as exc:
        print(f"[ERROR] failed to import app.utils.LdapAuth: {exc}")
        return 2

    if not bool(getattr(ldap_auth, "is_enabled", lambda: False)()):
        print("[FAIL] BEACON_LDAP_ENABLED is not enabled (set BEACON_LDAP_ENABLED=1)")
        return 2

    try:
        ok, info = getattr(ldap_auth, "authenticate")(str(username or ""), str(password or ""))
    except Exception as exc:
        print(f"[ERROR] LDAP auth raised exception: {exc}")
        return 2

    info = info if isinstance(info, dict) else {}
    if ok:
        dn = str(info.get("dn") or "").strip()
        email = str(info.get("email") or "").strip()
        print("[OK] LDAP auth success")
        if dn:
            print(f"dn={dn}")
        if email:
            print(f"email={email}")
        return 0

    reason = str(info.get("reason") or "unknown").strip()
    print(f"[FAIL] LDAP auth failed: reason={reason}")
    return 2


def main() -> int:
    """处理`main`。"""
    parser = argparse.ArgumentParser(description="Beacon LDAP/AD auth check")
    parser.add_argument("--username", required=True, help="LDAP username / login id (e.g. sAMAccountName or user@domain)")
    parser.add_argument("--password", default="", help="LDAP password (not recommended; prefer prompt)")
    args = parser.parse_args()

    password = _resolve_password(args)
    return _run_check(username=str(args.username or ""), password=password)


if __name__ == "__main__":
    raise SystemExit(main())
