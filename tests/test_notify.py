"""E-mail notifications (2.1.5 Messagerie, F-013, RG-011, error matrix, invitations)."""

from datetime import UTC, datetime
from typing import ClassVar

import pytest

from odoo_config_assistant import notify
from odoo_config_assistant.access import change_status
from odoo_config_assistant.db import Database, Role
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.models import StepStatus
from odoo_config_assistant.seed import ensure_ready
from odoo_config_assistant.sync import Anomaly, ImpactedStep, SyncReport, SyncStatus

CATALOG = load_catalog()


class FakeSMTP:
    sent: ClassVar[list] = []
    fail = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.login_as = (user, password)

    def send_message(self, message):
        if FakeSMTP.fail:
            raise OSError("connexion refusée")
        FakeSMTP.sent.append(message)


@pytest.fixture
def db(tmp_path, monkeypatch):
    database = Database(tmp_path / "notify.db")
    ensure_ready(database)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    return database


def configure(db):
    org = db.organisation()
    db.save_organisation(
        org.model_copy(update={"smtp_host": "smtp.example", "smtp_sender": "assistant@x.example"})
    )


def user(db, name):
    return db.user_by_email(f"{name}@organisation.example")


def report(**changes):
    base = dict(
        id="r1",
        trigger="planifiée",
        started_at=datetime(2026, 11, 15, 2, tzinfo=UTC),
        status=SyncStatus.PUBLISHED,
        active_commit="a" * 40,
        candidate_commit="b" * 40,
    )
    return SyncReport(**(base | changes))


def test_without_smtp_server_notifications_are_logged_not_sent(db):
    statuses = notify.send(db, "test", ["x@organisation.example"], "Objet", "Corps")
    assert statuses == [notify.NOT_CONFIGURED] and not FakeSMTP.sent
    assert db.notifications()[0]["status"] == notify.NOT_CONFIGURED


def test_sent_message_carries_the_organisation_identity(db):
    configure(db)
    assert notify.send(db, "test", ["x@organisation.example"], "Objet", "Corps") == [notify.SENT]
    message = FakeSMTP.sent[0]
    assert message["Subject"] == "[Organisation de démonstration] Objet"
    assert message["From"] == "assistant@x.example"
    assert "Organisation de démonstration" in message.get_content()


def test_smtp_failure_is_logged_with_the_error(db):
    configure(db)
    FakeSMTP.fail = True
    assert notify.send(db, "test", ["x@organisation.example"], "Objet", "Corps") == [notify.FAILED]
    assert "connexion refusée" in db.notifications()[0]["error"]


def test_rg011_impacted_step_alerts_the_referent_and_the_project_consultants(db):
    configure(db)
    impacted = ImpactedStep(
        step_id="frf_taxes",
        journey_id="finance_fr",
        title="Taxes de TVA",
        change="modifiée",
        paths=["content/applications/finance/accounting/taxes.rst"],
    )
    notify.notify_sync(db, report(impacted_steps=[impacted]))
    by_recipient = {m["To"]: m for m in FakeSMTP.sent}
    assert "referent@organisation.example" in by_recipient
    consultant = by_recipient["consultant@organisation.example"]
    assert "Cabinet Vauban" in consultant["Subject"] and "taxes.rst" in consultant.get_content()
    assert "client.vauban@organisation.example" not in by_recipient
    assert "admin@organisation.example" not in by_recipient


def test_error_matrix_routes_anomalies_to_admin_or_referent(db):
    configure(db)
    failed = report(
        status=SyncStatus.FAILED,
        anomalies=[Anomaly(code="ERR-001", stage=1, message="dépôt inaccessible")],
    )
    notify.notify_sync(db, failed)
    assert [m["To"] for m in FakeSMTP.sent] == ["admin@organisation.example"]
    FakeSMTP.sent.clear()
    partial = report(anomalies=[Anomaly(code="ERR-004", stage=3, message="partielle")])
    notify.notify_sync(db, partial)
    assert [m["To"] for m in FakeSMTP.sent] == ["referent@organisation.example"]


def test_invitations(db):
    configure(db)
    created = db.create_user("nouveau@organisation.example", "Nora Nouvelle", Role.CLIENT, "x" * 10)
    notify.notify_account(db, created)
    notify.notify_member(db, db.project("exemple"), created)
    subjects = [m["Subject"] for m in FakeSMTP.sent]
    assert any("Ouverture de votre compte" in s for s in subjects)
    assert any("Atelier Boréal" in s for s in subjects)
    assert "x" * 10 not in "".join(m.get_content() for m in FakeSMTP.sent)  # pas de mot de passe


def test_validation_workflow_notifications(db):
    configure(db)
    project = db.project("exemple-fr")
    consultant, client = user(db, "consultant"), user(db, "client.vauban")
    done = change_status(db, consultant, project, "frf_journals", StepStatus.DONE, CATALOG)
    notify.notify_status(db, done, "frf_journals", CATALOG, consultant)
    assert [m["To"] for m in FakeSMTP.sent] == ["client.vauban@organisation.example"]
    validated = change_status(db, client, done, "frf_journals", StepStatus.VALIDATED, CATALOG)
    notify.notify_status(db, validated, "frf_journals", CATALOG, client)
    assert FakeSMTP.sent[-1]["To"] == "consultant@organisation.example"
    assert "validé" in FakeSMTP.sent[-1].get_content()
