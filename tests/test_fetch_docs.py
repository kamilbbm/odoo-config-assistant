import json
import subprocess

import pytest

from scripts.fetch_docs import fetch, version_file


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def local_docs_repo(tmp_path):
    origin = tmp_path / "origin"
    (origin / "content").mkdir(parents=True)
    (origin / "content" / "page.rst").write_text("Title\n=====\n\nText.\n", encoding="utf-8")
    run("git", "init", "-q", "-b", "18.0", cwd=origin)
    run("git", "add", ".", cwd=origin)
    run(
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-q",
        "-m",
        "init",
        cwd=origin,
    )
    return origin


def test_fetch_clones_and_records_commit(tmp_path, local_docs_repo):
    dest = tmp_path / "vendor" / "odoo-docs"
    info = fetch(dest, "18.0", repo=local_docs_repo.as_uri())
    assert len(info["commit"]) == 40 and info["rst_pages"] == 1
    assert json.loads(version_file(dest).read_text())["commit"] == info["commit"]
    assert fetch(dest, "18.0", repo=local_docs_repo.as_uri())["commit"] == info["commit"]


def test_fetch_unknown_branch_is_err002(tmp_path, local_docs_repo):
    with pytest.raises(SystemExit, match="ERR-002"):
        fetch(tmp_path / "docs", "99.0", repo=local_docs_repo.as_uri())


def test_fetch_unreachable_repo_is_err001(tmp_path):
    with pytest.raises(SystemExit, match="ERR-001"):
        fetch(tmp_path / "docs", "18.0", repo=(tmp_path / "missing").as_uri())
