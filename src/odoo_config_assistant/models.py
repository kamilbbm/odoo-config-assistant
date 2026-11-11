"""Domain models: company profile, journey steps, projects and step statuses."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from odoo_config_assistant import DOC_VERSION, ERP
from odoo_config_assistant.referential import ParameterPath, Referential

PUBLIC_DOC_BASE = "https://www.odoo.com/documentation"
DOC_LANG = "fr"
LICENSE_NOTICE = "Documentation Odoo, licence CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/deed.fr"

_STEP_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_MODULE = re.compile(r"^[a-z][a-z0-9_]*$")


def _now() -> datetime:
    return datetime.now(UTC)


class StepStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    VALIDATED = "validated"
    OUT_OF_SCOPE = "out_of_scope"

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]

    @property
    def is_complete(self) -> bool:
        """A step counts as finished for RG-003 when it is Done or Validated."""
        return self in (StepStatus.DONE, StepStatus.VALIDATED)


STATUS_LABELS: dict[StepStatus, str] = {
    StepStatus.TODO: "À faire",
    StepStatus.IN_PROGRESS: "En cours",
    StepStatus.DONE: "Fait",
    StepStatus.VALIDATED: "Validé",
    StepStatus.OUT_OF_SCOPE: "Hors périmètre",
}


class Activity(StrEnum):
    MANUFACTURING = "manufacturing"
    DISTRIBUTION = "distribution"
    SERVICES = "services"
    RETAIL = "retail"


ACTIVITY_LABELS: dict[Activity, str] = {
    Activity.MANUFACTURING: "Fabrication",
    Activity.DISTRIBUTION: "Distribution",
    Activity.SERVICES: "Prestation de services",
    Activity.RETAIL: "Commerce de détail",
}


class CompanySize(StrEnum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"


SIZE_LABELS: dict[CompanySize, str] = {
    CompanySize.MICRO: "Micro (moins de 10 employés)",
    CompanySize.SMALL: "Petite (10 à 49 employés)",
    CompanySize.MEDIUM: "Moyenne (50 à 249 employés)",
}


class Edition(StrEnum):
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"


EDITION_LABELS: dict[Edition, str] = {
    Edition.COMMUNITY: "Community",
    Edition.ENTERPRISE: "Enterprise (Online, Odoo.sh ou sur site)",
}


class Profile(BaseModel):
    """Company profile filling the questionnaire (F-007)."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = ""
    country: str | None = None
    province: str | None = None
    activity: Activity | None = None
    size: CompanySize | None = None
    edition: Edition | None = None
    tax_regime: str | None = None
    modules: list[str] = Field(default_factory=list)
    fiscal_year_end: str = "12-31"
    foreign_currencies: list[str] = Field(default_factory=list)
    uses_checks: bool = False
    tracks_lots: bool = False
    make_to_order: bool = False
    uses_direct_debit: bool = False
    b2g_invoicing: bool = False
    imports_fec_history: bool = False

    @field_validator("country", "province")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        value = (value or "").strip().upper()
        return value or None

    @field_validator("fiscal_year_end")
    @classmethod
    def _month_day(cls, value: str) -> str:
        if not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", value):
            raise ValueError("fiscal_year_end doit être au format MM-JJ")
        return value

    def missing_required(self) -> list[str]:
        """Return the required fields that are empty (RG-002)."""
        missing = []
        if not self.country:
            missing.append("country")
        if self.activity is None:
            missing.append("activity")
        if not self.modules:
            missing.append("modules")
        return missing


REQUIRED_FIELD_LABELS = {
    "country": "Pays",
    "activity": "Activité",
    "modules": "Modules souhaités",
}

_LIST_FIELDS = {"modules", "foreign_currencies"}
_BOOL_FIELDS = {
    "uses_checks",
    "tracks_lots",
    "make_to_order",
    "uses_direct_debit",
    "b2g_invoicing",
    "imports_fec_history",
}


