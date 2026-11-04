"""Clone or update odoo/documentation (branch 18.0, shallow) into vendor/odoo-docs.

The documentation is not copied into this repository: it is downloaded here and stays under
CC BY-SA 4.0. The commit used is written to vendor/odoo-docs.version.json.

Usage: python scripts/fetch_docs.py [--branch 18.0] [--dest vendor/odoo-docs]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/odoo/documentation"
DEFAULT_DEST = ROOT / "vendor" / "odoo-docs"


def version_file(dest: Path) -> Path:
    return dest.with_name(dest.name + ".version.json")


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def fetch(dest: Path, branch: str, repo: str = REPO_URL) -> dict:
    try:
        heads = git("ls-remote", "--heads", repo, branch)
    except RuntimeError as exc:
        raise SystemExit(f"ERR-001 dépôt inaccessible : {repo} ({exc})") from exc
    if not heads:
        raise SystemExit(f"ERR-002 branche introuvable : {branch} sur {repo}")

    if (dest / ".git").is_dir():
        git("fetch", "--depth", "1", "origin", branch, cwd=dest)
        git("checkout", "-q", "-B", branch, "FETCH_HEAD", cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--depth", "1", "--branch", branch, repo, str(dest))

    commit = git("rev-parse", "HEAD", cwd=dest)
    pages = sum(1 for _ in (dest / "content").rglob("*.rst"))
    info = {
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "rst_pages": pages,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    version_file(dest).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", default="18.0")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--repo", default=REPO_URL)
    args = parser.parse_args(argv)
    info = fetch(args.dest, args.branch, args.repo)
    print(f"odoo/documentation {info['branch']} @ {info['commit']} ({info['rst_pages']} pages RST)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
