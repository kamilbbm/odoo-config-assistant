"""Journey engine: profile -> applicable steps -> plan ordered by prerequisites.

Business rules implemented here:

- RG-001: a project is tied to one ERP and one version; changing version creates a new project
  with a new plan, the original one is left untouched.
- RG-002: no plan while country, activity or wished modules are missing.
- RG-003: a step moves to Done (or Validated) only if every prerequisite in the plan is Done or
  Validated. A prerequisite outside the plan (not applicable to the profile) does not block.
- RG-005: a profile change recomputes the plan. Statuses are kept; steps that are no longer
  applicable move to Out of scope and stay in the plan.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from odoo_config_assistant import DOC_VERSION, ERP
from odoo_config_assistant.models import (
    REQUIRED_FIELD_LABELS,
    Catalog,
    Profile,
    Project,
    ProjectStep,
    Step,
    StepStatus,
)


class IncompleteProfileError(ValueError):
    """RG-002: required profile fields are missing."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        labels = ", ".join(REQUIRED_FIELD_LABELS.get(f, f) for f in missing)
        super().__init__(f"Profil incomplet, champs à renseigner : {labels}")


class PrerequisiteError(ValueError):
    """RG-003: the step cannot move to Done while prerequisites are not finished."""

    def __init__(self, step_id: str, blocking: list[str]):
        self.step_id = step_id
        self.blocking = blocking
        super().__init__(
            f"L'étape {step_id} ne peut pas passer à Fait : prérequis non terminés : "
            + ", ".join(blocking)
        )


class StatusTransitionError(ValueError):
    """Invalid status change (for example Validated before Done)."""


class NoJourneyError(ValueError):
    """No journey exists for the requested ERP and version."""


@dataclass
class PrerequisiteInfo:
    """Prerequisites of a plan step, split for display on the step sheet."""

    finished: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    outside_plan: list[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocking)


def _now() -> datetime:
    return datetime.now(UTC)


def applicable_steps(
    profile: Profile, catalog: Catalog, erp: str = ERP, version: str = DOC_VERSION
) -> list[tuple[str, Step]]:
    """Steps (with their journey id) that apply to the profile, in repository order."""
    result = []
    for journey in catalog.for_version(erp, version):
        if not journey.applies_to(profile):
            continue
        result.extend(
            (journey.id, step)
            for step in journey.steps
            if step.applies_to(profile) and catalog.is_available(step, profile)
        )
    return result


def topological_sort(steps: list[tuple[str, Step]]) -> list[tuple[str, Step]]:
    """Kahn's algorithm, stable: among available steps, the repository order wins.

    Prerequisites that are not part of ``steps`` are ignored.
    """
    ids = [step.id for _, step in steps]
    index = {step_id: i for i, step_id in enumerate(ids)}
    pending = {
        step.id: {p for p in step.prerequisites if p in index and p != step.id} for _, step in steps
    }
    ordered: list[tuple[str, Step]] = []
    done: set[str] = set()
    while len(ordered) < len(steps):
        ready = [i for i in ids if i not in done and pending[i] <= done]
        if not ready:
            remaining = [i for i in ids if i not in done]
            raise ValueError("cycle de prérequis entre : " + ", ".join(remaining))
        chosen = min(ready, key=index.__getitem__)
        done.add(chosen)
        ordered.append(steps[index[chosen]])
    return ordered


def generate_plan(
    profile: Profile,
    catalog: Catalog,
    erp: str = ERP,
    version: str = DOC_VERSION,
    doc_commit: str | None = None,
) -> list[ProjectStep]:
    """Ordered plan for a profile (F-008). Raises IncompleteProfileError (RG-002)."""
    missing = profile.missing_required()
    if missing:
        raise IncompleteProfileError(missing)
    if not catalog.for_version(erp, version):
        raise NoJourneyError(f"Aucun parcours disponible pour {erp} {version}")
    ordered = topological_sort(applicable_steps(profile, catalog, erp, version))
    return [
        ProjectStep(step_id=step.id, journey_id=journey_id, order=i, doc_commit=doc_commit)
        for i, (journey_id, step) in enumerate(ordered)
    ]


