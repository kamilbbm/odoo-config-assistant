"""Assistant exchanges (F-010, E-05, data model 4.6 "Échange avec l'assistant").

A question is asked in the context of the open step and of the project version (RG-007); the
exchange is stored with its citations and the documentation commit (RG-008), linked to the
project and the step. Only project members (or the administrator) ask within a project (RG-015).
"""

from __future__ import annotations

from typing import Any

from odoo_config_assistant import DOC_VERSION, ERP
from odoo_config_assistant.access import require_view
from odoo_config_assistant.assistant import answer
from odoo_config_assistant.db import Database, Exchange, User
from odoo_config_assistant.knowledge import Citation
from odoo_config_assistant.models import Catalog, Project


def ask(
    db: Database,
    user: User,
    retriever: Any,
    catalog: Catalog,
    question: str,
    project: Project | None = None,
    step_id: str | None = None,
    client: Any | None = None,
    doc_commit: str | None = None,
) -> Exchange:
    if project is not None:
        require_view(db, user, project.id)
    in_plan = {s.step_id for s in project.plan} if project else set()
    if step_id is not None and step_id not in in_plan:
        raise ValueError(f"étape hors du plan du projet : {step_id}")
    result = answer(
        question,
        retriever,
        erp=project.erp if project else ERP,
        version=project.version if project else DOC_VERSION,
        doc_commit=doc_commit,
        step=catalog.step(step_id) if step_id else None,
        country=project.profile.country if project else None,
        client=client,
    )
    return db.add_exchange(
        Exchange(
            project_id=project.id if project else None,
            step_id=step_id,
            user_id=user.id,
            question=result.question,
            text=result.text,
            covered=result.covered,
            mode=result.mode,
            citations=[c.model_dump() for c in result.citations],
            doc_commit=result.doc_commit,
            version=result.version,
        )
    )


def history(
    db: Database, user: User, project: Project | None, step_id: str | None = None
) -> list[Exchange]:
    """Exchanges of the project (all members), or the user's own outside any project."""
    if project is None:
        return db.exchanges(None, user_id=user.id)
    require_view(db, user, project.id)
    return db.exchanges(project.id, step_id=step_id)


def citations(exchange: Exchange) -> list[Citation]:
    return [Citation.model_validate(c) for c in exchange.citations]
