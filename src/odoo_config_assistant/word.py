"""Configuration workbook as a Word document (F-012, Q-010), with the organisation identity.

Content: cover (logo, organisation, project, company, ERP, documentation commit), project
profile, plan by domain with menu path, recommended and retained values, "À confirmer" flags and
sources, printable checklist, warning and licence. Header: organisation name; footer: mentions
(RG-013). Nothing is hard-coded.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Cm, Pt, RGBColor

from odoo_config_assistant.db import Organisation
from odoo_config_assistant.models import (
    ACTIVITY_LABELS,
    EDITION_LABELS,
    LICENSE_NOTICE,
    LICENSE_URL,
    SIZE_LABELS,
    Catalog,
    Project,
)

_ORANGE = RGBColor(0xB4, 0x5F, 0x06)


def _french_menu(items: list[str], labels: dict[str, str] | None) -> str | None:
    if not labels:
        return None
    french = [labels.get(item) for item in items]
    return None if None in french else " > ".join(french)


def build_docx(
    project: Project,
    catalog: Catalog,
    organisation: Organisation | None = None,
    menu_labels: dict[str, str] | None = None,
) -> bytes:
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(1.8))
    document.styles["Normal"].font.size = Pt(10)

    if organisation is not None:
        section.header.paragraphs[0].text = f"{organisation.name} · {project.name}"
        section.footer.paragraphs[0].text = organisation.mentions or organisation.name

    # Cover.
    if organisation is not None and organisation.logo_b64:
        document.add_picture(BytesIO(base64.b64decode(organisation.logo_b64)), height=Cm(2.5))
    if organisation is not None:
        document.add_paragraph(organisation.name).runs[0].bold = True
    document.add_heading("Cahier de paramétrage", level=0)
    profile = project.profile
    facts = [
        ("Projet", project.name),
        ("Société", profile.company_name),
        ("ERP", f"{project.erp} {project.version}"),
        ("Documentation Odoo (commit)", project.doc_commit or ""),
        ("Généré le", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    _table(document, ["", ""], facts, header=False)

    document.add_heading("Profil de l'entreprise", level=1)
    profile_rows = [
        ("Pays / province", f"{profile.country or ''} / {profile.province or ''}"),
        ("Activité", ACTIVITY_LABELS.get(profile.activity, "") if profile.activity else ""),
        ("Taille", SIZE_LABELS.get(profile.size, "") if profile.size else ""),
        ("Édition Odoo", EDITION_LABELS[profile.edition] if profile.edition else "Non précisée"),
        ("Régime fiscal", profile.tax_regime or ""),
        ("Modules", ", ".join(profile.modules)),
        ("Fin d'exercice", profile.fiscal_year_end),
    ]
    _table(document, ["", ""], profile_rows, header=False)

    document.add_heading("Plan de configuration", level=1)
    in_scope = project.in_scope()
    domains: dict[str, list] = {}
    for item in in_scope:
        domains.setdefault(catalog.journey_of(item.step_id).domain, []).append(item)
    for domain, items in domains.items():
        document.add_heading(domain, level=2)
        for item in items:
            step = catalog.step(item.step_id)
            rec = step.recommendation_for(project.profile)
            document.add_heading(f"{item.order + 1}. {step.title} [{item.status.label}]", level=3)
            document.add_paragraph(step.objective)
            menu = _french_menu(step.menu_items, menu_labels)
            paragraph = document.add_paragraph()
            paragraph.add_run("Chemin de menu : ").bold = True
            paragraph.add_run(menu or step.menu_path)
            if menu:
                paragraph.add_run(f" (interface anglaise : {step.menu_path})").italic = True
            if catalog.enterprise_modules(step):
                paragraph = document.add_paragraph()
                paragraph.add_run("Édition requise : ").bold = True
                paragraph.add_run(catalog.edition_label(step))
            paragraph = document.add_paragraph()
            paragraph.add_run("Valeur recommandée : ").bold = True
            paragraph.add_run(rec.value)
            if not rec.verified:
                flag = document.add_paragraph()
                run = flag.add_run(f"À confirmer : {rec.note}")
                run.font.color.rgb = _ORANGE
            if item.retained_value:
                paragraph = document.add_paragraph()
                paragraph.add_run("Valeur retenue : ").bold = True
                paragraph.add_run(item.retained_value)
            if item.comment:
                paragraph = document.add_paragraph()
                paragraph.add_run("Commentaire : ").bold = True
                paragraph.add_run(item.comment)
            sources = "; ".join(f"{s.title} ({s.url})" for s in step.sources)
            document.add_paragraph(f"Sources : {sources}").runs[0].font.size = Pt(8)

    document.add_heading("Checklist de configuration", level=1)
    rows = []
    for item in in_scope:
        step = catalog.step(item.step_id)
        menu = _french_menu(step.menu_items, menu_labels) or step.menu_path
        mark = "☑" if item.status.is_complete else "☐"
        rows.append((mark, str(item.order + 1), step.title, menu, item.status.label, ""))
    _table(document, ["Fait", "N°", "Étape", "Chemin de menu", "Statut", "Date et initiales"], rows)

    document.add_heading("Avertissement et licence", level=1)
    document.add_paragraph(
        "Les valeurs marquées « À confirmer » ne sont pas confirmées par la documentation Odoo "
        "et doivent être validées avec le client."
    )
    document.add_paragraph(
        f"Les objectifs et chemins de menu citent la documentation officielle Odoo : "
        f"{LICENSE_NOTICE} ({LICENSE_URL}). Odoo est une marque d'Odoo S.A."
    )
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _table(document, headers: list[str], rows: list[tuple], header: bool = True) -> None:
    table = document.add_table(rows=0, cols=len(headers))
    table.style = "Table Grid"
    if header:
        cells = table.add_row().cells
        for cell, title in zip(cells, headers, strict=True):
            cell.text = title
            cell.paragraphs[0].runs[0].bold = True
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row, strict=True):
            cell.text = str(value)
        if not header:
            cells[0].paragraphs[0].runs[0].bold = True
    document.add_paragraph()
