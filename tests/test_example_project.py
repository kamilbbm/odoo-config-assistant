"""The versioned example projects (projects/exemple*.json) stay consistent with the journeys."""

from pathlib import Path

import pytest

from odoo_config_assistant.engine import generate_plan
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.storage import list_projects, load_project

PROJECTS = Path(__file__).resolve().parents[1] / "projects"

EXAMPLES = {
    "exemple": ("Atelier Boréal inc.", "fin_"),
    "exemple-fr": ("Cabinet Vauban Conseil SAS", "frf_"),
}


@pytest.mark.parametrize("project_id", EXAMPLES)
def test_example_project_matches_current_plan_and_rg003(project_id):
    company, finance_prefix = EXAMPLES[project_id]
    catalog = load_catalog()
    project = load_project(project_id, PROJECTS)
    assert project.profile.company_name == company
    expected = [s.step_id for s in generate_plan(project.profile, catalog)]
    assert [s.step_id for s in project.plan] == expected
    assert any(s.step_id.startswith(finance_prefix) for s in project.plan)
    statuses = {s.step_id: s.status for s in project.plan}
    for step_id, status in statuses.items():
        if status.is_complete:
            for prerequisite in catalog.step(step_id).prerequisites:
                if prerequisite in statuses:
                    assert statuses[prerequisite].is_complete, (prerequisite, step_id)
    assert {s.doc_commit for s in project.plan} == {project.doc_commit}


def test_quebec_example_opens_first():
    """The app opens the most recently updated project: the screenshots show Atelier Boréal."""
    examples = [p.id for p in list_projects(PROJECTS) if p.id in EXAMPLES]
    assert examples[0] == "exemple"
