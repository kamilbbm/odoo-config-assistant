"""Clone or update odoo/documentation (branch 18.0, shallow) into vendor/odoo-docs.

The documentation is not copied into this repository: it is downloaded here and stays under
CC BY-SA 4.0. The commit used is written to vendor/odoo-docs.version.json. By default only the
RST pages are downloaded; --full also fetches images and translations.

Usage: python scripts/fetch_docs.py [--branch 18.0] [--dest vendor/odoo-docs] [--full]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odoo_config_assistant.sources import (
    DEFAULT_DOCS_DIR,
    REPO_URL,
    fetch_docs,
    version_file,
)


def fetch(dest: Path, branch: str, repo: str = REPO_URL, rst_only: bool = True) -> dict:
    return fetch_docs(dest, branch, repo, rst_only=rst_only)


__all__ = ["fetch", "version_file"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", default="18.0")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DOCS_DIR)
    parser.add_argument("--repo", default=REPO_URL)
    parser.add_argument("--full", action="store_true", help="dépôt complet (images, .po)")
    args = parser.parse_args(argv)
    info = fetch(args.dest, args.branch, args.repo, rst_only=not args.full)
    print(f"odoo/documentation {info['branch']} @ {info['commit']} ({info['rst_pages']} pages RST)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
