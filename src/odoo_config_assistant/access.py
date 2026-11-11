"""Roles and access rules (F-001, F-006, F-011, RG-004, RG-015).

- Administrateur: organisation, users, sources; sees every project (RG-015 exception) but does
  not validate steps (RG-004).
- Référent contenu: sources, business repository and journeys; no project access unless member.
- Consultant: creates projects, manages their members, runs the steps, produces deliverables.
- Utilisateur client: member of a project; fills the profile with the consultant, comments,
  validates the steps that are Done (RG-004).
"""

from __future__ import annotations

from odoo_config_assistant.db import Database, Role, User
from odoo_config_assistant.engine import set_status, update_step
from odoo_config_assistant.models import Catalog, Project, StepStatus


class AccessDenied(PermissionError):
    """Action refused by a role rule; the message names the rule."""


def visible_projects(db: Database, user: User) -> list[Project]:
    """RG-015: a user only sees the projects they are a member of, the administrator excepted."""
    projects = db.projects()
    if user.role is Role.ADMIN:
        return projects
    allowed = db.member_project_ids(user.id)
    return [p for p in projects if p.id in allowed]


def can_view(db: Database, user: User, project_id: str) -> bool:
    return user.role is Role.ADMIN or project_id in db.member_project_ids(user.id)


def require_view(db: Database, user: User, project_id: str) -> None:
    if not can_view(db, user, project_id):
        raise AccessDenied("RG-015 : accès réservé aux membres du projet")


def can_create_project(user: User) -> bool:
    return user.role in (Role.CONSULTANT, Role.ADMIN)


def can_manage_project(db: Database, user: User, project_id: str) -> bool:
    """Profile, members and deliverables: consultant member, or administrator."""
    if user.role is Role.ADMIN:
        return True
    return user.role is Role.CONSULTANT and project_id in db.member_project_ids(user.id)


def can_edit_profile(db: Database, user: User, project_id: str) -> bool:
    """F-007: the consultant and the client user fill the profile together."""
    return can_manage_project(db, user, project_id) or (
        user.role is Role.CLIENT and project_id in db.member_project_ids(user.id)
    )


def allowed_statuses(db: Database, user: User, project: Project, step_id: str) -> list[StepStatus]:
    """Statuses this user may give to the step (current one included)."""
    current = project.plan_step(step_id).status
    member = project.id in db.member_project_ids(user.id)
    if user.role is Role.CLIENT and member:
        # RG-004 : le client valide une étape faite, ou revient sur sa validation.
        if current in (StepStatus.DONE, StepStatus.VALIDATED):
            return [StepStatus.DONE, StepStatus.VALIDATED]
        return [current]
    if can_manage_project(db, user, project.id):
        statuses = [s for s in StepStatus if s is not StepStatus.VALIDATED]
        return statuses if current is not StepStatus.VALIDATED else [current, *statuses]
    return [current]


def change_status(
    db: Database,
    user: User,
    project: Project,
    step_id: str,
    status: StepStatus,
    catalog: Catalog,
) -> Project:
    """Status change with the role rules, then the engine rules (RG-003)."""
    require_view(db, user, project.id)
    current = project.plan_step(step_id).status
    if status is current:
        return project
    if status is StepStatus.VALIDATED or current is StepStatus.VALIDATED:
        member = project.id in db.member_project_ids(user.id)
        if not (user.role is Role.CLIENT and member):
            raise AccessDenied(
                "RG-004 : la validation est réservée à l'utilisateur client membre du projet"
            )
    elif status not in allowed_statuses(db, user, project, step_id):
        raise AccessDenied("Statut réservé au consultant du projet")
    return set_status(project, step_id, status, catalog)


def edit_step(
    db: Database,
    user: User,
    project: Project,
    step_id: str,
    retained_value: str | None,
    comment: str,
) -> Project:
    """Retained value: consultant side; comment: any member (F-011)."""
    require_view(db, user, project.id)
    item = project.plan_step(step_id)
    changes: dict = {"comment": comment}
    if retained_value != item.retained_value:
        if not can_manage_project(db, user, project.id):
            raise AccessDenied("La valeur retenue est saisie par le consultant du projet")
        changes["retained_value"] = retained_value
    return update_step(project, step_id, **changes)


def can_admin(user: User) -> bool:
    return user.role is Role.ADMIN


def can_manage_sources(user: User) -> bool:
    """E-08: administrator and content owner."""
    return user.role in (Role.ADMIN, Role.REFERENT)


def can_edit_repository(user: User) -> bool:
    """E-09: content owner (and administrator)."""
    return user.role in (Role.REFERENT, Role.ADMIN)
