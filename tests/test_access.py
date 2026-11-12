"""Database, organisation, users, roles and access rules (F-001, F-006, RG-004, RG-015)."""

import pytest

from odoo_config_assistant.access import (
    AccessDenied,
    allowed_statuses,
    can_edit_profile,
    can_manage_project,
    can_manage_sources,
    change_status,
    edit_step,
    visible_projects,
)
from odoo_config_assistant.db import (
    Database,
    Exchange,
    Organisation,
    Role,
    hash_password,
    verify_password,
)
from odoo_config_assistant.engine import project_progress, set_status
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.models import StepStatus
from odoo_config_assistant.seed import demo_enabled, ensure_ready, setup_organisation

CATALOG = load_catalog()
PASSWORD = "demo-odoo-18"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    assert ensure_ready(database)
    return database


def user(db, email):
    return db.user_by_email(f"{email}@organisation.example")


def test_passwords_are_hashed_and_checked():
    stored = hash_password("correct horse")
    assert stored.startswith("pbkdf2_sha256$") and "correct horse" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)
    with pytest.raises(ValueError):
        hash_password("short")


def test_demo_seed_loads_organisation_users_and_example_projects(db):
    organisation = db.organisation()
    assert organisation.demo and organisation.name == "Organisation de démonstration"
    assert {u.role for u in db.users()} == set(Role)
    assert {p.id for p in db.projects()} == {"exemple", "exemple-fr"}
    assert {m.email for m in db.members("exemple-fr")} == {
        "consultant@organisation.example",
        "client.vauban@organisation.example",
    }
    assert db.authenticate("consultant@organisation.example", PASSWORD).role is Role.CONSULTANT
    assert db.authenticate("consultant@organisation.example", "bad password") is None


def test_setup_without_demo_creates_the_organisation_and_its_administrator(tmp_path, monkeypatch):
    monkeypatch.setenv("OCA_DEMO", "0")
    assert not demo_enabled()
    database = Database(tmp_path / "empty.db")
    assert not ensure_ready(database)
    admin = setup_organisation(database, "Mon cabinet", "moi@cabinet.example", "Moi", "secret-123")
    assert admin.role is Role.ADMIN and database.organisation().name == "Mon cabinet"
    assert not database.organisation().demo and database.projects() == []
    with pytest.raises(ValueError):
        setup_organisation(database, "Autre", "autre@cabinet.example", "Autre", "secret-123")


def test_organisation_name_is_required():
    with pytest.raises(ValueError):
        Organisation(name="  ")


def test_inactive_user_cannot_log_in_and_last_admin_is_kept(db):
    client = user(db, "client.boreal")
    db.update_user(client.id, active=False)
    assert db.authenticate(client.email, PASSWORD) is None
    admin = user(db, "admin")
    with pytest.raises(ValueError, match="administrateur"):
        db.update_user(admin.id, role=Role.CONSULTANT)
    with pytest.raises(ValueError):
        db.create_user(admin.email, "Doublon", Role.CLIENT, PASSWORD)


def test_rg015_users_only_see_their_projects_except_the_administrator(db):
    assert {p.id for p in visible_projects(db, user(db, "admin"))} == {"exemple", "exemple-fr"}
    assert {p.id for p in visible_projects(db, user(db, "consultant"))} == {
        "exemple",
        "exemple-fr",
    }
    assert [p.id for p in visible_projects(db, user(db, "client.vauban"))] == ["exemple-fr"]
    assert visible_projects(db, user(db, "referent")) == []


