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


def test_rst_only_clone_skips_other_files(tmp_path, local_docs_repo):
    (local_docs_repo / "content" / "image.png").write_bytes(b"png")
    run("git", "add", ".", cwd=local_docs_repo)
    run(
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-q",
        "-m",
        "image",
        cwd=local_docs_repo,
    )
    dest = tmp_path / "docs"
    fetch(dest, "18.0", repo=local_docs_repo.as_uri())
    assert (dest / "content" / "page.rst").is_file()
    assert not (dest / "content" / "image.png").exists()
    full = tmp_path / "full"
    fetch(full, "18.0", repo=local_docs_repo.as_uri(), rst_only=False)
    assert (full / "content" / "image.png").is_file()


def test_ensure_index_downloads_and_builds_once(tmp_path, local_docs_repo, monkeypatch):
    from odoo_config_assistant import sources

    monkeypatch.setattr(sources, "REPO_URL", local_docs_repo.as_uri())
    calls = []
    real_fetch = sources.fetch_docs

    def fake_fetch(dest, *args, **kwargs):
        calls.append(dest)
        return real_fetch(dest, "18.0", local_docs_repo.as_uri())

    monkeypatch.setattr(sources, "fetch_docs", fake_fetch)
    docs, out = tmp_path / "vendor" / "odoo-docs", tmp_path / "index" / "idx.json"
    index = sources.ensure_index(docs, out)
    assert out.exists() and index.commit and len(calls) == 1
    assert sources.ensure_index(docs, out).commit == index.commit
    assert len(calls) == 1
