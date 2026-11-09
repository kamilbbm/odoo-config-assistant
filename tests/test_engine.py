import pytest
from pydantic import ValidationError

from conftest import make_journey, make_step
from odoo_config_assistant.engine import (
    IncompleteProfileError,
    NoJourneyError,
    PrerequisiteError,
    StatusTransitionError,
    change_version,
    create_project,
    generate_plan,
    prerequisite_info,
    recompute_plan,
    set_status,
    topological_sort,
)
from odoo_config_assistant.models import Catalog, Edition, Journey, Profile, StepStatus

COMMIT = "c" * 40


def ids(plan):
    return [s.step_id for s in plan]


def statuses(project):
    return {s.step_id: s.status for s in project.plan}


# RG-002 -------------------------------------------------------------------------------


def test_rg002_empty_profile_lists_all_missing_fields(small_catalog):
    with pytest.raises(IncompleteProfileError) as exc:
        generate_plan(Profile(), small_catalog)
    assert exc.value.missing == ["country", "activity", "modules"]
    assert "Pays" in str(exc.value) and "Modules souhaités" in str(exc.value)


def test_rg002_profile_without_country_is_refused(small_catalog, complete_profile):
    profile = complete_profile.model_copy(update={"country": None})
    with pytest.raises(IncompleteProfileError) as exc:
        generate_plan(profile, small_catalog)
    assert exc.value.missing == ["country"]


def test_rg002_complete_profile_generates_plan(small_catalog, complete_profile):
    assert ids(generate_plan(complete_profile, small_catalog)) == ["a", "b", "c", "e"]


# Plan ordering ---------------------------------------------------------------------------


def test_plan_puts_prerequisites_first_even_if_listed_later(complete_profile):
    steps = [make_step("late", ["early"]), make_step("other"), make_step("early")]
    catalog = Catalog(journeys=[Journey.model_validate(make_journey("j", steps))])
    assert ids(generate_plan(complete_profile, catalog)) == ["other", "early", "late"]


def test_plan_filters_steps_and_journeys_by_profile(small_catalog, complete_profile):
    plan = generate_plan(complete_profile, small_catalog)
    assert "d" not in ids(plan)
    with_mrp = complete_profile.model_copy(update={"modules": ["account", "mrp"]})
    assert ids(generate_plan(with_mrp, small_catalog)) == ["a", "b", "c", "d", "e"]

    qc_only = make_journey("qc", [make_step("x")], applies_when={"province": ["QC"]})
    catalog = Catalog(journeys=[Journey.model_validate(qc_only)])
    on_profile = complete_profile.model_copy(update={"province": "ON"})
    assert ids(generate_plan(on_profile, catalog)) == []


