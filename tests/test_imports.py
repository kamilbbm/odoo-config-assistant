"""Import file templates (F-012): columns checked against the Odoo Community source."""

import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from odoo_config_assistant.engine import recompute_plan
from odoo_config_assistant.imports import export_templates_zip, load_import_templates
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.knowledge import split_sections
from odoo_config_assistant.storage import load_project

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "vendor" / "odoo-docs"
CATALOG = load_catalog()
IMPORTS = load_import_templates()
FIELDS = json.loads((ROOT / "data" / "odoo_fields.json").read_text(encoding="utf-8"))
EDITIONS = json.loads((ROOT / "data" / "editions.json").read_text(encoding="utf-8"))
CHECKS = [(t.id, model, field) for t in IMPORTS.templates for model, field in t.field_checks()]


def project(project_id):
    return load_project(project_id, ROOT / "projects")


def test_fields_file_comes_from_the_same_community_commit():
    assert FIELDS["commit"] == EDITIONS["commit"] and FIELDS["branch"] == "18.0"
    assert {m for t in IMPORTS.templates for m in t.modules} <= set(FIELDS["modules_scanned"])


@pytest.mark.parametrize(("template", "model", "field"), CHECKS, ids=lambda x: str(x))
def test_every_column_is_a_field_of_the_odoo_model(template, model, field):
    assert field in FIELDS["models"].get(model, []), f"{template} : {model}.{field} inconnu"


def test_template_modules_are_community_modules():
    community = set(EDITIONS["community_modules"])
    assert all(set(t.modules) <= community for t in IMPORTS.templates)


@pytest.mark.parametrize("template", IMPORTS.templates, ids=lambda t: t.id)
def test_template_steps_exist(template):
    for step_id in template.steps:
        CATALOG.step(step_id)


def test_source_url_matches_rst_path():
    assert IMPORTS.source.url == IMPORTS.source.expected_url


@pytest.mark.skipif(not (DOCS / "content").is_dir(), reason="clone absent")
def test_source_anchor_and_title_exist_in_the_doc():
    text = (DOCS / IMPORTS.source.path).read_text(encoding="utf-8")
    assert IMPORTS.source.anchor in re.findall(r"^\.\. _([^:]+):", text, re.M)
    assert next(t for t, _, _ in split_sections(text) if t) == IMPORTS.source.title


def test_templates_follow_the_plan():
    boreal = {t.id for t in IMPORTS.for_project(project("exemple"))}
    assert boreal == {t.id for t in IMPORTS.templates}
    vauban = {t.id for t in IMPORTS.for_project(project("exemple-fr"))}
    assert vauban == {"chart_of_accounts", "opening_balances", "partners"}


def test_out_of_scope_steps_bring_no_template():
    boreal = project("exemple")
    finance_only = boreal.profile.model_copy(update={"modules": ["account"]})
    reduced = recompute_plan(boreal, finance_only, CATALOG)
    ids = {t.id for t in IMPORTS.for_project(reduced)}
    assert "bills_of_materials" not in ids and "initial_quantities" not in ids


def test_zip_contains_one_workbook_per_template_with_import_sheet_first():
    archive = zipfile.ZipFile(BytesIO(export_templates_zip(project("exemple-fr"), CATALOG)))
    assert sorted(archive.namelist()) == [
        "import_chart_of_accounts.xlsx",
        "import_opening_balances.xlsx",
        "import_partners.xlsx",
    ]
    workbook = load_workbook(BytesIO(archive.read("import_partners.xlsx")))
    assert workbook.sheetnames == ["Import", "Aide"]
    headers = [c.value for c in workbook["Import"][1]]
    template = next(t for t in IMPORTS.templates if t.id == "partners")
    assert headers == [c.field for c in template.columns]
    assert workbook["Import"].max_row == 1
    help_text = " ".join(str(c.value) for row in workbook["Aide"].iter_rows() for c in row)
    assert "res.partner" in help_text and IMPORTS.source.url in help_text