class Condition(RootModel[dict[str, Any]]):
    """Applicability condition: every key must match the profile (logical AND).

    - list profile field (modules, foreign_currencies): matches when it shares at least one value
      with the condition; ``true`` means "not empty", ``false`` means "empty";
    - boolean field: matches when equal;
    - scalar field: matches when the profile value is one of the accepted values.
    """

    root: dict[str, Any] = Field(default_factory=dict)

    @field_validator("root")
    @classmethod
    def _known_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - set(Profile.model_fields)
        if unknown:
            raise ValueError(f"champ de profil inconnu dans la condition : {sorted(unknown)}")
        for key, expected in value.items():
            if key in _BOOL_FIELDS and not isinstance(expected, bool):
                raise ValueError(f"la condition sur {key} doit être true ou false")
        return value

    def matches(self, profile: Profile) -> bool:
        return all(self._match_one(key, expected, profile) for key, expected in self.root.items())

    @staticmethod
    def _match_one(key: str, expected: Any, profile: Profile) -> bool:
        actual = getattr(profile, key)
        if key in _LIST_FIELDS:
            if isinstance(expected, bool):
                return bool(actual) is expected
            accepted = expected if isinstance(expected, list) else [expected]
            return bool(set(actual) & {str(v) for v in accepted})
        if key in _BOOL_FIELDS:
            return actual is expected
        accepted = expected if isinstance(expected, list) else [expected]
        if actual is None:
            return False
        return str(actual).upper() in {str(v).upper() for v in accepted}


def public_url(path: str, anchor: str | None = None, version: str = DOC_VERSION) -> str:
    """Build the public odoo.com URL of an RST page of odoo/documentation."""
    if not path.startswith("content/") or not path.endswith(".rst"):
        raise ValueError(f"chemin RST inattendu : {path}")
    page = path.removeprefix("content/").removesuffix(".rst")
    url = f"{PUBLIC_DOC_BASE}/{version}/{DOC_LANG}/{page}.html"
    if anchor:
        url += "#" + anchor_to_html_id(anchor)
    return url


def anchor_to_html_id(anchor: str) -> str:
    """Sphinx turns an RST label into an HTML id: lowercase, non-alphanumerics become hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", anchor.lower()).strip("-")


class Source(BaseModel):
    """A documentation source cited by a step."""

    model_config = ConfigDict(extra="forbid")

    path: str
    title: str
    url: str
    anchor: str | None = None

    @field_validator("path")
    @classmethod
    def _rst_path(cls, value: str) -> str:
        if not value.startswith("content/") or not value.endswith(".rst"):
            raise ValueError("le chemin source doit être un fichier .rst sous content/")
        return value

    @property
    def expected_url(self) -> str:
        return public_url(self.path, self.anchor)


class Recommendation(BaseModel):
    """Recommended value, optionally depending on the profile."""

    model_config = ConfigDict(extra="forbid")

    value: str
    when: Condition | None = None
    verified: bool = True
    note: str | None = None

    @model_validator(mode="after")
    def _unverified_needs_note(self) -> Recommendation:
        if not self.verified and not (self.note or "").strip():
            raise ValueError("une recommandation verified: false doit avoir une note")
        return self


class Step(BaseModel):
    """Template step of a journey (Étape modèle)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    parameter: str | None = None  # paramètre du référentiel métier (F-004)
    objective: str
    menu_path: str
    recommendations: list[Recommendation] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    applies_when: Condition | None = None
    modules: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_format(cls, value: str) -> str:
        if not _STEP_ID.match(value):
            raise ValueError(f"identifiant d'étape invalide : {value}")
        return value

    @field_validator("modules")
    @classmethod
    def _module_names(cls, value: list[str]) -> list[str]:
        bad = [m for m in value if not _MODULE.match(m)]
        if bad:
            raise ValueError(f"nom technique de module invalide : {bad}")
        return value

    @model_validator(mode="after")
    def _rg012_has_source(self) -> Step:
        if not self.sources:
            raise ValueError(f"RG-012 : l'étape {self.id} n'est rattachée à aucune source")
        return self

    def applies_to(self, profile: Profile) -> bool:
        return self.applies_when is None or self.applies_when.matches(profile)

    def recommendation_for(self, profile: Profile) -> Recommendation:
        """First recommendation whose condition matches; the last one serves as fallback."""
        for rec in self.recommendations:
            if rec.when is None or rec.when.matches(profile):
                return rec
        return self.recommendations[-1]

    @property
    def menu_items(self) -> list[str]:
        return [part.strip() for part in self.menu_path.split(">")]


