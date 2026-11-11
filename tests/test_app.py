"""Streamlit interface with Streamlit's own test harness: login, screens by role, RG-004.

Each test uses its own database (OCA_DB) seeded with the demonstration data."""

from pathlib import Path

import pytest

from odoo_config_assistant.db import Database
from odoo_config_assistant.models import StepStatus

app_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    monkeypatch.setenv("OCA_DB", str(path))
    # Pas de téléchargement de la documentation pendant les tests unitaires.
    monkeypatch.setenv("OCA_AUTO_FETCH", "0")
    return path


def run_as(email, db_path):
    database = Database(db_path)
    app = app_testing.AppTest.from_file(str(APP), default_timeout=60)
    if email:
        from odoo_config_assistant.seed import ensure_ready

        ensure_ready(database)
        app.session_state["user_id"] = database.user_by_email(email).id
    return app.run(), database


def test_login_screen_offers_the_demo_accounts(db_path):
    app, _ = run_as(None, db_path)
    assert not app.exception and not app.tabs
    labels = [b.label for b in app.button]
    assert "Se connecter" in labels
    assert "Camille Consultante (Consultant)" in labels


def test_wrong_password_is_refused(db_path):
    app, _ = run_as(None, db_path)
    app.text_input[0].input("consultant@organisation.example")
    app.text_input[1].input("mauvais mot de passe")
    app.button[0].click().run()
    assert any("incorrect" in e.value for e in app.error)


def test_demo_button_logs_in(db_path):
    app, _ = run_as(None, db_path)
    next(b for b in app.button if b.label.startswith("Camille")).click().run()
    assert not app.exception
    assert "Tableau de bord" in [t.label for t in app.tabs]


@pytest.mark.parametrize(
    ("email", "screens"),
    [
        (
            "admin@organisation.example",
            ["Tableau de bord", "Projet", "Plan", "Fiche étape", "Assistant", "Livrables",
             "Contrôle d'écart", "Administration", "Sources", "Référentiel"],
        ),
        (
            "consultant@organisation.example",
            ["Tableau de bord", "Projet", "Plan", "Fiche étape", "Assistant", "Livrables",
             "Contrôle d'écart"],
        ),
        (
            "client.vauban@organisation.example",
            ["Tableau de bord", "Projet", "Plan", "Fiche étape", "Assistant"],
        ),
        ("referent@organisation.example", ["Assistant", "Sources", "Référentiel"]),
    ],
)
def test_screens_depend_on_the_role(db_path, email, screens):
    app, _ = run_as(email, db_path)
    assert not app.exception
    assert [t.label for t in app.tabs] == screens


def test_rg015_client_only_sees_their_project(db_path):
    app, _ = run_as("client.vauban@organisation.example", db_path)
    assert app.sidebar.selectbox[0].options == ["Cabinet Vauban : comptabilité Odoo 18"]


def test_plan_table_lists_every_step(db_path):
    app, database = run_as("consultant@organisation.example", db_path)
    project = database.project("exemple")
    plan_table = next(d for d in app.dataframe if "Étape" in d.value.columns)
    assert len(plan_table.value) == len(project.plan)


def test_rg004_client_validates_a_done_step_from_the_step_sheet(db_path):
    app, database = run_as("client.vauban@organisation.example", db_path)
    step = "frf_main_currency"
    app.selectbox(key="step_id").set_value(step).run()
    radio = next(r for r in app.radio if r.label == "Statut")
    radio.set_value(StepStatus.VALIDATED)
    next(b for b in app.button if b.label == "Enregistrer l'étape").click().run()
    assert not app.exception
    assert database.project("exemple-fr").plan_step(step).status is StepStatus.VALIDATED


def test_referent_edits_a_step_title_in_the_journey_editor(db_path):
    app, database = run_as("referent@organisation.example", db_path)
    app.selectbox(key="editor-step-finance_fr").set_value("frf_journals").run()
    title = next(t for t in app.text_input if t.label == "Titre")
    title.input("Journaux comptables (E-09)")
    next(b for b in app.button if b.label == "Enregistrer l'étape").click().run()
    assert not app.exception
    from odoo_config_assistant.repository import catalog_for

    assert catalog_for(database).step("frf_journals").title == "Journaux comptables (E-09)"
