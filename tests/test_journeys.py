import pytest

from conftest import make_journey, make_step, write_journeys
from odoo_config_assistant.journeys import JourneyValidationError, find_cycle, load_catalog
from odoo_config_assistant.models import (
    Condition,
    Profile,
    Recommendation,
    Source,
    Step,
    public_url,
)


def test_valid_catalog_loads(tmp_path):
    write_journeys(tmp_path, make_journey("j", [make_step("a"), make_step("b", ["a"])]))
    catalog = load_catalog(tmp_path)
    assert [s.id for s in catalog.journeys[0].steps] == ["a", "b"]


def test_rg012_step_with_empty_sources_is_rejected(tmp_path):
    write_journeys(tmp_path, make_journey("j", [make_step("a", sources=[])]))
    with pytest.raises(JourneyValidationError, match="RG-012"):
        load_catalog(tmp_path)


def test_rg012_step_without_sources_key_is_rejected(tmp_path):
    step = make_step("a")
    del step["sources"]
    write_journeys(tmp_path, make_journey("j", [step]))
    with pytest.raises(JourneyValidationError, match="RG-012"):
        load_catalog(tmp_path)


def test_rg012_rejects_whole_catalog_and_names_the_file(tmp_path):
    write_journeys(
        tmp_path,
        make_journey("ok", [make_step("a")]),
        make_journey("bad", [make_step("b", sources=[])]),
    )
    with pytest.raises(JourneyValidationError) as exc:
        load_catalog(tmp_path)
    assert any("bad.yaml" in e and "RG-012" in e for e in exc.value.errors)


def test_source_must_be_rst_under_content():
    with pytest.raises(ValueError):
        Source(path="docs/page.md", title="x", url="https://example.org")


def test_unknown_prerequisite_is_rejected(tmp_path):
    write_journeys(tmp_path, make_journey("j", [make_step("a", ["ghost"])]))
    with pytest.raises(JourneyValidationError, match="prérequis inexistant ghost"):
        load_catalog(tmp_path)


def test_prerequisite_cycle_is_rejected(tmp_path):
    steps = [make_step("a", ["c"]), make_step("b", ["a"]), make_step("c", ["b"])]
    write_journeys(tmp_path, make_journey("j", steps))
    with pytest.raises(JourneyValidationError, match="cycle de prérequis"):
        load_catalog(tmp_path)


def test_cross_journey_prerequisites_are_allowed(tmp_path):
    write_journeys(
        tmp_path,
        make_journey("fin", [make_step("fin_a")]),
        make_journey("inv", [make_step("inv_a", ["fin_a"])]),
    )
    assert len(load_catalog(tmp_path).journeys) == 2


def test_duplicate_step_id_is_rejected(tmp_path):
    write_journeys(
        tmp_path,
        make_journey("j1", [make_step("a")]),
        make_journey("j2", [make_step("a")]),
    )
    with pytest.raises(JourneyValidationError, match="définie deux fois"):
        load_catalog(tmp_path)


def test_find_cycle_returns_closed_path():
    assert find_cycle({"a": ["b"], "b": ["a"]}) in (["a", "b", "a"], ["b", "a", "b"])
    assert find_cycle({"a": [], "b": ["a"]}) is None


def test_unverified_recommendation_requires_note():
    with pytest.raises(ValueError, match="note"):
        Recommendation(value="5 %", verified=False)
    assert Recommendation(value="5 %", verified=False, note="À confirmer").note


def test_condition_rejects_unknown_profile_field():
    with pytest.raises(ValueError, match="inconnu"):
        Condition({"planet": ["Mars"]})


def test_condition_semantics():
    profile = Profile(country="ca", province="QC", modules=["account"], uses_checks=True)
    assert Condition({"country": ["CA"], "province": "QC"}).matches(profile)
    assert Condition({"modules": ["mrp", "account"]}).matches(profile)
    assert not Condition({"modules": ["mrp"]}).matches(profile)
    assert Condition({"uses_checks": True}).matches(profile)
    assert not Condition({"tracks_lots": True}).matches(profile)
    assert Condition({"foreign_currencies": False}).matches(profile)
    assert not Condition({"foreign_currencies": True}).matches(profile)
    assert not Condition({"activity": ["manufacturing"]}).matches(profile)


def test_recommendation_depends_on_profile():
    step_data = make_step(
        "s",
        recommendations=[
            {"value": "1 étape", "when": {"size": ["micro"]}},
            {"value": "2 étapes"},
        ],
    )
    step = Step.model_validate(step_data)
    assert step.recommendation_for(Profile(size="micro")).value == "1 étape"
    assert step.recommendation_for(Profile(size="medium")).value == "2 étapes"


def test_public_url_uses_french_18_doc_and_sphinx_anchor():
    url = public_url(
        "content/applications/finance/fiscal_localizations/canada.rst",
        "localizations/canada/fiscal-positions",
    )
    assert url == (
        "https://www.odoo.com/documentation/18.0/fr/applications/finance/"
        "fiscal_localizations/canada.html#localizations-canada-fiscal-positions"
    )
