"""Deliverables with the organisation identity (F-012, RG-013, US-006) and Word export (Q-010)."""

import base64
import re
import zipfile
from io import BytesIO
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from PIL import Image

from odoo_config_assistant.db import Organisation
from odoo_config_assistant.export import export_bytes
from odoo_config_assistant.imports import export_templates_zip
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.storage import load_project
from odoo_config_assistant.word import build_docx

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog()
PROJECT = load_project("exemple-fr", ROOT / "projects")


def logo_b64() -> str:
    buffer = BytesIO()
    Image.new("RGB", (120, 60), (31, 78, 120)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


ORG = Organisation(
    name="Cabinet Conseil Exemple",
    mentions="Cabinet Conseil Exemple, SAS au capital fictif, document confidentiel.",
    logo_b64=logo_b64(),
    logo_mime="image/png",
)


def test_us006_workbook_carries_the_organisation_name_logo_and_mentions():
    workbook = load_workbook(BytesIO(export_bytes(PROJECT, CATALOG, ORG)))
    project_sheet = workbook["Projet"]
    values = {row[0].value: row[1].value for row in project_sheet.iter_rows()}
    assert values["Organisation"] == ORG.name and values["Mentions"] == ORG.mentions
    assert len(project_sheet._images) == 1
    for sheet in workbook.worksheets:
        assert sheet.oddHeader.left.text == ORG.name
        assert sheet.oddFooter.left.text == ORG.mentions


def test_without_organisation_no_identity_is_written():
    workbook = load_workbook(BytesIO(export_bytes(PROJECT, CATALOG)))
    labels = [row[0].value for row in workbook["Projet"].iter_rows()]
    assert "Organisation" not in labels
    assert not workbook["Projet"]._images


def test_us006_word_workbook_carries_the_identity_and_no_other():
    document = Document(BytesIO(build_docx(PROJECT, CATALOG, ORG, {"Accounting": "Comptabilité"})))
    text = "\n".join(p.text for p in document.paragraphs)
    header = document.sections[0].header.paragraphs[0].text
    footer = document.sections[0].footer.paragraphs[0].text
    assert header.startswith(ORG.name) and footer == ORG.mentions
    assert ORG.name in text and "Cahier de paramétrage" in text
    assert len(document.inline_shapes) == 1  # logo
    assert "Organisation de démonstration" not in text  # aucune autre identité


def test_word_workbook_lists_the_plan_and_the_checklist():
    document = Document(BytesIO(build_docx(PROJECT, CATALOG, ORG)))
    text = "\n".join(p.text for p in document.paragraphs)
    in_scope = PROJECT.in_scope()
    first = CATALOG.step(in_scope[0].step_id)
    assert f"1. {first.title}" in text
    assert "À confirmer" in text and "Checklist de configuration" in text
    checklist = document.tables[-1]
    assert len(checklist.rows) == len(in_scope) + 1
    assert "CC BY-SA 4.0" in text


def test_import_templates_name_the_organisation():
    archive = zipfile.ZipFile(BytesIO(export_templates_zip(PROJECT, CATALOG, organisation=ORG)))
    workbook = load_workbook(BytesIO(archive.read("import_partners.xlsx")))
    assert workbook["Aide"]["B1"].value == ORG.name


def test_rg013_no_organisation_is_hard_coded_in_the_code():
    """The demo organisation lives in data/demo_seed.yaml only, never in the code."""
    names = ["Organisation de démonstration", "Atelier Boréal", "Cabinet Vauban"]
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(re.search(re.escape(n), text) for n in names), path
