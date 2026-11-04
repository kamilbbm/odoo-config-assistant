"""Local documentary source: download of odoo/documentation and construction of the index.

Used by scripts/fetch_docs.py, scripts/build_index.py and by the app on first start (for example
on Streamlit Community Cloud, where vendor/ and index/ do not exist yet).

By default only the RST pages are downloaded (partial, sparse clone): about 1,000 text files
instead of the full repository with its images.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from odoo_config_assistant import DOC_VERSION
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.knowledge import DEFAULT_INDEX_PATH, KnowledgeIndex, build_index

ROOT = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/odoo/documentation"
DEFAULT_DOCS_DIR = ROOT / "vendor" / "odoo-docs"
BASE_SCOPE = ["content/applications/finance", "content/applications/inventory_and_mrp"]
RST_ONLY_PATTERNS = ["/content/**/*.rst"]


def version_file(dest: Path) -> Path:
    return dest.with_name(dest.name + ".version.json")


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def fetch_docs(
    dest: Path = DEFAULT_DOCS_DIR,
    branch: str = DOC_VERSION,
    repo: str = REPO_URL,
    rst_only: bool = True,
) -> dict:
    """Clone (shallow) or update the documentation, then record the commit used."""
    try:
        heads = _git("ls-remote", "--heads", repo, branch)
    except RuntimeError as exc:
        raise SystemExit(f"ERR-001 dépôt inaccessible : {repo} ({exc})") from exc
    if not heads:
        raise SystemExit(f"ERR-002 branche introuvable : {branch} sur {repo}")

    if (dest / ".git").is_dir():
        _git("fetch", "--depth", "1", "origin", branch, cwd=dest)
        _git("checkout", "-q", "-B", branch, "FETCH_HEAD", cwd=dest)
    elif rst_only:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(
            "clone", "-q", "--depth", "1", "--branch", branch,
            "--filter=blob:none", "--no-checkout", repo, str(dest),
        )  # fmt: skip
        _git("sparse-checkout", "set", "--no-cone", *RST_ONLY_PATTERNS, cwd=dest)
        _git("checkout", "-q", branch, cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "-q", "--depth", "1", "--branch", branch, repo, str(dest))

    info = {
        "repo": repo,
        "branch": branch,
        "commit": _git("rev-parse", "HEAD", cwd=dest),
        "rst_pages": sum(1 for _ in (dest / "content").rglob("*.rst")),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    version_file(dest).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def build_knowledge_index(
    docs: Path = DEFAULT_DOCS_DIR, out: Path = DEFAULT_INDEX_PATH
) -> KnowledgeIndex:
    """Index finance, inventory_and_mrp and every page cited by the journeys."""
    path = version_file(docs)
    if not path.exists():
        raise FileNotFoundError("Documentation absente : lancer d'abord scripts/fetch_docs.py")
    info = json.loads(path.read_text(encoding="utf-8"))
    catalog = load_catalog()
    cited = sorted({s.path for j in catalog.journeys for step in j.steps for s in step.sources})
    index = build_index(docs, info["commit"], [*BASE_SCOPE, *cited], version=info["branch"])
    index.save(out)
    return index


def ensure_index(docs: Path = DEFAULT_DOCS_DIR, out: Path = DEFAULT_INDEX_PATH) -> KnowledgeIndex:
    """Load the index, building it (and downloading the documentation) if it is missing."""
    if out.exists():
        return KnowledgeIndex.load(out)
    if not version_file(docs).exists():
        fetch_docs(docs)
    return build_knowledge_index(docs, out)
