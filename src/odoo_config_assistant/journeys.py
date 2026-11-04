"""Loading and validation of the journey repository (data/journeys/*.yaml).

A journey that fails validation is rejected as a whole: a step without a source (RG-012), an
unknown prerequisite, a duplicated step id or a prerequisite cycle all stop the loading.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from odoo_config_assistant.models import Catalog, Journey

DEFAULT_JOURNEYS_DIR = Path(__file__).resolve().parents[2] / "data" / "journeys"


class JourneyValidationError(ValueError):
    """Raised when the journey repository is invalid. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Référentiel de parcours invalide :\n- " + "\n- ".join(errors))


def load_journey(path: Path) -> Journey:
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    try:
        return Journey.model_validate(raw)
    except ValidationError as exc:
        errors = [
            f"{path.name} : {'.'.join(str(p) for p in err['loc'])} : {err['msg']}"
            for err in exc.errors()
        ]
        raise JourneyValidationError(errors) from exc


def load_catalog(directory: Path = DEFAULT_JOURNEYS_DIR) -> Catalog:
    """Load every ``*.yaml`` journey of ``directory`` and validate them together."""
    errors: list[str] = []
    journeys: list[Journey] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            journeys.append(load_journey(path))
        except JourneyValidationError as exc:
            errors.extend(exc.errors)
    if errors:
        raise JourneyValidationError(errors)
    catalog = Catalog(journeys=journeys)
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: Catalog) -> None:
    """Cross-journey checks: unique ids, existing prerequisites, no cycle."""
    errors: list[str] = []
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
