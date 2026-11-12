"""Loading and validation of the journey repository (data/journeys/*.yaml).

A journey that fails validation is rejected as a whole: a step without a source (RG-012), an
unknown prerequisite, a duplicated step id or a prerequisite cycle all stop the loading.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from odoo_config_assistant.models import Catalog, Journey
from odoo_config_assistant.referential import Referential

DEFAULT_JOURNEYS_DIR = Path(__file__).resolve().parents[2] / "data" / "journeys"
DEFAULT_EDITIONS_FILE = DEFAULT_JOURNEYS_DIR.parent / "editions.json"
DEFAULT_REFERENTIAL_FILE = DEFAULT_JOURNEYS_DIR.parent / "referential.yaml"
REFERENTIAL_NAME = "referential.yaml"


class JourneyValidationError(ValueError):
    """Raised when the journey repository is invalid. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Référentiel de parcours invalide :\n- " + "\n- ".join(errors))


def parse_journey(text: str, name: str) -> Journey:
    raw = yaml.safe_load(text)
    try:
        return Journey.model_validate(raw)
    except ValidationError as exc:
        errors = [
            f"{name} : {'.'.join(str(p) for p in err['loc'])} : {err['msg']}"
            for err in exc.errors()
        ]
        raise JourneyValidationError(errors) from exc


def load_journey(path: Path) -> Journey:
    return parse_journey(path.read_text(encoding="utf-8"), path.name)


def parse_referential(text: str) -> Referential:
    try:
        return Referential.model_validate(yaml.safe_load(text))
    except (ValidationError, yaml.YAMLError) as exc:
        raise JourneyValidationError([f"{REFERENTIAL_NAME} : {exc}"]) from exc


def load_community_modules(path: Path = DEFAULT_EDITIONS_FILE) -> frozenset[str] | None:
    """Modules of the Community edition (scripts/fetch_editions.py), None if the file is absent."""
    if not path.is_file():
        return None
    return frozenset(json.loads(path.read_text(encoding="utf-8"))["community_modules"])


def repository_files(
    directory: Path = DEFAULT_JOURNEYS_DIR, referential_file: Path = DEFAULT_REFERENTIAL_FILE
) -> dict[str, str]:
    """Shipped repository: ``journeys/<file>.yaml`` and ``referential.yaml`` texts."""
    files = {
        f"journeys/{path.name}": path.read_text(encoding="utf-8")
        for path in sorted(directory.glob("*.yaml"))
    }
    if referential_file.is_file():
        files[REFERENTIAL_NAME] = referential_file.read_text(encoding="utf-8")
    return files


def load_catalog(
    directory: Path = DEFAULT_JOURNEYS_DIR,
    editions_file: Path = DEFAULT_EDITIONS_FILE,
    overrides: dict[str, str | None] | None = None,
    referential_file: Path = DEFAULT_REFERENTIAL_FILE,
) -> Catalog:
    """Load the journeys and the business repository and validate them together.

    ``overrides`` (E-09 edits stored in the database) replace or add files by name
    (``journeys/<id>.yaml``, ``referential.yaml``); a ``None`` value removes a journey.
    """
    files = repository_files(directory, referential_file)
    for name, text in (overrides or {}).items():
        if text is None:
            files.pop(name, None)
        else:
            files[name] = text
    errors: list[str] = []
    journeys: list[Journey] = []
    referential = None
    for name, text in sorted(files.items()):
        try:
            if name == REFERENTIAL_NAME:
                referential = parse_referential(text)
            else:
                journeys.append(parse_journey(text, name.removeprefix("journeys/")))
        except JourneyValidationError as exc:
            errors.extend(exc.errors)
    if errors:
        raise JourneyValidationError(errors)
    catalog = Catalog(
        journeys=journeys,
        community_modules=load_community_modules(editions_file),
        referential=referential,
    )
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: Catalog) -> None:
    """Cross-journey checks: unique ids, existing prerequisites, no cycle, known parameters."""
    errors: list[str] = []
    paths = catalog.referential.paths() if catalog.referential else None
    for journey in catalog.journeys:
        for step in journey.steps:
            if paths is None or step.parameter is None:
                continue
            path = paths.get(step.parameter)
            if path is None:
                errors.append(f"étape {step.id} : paramètre inconnu : {step.parameter}")
            elif path.domain.label != journey.domain:
                errors.append(
                    f"étape {step.id} : paramètre du domaine {path.domain.label}, parcours du "
                    f"domaine {journey.domain}"
                )
    seen: dict[str, str] = {}
    graph: dict[str, list[str]] = {}
    for journey in catalog.journeys:
        for step in journey.steps:
            if step.id in seen:
                errors.append(f"étape {step.id} définie deux fois ({seen[step.id]}, {journey.id})")
            seen[step.id] = journey.id
            graph[step.id] = step.prerequisites
    for step_id, prerequisites in graph.items():
        for prerequisite in prerequisites:
            if prerequisite not in graph:
                errors.append(f"étape {step_id} : prérequis inexistant {prerequisite}")
            if prerequisite == step_id:
                errors.append(f"étape {step_id} : se cite elle-même en prérequis")
    if not errors:
        cycle = find_cycle(graph)
        if cycle:
            errors.append("cycle de prérequis : " + " -> ".join(cycle))
    if errors:
        raise JourneyValidationError(errors)


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return one prerequisite cycle as a closed path, or None if the graph is acyclic."""
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(graph, white)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = grey
        stack.append(node)
        for nxt in graph.get(node, []):
            if color.get(nxt) == grey:
                return [*stack[stack.index(nxt) :], nxt]
            if color.get(nxt) == white:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = black
        return None

    for node in graph:
        if color[node] == white:
            found = visit(node)
            if found:
                return found
    return None