def test_rg004_only_the_client_member_validates(db):
    project = db.project("exemple-fr")
    step = "frf_main_currency"
    assert project.plan_step(step).status is StepStatus.DONE
    consultant, client = user(db, "consultant"), user(db, "client.vauban")
    with pytest.raises(AccessDenied, match="RG-004"):
        change_status(db, consultant, project, step, StepStatus.VALIDATED, CATALOG)
    with pytest.raises(AccessDenied, match="RG-004"):
        change_status(db, user(db, "admin"), project, step, StepStatus.VALIDATED, CATALOG)
    with pytest.raises(AccessDenied, match="RG-015"):
        change_status(db, user(db, "client.boreal"), project, step, StepStatus.VALIDATED, CATALOG)
    validated = change_status(db, client, project, step, StepStatus.VALIDATED, CATALOG)
    assert validated.plan_step(step).status is StepStatus.VALIDATED
    assert allowed_statuses(db, client, validated, step) == [StepStatus.DONE, StepStatus.VALIDATED]
    # Le consultant ne revient pas sur une validation client.
    with pytest.raises(AccessDenied):
        change_status(db, consultant, validated, step, StepStatus.TODO, CATALOG)


def test_client_cannot_run_steps_but_can_comment(db):
    project = db.project("exemple-fr")
    client = user(db, "client.vauban")
    step = "frf_journals"  # En cours
    assert allowed_statuses(db, client, project, step) == [StepStatus.IN_PROGRESS]
    with pytest.raises(AccessDenied):
        change_status(db, client, project, step, StepStatus.DONE, CATALOG)
    commented = edit_step(db, client, project, step, project.plan_step(step).retained_value, "OK")
    assert commented.plan_step(step).comment == "OK"
    with pytest.raises(AccessDenied):
        edit_step(db, client, project, step, "valeur client", "OK")


def test_consultant_runs_steps_with_rg003(db):
    project = db.project("exemple-fr")
    consultant = user(db, "consultant")
    assert StepStatus.VALIDATED not in allowed_statuses(db, consultant, project, "frf_journals")
    done = change_status(db, consultant, project, "frf_journals", StepStatus.DONE, CATALOG)
    assert done.plan_step("frf_journals").status is StepStatus.DONE
    assert can_manage_project(db, consultant, project.id)
    assert can_edit_profile(db, user(db, "client.vauban"), project.id)
    assert not can_manage_project(db, user(db, "client.vauban"), project.id)


def test_members_are_consultants_or_clients(db):
    with pytest.raises(ValueError):
        db.add_member("exemple", user(db, "referent").id)
    db.add_member("exemple", user(db, "client.vauban").id)
    assert "exemple" in db.member_project_ids(user(db, "client.vauban").id)
    db.remove_member("exemple", user(db, "client.vauban").id)
    assert "exemple" not in db.member_project_ids(user(db, "client.vauban").id)


def test_roles_for_sources():
    from odoo_config_assistant.db import User

    assert can_manage_sources(User(id=1, email="a@b.c", name="A", role=Role.REFERENT))
    assert not can_manage_sources(User(id=2, email="c@b.c", name="C", role=Role.CONSULTANT))


def test_projects_are_saved_in_the_database(db):
    project = db.project("exemple")
    changed = set_status(project, "fin_fiscal_year", StepStatus.IN_PROGRESS, CATALOG)
    db.save_project(changed)
    assert db.project("exemple").plan_step("fin_fiscal_year").status is StepStatus.IN_PROGRESS
    assert db.projects()[0].id == "exemple"


def test_exchanges_and_deliverables_are_recorded(db):
    consultant = user(db, "consultant")
    saved = db.add_exchange(
        Exchange(
            project_id="exemple",
            step_id="fin_taxes",
            user_id=consultant.id,
            question="Q",
            text="R",
            covered=True,
            mode="extracts",
            doc_commit="c" * 40,
            version="18.0",
        )
    )
    assert saved.id and db.exchanges("exemple")[0].doc_commit == "c" * 40
    assert db.exchanges("exemple", step_id="other") == []
    db.log_deliverable("exemple", "cahier", "xlsx", consultant.id)
    assert db.deliverables("exemple")[0]["user_name"] == consultant.name


def test_dashboard_progress_by_domain(db):
    progress = project_progress(db.project("exemple"), CATALOG)
    assert set(progress.by_domain) == {"Finance", "Supply chain"}
    assert progress.total == sum(total for _, total in progress.by_domain.values())
    assert 0 < progress.ratio < 1
