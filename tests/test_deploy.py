"""Deployment files stay consistent with the project definition."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def _names(lines):
    return {Requirement(line).name.lower(): str(Requirement(line).specifier) for line in lines}


def test_requirements_txt_matches_pyproject_runtime_and_llm_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    expected = _names(project["dependencies"] + project["optional-dependencies"]["llm"])
    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert _names(lines) == expected


def test_streamlit_secrets_are_ignored_by_git():
    assert ".streamlit/secrets.toml" in (ROOT / ".gitignore").read_text()
