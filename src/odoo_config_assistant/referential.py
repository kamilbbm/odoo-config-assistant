"""Business repository (F-004): Domaine > Module > Processus > Paramètre.

Each parameter is linked to documentation pages (indexed units); each journey step is linked
to a parameter (``Step.parameter``). The repository is data/referential.yaml, editable by the
content owner in the E-09 screen (the edited version is stored in the database).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str

    @field_validator("id")
    @classmethod
    def _id_format(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(f"identifiant invalide : {value}")
        return value


class Parameter(_Node):
    sources: list[str] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def _rst(cls, value: list[str]) -> list[str]:
        bad = [p for p in value if not (p.startswith("content/") and p.endswith(".rst"))]
        if bad:
            raise ValueError(f"source hors documentation RST : {bad}")
        return value


class Process(_Node):
    parameters: list[Parameter] = Field(default_factory=list)


class Module(_Node):
    odoo_modules: list[str] = Field(default_factory=list)
    processes: list[Process] = Field(default_factory=list)


class Domain(_Node):
    modules: list[Module] = Field(default_factory=list)


@dataclass(frozen=True)
class ParameterPath:
    domain: Domain
    module: Module
    process: Process
    parameter: Parameter

    @property
    def label(self) -> str:
        return " > ".join(
            n.label for n in (self.domain, self.module, self.process, self.parameter)
        )


class Referential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp: str = "odoo"
    version: str = "18.0"
    domains: list[Domain]

    @model_validator(mode="after")
    def _unique_ids(self) -> Referential:
        seen: dict[str, str] = {}
        for kind, node in self._nodes():
            key = f"{kind}:{node.id}"
            if key in seen:
                raise ValueError(f"identifiant en double dans le référentiel : {kind} {node.id}")
            seen[key] = node.label
        return self

    def _nodes(self):
        for domain in self.domains:
            yield "domaine", domain
            for module in domain.modules:
                yield "module", module
                for process in module.processes:
                    yield "processus", process
                    for parameter in process.parameters:
                        yield "paramètre", parameter

    def paths(self) -> dict[str, ParameterPath]:
        return {
            parameter.id: ParameterPath(domain, module, process, parameter)
            for domain in self.domains
            for module in domain.modules
            for process in module.processes
            for parameter in process.parameters
        }

    def path(self, parameter_id: str) -> ParameterPath:
        return self.paths()[parameter_id]

    def domain_labels(self) -> list[str]:
        return [d.label for d in self.domains]
