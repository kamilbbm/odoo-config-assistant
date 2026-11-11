"""Synchronize the Odoo documentation: candidate version, controls, publication, report (F-002).

The active index (index/odoo-18.0.json) is replaced only if every control passes (RG-009). The
report lists pages added, modified and deleted, and the journey steps whose source page changed
(RG-011). Reports: index/sync/reports/*.json.

Exit code: 0 published or no change; 1 failure or publication blocked; 2 with --fail-on-alert
when steps are impacted or a source is missing (the scheduled workflow then fails and GitHub
notifies the repository owner).

Usage:
  python scripts/sync_docs.py [--trigger manuelle] [--commit SHA] [--summary FILE]
                              [--force --forced-by NOM] [--drop-threshold 0.05]
                              [--retries 3] [--retry-delay 900] [--fail-on-alert]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odoo_config_assistant.knowledge import DEFAULT_INDEX_PATH
from odoo_config_assistant.sources import DEFAULT_DOCS_DIR
from odoo_config_assistant.sync import SyncSettings, SyncStatus, synchronize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS_DIR)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--trigger", default="manuelle")
    parser.add_argument("--commit", help="commit précis de la branche, par défaut sa tête")
    parser.add_argument("--force", action="store_true", help="publier malgré ERR-008")
    parser.add_argument("--forced-by", help="auteur de la publication forcée (tracé)")
    parser.add_argument("--drop-threshold", type=float, default=SyncSettings.drop_threshold)
    parser.add_argument("--retries", type=int, default=SyncSettings.retries)
    parser.add_argument("--retry-delay", type=float, default=SyncSettings.retry_delay)
    parser.add_argument("--summary", type=Path, help="ajouter le compte rendu à ce fichier")
    parser.add_argument("--fail-on-alert", action="store_true")
    args = parser.parse_args(argv)
    if args.force and not args.forced_by:
        parser.error("--force demande --forced-by")

    settings = SyncSettings(args.drop_threshold, args.retries, args.retry_delay)
    report = synchronize(
        args.docs,
        args.index,
        trigger=args.trigger,
        force=args.force,
        forced_by=args.forced_by,
        commit=args.commit,
        settings=settings,
    )
    text = report.markdown()
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    if report.status in (SyncStatus.FAILED, SyncStatus.BLOCKED):
        return 1
    if args.fail_on_alert and report.has_alerts:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
