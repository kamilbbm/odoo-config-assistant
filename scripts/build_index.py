"""Build the BM25 search index from the downloaded Odoo documentation.

Indexed scope: finance and inventory_and_mrp, plus every page cited by the journeys.
Output: index/odoo-18.0.json (ignored by git).

Usage: python scripts/build_index.py [--docs vendor/odoo-docs] [--out index/odoo-18.0.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from odoo_config_assistant.journeys import load_catalog  # noqa: E402
from odoo_config_assistant.knowledge import DEFAULT_INDEX_PATH, build_index  # noqa: E402

DEFAULT_DOCS = ROOT / "vendor" / "odoo-docs"
BASE_SCOPE = ["content/applications/finance", "content/applications/inventory_and_mrp"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    parser.add_argument("--out", type=Path, default=DEFAULT_INDEX_PATH)
    args = parser.parse_args(argv)

    version_path = args.docs.with_name(args.docs.name + ".version.json")
    if not version_path.exists():
        print("Documentation absente : lancer d'abord python scripts/fetch_docs.py")
        return 1
    info = json.loads(version_path.read_text(encoding="utf-8"))

    catalog = load_catalog()
    cited = sorted({s.path for j in catalog.journeys for step in j.steps for s in step.sources})
    index = build_index(args.docs, info["commit"], [*BASE_SCOPE, *cited], version=info["branch"])
    index.save(args.out)
    pages = len({c.path for c in index.chunks})
    commit = info["commit"][:7]
    print(f"Index {args.out} : {len(index.chunks)} sections, {pages} pages, commit {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
