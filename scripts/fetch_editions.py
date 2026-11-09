"""Record which Odoo modules exist in the Community edition (odoo/odoo, branch 18.0).

Writes data/editions.json, versioned, read by the journey loader:

- ``community_modules``: module directories of odoo/odoo (addons/ and odoo/addons/);
- ``enterprise_upgrade_modules``: modules that the Community settings of the Accounting app
  offer only as an upgrade (``widget="upgrade_boolean"``), i.e. Enterprise modules.

A step that requires a module absent from ``community_modules`` is Enterprise only (Q-008).
Only trees and two settings views are downloaded (shallow, blobless clone).

Usage: python scripts/fetch_editions.py [--branch 18.0] [--output data/editions.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/odoo/odoo"
SETTINGS_VIEWS = ["addons/account/views/res_config_settings_views.xml"]
_UPGRADE = re.compile(r'field name="module_([a-z0-9_]+)"[^>]*widget="upgrade_boolean"')


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def fetch_editions(branch: str = "18.0", repo: str = REPO) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "odoo"
        _git(
            "clone", "-q", "--depth", "1", "--branch", branch, "--filter=blob:none",
            "--no-checkout", repo, str(clone),
        )
        commit = _git("rev-parse", "HEAD", cwd=clone).strip()
        modules: set[str] = set()
        for tree in ("addons/", "odoo/addons/"):
            listing = _git("ls-tree", "-d", "--name-only", "HEAD", tree, cwd=clone)
            modules.update(Path(line).name for line in listing.splitlines() if line)
        upgrades: set[str] = set()
        for view in SETTINGS_VIEWS:
            upgrades.update(_UPGRADE.findall(_git("show", f"HEAD:{view}", cwd=clone)))
    return {
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "note": "Modules de l'édition Community. Un module absent de cette liste est Enterprise.",
        "community_modules": sorted(modules),
        "enterprise_upgrade_modules": sorted(upgrades - modules),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", default="18.0")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "editions.json")
    args = parser.parse_args(argv)
    info = fetch_editions(args.branch)
    args.output.write_text(json.dumps(info, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"odoo/odoo {info['branch']} @ {info['commit']} : {len(info['community_modules'])} "
        f"modules Community, {len(info['enterprise_upgrade_modules'])} modules Enterprise proposés"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
