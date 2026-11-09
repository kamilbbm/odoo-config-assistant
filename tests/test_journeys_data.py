"""Checks on the real journey repository (data/journeys).

The tests marked ``needs_docs`` compare every step with the downloaded Odoo documentation
(vendor/odoo-docs, see scripts/fetch_docs.py). They are skipped when the clone is absent.
"""

import json
import re
from pathlib import Path

import pytest

from odoo_config_assistant.engine import generate_plan, topological_sort
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.knowledge import split_sections
from odoo_config_assistant.models import Activity, CompanySize, Profile

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "vendor" / "odoo-docs"
needs_docs = pytest.mark.skipif(
    not (DOCS / "content").is_dir(), reason="clone absent : lancer scripts/fetch_docs.py"
)

CATALOG = load_catalog()
STEPS = [(j, s) for j in CATALOG.journeys for s in j.steps]
SOURCES = [(s, src) for _, s in STEPS for src in s.sources]


def step_ids(steps):
    return [s.id for s in steps]


def boreal_profile(**changes) -> Profile:
    profile = Profile(
        company_name="Atelier Boréal inc.",
        country="CA",
        province="QC",
        activity=Activity.MANUFACTURING,
        size=CompanySize.SMALL,
        modules=["account", "stock", "mrp", "purchase"],
    )
    return profile.model_copy(update=changes)


def test_all_journeys_are_loaded_for_odoo_18():
    assert {j.id for j in CATALOG.journeys} == {"finance_qc", "finance_fr", "inventory_mrp"}
    assert all(j.erp == "odoo" and j.version == "18.0" for j in CATALOG.journeys)


@pytest.mark.parametrize("journey", CATALOG.journeys, ids=lambda j: j.id)
def test_journey_has_12_to_19_steps(journey):
    assert 12 <= len(journey.steps) <= 19


@pytest.mark.parametrize(("step", "source"), SOURCES, ids=lambda x: getattr(x, "id", ""))
def test_rg014_source_url_matches_rst_path(step, source):
    assert source.url == source.expected_url, step.id


def test_unverified_recommendations_are_flagged_with_a_note():
    unverified = [r for _, s in STEPS for r in s.recommendations if not r.verified]
    assert unverified, "les valeurs propres au Québec doivent être marquées verified: false"
    assert all(r.note for r in unverified)


def test_gst_qst_rates_are_not_presented_as_verified():
    taxes = CATALOG.step("fin_taxes")
    assert all(not r.verified for r in taxes.recommendations)


