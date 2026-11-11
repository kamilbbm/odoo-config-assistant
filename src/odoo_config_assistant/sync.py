"""Documentary synchronization (F-002, RG-009, RG-011, SFD 3.3).

Flow: fetch the branch (candidate version) -> compare its pages with the active version ->
build the candidate index aside -> run the controls -> publish in a single swap, or keep the
active version. Each run writes a report (pages added, modified, deleted, impacted journey
steps, anomalies with their SFD code) in ``<index dir>/sync/reports``.

Not in this module: the French recomposition from the .po files (step 3 of the SFD, F-003) and
the notifications by e-mail; the report is shown in the Sources tab and by scripts/sync_docs.py.

Error codes (SFD 3.3.4):

- ERR-001 repository unreachable: retried, then the active version stays in service;
- ERR-002 branch (or commit) not found: stop, active version kept;
- ERR-005 RST page that cannot be parsed: page left out, its previous sections kept;
- ERR-006 indexing interrupted (no vector service in V0, the BM25 build stands for it):
  candidate abandoned;
- ERR-007 source page or anchor of a step missing from the candidate: step flagged, not blocking;
- ERR-008 abnormal drop of the number of pages: publication blocked unless forced, the decision
  being recorded with its author.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from odoo_config_assistant import DOC_VERSION, sources
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.knowledge import DEFAULT_INDEX_PATH, KnowledgeIndex
from odoo_config_assistant.models import Catalog

_LABEL = re.compile(r"^\.\. _([^:]+):", re.M)


class SyncStatus(StrEnum):
    PUBLISHED = "published"
    FORCED = "forced"
    NO_CHANGE = "no_change"
    BLOCKED = "blocked"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return SYNC_STATUS_LABELS[self]

    @property
    def published(self) -> bool:
        return self in (SyncStatus.PUBLISHED, SyncStatus.FORCED)


SYNC_STATUS_LABELS = {
    SyncStatus.PUBLISHED: "Publiée",
    SyncStatus.FORCED: "Publiée (forcée)",
    SyncStatus.NO_CHANGE: "Aucun changement",
    SyncStatus.BLOCKED: "Bloquée",
    SyncStatus.FAILED: "Échec",
}


class Anomaly(BaseModel):
    code: str
    stage: int
    message: str
    path: str | None = None
    step_id: str | None = None


class ImpactedStep(BaseModel):
    """Journey step whose source page changed between the two versions (RG-011)."""

    step_id: str
    journey_id: str
    title: str
    change: str  # "modifiée" ou "supprimée"
    paths: list[str]


class SyncReport(BaseModel):
    id: str
    trigger: str
    status: SyncStatus = SyncStatus.FAILED
    started_at: datetime
    finished_at: datetime | None = None
    repo: str = sources.REPO_URL
    branch: str = DOC_VERSION
    active_commit: str | None = None
    candidate_commit: str | None = None
    pages_before: int = 0
    pages_after: int = 0
    added: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    impacted_steps: list[ImpactedStep] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    drop_threshold: float = 0.05
    forced_by: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def has_alerts(self) -> bool:
        """Something the content owner must look at: impacted steps or blocking anomalies."""
        blocking = {"ERR-001", "ERR-002", "ERR-006", "ERR-007", "ERR-008"}
        return bool(self.impacted_steps) or any(a.code in blocking for a in self.anomalies)

    def step_alerts(self) -> dict[str, list[str]]:
        """Messages per step id, for the step sheet."""
        alerts: dict[str, list[str]] = {}
        before = (self.active_commit or "?")[:7]
        after = (self.candidate_commit or "?")[:7]
        for step in self.impacted_steps:
            pages = ", ".join(step.paths)
            alerts.setdefault(step.step_id, []).append(
                f"Page source {step.change} entre les commits {before} et {after} : {pages}. "
                "Revalider l'étape (RG-011)."
            )
        for anomaly in self.anomalies:
            if anomaly.code == "ERR-007" and anomaly.step_id:
                alerts.setdefault(anomaly.step_id, []).append(
                    f"Source introuvable (ERR-007) : {anomaly.message}"
                )
        return alerts

    def markdown(self) -> str:
        """Report for the content owner (job summary of the scheduled workflow)."""
        lines = [
            f"## Synchronisation documentaire : {self.status.label}",
            "",
            f"- Déclencheur : {self.trigger}",
            f"- Dépôt : {self.repo}, branche {self.branch}",
            f"- Version active avant : `{self.active_commit or 'aucune'}`",
            f"- Version candidate : `{self.candidate_commit or 'non récupérée'}`",
            f"- Pages RST : {self.pages_before} avant, {self.pages_after} après",
            f"- Pages ajoutées : {len(self.added)}, modifiées : {len(self.modified)}, "
            f"supprimées : {len(self.deleted)}",
        ]
        if self.forced_by:
            lines.append(f"- Publication forcée par : {self.forced_by}")
        lines += [f"- Note : {note}" for note in self.notes]
        if self.impacted_steps:
            lines += ["", "### Étapes de parcours impactées (RG-011)", ""]
            lines += [
                f"- `{s.step_id}` {s.title} : page {s.change} ({', '.join(s.paths)})"
                for s in self.impacted_steps
            ]
        if self.anomalies:
            lines += ["", "### Anomalies", ""]
            lines += [f"- {a.code} (étape {a.stage}) : {a.message}" for a in self.anomalies]
        if self.modified or self.deleted:
            lines += ["", "<details><summary>Pages modifiées ou supprimées</summary>", ""]
            lines += [f"- modifiée : `{p}`" for p in self.modified]
            lines += [f"- supprimée : `{p}`" for p in self.deleted]
            lines += ["", "</details>"]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class SyncSettings:
    """Parameters of the organization (SFD 4.6). Default threshold to be decided (Q-004)."""

    drop_threshold: float = 0.05
    retries: int = 3
    retry_delay: float = 15 * 60


def sync_dir(index_path: Path = DEFAULT_INDEX_PATH) -> Path:
    return index_path.parent / "sync"


def list_reports(index_path: Path = DEFAULT_INDEX_PATH) -> list[SyncReport]:
    """Reports, most recent first. Unreadable files are skipped."""
    reports = []
    for path in (sync_dir(index_path) / "reports").glob("*.json"):
        try:
            reports.append(SyncReport.model_validate_json(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(reports, key=lambda r: r.started_at, reverse=True)


def last_published_report(index_path: Path = DEFAULT_INDEX_PATH) -> SyncReport | None:
    return next((r for r in list_reports(index_path) if r.status.published), None)


def _save_report(report: SyncReport, index_path: Path) -> SyncReport:
    report.finished_at = datetime.now(UTC)
    directory = sync_dir(index_path) / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return report


def _fetch(
    report: SyncReport,
    docs: Path,
    commit: str | None,
    settings: SyncSettings,
    sleep: Callable[[float], None],
) -> dict | None:
    attempts = max(1, settings.retries)
    for attempt in range(1, attempts + 1):
        try:
            return sources.fetch_docs(docs, report.branch, report.repo, commit=commit)
        except SystemExit as exc:
            message = str(exc)
            code = message.split(" ", 1)[0] if message.startswith("ERR-") else "ERR-001"
            if code != "ERR-001" or attempt == attempts:
                suffix = f" (après {attempt} tentative(s))" if code == "ERR-001" else ""
                report.anomalies.append(Anomaly(code=code, stage=1, message=message + suffix))
                return None
            sleep(settings.retry_delay)
    return None


def _source_checks(catalog: Catalog, docs: Path, hashes: dict[str, str]) -> list[Anomaly]:
    """ERR-007: every source page and anchor of the journeys must exist in the candidate."""
    anomalies = []
    labels: dict[str, set[str]] = {}
    for journey in catalog.journeys:
        for step in journey.steps:
            for source in step.sources:
                if source.path not in hashes:
                    anomalies.append(
                        Anomaly(
                            code="ERR-007",
                            stage=5,
                            message=f"page {source.path} absente de la version candidate",
                            path=source.path,
                            step_id=step.id,
                        )
                    )
                    continue
                if source.anchor is None:
                    continue
                if source.path not in labels:
                    text = (docs / source.path).read_text(encoding="utf-8", errors="replace")
                    labels[source.path] = set(_LABEL.findall(text))
                if source.anchor not in labels[source.path]:
                    anomalies.append(
                        Anomaly(
                            code="ERR-007",
                            stage=5,
                            message=f"ancre {source.anchor} absente de {source.path}",
                            path=source.path,
                            step_id=step.id,
                        )
                    )
    return anomalies


def _impacted(catalog: Catalog, modified: set[str], deleted: set[str]) -> list[ImpactedStep]:
    impacted = []
    for journey in catalog.journeys:
        for step in journey.steps:
            paths = sorted({s.path for s in step.sources} & (modified | deleted))
            if paths:
                change = "supprimée" if set(paths) & deleted else "modifiée"
                impacted.append(
                    ImpactedStep(
                        step_id=step.id,
                        journey_id=journey.id,
                        title=step.title,
                        change=change,
                        paths=paths,
                    )
                )
    return impacted


def _publish(candidate: KnowledgeIndex, active: KnowledgeIndex | None, index_path: Path) -> None:
    """Archive the active version, then swap in the candidate with one atomic rename."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if active is not None and index_path.exists():
        archive = sync_dir(index_path) / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.copy2(index_path, archive / f"{index_path.stem}-{active.commit[:12]}.json")
    tmp = index_path.with_suffix(".candidate.tmp")
    candidate.save(tmp)
    os.replace(tmp, index_path)


