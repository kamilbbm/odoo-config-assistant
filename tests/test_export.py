from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from odoo_config_assistant.engine import create_project, recompute_plan, set_status, update_step
from odoo_config_assistant.export import COLUMNS, TO_CONFIRM, export_bytes, export_file
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.models import Activity, Profile, StepStatus
from odoo_config_assistant.storage import load_project

COMMIT = "ca129a822019682bd32552e4cbabba2520d1308e"
CATALOG = load_catalog()


def boreal_project():
    profile = Profile(
        company_name="Atelier Boréal inc.",
        country="CA",
        province="QC",
        activity=Activity.MANUFACTURING,
        size="small",
        modules=["account", "stock", "mrp", "purchase"],
        tracks_lots=True,
    )
    return create_project("Atelier Boréal", profile, CATALOG, doc_commit=COMMIT)


def rows_by_id(project):
    workbook = load_workbook(BytesIO(export_bytes(project, CATALOG)))
    sheet = workbook["Cahier de paramétrage"]
    header = [c.value for c in sheet[1]]
    rows = {}
    for values in sheet.iter_rows(min_row=2, values_only=True):
        record = dict(zip(header, values, strict=True))
        rows[record["Identifiant"]] = record
    return workbook, header, rows


def test_export_has_one_row_per_plan_step_with_expected_columns():
    project = boreal_project()
    _, header, rows = rows_by_id(project)
    assert header == [title for title, _ in COLUMNS]
    assert list(rows) == [s.step_id for s in project.plan]


def test_export_carries_status_retained_value_comment_and_commit():
    project = boreal_project()
    project = set_status(project, "fin_company", StepStatus.DONE, CATALOG)
    project = update_step(
        project, "fin_company", retained_value="Tax ID : 123456789", comment="Validé avec la DAF"
    )
    _, _, rows = rows_by_id(project)
    row = rows["fin_company"]
    assert row["Statut"] == "Fait"
    assert row["Valeur retenue"] == "Tax ID : 123456789"
    assert row["Commentaire"] == "Validé avec la DAF"
    assert row["Version documentaire (commit)"] == COMMIT


def test_unverified_recommendation_is_flagged_with_its_note():
    _, _, rows = rows_by_id(boreal_project())
    taxes = rows["fin_taxes"]
    assert taxes[TO_CONFIRM] == TO_CONFIRM
    assert "Revenu Québec" in taxes["Note de vérification"]
    assert rows["fin_chart_of_accounts"][TO_CONFIRM] is None


def test_sources_column_lists_public_urls():
    workbook, _, rows = rows_by_id(boreal_project())
    assert "fiscal_localizations/canada.html" in rows["fin_fiscal_positions"]["Sources"]
    sheet = workbook["Cahier de paramétrage"]
    assert sheet.cell(row=2, column=13).hyperlink.target.startswith("https://www.odoo.com/")


def test_out_of_scope_steps_stay_in_the_export():
    project = boreal_project()
    without_lots = project.profile.model_copy(update={"tracks_lots": False})
    project = recompute_plan(project, without_lots, CATALOG)
    _, _, rows = rows_by_id(project)
    assert rows["inv_lots"]["Statut"] == "Hors périmètre"


def test_project_sheet_mentions_commit_and_license(tmp_path):
    path = export_file(boreal_project(), CATALOG, tmp_path / "cahier.xlsx")
    sheet = load_workbook(path)["Projet"]
    values = {row[0]: row[1] for row in sheet.iter_rows(values_only=True)}
    assert values["Documentation Odoo (commit)"] == COMMIT
    assert "CC BY-SA 4.0" in values["Licence des contenus cités"]
    assert values["Société"] == "Atelier Boréal inc."


def test_export_shows_the_required_edition():
    project = load_project("exemple-fr", Path(__file__).resolve().parents[1] / "projects")
    sheet = load_workbook(BytesIO(export_bytes(project, CATALOG)))["Cahier de paramétrage"]
    titles = [c.value for c in sheet[1]]
    col = titles.index("Édition Odoo requise")
    by_step = {row[2].value: row[col].value for row in sheet.iter_rows(min_row=2)}
    assert by_step["frf_tax_report"] == "Enterprise (account_reports, l10n_fr_reports)"
    assert by_step["frf_e_invoicing"] == "Community et Enterprise"


def test_checklist_sheet_lists_the_plan_in_order():
    project = load_project("exemple", Path(__file__).resolve().parents[1] / "projects")
    workbook = load_workbook(BytesIO(export_bytes(project, CATALOG)))
    assert workbook.sheetnames == ["Cahier de paramétrage", "Checklist", "Projet"]
    rows = list(workbook["Checklist"].iter_rows(min_row=2, values_only=True))
    in_scope = project.in_scope()
    assert len(rows) == len(in_scope)
    assert [r[1] for r in rows] == [s.order + 1 for s in in_scope]
    for row, item in zip(rows, in_scope, strict=True):
        assert row[0] == ("☑" if item.status.is_complete else "☐")
