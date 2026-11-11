"""Business repository and journey editor (F-004, F-005, E-09, RG-011, RG-012)."""

import io
import zipfile
from pathlib import Path

import pytest
import yaml

from odoo_config_assistant import repository
from odoo_config_assistant.access import AccessDenied
from odoo_config_assistant.db import Database
from odoo_config_assistant.journeys import JourneyValidationError, load_catalog
from odoo_config_assistant.seed import ensure_ready

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "vendor" / "odoo-docs"
CATALOG = load_catalog()
SFD_DOMAINS = ["Finance", "Ventes", "Services", "Supply chain", "RH", "Marketing", "Site web"]


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "repo.db")
    ensure_ready(database)
    return database


def user(db, name):
    return db.user_by_email(f"{name}@organisation.example")


# Shipped repository ------------------------------------------------------------------------


def test_referential_covers_the_sfd_domains():
    assert CATALOG.referential.domain_labels() == SFD_DOMAINS


def test_every_step_is_linked_to_a_parameter_of_its_domain():
    for journey in CATALOG.journeys:
        for step in journey.steps:
            location = CATALOG.location(step)
            assert location is not None, step.id
            assert location.domain.label == journey.domain


def test_parameter_sources_include_the_pages_of_their_steps():
    paths = CATALOG.referential.paths()
    for journey in CATALOG.journeys:
        for step in journey.steps:
            assert {s.path for s in step.sources} <= set(paths[step.parameter].parameter.sources)


@pytest.mark.skipif(not (DOCS / "content").is_dir(), reason="clone absent")
def test_parameter_sources_exist_in_the_documentation():
    for path in CATALOG.referential.paths().values():
        for source in path.parameter.sources:
            assert (DOCS / source).is_file(), source


def test_unknown_parameter_or_wrong_domain_is_refused():
    name = "journeys/inventory_mrp.yaml"
    text = repository.repository_files()[name]
    with pytest.raises(JourneyValidationError, match="paramètre inconnu"):
        load_catalog(overrides={name: text.replace("parameter: warehouse", "parameter: nope", 1)})
    with pytest.raises(JourneyValidationError, match="domaine"):
        load_catalog(
            overrides={name: text.replace("parameter: warehouse", "parameter: taxes", 1)}
        )


# Editor ------------------------------------------------------------------------------------


def test_referent_edits_a_step_and_the_change_is_traced(db):
    referent = user(db, "referent")
    step = repository.step_as_dict(db, "finance_fr", "frf_journals")
    step["title"] = "Journaux comptables"
    catalog = repository.save_step(db, referent, "finance_fr", step, "frf_journals")
    assert catalog.step("frf_journals").title == "Journaux comptables"
    assert repository.catalog_for(db).step("frf_journals").title == "Journaux comptables"
    history = db.repository_history()[0]
    assert history["action"] == "modification" and history["user_name"] == referent.name


def test_rg012_step_without_source_is_refused(db):
    step = repository.step_as_dict(db, "finance_fr", "frf_journals")
    step["sources"] = []
    with pytest.raises(JourneyValidationError, match="RG-012"):
        repository.save_step(db, user(db, "referent"), "finance_fr", step, "frf_journals")
    assert db.repository_overrides() == {}


def test_new_step_with_cycle_or_duplicate_id_is_refused(db):
    referent = user(db, "referent")
    new = repository.step_as_dict(db, "finance_fr", "frf_journals") | {
        "id": "frf_new",
        "title": "Nouvelle étape",
        "prerequisites": ["frf_journals"],
    }
    catalog = repository.save_step(db, referent, "finance_fr", new)
    assert catalog.step("frf_new").prerequisites == ["frf_journals"]
    looping = repository.step_as_dict(db, "finance_fr", "frf_journals")
    looping["prerequisites"] = [*looping.get("prerequisites", []), "frf_new"]
    with pytest.raises(JourneyValidationError, match="cycle"):
        repository.save_step(db, referent, "finance_fr", looping, "frf_journals")
    with pytest.raises(JourneyValidationError, match="déjà utilisé"):
        repository.save_step(db, referent, "finance_fr", new)


def test_step_used_by_a_project_cannot_be_deleted(db):
    referent = user(db, "referent")
    with pytest.raises(JourneyValidationError, match="utilisée par un projet"):
        repository.delete_step(db, referent, "finance_fr", "frf_chorus_pro")
    new = repository.step_as_dict(db, "finance_fr", "frf_chorus_pro") | {
        "id": "frf_extra",
        "prerequisites": [],
    }
    repository.save_step(db, referent, "finance_fr", new)
    catalog = repository.delete_step(db, referent, "finance_fr", "frf_extra")
    assert "frf_extra" not in {s.id for j in catalog.journeys for s in j.steps}


def test_only_the_content_owner_or_admin_edits_the_repository(db):
    step = repository.step_as_dict(db, "finance_fr", "frf_journals")
    with pytest.raises(AccessDenied):
        repository.save_step(db, user(db, "consultant"), "finance_fr", step, "frf_journals")
    repository.save_step(db, user(db, "admin"), "finance_fr", step, "frf_journals")


def test_referential_edit_is_validated_and_can_be_reset(db):
    referent = user(db, "referent")
    text = repository.current_files(db)["referential.yaml"]
    data = yaml.safe_load(text)
    data["domains"][1]["modules"][0]["label"] = "Ventes et devis"
    repository.save_referential(db, referent, yaml.safe_dump(data, allow_unicode=True))
    assert repository.catalog_for(db).referential.domains[1].modules[0].label == "Ventes et devis"
    broken = text.replace("id: taxes\n", "id: journals\n", 1)
    with pytest.raises(JourneyValidationError):
        repository.save_referential(db, referent, broken)
    repository.reset_file(db, referent, "referential.yaml")
    assert repository.catalog_for(db).referential.domains[1].modules[0].label == "Ventes"


def test_export_zip_contains_the_current_repository(db):
    step = repository.step_as_dict(db, "finance_qc", "fin_journals")
    step["title"] = "Journaux (édités)"
    repository.save_step(db, user(db, "referent"), "finance_qc", step, "fin_journals")
    archive = zipfile.ZipFile(io.BytesIO(repository.export_zip(db)))
    assert "data/referential.yaml" in archive.namelist()
    assert "Journaux (édités)" in archive.read("data/journeys/finance_qc.yaml").decode()


def test_rg011_reviewed_steps_are_recorded_per_report(db):
    db.review_step("frf_taxes", "report-1", user(db, "referent").id)
    assert db.reviewed_steps("report-1") == {"frf_taxes"}
    assert db.reviewed_steps("report-2") == set()
