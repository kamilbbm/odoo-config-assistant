import pytest

from odoo_config_assistant.engine import create_project, set_status
from odoo_config_assistant.models import StepStatus
from odoo_config_assistant.storage import list_projects, load_project, save_project


def test_project_round_trip_keeps_plan_and_statuses(tmp_path, small_catalog, complete_profile):
    project = create_project("P", complete_profile, small_catalog, doc_commit="c" * 40)
    project = set_status(project, "a", StepStatus.DONE, small_catalog)
    save_project(project, tmp_path)
    loaded = load_project(project.id, tmp_path)
    assert loaded == project
    assert loaded.plan_step("a").status is StepStatus.DONE


def test_list_projects_skips_broken_files(tmp_path, small_catalog, complete_profile):
    save_project(create_project("P", complete_profile, small_catalog), tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert [p.name for p in list_projects(tmp_path)] == ["P"]


def test_project_id_cannot_escape_the_directory(tmp_path):
    with pytest.raises(ValueError):
        load_project("../secret", tmp_path)
