"""Build the BM25 search index from the downloaded Odoo documentation.

Indexed scope: finance and inventory_and_mrp, plus every page cited by the journeys.
Output: index/odoo-18.0.json (ignored by git).

Usage: python scripts/build_index.py [--docs vendor/odoo-docs] [--out index/odoo-18.0.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odoo_config_assistant.knowledge import DEFAULT_INDEX_PATH
from odoo_config_assistant.sources import DEFAULT_DOCS_DIR, build_knowledge_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_INDEX_PATH)
    args = parser.parse_args(argv)
    try:
        index = build_knowledge_index(args.docs, args.out)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    pages = len({c.path for c in index.chunks})
    commit = index.commit[:7]
    print(f"Index {args.out} : {len(index.chunks)} sections, {pages} pages, commit {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