def synchronize(
    docs: Path = sources.DEFAULT_DOCS_DIR,
    index_path: Path = DEFAULT_INDEX_PATH,
    trigger: str = "manuelle",
    force: bool = False,
    forced_by: str | None = None,
    commit: str | None = None,
    settings: SyncSettings | None = None,
    catalog: Catalog | None = None,
    sleep: Callable[[float], None] = time.sleep,
    repo: str | None = None,
) -> SyncReport:
    """Run one synchronization and return its report (also written to disk).

    The active index (``index_path``) is replaced only when every control passes (RG-009), or
    when ``force`` is set after an ERR-008 block, with ``forced_by`` recorded.
    """
    settings = settings or SyncSettings()
    catalog = catalog or load_catalog()
    started = datetime.now(UTC)
    report = SyncReport(
        id=started.strftime("%Y%m%dT%H%M%S%fZ"),
        trigger=trigger,
        started_at=started,
        repo=repo or sources.REPO_URL,
        drop_threshold=settings.drop_threshold,
    )
    active = KnowledgeIndex.load(index_path) if index_path.exists() else None
    if active is not None:
        report.active_commit = active.commit
        report.pages_before = len(active.page_hashes)

    # Step 1: candidate version.
    info = _fetch(report, docs, commit, settings, sleep)
    if info is None:
        return _save_report(report, index_path)
    report.candidate_commit = info["commit"]

    # Step 2: changes against the active version.
    hashes = sources.page_hashes(docs)
    before = active.page_hashes if active is not None else {}
    if active is not None and not before:
        report.notes.append(
            "la version active n'a pas d'empreintes de pages (index antérieur) : comparaison "
            "impossible, toutes les pages sont comptées comme ajoutées"
        )
    report.pages_after = len(hashes)
    report.added = sorted(set(hashes) - set(before))
    report.deleted = sorted(set(before) - set(hashes))
    report.modified = sorted(p for p in set(hashes) & set(before) if hashes[p] != before[p])
    unchanged = before and not (report.added or report.deleted or report.modified)
    if active is not None and unchanged and not force:
        report.status = SyncStatus.NO_CHANGE
        return _save_report(report, index_path)

    # Step 4: candidate index, built aside (step 3, French recomposition, is F-003).
    errors: list[tuple[str, str]] = []
    try:
        candidate = sources.build_knowledge_index(docs, None, previous=active, errors=errors)
    except Exception as exc:
        report.anomalies.append(
            Anomaly(code="ERR-006", stage=4, message=f"indexation interrompue : {exc}")
        )
        return _save_report(report, index_path)
    report.anomalies += [
        Anomaly(code="ERR-005", stage=4, message=f"page exclue : {message}", path=path)
        for path, message in errors
    ]

    # Step 5: controls, publication, alerts.
    report.anomalies += _source_checks(catalog, docs, hashes)
    if before:
        report.impacted_steps = _impacted(catalog, set(report.modified), set(report.deleted))
    dropped = bool(before) and len(hashes) < len(before) * (1 - settings.drop_threshold)
    if dropped:
        report.anomalies.append(
            Anomaly(
                code="ERR-008",
                stage=5,
                message=(
                    f"pages en baisse : {len(before)} -> {len(hashes)}, au-delà du seuil de "
                    f"{settings.drop_threshold:.0%}"
                ),
            )
        )
        if not force:
            report.status = SyncStatus.BLOCKED
            return _save_report(report, index_path)
        if not (forced_by or "").strip():
            raise ValueError("une publication forcée doit indiquer son auteur (ERR-008)")
        report.forced_by = forced_by.strip()
    _publish(candidate, active, index_path)
    report.status = SyncStatus.FORCED if dropped else SyncStatus.PUBLISHED
    return _save_report(report, index_path)
