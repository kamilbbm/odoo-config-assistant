"""E-mail notifications (SFD 2.1.5 "Messagerie", F-013, RG-011, 3.3.4 error matrix).

Events:

- synchronization report: to the content owners (report, steps to revalidate, ERR-003, 004,
  005, 007), to the administrators (ERR-001, 002, 006, 008) and to the consultants of the
  projects whose plan contains an impacted step (RG-011);
- invitation: account created, member added to a project;
- validation: step done (to the client users of the project), step validated (to the
  consultants of the project).

The SMTP server is set in the organisation (E-07); its password comes from the
``OCA_SMTP_PASSWORD`` environment variable, never from the database. Every notification is
logged, sent or not ("non configurée" when no server is set, "échec" with the error).
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from odoo_config_assistant.db import Database, Role, User
from odoo_config_assistant.models import Catalog, Project
from odoo_config_assistant.sync import SyncReport

ADMIN_CODES = {"ERR-001", "ERR-002", "ERR-006", "ERR-008"}
REFERENT_CODES = {"ERR-003", "ERR-004", "ERR-005", "ERR-007"}

SENT = "envoyée"
NOT_CONFIGURED = "non envoyée (messagerie non configurée)"
FAILED = "échec"


def send(
    db: Database,
    kind: str,
    recipients: list[str],
    subject: str,
    body: str,
    project_id: str | None = None,
    step_id: str | None = None,
) -> list[str]:
    """Send one message per recipient and log each; returns the statuses."""
    organisation = db.organisation()
    statuses = []
    for recipient in sorted(set(recipients)):
        if organisation is None or not organisation.smtp_host:
            status, error = NOT_CONFIGURED, None
        else:
            try:
                _smtp_send(organisation, recipient, subject, body)
                status, error = SENT, None
            except (OSError, smtplib.SMTPException) as exc:
                status, error = FAILED, f"{type(exc).__name__} : {exc}"
        db.log_notification(kind, recipient, subject, body, status, error, project_id, step_id)
        statuses.append(status)
    return statuses


def _smtp_send(organisation, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = organisation.smtp_sender or organisation.smtp_user or "noreply@localhost"
    message["To"] = recipient
    message["Subject"] = f"[{organisation.name}] {subject}"
    message.set_content(body + _signature(organisation))
    with smtplib.SMTP(organisation.smtp_host, organisation.smtp_port, timeout=20) as smtp:
        if organisation.smtp_starttls:
            smtp.starttls()
        password = os.environ.get("OCA_SMTP_PASSWORD")
        if organisation.smtp_user and password:
            smtp.login(organisation.smtp_user, password)
        smtp.send_message(message)


def _signature(organisation) -> str:
    lines = ["", "--", organisation.name]
    if organisation.mentions:
        lines.append(organisation.mentions)
    return "\n".join(lines) + "\n"


def _emails(users: list[User], *roles: Role) -> list[str]:
    return [u.email for u in users if u.active and u.role in roles]


# --------------------------------------------------------------------------- synchronization


def notify_sync(db: Database, report: SyncReport) -> list[str]:
    """F-013 / RG-011: report and alerts after a synchronization."""
    users = db.users()
    statuses: list[str] = []
    codes = {a.code for a in report.anomalies}
    subject = f"Synchronisation documentaire : {report.status.label}"

    referents = _emails(users, Role.REFERENT)
    if report.status.published or codes & REFERENT_CODES or report.impacted_steps:
        statuses += send(db, "synchronisation", referents, subject, report.markdown())

    admin_codes = sorted(codes & ADMIN_CODES)
    if admin_codes:
        lines = [
            f"- {a.code} (étape {a.stage}) : {a.message}"
            for a in report.anomalies
            if a.code in ADMIN_CODES
        ]
        body = (
            f"La synchronisation du {report.started_at:%Y-%m-%d %H:%M} UTC signale "
            f"{', '.join(admin_codes)}. La version active reste en service.\n\n"
            + "\n".join(lines)
            + "\n\nVoir l'écran Sources (E-08)."
        )
        statuses += send(db, "anomalie", _emails(users, Role.ADMIN), subject, body)

    impacted = {s.step_id: s for s in report.impacted_steps}
    if impacted:
        for project in db.projects():
            steps = [impacted[i.step_id] for i in project.in_scope() if i.step_id in impacted]
            if not steps:
                continue
            consultants = _emails(db.members(project.id), Role.CONSULTANT)
            body = (
                f"Des pages sources d'étapes du projet « {project.name} » ont changé "
                "dans la documentation Odoo (RG-011) :\n\n"
                + "\n".join(f"- {s.title} : page {s.change} ({', '.join(s.paths)})" for s in steps)
                + "\n\nLe référent contenu revalide ces étapes ; vérifier le paramétrage concerné."
            )
            statuses += send(
                db,
                "alerte étape",
                consultants,
                f"Étapes à revalider : {project.name}",
                body,
                project_id=project.id,
            )
    return statuses


# --------------------------------------------------------------------------- invitations


def notify_account(db: Database, user: User) -> list[str]:
    organisation = db.organisation()
    name = organisation.name if organisation else "l'organisation"
    body = (
        f"Bonjour {user.name},\n\nUn compte {user.role.label} vous a été ouvert sur l'assistant "
        f"de configuration Odoo de {name}, avec l'identifiant {user.email}. Le mot de passe "
        "initial vous est communiqué séparément par l'administrateur."
    )
    return send(db, "invitation", [user.email], "Ouverture de votre compte", body)


def notify_member(db: Database, project: Project, user: User) -> list[str]:
    body = (
        f"Bonjour {user.name},\n\nVous êtes membre du projet « {project.name} » "
        f"({project.profile.company_name}, {project.erp} {project.version})."
    )
    return send(
        db, "invitation", [user.email], f"Projet {project.name}", body, project_id=project.id
    )


# --------------------------------------------------------------------------- validations


def notify_status(
    db: Database, project: Project, step_id: str, catalog: Catalog, actor: User
) -> list[str]:
    """Step done: the client users validate it (RG-004); step validated: the consultants know."""
    from odoo_config_assistant.models import StepStatus

    status = project.plan_step(step_id).status
    title = catalog.step(step_id).title
    members = db.members(project.id)
    if status is StepStatus.DONE:
        recipients = _emails(members, Role.CLIENT)
        subject = f"Étape à valider : {title}"
        body = (
            f"{actor.name} a passé l'étape « {title} » du projet « {project.name} » à Fait. "
            "Merci de la vérifier puis de la valider (RG-004)."
        )
    elif status is StepStatus.VALIDATED:
        recipients = _emails(members, Role.CONSULTANT)
        subject = f"Étape validée : {title}"
        body = f"{actor.name} a validé l'étape « {title} » du projet « {project.name} »."
    else:
        return []
    return send(db, "validation", recipients, subject, body, project.id, step_id)
