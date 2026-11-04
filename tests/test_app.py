"""Smoke test of the Streamlit interface with Streamlit's own test harness.

Skipped when Streamlit is not installed."""

from pathlib import Path

import pytest

app_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"


@pytest.fixture
def app(monkeypatch):
    # Pas de téléchargement de la documentation pendant les tests unitaires.
    monkeypatch.setenv("OCA_AUTO_FETCH", "0")
    return app_testing.AppTest.from_file(str(APP), default_timeout=60).run()


def test_app_renders_without_exception(app):
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Profil", "Plan", "Fiche étape", "Assistant", "Export"]
    # Au premier chargement, le dernier projet enregistré est ouvert (ici le projet exemple).
    assert app.selectbox[0].value != "+ Nouveau projet"


def test_plan_table_lists_every_step(app):
    from odoo_config_assistant.storage import load_project

    project = load_project("exemple", ROOT / "projects")
    assert len(app.dataframe[0].value) == len(project.plan)
