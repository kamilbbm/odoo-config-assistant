"""Smoke test of the Streamlit interface with Streamlit's own test harness.

Skipped when Streamlit is not installed (it is installed in CI)."""

import pytest

app_testing = pytest.importorskip("streamlit.testing.v1")


def test_app_renders_without_exception():
    at = app_testing.AppTest.from_file("app/streamlit_app.py", default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Profil", "Plan", "Fiche étape", "Assistant", "Export"]
