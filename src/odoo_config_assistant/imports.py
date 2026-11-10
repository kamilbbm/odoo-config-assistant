"""Import file templates (F-012): one Excel file per data set to load into Odoo.

The repository is data/import_templates.yaml. A template is delivered only if one of its steps is
in the project plan (not Hors périmètre). Each file has:

- an ``Import`` sheet, first so that Odoo opens it, with the technical field names as headers
  (the names of an import-compatible export, recognized by the Odoo import tool);
- an ``Aide`` sheet: meaning and example of each column, linked steps, Odoo model, source.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, ConfigDict, Field, model_validator

from odoo_config_assistant.models import LICENSE_NOTICE, Catalog, Project, Source

DEFAULT_TEMPLATES_FILE = Path(__file__).resolve().parents[2] / "data" / "import_templates.yaml"

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_WRAP = Alignment(wrap_text=True, vertical="top")


class ImportColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    description: str
    example: str = ""


class ImportTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    model: str
    modules: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    subfields: dict[str, str] = Field(default_factory=dict)
    columns: list[ImportColumn] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_columns(self) -> ImportTemplate:
        fields = [c.field for c in self.columns]
        if len(fields) != len(set(fields)):
            raise ValueError(f"modèle {self.id} : colonne en double")
        return self

    @property
    def filename(self) -> str:
        return f"import_{self.id}.xlsx"

    def field_checks(self) -> list[tuple[str, str]]:
        """(model, field) pairs to verify: ``a/b`` is ``b`` on the model of the one2many ``a``.

        ``id`` (External ID) and the ``/id`` suffix (reference by External ID) are import
        conventions, not fields.
        """
        checks = []
        for column in self.columns:
            parts = [p for p in column.field.split("/") if p != "id"]
            if not parts:
                continue
            checks.append((self.model, parts[0]))
            if len(parts) > 1:
                checks.append((self.subfields.get(parts[0], "?"), parts[1]))
        return checks


class ImportCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    templates: list[ImportTemplate]

    def for_project(self, project: Project) -> list[ImportTemplate]:
        in_plan = {s.step_id for s in project.in_scope()}
        return [t for t in self.templates if in_plan & set(t.steps)]


def load_import_templates(path: Path = DEFAULT_TEMPLATES_FILE) -> ImportCatalog:
    return ImportCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def template_workbook(
    template: ImportTemplate, imports: ImportCatalog, catalog: Catalog
) -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Import"
    for col, column in enumerate(template.columns, start=1):
        cell = sheet.cell(row=1, column=col, value=column.field)
        cell.font = Font(bold=True)
        sheet.column_dimensions[cell.column_letter].width = max(14, len(column.field) + 4)

    help_sheet = workbook.create_sheet("Aide")
    help_sheet.column_dimensions["A"].width = 34
    help_sheet.column_dimensions["B"].width = 60
    help_sheet.column_dimensions["C"].width = 28
    steps = ", ".join(
        f"{catalog.step(s).title} ({s})" for s in template.steps if _known(catalog, s)
    )
    intro = [
        ("Modèle d'import", template.title),
        ("Objet Odoo", template.model),
        ("Étapes du plan", steps),
        (
            "Mode d'emploi",
            "Remplir la feuille Import (ne pas changer les en-têtes), puis dans Odoo : vue liste "
            "de l'objet, Action, Import records, Upload Data File, Test, Import.",
        ),
        ("Source", f"{imports.source.title} : {imports.source.url}"),
        ("Licence de la documentation citée", LICENSE_NOTICE),
    ]
    for row, (label, value) in enumerate(intro, start=1):
        help_sheet.cell(row=row, column=1, value=label).font = Font(bold=True)
        help_sheet.cell(row=row, column=2, value=value).alignment = _WRAP
    start = len(intro) + 2
    for col, title in enumerate(("Colonne", "Signification", "Exemple"), start=1):
        cell = help_sheet.cell(row=start, column=col, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
    for row, column in enumerate(template.columns, start=start + 1):
        help_sheet.cell(row=row, column=1, value=column.field)
        help_sheet.cell(row=row, column=2, value=column.description).alignment = _WRAP
        help_sheet.cell(row=row, column=3, value=column.example)
    return workbook


def _known(catalog: Catalog, step_id: str) -> bool:
    try:
        catalog.step(step_id)
    except KeyError:
        return False
    return True


def export_templates_zip(
    project: Project, catalog: Catalog, imports: ImportCatalog | None = None
) -> bytes:
    """ZIP of the import templates relevant to the project plan."""
    imports = imports or load_import_templates()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for template in imports.for_project(project):
            content = BytesIO()
            template_workbook(template, imports, catalog).save(content)
            archive.writestr(template.filename, content.getvalue())
    return buffer.getvalue()
