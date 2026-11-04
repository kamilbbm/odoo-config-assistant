"""Shared fixtures: small synthetic journeys, independent from data/journeys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from odoo_config_assistant.models import Activity, Catalog, Journey, Profile

SAMPLE_PATH = "content/applications/finance/accounting/taxes.rst"


def make_step(step_id: str, prerequisites: list[str] | None = None, **extra: Any) -> dict:
    step = {
        "id": step_id,
        "title": f"Étape {step_id}",
        "objective": "Objectif de test",
        "menu_path": "Accounting > Configuration > Taxes",
        "recommendations": [{"value": "Valeur par défaut"}],
        "prerequisites": prerequisites or [],
        "sources": [
            {
                "path": SAMPLE_PATH,
                "title": "Taxes",
                "url": "https://www.odoo.com/documentation/18.0/fr/applications/finance/accounting/taxes.html",
            }
        ],
    }
    step.update(extra)
    return step


def make_journey(journey_id: str, steps: list[dict], **extra: Any) -> dict:
    journey = {
        "id": journey_id,
        "title": f"Parcours {journey_id}",
        "domain": "Test",
        "steps": steps,
    }
    journey.update(extra)
    return journey


def write_journeys(directory: Path, *journeys: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for journey in journeys:
        path = directory / f"{journey['id']}.yaml"
        path.write_text(yaml.safe_dump(journey, allow_unicode=True), encoding="utf-8")
    return directory


@pytest.fixture
def complete_profile() -> Profile:
    return Profile(
        company_name="Société Test inc.",
        country="CA",
        province="QC",
        activity=Activity.MANUFACTURING,
        modules=["account", "stock"],
    )


@pytest.fixture
def small_catalog() -> Catalog:
    """a <- b <- c, plus d (needs module mrp) and e <- d."""
    steps = [
        make_step("a"),
        make_step("b", ["a"]),
        make_step("c", ["b"]),
        make_step("d", applies_when={"modules": ["mrp"]}),
        make_step("e", ["d", "a"]),
    ]
    return Catalog(journeys=[Journey.model_validate(make_journey("test", steps))])
