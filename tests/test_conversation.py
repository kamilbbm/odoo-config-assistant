"""Assistant exchanges stored per project and step (F-010, E-05, RG-008, RG-015)."""

import pytest

from odoo_config_assistant import conversation
from odoo_config_assistant.access import AccessDenied
from odoo_config_assistant.db import Database
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.knowledge import BM25Retriever, Chunk
from odoo_config_assistant.seed import ensure_ready

CATALOG = load_catalog()
COMMIT = "d" * 40
CHUNKS = [
    Chunk(
        id="content/applications/finance/accounting/taxes.rst#1",
        commit=COMMIT,
        path="content/applications/finance/accounting/taxes.rst",
        page_title="Taxes",
        section_title="Default taxes",
        text="Default taxes are set in the accounting settings for sales and purchases.",
        text_fr="Les taxes par défaut se définissent dans les paramètres de comptabilité.",
        section_title_fr="Taxes par défaut",
    ),
    Chunk(
        id="content/applications/finance/accounting/journals.rst#1",
        commit=COMMIT,
        path="content/applications/finance/accounting/journals.rst",
        page_title="Journals",
        section_title="Journals",
        text="Journals classify the accounting entries: bank, cash, sales and purchases.",
    ),
]
RETRIEVER = BM25Retriever(CHUNKS, min_score=0.1)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "conv.db")
    ensure_ready(database)
    return database


def user(db, name):
    return db.user_by_email(f"{name}@organisation.example")


def test_exchange_is_stored_with_project_step_citations_and_commit(db):
    project = db.project("exemple-fr")
    exchange = conversation.ask(
        db,
        user(db, "client.vauban"),
        RETRIEVER,
        CATALOG,
        "Où définir les taxes par défaut ?",
        project=project,
        step_id="frf_taxes",
    )
    assert exchange.id and exchange.covered and exchange.doc_commit == COMMIT
    stored = conversation.history(db, user(db, "consultant"), project, "frf_taxes")
    assert [e.id for e in stored] == [exchange.id]
    citation = conversation.citations(stored[0])[0]
    assert citation.title == "Taxes : Taxes par défaut" and citation.commit == COMMIT


def test_not_covered_question_is_stored_as_such(db):
    exchange = conversation.ask(
        db, user(db, "consultant"), RETRIEVER, CATALOG, "Comment configurer la paie ?"
    )
    assert not exchange.covered and exchange.mode == "not_covered"
    assert conversation.history(db, user(db, "consultant"), None)[0].id == exchange.id
    assert conversation.history(db, user(db, "admin"), None) == []  # échanges personnels


def test_rg015_non_member_cannot_ask_or_read_in_a_project(db):
    project = db.project("exemple-fr")
    with pytest.raises(AccessDenied):
        conversation.ask(db, user(db, "client.boreal"), RETRIEVER, CATALOG, "taxes", project)
    with pytest.raises(AccessDenied):
        conversation.history(db, user(db, "client.boreal"), project)


def test_step_outside_the_plan_is_refused(db):
    with pytest.raises(ValueError):
        conversation.ask(
            db,
            user(db, "consultant"),
            RETRIEVER,
            CATALOG,
            "taxes",
            db.project("exemple-fr"),
            step_id="fin_taxes",
        )
