"""Configuration workbook export (cahier de paramétrage, F-012) with openpyxl.

One row per plan step: status, recommended value (with an "À confirmer" flag when the value is
not confirmed by the documentation), retained value, comment, sources and documentation commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from odoo_config_assistant.models import (
    ACTIVITY_LABELS,
    LICENSE_NOTICE,
    LICENSE_URL,
    SIZE_LABELS,
    Catalog,
    Project,
)

TO_CONFIRM = "À confirmer"

COLUMNS: list[tuple[str, int]] = [
    ("N°", 5),
    ("Parcours", 22),
    ("Identifiant", 22),
    ("Étape", 32),
    ("Chemin de menu (Odoo 18)", 40),
    ("Prérequis", 28),
    ("Statut", 14),
    ("Valeur recommandée", 50),
    (TO_CONFIRM, 13),
    ("Note de vérification", 45),
    ("Valeur retenue", 35),
    ("Commentaire", 35),
    ("Sources", 60),
    ("Version documentaire (commit)", 44),
    ("Mis à jour le", 18),
]

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_CONFIRM_FILL = PatternFill("solid", fgColor="FFF2CC")
_WRAP = Alignment(wrap_text=True, vertical="top")


def build_workbook(project: Project, catalog: Catalog) -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cahier de paramétrage"
    _plan_sheet(sheet, project, catalog)
    _project_sheet(workbook.create_sheet("Projet"), project)
    return workbook


def export_bytes(project: Project, catalog: Catalog) -> bytes:
    buffer = BytesIO()
    build_workbook(project, catalog).save(buffer)
    return buffer.getvalue()


def export_file(project: Project, catalog: Catalog, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(project, catalog).save(path)
    return path


def _plan_sheet(sheet, project: Project, catalog: Catalog) -> None:
    for col, (title, width) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=col, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = _WRAP
        sheet.column_dimensions[get_column_letter(col)].width = width

    titles = [t for t, _ in COLUMNS]
    confirm_col = titles.index(TO_CONFIRM) + 1
    sources_col = titles.index("Sources") + 1
    for row, item in enumerate(project.plan, start=2):
        step = catalog.step(item.step_id)
        journey = catalog.journey_of(item.step_id)
        recommendation = step.recommendation_for(project.profile)
        sources = "\n".join(f"{s.title} : {s.url} ({s.path})" for s in step.sources)
        values = [
            item.order + 1,
            journey.title,
            step.id,
            step.title,
            step.menu_path,
            ", ".join(step.prerequisites),
            item.status.label,
            recommendation.value,
            "" if recommendation.verified else TO_CONFIRM,
            "" if recommendation.verified else (recommendation.note or ""),
            item.retained_value or "",
            item.comment,
            sources,
            item.doc_commit or project.doc_commit or "",
            item.updated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
        ]
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=col, value=value)
            cell.alignment = _WRAP
        if not recommendation.verified:
            sheet.cell(row=row, column=confirm_col).fill = _CONFIRM_FILL
        sources_cell = sheet.cell(row=row, column=sources_col)
        sources_cell.hyperlink = step.sources[0].url
        sources_cell.font = Font(color="0563C1", underline="single")

    sheet.freeze_panes = "E2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(len(project.plan) + 1, 1)}"


def _project_sheet(sheet, project: Project) -> None:
    profile = project.profile
    rows = [
        ("Projet", project.name),
        ("Société", profile.company_name),
        ("ERP", f"{project.erp} {project.version}"),
        ("Pays / province", f"{profile.country or ''} / {profile.province or ''}"),
        ("Activité", ACTIVITY_LABELS.get(profile.activity, "") if profile.activity else ""),
        ("Taille", SIZE_LABELS.get(profile.size, "") if profile.size else ""),
        ("Modules", ", ".join(profile.modules)),
        ("Fin d'exercice", profile.fiscal_year_end),
        ("Documentation Odoo (commit)", project.doc_commit or ""),
        ("Exporté le", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
        ("Étapes du plan", len(project.in_scope())),
        ("Licence des contenus cités", f"{LICENSE_NOTICE} : {LICENSE_URL}"),
        (
            "Avertissement",
            "Les valeurs marquées « À confirmer » ne sont pas confirmées par la documentation "
            "Odoo et doivent être validées avec le client.",
        ),
    ]
    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 90
    for row, (label, value) in enumerate(rows, start=1):
        sheet.cell(row=row, column=1, value=label).font = Font(bold=True)
        cell = sheet.cell(row=row, column=2, value=value)
        cell.alignment = _WRAP