class Journey(BaseModel):
    """Journey template (Modèle de parcours)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    domain: str
    description: str = ""
    erp: str = ERP
    version: str = DOC_VERSION
    applies_when: Condition | None = None
    steps: list[Step] = Field(min_length=1)

    def applies_to(self, profile: Profile) -> bool:
        return self.applies_when is None or self.applies_when.matches(profile)


class Catalog(BaseModel):
    """All journeys loaded from the repository, already validated.

    ``community_modules`` lists the modules of the Community edition (data/editions.json). When it
    is unknown (None), no step is considered Enterprise only.
    """

    journeys: list[Journey] = Field(default_factory=list)
    community_modules: frozenset[str] | None = None
    referential: Referential | None = None

    def location(self, step: Step) -> ParameterPath | None:
        """Domain, module, process and parameter of a step (E-03), when the repository is known."""
        if self.referential is None or step.parameter is None:
            return None
        return self.referential.paths().get(step.parameter)

    def enterprise_modules(self, step: Step) -> list[str]:
        """Modules required by the step that the Community edition does not have (Q-008)."""
        if self.community_modules is None:
            return []
        return [m for m in step.modules if m not in self.community_modules]

    def edition_label(self, step: Step) -> str:
        """Text shown in the plan, the step sheet and the workbook."""
        enterprise = self.enterprise_modules(step)
        if enterprise:
            return f"Enterprise ({', '.join(enterprise)})"
        return "Community et Enterprise" if self.community_modules is not None else ""

    def is_available(self, step: Step, profile: Profile) -> bool:
        """A Community profile does not get Enterprise-only steps; unknown edition gets all."""
        return profile.edition is not Edition.COMMUNITY or not self.enterprise_modules(step)

    def for_version(self, erp: str, version: str) -> list[Journey]:
        return [j for j in self.journeys if j.erp == erp and j.version == version]

    def step(self, step_id: str) -> Step:
        for journey in self.journeys:
            for step in journey.steps:
                if step.id == step_id:
                    return step
        raise KeyError(step_id)

    def journey_of(self, step_id: str) -> Journey:
        for journey in self.journeys:
            if any(step.id == step_id for step in journey.steps):
                return journey
        raise KeyError(step_id)


class ProjectStep(BaseModel):
    """Instance of a template step in a project plan (Étape projet)."""

    step_id: str
    journey_id: str
    order: int
    status: StepStatus = StepStatus.TODO
    retained_value: str | None = None
    comment: str = ""
    doc_commit: str | None = None
    status_before_out_of_scope: StepStatus | None = None
    updated_at: datetime = Field(default_factory=_now)


class Project(BaseModel):
    """Client project. ERP and version are frozen (RG-001)."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    name: str
    erp: str = Field(default=ERP, frozen=True)
    version: str = Field(default=DOC_VERSION, frozen=True)
    profile: Profile = Field(default_factory=Profile)
    plan: list[ProjectStep] = Field(default_factory=list)
    doc_commit: str | None = None
    derived_from: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def plan_step(self, step_id: str) -> ProjectStep:
        for item in self.plan:
            if item.step_id == step_id:
                return item
        raise KeyError(step_id)

    def in_scope(self) -> list[ProjectStep]:
        return [s for s in self.plan if s.status is not StepStatus.OUT_OF_SCOPE]