def create_project(
    name: str,
    profile: Profile,
    catalog: Catalog,
    doc_commit: str | None = None,
    erp: str = ERP,
    version: str = DOC_VERSION,
    project_id: str | None = None,
) -> Project:
    plan = generate_plan(profile, catalog, erp, version, doc_commit)
    return Project(
        id=project_id or uuid.uuid4().hex[:12],
        name=name,
        erp=erp,
        version=version,
        profile=profile,
        plan=plan,
        doc_commit=doc_commit,
    )


def recompute_plan(project: Project, profile: Profile, catalog: Catalog) -> Project:
    """RG-005: apply a new profile and recompute the plan without deleting any step."""
    fresh = generate_plan(profile, catalog, project.erp, project.version, project.doc_commit)
    previous = {item.step_id: item for item in project.plan}
    new_plan: list[ProjectStep] = []
    for item in fresh:
        old = previous.pop(item.step_id, None)
        if old is None:
            new_plan.append(item)
            continue
        kept = old.model_copy(update={"order": item.order})
        if old.status is StepStatus.OUT_OF_SCOPE:
            kept.status = old.status_before_out_of_scope or StepStatus.TODO
            kept.status_before_out_of_scope = None
            kept.updated_at = _now()
        new_plan.append(kept)
    for old in sorted(previous.values(), key=lambda s: s.order):
        kept = old.model_copy(update={"order": len(new_plan)})
        if old.status is not StepStatus.OUT_OF_SCOPE:
            kept.status_before_out_of_scope = old.status
            kept.status = StepStatus.OUT_OF_SCOPE
            kept.updated_at = _now()
        new_plan.append(kept)
    return project.model_copy(update={"profile": profile, "plan": new_plan, "updated_at": _now()})


def change_version(
    project: Project,
    version: str,
    catalog: Catalog,
    doc_commit: str | None = None,
) -> Project:
    """RG-001: a new version means a new project and a new plan; the source project is kept."""
    if version == project.version:
        raise ValueError("La version demandée est déjà celle du projet")
    new_project = create_project(
        name=project.name,
        profile=project.profile,
        catalog=catalog,
        doc_commit=doc_commit,
        erp=project.erp,
        version=version,
    )
    return new_project.model_copy(update={"derived_from": project.id})


def prerequisite_info(project: Project, step_id: str, catalog: Catalog) -> PrerequisiteInfo:
    step = catalog.step(step_id)
    in_plan = {s.step_id: s for s in project.plan}
    info = PrerequisiteInfo()
    for prerequisite in step.prerequisites:
        item = in_plan.get(prerequisite)
        if item is None or item.status is StepStatus.OUT_OF_SCOPE:
            info.outside_plan.append(prerequisite)
        elif item.status.is_complete:
            info.finished.append(prerequisite)
        else:
            info.blocking.append(prerequisite)
    return info


def set_status(project: Project, step_id: str, status: StepStatus, catalog: Catalog) -> Project:
    """Change a step status, enforcing RG-003. Returns the updated project."""
    item = project.plan_step(step_id)
    if status.is_complete:
        info = prerequisite_info(project, step_id, catalog)
        if info.is_blocked:
            raise PrerequisiteError(step_id, info.blocking)
    if status is StepStatus.VALIDATED and not item.status.is_complete:
        raise StatusTransitionError(f"L'étape {step_id} doit être à Fait avant d'être validée")
    reopening = item.status is StepStatus.OUT_OF_SCOPE and status is not StepStatus.OUT_OF_SCOPE
    step = catalog.step(step_id)
    if reopening and not (
        step.applies_to(project.profile) and catalog.is_available(step, project.profile)
    ):
        raise StatusTransitionError(f"L'étape {step_id} n'est pas applicable au profil actuel")
    return update_step(project, step_id, status=status)


def update_step(project: Project, step_id: str, **changes) -> Project:
    """Update fields of a plan step (status, retained_value, comment) and stamp the doc commit."""
    plan = []
    for item in project.plan:
        if item.step_id == step_id:
            item = item.model_copy(
                update={**changes, "doc_commit": project.doc_commit, "updated_at": _now()}
            )
        plan.append(item)
    return project.model_copy(update={"plan": plan, "updated_at": _now()})
