"""The versioned example project (projects/exemple.json) stays consistent with the journeys."""

from pathlib import Path

from odoo_config_assistant.engine import generate_plan
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.storage import load_project

PROJECTS = Path(__file__).resolve().parents[1] / "projects"


def test_example_project_matches_current_plan_and_rg003():
    catalog = load_catalog()
    project = load_project("exemple", PROJECTS)
    assert project.profile.company_name == "Atelier Boréal inc."
    expected = [s.step_id for s in generate_plan(project.profile, catalog)]
    assert [s.step_id for s in project.plan] == expected
    statuses = {s.step_id: s.status for s in project.plan}
    for step_id, status in statuses.items():
        if status.is_complete:
            for prerequisite in catalog.step(step_id).prerequisites:
                if prerequisite in statuses:
                    assert statuses[prerequisite].is_complete, (prerequisite, step_id)
    assert {s.doc_commit for s in project.plan} == {project.doc_commit}
