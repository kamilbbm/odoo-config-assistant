"""Record what the Odoo Community edition contains (odoo/odoo, branch 18.0).

Writes two versioned files:

- data/editions.json, read by the journey loader (Q-008):
  ``community_modules`` lists the module directories of odoo/odoo (addons/ and odoo/addons/);
  ``enterprise_upgrade_modules`` lists the modules that the Community accounting settings offer
  only as an upgrade (``widget="upgrade_boolean"``), i.e. Enterprise modules. A step that requires
  a module absent from ``community_modules`` is Enterprise only.
- data/odoo_fields.json: the fields of the models used by data/import_templates.yaml, read from
  the ``models/`` folders of the modules each template lists. The tests check every column of
  the import templates against it (F-012).

Only trees, one settings view and a few models folders are downloaded (shallow, blobless,
sparse clone).

Usage: python scripts/fetch_editions.py [--branch 18.0]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/odoo/odoo"
SETTINGS_VIEWS = ["addons/account/views/res_config_settings_views.xml"]
TEMPLATES = ROOT / "data" / "import_templates.yaml"
_UPGRADE = re.compile(r'field name="module_([a-z0-9_]+)"[^>]*widget="upgrade_boolean"')


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _module_dir(module: str) -> str:
    return "odoo/addons/base" if module == "base" else f"addons/{module}"


def model_fields(sources: list[Path]) -> dict[str, set[str]]:
    """Fields declared (``x = fields.Xxx(...)``) per model name, from ``_name``/``_inherit``."""
    result: dict[str, set[str]] = {}
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            names: list[str] = []
            declared: list[str] = []
            for stmt in cls.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target, value = stmt.targets[0], stmt.value
                elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                    target, value = stmt.target, stmt.value
                else:
                    continue
                if not isinstance(target, ast.Name):
                    continue
                if target.id in ("_name", "_inherit"):
                    if isinstance(value, ast.Constant):
                        names.append(value.value)
                    elif isinstance(value, ast.List | ast.Tuple):
                        names += [e.value for e in value.elts if isinstance(e, ast.Constant)]
                elif (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and isinstance(value.func.value, ast.Name)
                    and value.func.value.id == "fields"
                ):
                    declared.append(target.id)
            for name in set(names):
                result.setdefault(name, set()).update(declared)
    return result


def _template_models() -> tuple[set[str], set[str]]:
    data = yaml.safe_load(TEMPLATES.read_text(encoding="utf-8"))
    models: set[str] = set()
    modules: set[str] = set()
    for template in data["templates"]:
        models.add(template["model"])
        models.update((template.get("subfields") or {}).values())
        modules.update(template["modules"])
    return models, modules


def fetch_editions(branch: str = "18.0", repo: str = REPO) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "odoo"
        _git(
            "clone", "-q", "--depth", "1", "--branch", branch, "--filter=blob:none",
            "--no-checkout", repo, str(clone),
        )
        commit = _git("rev-parse", "HEAD", cwd=clone).strip()
        modules: set[str] = set()
        for tree in ("addons/", "odoo/addons/"):
            listing = _git("ls-tree", "-d", "--name-only", "HEAD", tree, cwd=clone)
            modules.update(Path(line).name for line in listing.splitlines() if line)
        upgrades: set[str] = set()
        for view in SETTINGS_VIEWS:
            upgrades.update(_UPGRADE.findall(_git("show", f"HEAD:{view}", cwd=clone)))
        models, scanned = _template_models()
        dirs = [f"{_module_dir(m)}/models/" for m in sorted(scanned)]
        _git("sparse-checkout", "set", "--no-cone", *dirs, cwd=clone)
        _git("checkout", "-q", "HEAD", cwd=clone)
        sources = [p for d in dirs for p in sorted((clone / d).glob("*.py"))]
        found = model_fields(sources)
    fields_info = {
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "modules_scanned": sorted(scanned),
        "models": {m: sorted(found.get(m, set())) for m in sorted(models)},
    }
    editions = {
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "note": "Modules de l'édition Community. Un module absent de cette liste est Enterprise.",
        "community_modules": sorted(modules),
        "enterprise_upgrade_modules": sorted(upgrades - modules),
    }
    return editions, fields_info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", default="18.0")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    args = parser.parse_args(argv)
    info, fields_info = fetch_editions(args.branch)
    for name, content in (("editions.json", info), ("odoo_fields.json", fields_info)):
        text = json.dumps(content, indent=1, ensure_ascii=False) + "\n"
        (args.data / name).write_text(text, encoding="utf-8")
    print(
        f"odoo/odoo {info['branch']} @ {info['commit']} : "
        f"{len(info['community_modules'])} modules Community, "
        f"{len(info['enterprise_upgrade_modules'])} modules Enterprise proposés, "
        f"champs de {len(fields_info['models'])} modèles"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