def test_doc_version_file_records_a_full_commit():
    info = json.loads((ROOT / "data" / "doc_version.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{40}", info["commit"]) and info["branch"] == "18.0"


# Plans generated from the real repository ---------------------------------------------


def test_boreal_plan_contains_both_journeys_in_prerequisite_order():
    plan = generate_plan(boreal_profile(), CATALOG)
    ids = [p.step_id for p in plan]
    assert ids[0] == "fin_company"
    position = {step_id: i for i, step_id in enumerate(ids)}
    for step_id in ids:
        for prerequisite in CATALOG.step(step_id).prerequisites:
            if prerequisite in position:
                assert position[prerequisite] < position[step_id], (prerequisite, step_id)
    assert ids.index("mrp_first_mo") > ids.index("inv_initial_quantities")


def test_optional_steps_follow_the_profile():
    base = {p.step_id for p in generate_plan(boreal_profile(), CATALOG)}
    assert not base & {"fin_check_printing", "fin_foreign_currencies", "inv_lots", "mrp_mto"}
    full = boreal_profile(
        uses_checks=True, foreign_currencies=["USD"], tracks_lots=True, make_to_order=True
    )
    extended = {p.step_id for p in generate_plan(full, CATALOG)}
    assert extended - base == {
        "fin_check_printing",
        "fin_foreign_currencies",
        "inv_lots",
        "mrp_mto",
    }


def test_ontario_company_gets_no_quebec_finance_journey():
    ids = step_ids_from(generate_plan(boreal_profile(province="ON"), CATALOG))
    assert not any(i.startswith("fin_") for i in ids)
    assert "mrp_bom" in ids


def test_inventory_only_profile_skips_manufacturing_and_purchase_steps():
    profile = boreal_profile(modules=["stock"], activity=Activity.DISTRIBUTION)
    ids = step_ids_from(generate_plan(profile, CATALOG))
    assert ids and all(i.startswith("inv_") for i in ids)
    assert "inv_components" not in ids


def test_recommendation_depends_on_company_size():
    step = CATALOG.step("inv_receipt_steps")
    assert "1 step" in step.recommendation_for(boreal_profile(size=CompanySize.MICRO)).value
    assert "2 steps" in step.recommendation_for(boreal_profile()).value


def test_full_catalog_sorts_without_cycle():
    ordered = topological_sort([(j.id, s) for j, s in STEPS])
    assert len(ordered) == len(STEPS)


def step_ids_from(plan):
    return [p.step_id for p in plan]


# Truthfulness against the downloaded documentation -------------------------------------


def _normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _menus(path: Path) -> set[str]:
    return {m.strip() for m in re.findall(r":menuselection:`([^`]*)`", _normalized(path))}


@needs_docs
@pytest.mark.parametrize(("step", "source"), SOURCES, ids=lambda x: getattr(x, "id", ""))
def test_cited_source_exists_in_clone(step, source):
    assert (DOCS / source.path).is_file(), f"{step.id} : {source.path} introuvable"


@needs_docs
@pytest.mark.parametrize(("step", "source"), SOURCES, ids=lambda x: getattr(x, "id", ""))
def test_cited_anchor_exists_in_page(step, source):
    if source.anchor is None:
        pytest.skip("pas d'ancre")
    labels = re.findall(r"^\.\. _([^:]+):", (DOCS / source.path).read_text("utf-8"), re.M)
    assert source.anchor in labels, f"{step.id} : ancre {source.anchor} absente"


@needs_docs
@pytest.mark.parametrize(("step", "source"), SOURCES, ids=lambda x: getattr(x, "id", ""))
def test_source_title_is_the_page_title(step, source):
    sections = split_sections((DOCS / source.path).read_text(encoding="utf-8"))
    page_title = next(title for title, _, _ in sections if title)
    assert source.title == page_title, step.id


@needs_docs
@pytest.mark.parametrize(("journey", "step"), STEPS, ids=lambda x: x.id)
def test_menu_path_appears_verbatim_in_a_cited_source(journey, step):
    """The menu must be written as such in the doc.

    Some pages name the app in the sentence ("In the Manufacturing app, select Configuration -->
    Work Centers"): the path without its first item is then accepted, if that first item is
    named in the same page.
    """
    wanted = " --> ".join(step.menu_items)
    tail = " --> ".join(step.menu_items[1:])
    app = step.menu_items[0].removesuffix(" app")
    for source in step.sources:
        menus = _menus(DOCS / source.path)
        if wanted in menus:
            return
        if len(step.menu_items) > 2 and tail in menus and app in _normalized(DOCS / source.path):
            return
    pytest.fail(f"{step.id} : menu « {step.menu_path} » absent des sources citées")


# Finance France (US-001) -----------------------------------------------------------------


def france_services_profile(**changes) -> Profile:
    profile = Profile(
        company_name="Conseil Exemple SAS",
        country="FR",
        activity=Activity.SERVICES,
        size=CompanySize.SMALL,
        modules=["account"],
    )
    return profile.model_copy(update=changes)


def test_us001_french_services_company_gets_the_finance_france_journey_in_order():
    plan = generate_plan(france_services_profile(), CATALOG)
    ids = step_ids_from(plan)
    assert ids and all(i.startswith("frf_") for i in ids)
    assert ids[0] == "frf_company"
    position = {step_id: i for i, step_id in enumerate(ids)}
    for step_id in ids:
        for prerequisite in CATALOG.step(step_id).prerequisites:
            if prerequisite in position:
                assert position[prerequisite] < position[step_id], (prerequisite, step_id)
    assert position["frf_localization"] < position["frf_taxes"] < position["frf_tax_report"]


def test_quebec_company_gets_no_finance_france_journey():
    ids = step_ids_from(generate_plan(boreal_profile(), CATALOG))
    assert not any(i.startswith("frf_") for i in ids)


def test_france_optional_steps_follow_the_profile():
    base = set(step_ids_from(generate_plan(france_services_profile(), CATALOG)))
    assert not base & {"frf_chorus_pro", "frf_foreign_currencies"}
    full = france_services_profile(b2g_invoicing=True, foreign_currencies=["USD"])
    extended = set(step_ids_from(generate_plan(full, CATALOG)))
    assert extended - base == {"frf_chorus_pro", "frf_foreign_currencies"}


def test_france_recommendations_depend_on_the_profile():
    sepa = CATALOG.step("frf_sepa")
    assert "Direct Debit" not in sepa.recommendation_for(france_services_profile()).value
    debit = france_services_profile(uses_direct_debit=True)
    assert "Creditor Identifier" in sepa.recommendation_for(debit).value
    opening = CATALOG.step("frf_opening_balances")
    assert "Import FEC" in opening.recommendation_for(
        france_services_profile(imports_fec_history=True)
    ).value
    assert not opening.recommendation_for(france_services_profile()).verified


def test_french_vat_rates_are_not_presented_as_verified():
    assert all(not r.verified for r in CATALOG.step("frf_taxes").recommendations)
