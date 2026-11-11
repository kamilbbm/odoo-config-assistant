"""Documentary synchronization (F-002, RG-009, RG-011) on a local git repository."""

import json
import subprocess

import pytest

from conftest import make_journey, make_step
from odoo_config_assistant import sources
from odoo_config_assistant.knowledge import KnowledgeIndex
from odoo_config_assistant.models import Catalog, Journey
from odoo_config_assistant.sync import (
    SyncSettings,
    SyncStatus,
    last_published_report,
    list_reports,
    synchronize,
)
from scripts import sync_docs

CITED = "content/applications/finance/accounting/taxes.rst"
PAGE = "Taxes\n=====\n\n.. _taxes/default:\n\nDefault taxes\n-------------\n\n{body}\n"


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Origin:
    def __init__(self, path):
        self.path = path
        (path / "content").mkdir(parents=True)
        git("init", "-q", "-b", "18.0", cwd=path)
        git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=path)

    @property
    def uri(self):
        return self.path.as_uri()

    def write(self, rel, text):
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message="change"):
        git("add", "-A", cwd=self.path)
        git("commit", "-q", "--allow-empty", "-m", message, cwd=self.path)
        return git("rev-parse", "HEAD", cwd=self.path)


@pytest.fixture
def origin(tmp_path):
    repo = Origin(tmp_path / "origin")
    repo.write(CITED, PAGE.format(body="Set the default taxes of new products here, please."))
    for n in range(20):
        repo.write(
            f"content/applications/finance/page{n}.rst",
            f"Page {n}\n=======\n\nSome text about accounting page number {n} for tests.\n",
        )
    repo.commit("init")
    return repo


@pytest.fixture
def catalog():
    source = {
        "path": CITED,
        "title": "Taxes",
        "anchor": "taxes/default",
        "url": "https://www.odoo.com/documentation/18.0/fr/applications/finance/accounting/taxes.html#taxes-default",
    }
    other = {
        "path": "content/applications/finance/page0.rst",
        "title": "Page 0",
        "url": "https://www.odoo.com/documentation/18.0/fr/applications/finance/page0.html",
    }
    steps = [make_step("tax", sources=[source]), make_step("other", sources=[other])]
    return Catalog(journeys=[Journey.model_validate(make_journey("j", steps))])


@pytest.fixture
def run(tmp_path, origin, catalog):
    docs, index = tmp_path / "vendor" / "odoo-docs", tmp_path / "index" / "odoo-18.0.json"

    def _run(**kwargs):
        kwargs.setdefault("settings", SyncSettings(retries=1, retry_delay=0))
        return synchronize(docs, index, catalog=catalog, repo=origin.uri, **kwargs)

    _run.docs, _run.index = docs, index
    return _run


def test_first_synchronization_publishes_the_source(run):
    report = run(trigger="création de la source")
    assert report.status is SyncStatus.PUBLISHED and report.active_commit is None
    assert report.pages_after == 21 and len(report.added) == 21 and not report.impacted_steps
    index = KnowledgeIndex.load(run.index)
    assert index.commit == report.candidate_commit and len(index.page_hashes) == 21
    assert list_reports(run.index)[0].id == report.id


def test_no_change_stops_and_keeps_the_active_version(run):
    first = run()
    built = KnowledgeIndex.load(run.index).built_at
    report = run()
    assert report.status is SyncStatus.NO_CHANGE
    assert report.active_commit == report.candidate_commit == first.candidate_commit
    assert KnowledgeIndex.load(run.index).built_at == built


def test_rg011_modified_source_page_flags_the_step_and_archives_the_old_version(run, origin):
    first = run()
    origin.write(CITED, PAGE.format(body="New wording of the default taxes section for tests."))
    new_commit = origin.commit()
    report = run(trigger="planifiée")
    assert report.status is SyncStatus.PUBLISHED and report.modified == [CITED]
    assert [(s.step_id, s.change) for s in report.impacted_steps] == [("tax", "modifiée")]
    assert "Revalider" in report.step_alerts()["tax"][0]
    assert KnowledgeIndex.load(run.index).commit == new_commit
    archive_dir = run.index.parent / "sync" / "archive"
    archive = archive_dir / f"odoo-18.0-{first.candidate_commit[:12]}.json"
    assert json.loads(archive.read_text())["commit"] == first.candidate_commit
    assert last_published_report(run.index).id == report.id
    assert report.has_alerts and "`tax`" in report.markdown()


def test_err007_deleted_source_page_flags_the_step(run, origin):
    run()
    (origin.path / CITED).unlink()
    origin.commit()
    report = run()
    assert report.status is SyncStatus.PUBLISHED
    assert [(s.step_id, s.change) for s in report.impacted_steps] == [("tax", "supprimée")]
    codes = [(a.code, a.step_id) for a in report.anomalies]
    assert ("ERR-007", "tax") in codes
    assert any("ERR-007" in m for m in report.step_alerts()["tax"])


