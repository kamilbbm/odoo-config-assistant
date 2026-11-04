"""Smoke test of the Streamlit interface with Streamlit's own test harness.

Skipped when Streamlit is not installed (it is installed in CI)."""

from pathlib import Path

import pytest

app_testing = pytest.importorskip("streamlit.testing.v1")
APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def test_app_renders_without_exception():
    at = app_testing.AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Profil", "Plan", "Fiche étape", "Assistant", "Export"]
    # Au premier chargement, le dernier projet enregistré est ouvert (ici le projet exemple).
    assert at.selectbox[0].value != "+ Nouveau projet"
