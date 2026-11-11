"""Editing the business repository and the journey templates (F-004, F-005, E-09).

The shipped repository (data/referential.yaml, data/journeys/*.yaml) is the baseline; the
content owner's edits are stored in the database as whole files and validated together with
the rest before being saved: RG-012 (a step without source is refused), known prerequisites,
no cycle, known parameter. An edit that breaks a rule is refused with the list of errors.

A step used by a project plan cannot be deleted; its journey cannot be removed.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import yaml

from odoo_config_assistant.access import AccessDenied, can_edit_repository
from odoo_config_assistant.db import Database, User
from odoo_config_assistant.journeys import (
    REFERENTIAL_NAME,
    JourneyValidationError,
    load_catalog,
    repository_files,
)
from odoo_config_assistant.models import Catalog

HEADER = (
    "# Modifié dans l'éditeur de parcours (E-09). Chemins de menu en anglais, tels qu'écrits dans\n"
    "# la documentation. verified: false = à confirmer.\n\n"
)


def _dump(data: dict) -> str:
    return HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def current_files(db: Database) -> dict[str, str]:
    files = repository_files()
    for name, text in db.repository_overrides().items():
        if text is None:
            files.pop(name, None)
        else:
            files[name] = text
    return files


def catalog_for(db: Database) -> Catalog:
    return load_catalog(overrides=db.repository_overrides())


def journey_file(db: Database, journey_id: str) -> str:
    for name, text in current_files(db).items():
        if name.startswith("journeys/") and (yaml.safe_load(text) or {}).get("id") == journey_id:
            return name
    raise KeyError(journey_id)


def _check(db: Database, name: str, text: str | None) -> Catalog:
    overrides = {**db.repository_overrides(), name: text}
    return load_catalog(overrides=overrides)


def save_file(
    db: Database, user: User, name: str, text: str | None, action: str, detail: str
) -> Catalog:
    """Validate the whole repository with this file, then store it. Raises on any error."""
    if not can_edit_repository(user):
        raise AccessDenied("Référentiel et parcours réservés au référent contenu")
    if name != REFERENTIAL_NAME and not name.startswith("journeys/"):
        raise ValueError(f"fichier inconnu : {name}")
    if text is not None:
        yaml.safe_load(text)  # erreur de syntaxe remontée telle quelle
    catalog = _check(db, name, text)
    used = _steps_in_projects(db)
    missing = sorted(used - {s.id for j in catalog.journeys for s in j.steps})
    if missing:
        raise JourneyValidationError(
            [f"étape utilisée par un projet, suppression impossible : {s}" for s in missing]
        )
    db.save_repository_file(name, text, user.id, action, detail)
    return catalog


def _steps_in_projects(db: Database) -> set[str]:
    return {item.step_id for project in db.projects() for item in project.plan}


def save_referential(db: Database, user: User, text: str) -> Catalog:
    return save_file(db, user, REFERENTIAL_NAME, text, "référentiel", "arborescence modifiée")


def save_step(
    db: Database,
    user: User,
    journey_id: str,
    step: dict[str, Any],
    original_id: str | None = None,
) -> Catalog:
    """Create (``original_id`` None) or replace a step of a journey."""
    name = journey_file(db, journey_id)
    data = yaml.safe_load(current_files(db)[name])
    steps = data["steps"]
    ids = [s["id"] for s in steps]
    clean = {k: v for k, v in step.items() if v not in (None, [], {}, "")}
    if original_id is None:
        if clean["id"] in ids:
            raise JourneyValidationError([f"identifiant d'étape déjà utilisé : {clean['id']}"])
        steps.append(clean)
        action = "création"
    else:
        position = ids.index(original_id)
        if clean["id"] != original_id:
            raise JourneyValidationError(["l'identifiant d'une étape existante ne change pas"])
        steps[position] = clean
        action = "modification"
    return save_file(db, user, name, _dump(data), action, f"étape {clean['id']}")


def delete_step(db: Database, user: User, journey_id: str, step_id: str) -> Catalog:
    name = journey_file(db, journey_id)
    data = yaml.safe_load(current_files(db)[name])
    data["steps"] = [s for s in data["steps"] if s["id"] != step_id]
    return save_file(db, user, name, _dump(data), "suppression", f"étape {step_id}")


def step_as_dict(db: Database, journey_id: str, step_id: str) -> dict[str, Any]:
    data = yaml.safe_load(current_files(db)[journey_file(db, journey_id)])
    return next(s for s in data["steps"] if s["id"] == step_id)


def reset_file(db: Database, user: User, name: str) -> Catalog:
    """Back to the shipped version of a file."""
    if not can_edit_repository(user):
        raise AccessDenied("Référentiel et parcours réservés au référent contenu")
    overrides = db.repository_overrides()
    overrides.pop(name, None)
    load_catalog(overrides=overrides)
    db.reset_repository_file(name, user.id)
    return load_catalog(overrides=overrides)


def export_zip(db: Database) -> bytes:
    """Current repository, to version in git (data/)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in sorted(current_files(db).items()):
            archive.writestr(f"data/{name}", text)
    return buffer.getvalue()