def test_err007_missing_anchor(run, origin):
    run()
    origin.write(CITED, "Taxes\n=====\n\nThe default taxes section label was removed here.\n")
    origin.commit()
    report = run()
    assert any(a.code == "ERR-007" and "ancre" in a.message for a in report.anomalies)


def test_rg009_err008_page_drop_blocks_then_forced_publication_is_traced(run, origin):
    first = run()
    for n in range(5):
        (origin.path / f"content/applications/finance/page{n}.rst").unlink()
    origin.commit()
    blocked = run()
    assert blocked.status is SyncStatus.BLOCKED
    assert any(a.code == "ERR-008" for a in blocked.anomalies)
    assert KnowledgeIndex.load(run.index).commit == first.candidate_commit
    with pytest.raises(ValueError, match="auteur"):
        run(force=True)
    forced = run(force=True, forced_by="Référent contenu")
    assert forced.status is SyncStatus.FORCED and forced.forced_by == "Référent contenu"
    assert KnowledgeIndex.load(run.index).commit == forced.candidate_commit


def test_err001_unreachable_repository_is_retried_then_active_version_kept(
    run, tmp_path, catalog
):
    run()
    before = KnowledgeIndex.load(run.index).commit
    waits = []
    report = synchronize(
        run.docs,
        run.index,
        catalog=catalog,
        repo=(tmp_path / "missing").as_uri(),
        settings=SyncSettings(retries=3, retry_delay=7),
        sleep=waits.append,
    )
    assert report.status is SyncStatus.FAILED and report.anomalies[0].code == "ERR-001"
    assert waits == [7, 7]
    assert KnowledgeIndex.load(run.index).commit == before


def test_err002_unknown_commit_stops_without_retry(run):
    run()
    waits = []
    report = run(commit="f" * 40, sleep=waits.append, settings=SyncSettings(retries=3))
    assert report.status is SyncStatus.FAILED and report.anomalies[0].code == "ERR-002"
    assert waits == []


def test_err006_indexing_failure_abandons_the_candidate(run, origin, monkeypatch):
    first = run()
    origin.write("content/applications/finance/new.rst", "New\n===\n\nA brand new page here.\n")
    origin.commit()

    def broken(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr(sources, "build_knowledge_index", broken)
    report = run()
    assert report.status is SyncStatus.FAILED and report.anomalies[-1].code == "ERR-006"
    assert KnowledgeIndex.load(run.index).commit == first.candidate_commit


def test_err005_unreadable_page_keeps_its_previous_sections(run, origin):
    run()
    (origin.path / CITED).write_bytes(b"Taxes\n=====\n\n\xff\xfe broken encoding\n")
    origin.commit()
    report = run()
    assert report.status is SyncStatus.PUBLISHED
    assert [(a.code, a.path) for a in report.anomalies if a.code == "ERR-005"] == [
        ("ERR-005", CITED)
    ]
    texts = [c.text for c in KnowledgeIndex.load(run.index).chunks if c.path == CITED]
    assert any("default taxes" in t for t in texts)


def test_specific_commit_can_be_synchronized(run, origin):
    old = git("rev-parse", "HEAD", cwd=origin.path)
    origin.write("content/applications/finance/new.rst", "New\n===\n\nA brand new page here.\n")
    origin.commit()
    assert run(commit=old).candidate_commit == old


def test_cli_exit_codes(tmp_path, origin, monkeypatch, capsys):
    monkeypatch.setattr(sources, "REPO_URL", origin.uri)
    docs, index = tmp_path / "docs", tmp_path / "index" / "odoo-18.0.json"
    base = ["--docs", str(docs), "--index", str(index), "--retries", "1"]
    summary = tmp_path / "summary.md"
    assert sync_docs.main([*base, "--summary", str(summary)]) == 0
    assert "Synchronisation documentaire : Publiée" in summary.read_text()
    (origin.path / CITED).write_text(PAGE.format(body="Changed again for the CLI test."))
    origin.commit()
    # Le vrai référentiel cite taxes.rst (étape fin_taxes, frf_taxes) : alerte RG-011.
    assert sync_docs.main([*base, "--fail-on-alert"]) == 2
    with pytest.raises(SystemExit):
        sync_docs.main([*base, "--force"])


def test_active_index_without_page_hashes_is_reingested_with_a_note(run):
    run()
    legacy = KnowledgeIndex.load(run.index)
    legacy.page_hashes = {}
    legacy.save(run.index)
    report = run()
    assert report.status is SyncStatus.PUBLISHED and len(report.added) == 21
    assert report.notes and "empreintes" in report.markdown()
