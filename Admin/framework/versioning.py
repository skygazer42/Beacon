import os
import subprocess
from pathlib import Path
from typing import Optional


FALLBACK_PROJECT_VERSION = "v0.0.0"


def _env_version() -> str:
    for name in ("VITE_BEACON_VERSION", "BEACON_VERSION"):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _latest_git_tag(repo_root: Path) -> str:
    try:
        output = subprocess.check_output(
            ["git", "tag", "--sort=-creatordate"],
            cwd=str(repo_root),
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        return ""
    for line in output.splitlines():
        tag = line.strip()
        if tag:
            return tag
    return ""


def get_project_version(repo_root: Optional[Path] = None) -> str:
    explicit = _env_version()
    if explicit:
        return explicit

    module_path = Path(__file__).resolve()
    roots = []
    for root in (
        Path(repo_root) if repo_root is not None else module_path.parents[2],
        module_path.parents[1],
        module_path.parents[2],
    ):
        if root not in roots:
            roots.append(root)

    for root in roots:
        try:
            file_version = (root / "PROJECT_VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            file_version = ""
        if file_version:
            return file_version

    for root in roots:
        git_version = _latest_git_tag(root)
        if git_version:
            return git_version
    return FALLBACK_PROJECT_VERSION
