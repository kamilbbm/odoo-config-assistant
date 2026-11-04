"""Simple persistence: one JSON file per project in projects/ (ignored by git, except the
fictitious example). No database in V0."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from odoo_config_assistant.models import Project

DEFAULT_PROJECTS_DIR = Path(__file__).resolve().parents[2] / "projects"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _path(project_id: str, directory: Path) -> Path:
    if not _SAFE_ID.match(project_id):
        raise ValueError(f"identifiant de projet invalide : {project_id!r}")
    return directory / f"{project_id}.json"


def save_project(project: Project, directory: Path = DEFAULT_PROJECTS_DIR) -> Path:
    """Write atomically, so a crash never leaves a half-written project file."""
    directory.mkdir(parents=True, exist_ok=True)
    path = _path(project.id, directory)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(project.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_project(project_id: str, directory: Path = DEFAULT_PROJECTS_DIR) -> Project:
    return Project.model_validate(json.loads(_path(project_id, directory).read_text("utf-8")))


def list_projects(directory: Path = DEFAULT_PROJECTS_DIR) -> list[Project]:
    """All readable projects, most recently updated first. Unreadable files are skipped."""
    projects = []
    for path in directory.glob("*.json"):
        try:
            projects.append(Project.model_validate_json(path.read_text("utf-8")))
        except ValueError:
            continue
    return sorted(projects, key=lambda p: p.updated_at, reverse=True)
