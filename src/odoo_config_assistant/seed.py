"""First start: demonstration data (fictitious) or an empty organisation to set up."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from odoo_config_assistant.db import ROOT, Database, Organisation, Role
from odoo_config_assistant.storage import load_project

DEMO_SEED = ROOT / "data" / "demo_seed.yaml"


def demo_enabled() -> bool:
    return os.environ.get("OCA_DEMO", "1") != "0"


def seed_demo(db: Database, seed: Path = DEMO_SEED) -> None:
    """Load the demo organisation, users and example projects into an empty database."""
    data = yaml.safe_load(seed.read_text(encoding="utf-8"))
    db.save_organisation(Organisation.model_validate(data["organisation"]))
    for user in data["users"]:
        db.create_user(user["email"], user["name"], Role(user["role"]), data["password"])
    for entry in data["projects"]:
        path = ROOT / entry["file"]
        project = db.import_project(load_project(path.stem, path.parent))
        for email in entry["members"]:
            db.add_member(project.id, db.user_by_email(email).id)


def demo_accounts(seed: Path = DEMO_SEED) -> tuple[list[dict], str]:
    data = yaml.safe_load(seed.read_text(encoding="utf-8"))
    return data["users"], data["password"]


def setup_organisation(db: Database, name: str, admin_email: str, admin_name: str, password: str):
    """Installation without demo data (F-001): the organisation and its first administrator."""
    if db.users():
        raise ValueError("l'organisation est déjà configurée")
    db.save_organisation(Organisation(name=name))
    return db.create_user(admin_email, admin_name, Role.ADMIN, password)


def ensure_ready(db: Database) -> bool:
    """True when the database has users; seeds the demo when enabled and the base is empty."""
    if db.users():
        return True
    if demo_enabled():
        seed_demo(db)
        return True
    return False
