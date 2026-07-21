#!/usr/bin/env python3
"""Run the MkDocs strict build with third-party startup noise silenced."""

import logging
import os
import sys
import tempfile
import warnings


DEFAULT_ARGS_PREFIX = [
    "build",
    "--strict",
    "--site-dir",
]


def _quiet_third_party_startup() -> None:
    """静默文档构建中已知的第三方启动提示。"""

    os.environ.setdefault("NO_MKDOCS_2_WARNING", "true")

    # MkDocs 会在 CLI 启动时重设 warning 处理器;设置 sys.warnoptions 可保留这里的过滤。
    if not sys.warnoptions:
        sys.warnoptions.append("beacon-docs-quiet")

    warnings.filterwarnings(
        "ignore",
        message=r"pkg_resources is deprecated as an API.*",
        category=UserWarning,
    )
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    import jieba  # type: ignore

    jieba.setLogLevel(logging.CRITICAL)


def _default_args() -> list[str]:
    site_dir = tempfile.mkdtemp(prefix="beacon-mkdocs-strict-check-")
    return [*DEFAULT_ARGS_PREFIX, site_dir]


def main(argv: list[str]) -> int:
    """执行 MkDocs CLI,未传参数时使用仓库默认 strict 构建参数。"""

    _quiet_third_party_startup()

    from mkdocs.__main__ import cli

    args = argv or _default_args()
    return cli(args=args, prog_name="mkdocs", standalone_mode=False)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