def test_topological_sort_detects_cycle():
    steps = [
        ("j", Journey.model_validate(make_journey("j", [make_step("a", ["b"])])).steps[0]),
        ("j", Journey.model_validate(make_journey("j", [make_step("b", ["a"])])).steps[0]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        topological_sort(steps)


# RG-003 -------------------------------------------------------------------------------


def test_rg003_done_is_refused_and_lists_blocking_prerequisites(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    with pytest.raises(PrerequisiteError) as exc:
        set_status(project, "c", StepStatus.DONE, small_catalog)
    assert exc.value.blocking == ["b"]


def test_rg003_in_progress_is_allowed_without_prerequisites(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    project = set_status(project, "c", StepStatus.IN_PROGRESS, small_catalog)
    assert project.plan_step("c").status is StepStatus.IN_PROGRESS


def test_rg003_done_allowed_when_prerequisites_done_or_validated(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    project = set_status(project, "a", StepStatus.DONE, small_catalog)
    project = set_status(project, "a", StepStatus.VALIDATED, small_catalog)
    project = set_status(project, "b", StepStatus.DONE, small_catalog)
    project = set_status(project, "c", StepStatus.DONE, small_catalog)
    assert statuses(project)["c"] is StepStatus.DONE


def test_rg003_validated_also_requires_prerequisites(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    with pytest.raises(PrerequisiteError):
        set_status(project, "b", StepStatus.VALIDATED, small_catalog)


def test_validated_requires_done_first(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    with pytest.raises(StatusTransitionError):
        set_status(project, "a", StepStatus.VALIDATED, small_catalog)


def test_rg003_prerequisite_outside_plan_does_not_block(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    project = set_status(project, "a", StepStatus.DONE, small_catalog)
    info = prerequisite_info(project, "e", small_catalog)
    assert info.outside_plan == ["d"] and info.finished == ["a"] and not info.blocking
    project = set_status(project, "e", StepStatus.DONE, small_catalog)
    assert statuses(project)["e"] is StepStatus.DONE


# RG-005 -------------------------------------------------------------------------------


def test_rg005_profile_change_keeps_done_and_moves_to_out_of_scope(small_catalog, complete_profile):
    with_mrp = complete_profile.model_copy(update={"modules": ["account", "mrp"]})
    project = create_project("P", with_mrp, small_catalog)
    project = set_status(project, "a", StepStatus.DONE, small_catalog)
    project = set_status(project, "d", StepStatus.DONE, small_catalog)

    project = recompute_plan(project, complete_profile, small_catalog)
    assert ids(project.plan) == ["a", "b", "c", "e", "d"]
    assert statuses(project)["a"] is StepStatus.DONE
    assert statuses(project)["d"] is StepStatus.OUT_OF_SCOPE

    project = recompute_plan(project, with_mrp, small_catalog)
    assert statuses(project)["d"] is StepStatus.DONE
    assert ids(project.plan) == ["a", "b", "c", "d", "e"]


def test_rg005_new_applicable_step_is_added_as_todo(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    with_mrp = complete_profile.model_copy(update={"modules": ["account", "mrp"]})
    project = recompute_plan(project, with_mrp, small_catalog)
    assert statuses(project)["d"] is StepStatus.TODO


def test_rg005_out_of_scope_step_cannot_be_reopened(small_catalog, complete_profile):
    with_mrp = complete_profile.model_copy(update={"modules": ["account", "mrp"]})
    project = create_project("P", with_mrp, small_catalog)
    project = recompute_plan(project, complete_profile, small_catalog)
    with pytest.raises(StatusTransitionError):
        set_status(project, "d", StepStatus.IN_PROGRESS, small_catalog)


def test_rg005_incomplete_new_profile_leaves_plan_unchanged(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    with pytest.raises(IncompleteProfileError):
        recompute_plan(project, Profile(country="CA"), small_catalog)
    assert ids(project.plan) == ["a", "b", "c", "e"]


# RG-001 -------------------------------------------------------------------------------


def two_version_catalog() -> Catalog:
    return Catalog(
        journeys=[
            Journey.model_validate(make_journey("v18", [make_step("old")])),
            Journey.model_validate(make_journey("v19", [make_step("new")], version="19.0")),
        ]
    )


def test_rg001_project_version_and_erp_are_frozen(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog)
    with pytest.raises(ValidationError):
        project.version = "19.0"
    with pytest.raises(ValidationError):
        project.erp = "sap"


def test_rg001_plan_only_uses_journeys_of_project_version(complete_profile):
    project = create_project("P", complete_profile, two_version_catalog())
    assert ids(project.plan) == ["old"]


def test_rg001_version_change_creates_a_new_plan(complete_profile):
    catalog = two_version_catalog()
    project = create_project("P", complete_profile, catalog, doc_commit=COMMIT)
    project = set_status(project, "old", StepStatus.DONE, catalog)

    upgraded = change_version(project, "19.0", catalog)
    assert upgraded.id != project.id and upgraded.derived_from == project.id
    assert upgraded.version == "19.0" and ids(upgraded.plan) == ["new"]
    assert project.version == "18.0" and statuses(project)["old"] is StepStatus.DONE


def test_rg001_version_without_journey_is_refused(complete_profile, small_catalog):
    project = create_project("P", complete_profile, small_catalog)
    with pytest.raises(NoJourneyError):
        change_version(project, "17.0", small_catalog)


# RG-008 (plan side) -------------------------------------------------------------------


def test_rg008_plan_steps_keep_doc_commit(small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog, doc_commit=COMMIT)
    assert {s.doc_commit for s in project.plan} == {COMMIT}
    project = set_status(project, "a", StepStatus.DONE, small_catalog)
    assert project.plan_step("a").doc_commit == COMMIT


# Q-008 Community / Enterprise --------------------------------------------------------------


@pytest.fixture
def edition_catalog() -> Catalog:
    steps = [
        make_step("base", modules=["account"]),
        make_step("report", ["base"], modules=["account", "account_reports"]),
        make_step("free"),
    ]
    journey = Journey.model_validate(make_journey("j", steps))
    return Catalog(journeys=[journey], community_modules=frozenset({"account"}))


@pytest.mark.parametrize(
    ("edition", "expected"),
    [
        (None, ["base", "report", "free"]),
        (Edition.ENTERPRISE, ["base", "report", "free"]),
        (Edition.COMMUNITY, ["base", "free"]),
    ],
)
def test_q008_enterprise_steps_are_left_out_of_a_community_plan(
    edition_catalog, complete_profile, edition, expected
):
    profile = complete_profile.model_copy(update={"edition": edition})
    assert ids(generate_plan(profile, edition_catalog)) == expected


def test_q008_enterprise_modules_are_listed_per_step(edition_catalog):
    assert edition_catalog.enterprise_modules(edition_catalog.step("report")) == [
        "account_reports"
    ]
    assert edition_catalog.enterprise_modules(edition_catalog.step("base")) == []
    unknown = edition_catalog.model_copy(update={"community_modules": None})
    assert unknown.enterprise_modules(unknown.step("report")) == []


def test_q008_switching_to_community_puts_enterprise_steps_out_of_scope(
    edition_catalog, complete_profile
):
    project = create_project("P", complete_profile, edition_catalog, doc_commit=COMMIT)
    community = complete_profile.model_copy(update={"edition": Edition.COMMUNITY})
    project = recompute_plan(project, community, edition_catalog)
    assert statuses(project)["report"] is StepStatus.OUT_OF_SCOPE
    with pytest.raises(StatusTransitionError):
        set_status(project, "report", StepStatus.TODO, edition_catalog)


def test_q008_module_names_are_validated():
    with pytest.raises(ValidationError):
        Journey.model_validate(make_journey("j", [make_step("a", modules=["Account Reports"])]))
