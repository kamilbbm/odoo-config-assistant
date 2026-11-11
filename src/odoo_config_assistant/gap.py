"""Gap control between the plan and the client's Odoo instance (phase 2, F-014, RG-016).

The instance is read (companies, installed modules, taxes, journals, accounts, currencies,
fiscal positions, payment terms, warehouses, manufacturing data) through ``ReadOnlyOdoo``; each
step of the plan is checked according to its parameter in the business repository, then the
result is compared with the step status: a step marked Done or Validated whose configuration is
missing is an "écart".

Status of a check: Conforme, Écart, Non vérifiable (nothing readable proves it either way).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from odoo_config_assistant.models import Catalog, Project, Step
from odoo_config_assistant.odoo_client import ReadOnlyOdoo

CURRENCY_BY_COUNTRY = {"CA": "CAD", "FR": "EUR", "BE": "EUR", "CH": "CHF", "US": "USD"}


class GapStatus(StrEnum):
    OK = "Conforme"
    GAP = "Écart"
    UNKNOWN = "Non vérifiable"


class StepGap(BaseModel):
    step_id: str
    title: str
    plan_status: str
    status: GapStatus
    detail: str
    discrepancy: bool = False  # étape Fait ou Validé alors que la configuration manque


class GapReport(BaseModel):
    project_id: str
    url: str
    database: str
    server_version: str | None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    company: str | None = None
    results: list[StepGap] = Field(default_factory=list)

    def count(self, status: GapStatus) -> int:
        return sum(1 for r in self.results if r.status is status)

    @property
    def discrepancies(self) -> list[StepGap]:
        return [r for r in self.results if r.discrepancy]


@dataclass
class Snapshot:
    """What was read from the instance, once, for every check."""

    client: ReadOnlyOdoo
    modules: set[str]
    company: dict
    cache: dict = field(default_factory=dict)

    def count(self, model: str, domain: list | None = None) -> int | None:
        key = (model, repr(domain))
        if key not in self.cache:
            self.cache[key] = self.client.count(model, domain)
        return self.cache[key]


Check = Callable[[Snapshot, Project, Step], tuple[GapStatus, str]]


def _exists(model: str, label: str, domain: list | None = None) -> Check:
    def check(snap: Snapshot, project: Project, step: Step) -> tuple[GapStatus, str]:
        found = snap.count(model, domain)
        if found is None:
            return GapStatus.UNKNOWN, f"{label} : objet {model} absent de l'instance"
        if found:
            return GapStatus.OK, f"{label} : {found}"
        return GapStatus.GAP, f"{label} : aucun"

    return check


def _company_identity(snap, project, step):
    company = snap.company
    country = (company.get("country_id") or [None, None])[1]
    code = company.get("country_code")
    missing = [
        label for key, label in (("vat", "Tax ID"), ("street", "adresse")) if not company.get(key)
    ]
    expected = project.profile.country
    if code and expected and code.upper() != expected.upper():
        return GapStatus.GAP, f"pays de la société {code}, profil {expected}"
    if missing:
        return GapStatus.GAP, f"fiche société incomplète : {', '.join(missing)}"
    return GapStatus.OK, f"{company.get('name')}, {country or code or 'pays inconnu'}"


def _localization(snap, project, step):
    expected = [m for m in step.modules if m.startswith("l10n_")]
    if not expected:
        return GapStatus.UNKNOWN, "aucun module de localisation attendu"
    missing = [m for m in expected if m not in snap.modules]
    if missing:
        return GapStatus.GAP, f"module(s) non installé(s) : {', '.join(missing)}"
    return GapStatus.OK, f"installé(s) : {', '.join(expected)}"


def _main_currency(snap, project, step):
    expected = CURRENCY_BY_COUNTRY.get((project.profile.country or "").upper())
    currency = (snap.company.get("currency_id") or [None, None])[1]
    if not currency:
        return GapStatus.UNKNOWN, "devise de la société illisible"
    if expected and currency != expected:
        return GapStatus.GAP, f"devise {currency}, attendue {expected}"
    return GapStatus.OK, f"devise {currency}"


def _foreign_currencies(snap, project, step):
    wanted = project.profile.foreign_currencies
    rows = snap.client.records("res.currency", [["name", "in", wanted]], ["name", "active"])
    active = {r["name"] for r in rows if r.get("active")}
    missing = [c for c in wanted if c not in active]
    if missing:
        return GapStatus.GAP, f"devise(s) inactive(s) : {', '.join(missing)}"
    return GapStatus.OK, f"actives : {', '.join(wanted)}"


def _fiscal_year(snap, project, step):
    company = snap.company
    if "fiscalyear_last_month" not in company:
        return GapStatus.UNKNOWN, "exercice fiscal illisible"
    month, day = project.profile.fiscal_year_end.split("-")
    actual = (
        f"{int(company['fiscalyear_last_month']):02d}-{int(company['fiscalyear_last_day']):02d}"
    )
    if actual != f"{month}-{day}":
        return GapStatus.GAP, f"fin d'exercice {actual}, profil {month}-{day}"
    return GapStatus.OK, f"fin d'exercice {actual}"


def _journals(snap, project, step):
    missing = [
        label
        for kind, label in (
            ("sale", "Ventes"),
            ("purchase", "Achats"),
            ("bank", "Banque"),
            ("general", "Opérations diverses"),
        )
        if not snap.count("account.journal", [["type", "=", kind]])
    ]
    if missing:
        return GapStatus.GAP, f"journal manquant : {', '.join(missing)}"
    return GapStatus.OK, "journaux de ventes, achats, banque et opérations diverses présents"


def _bank_accounts(snap, project, step):
    found = snap.count("account.journal", [["type", "=", "bank"], ["bank_account_id", "!=", False]])
    if found is None:
        return GapStatus.UNKNOWN, "journaux illisibles"
    if not found:
        return GapStatus.GAP, "aucun journal de banque relié à un compte bancaire"
    return GapStatus.OK, f"{found} journal(aux) de banque avec compte"


def _taxes(snap, project, step):
    sale = snap.count("account.tax", [["type_tax_use", "=", "sale"], ["active", "=", True]])
    purchase = snap.count("account.tax", [["type_tax_use", "=", "purchase"], ["active", "=", True]])
    if sale is None:
        return GapStatus.UNKNOWN, "taxes illisibles"
    if not sale or not purchase:
        return GapStatus.GAP, f"taxes actives : {sale} en vente, {purchase} en achat"
    return GapStatus.OK, f"taxes actives : {sale} en vente, {purchase} en achat"


def _lock_dates(snap, project, step):
    company = snap.company
    keys = [k for k in ("fiscalyear_lock_date", "hard_lock_date") if k in company]
    if not keys:
        return GapStatus.UNKNOWN, "dates de verrouillage illisibles"
    if any(company.get(k) for k in keys):
        return GapStatus.OK, ", ".join(f"{k} : {company[k]}" for k in keys if company.get(k))
    return GapStatus.GAP, "aucune date de verrouillage"


def _modules_only(snap, project, step):
    if not step.modules:
        return GapStatus.UNKNOWN, "pas de contrôle automatique pour cette étape"
    missing = [m for m in step.modules if m not in snap.modules]
    if missing:
        return GapStatus.GAP, f"module(s) non installé(s) : {', '.join(missing)}"
    return GapStatus.OK, f"module(s) installé(s) : {', '.join(step.modules)}"


CHECKS: dict[str, Check] = {
    "company_identity": _company_identity,
    "fiscal_localization": _localization,
    "main_currency": _main_currency,
    "foreign_currencies": _foreign_currencies,
    "fiscal_year": _fiscal_year,
    "chart_of_accounts": _exists("account.account", "comptes"),
    "journals": _journals,
    "opening_balances": _exists(
        "account.move", "écritures comptabilisées", [["state", "=", "posted"]]
    ),
    "taxes": _taxes,
    "fiscal_positions": _exists("account.fiscal.position", "positions fiscales"),
    "bank_accounts": _bank_accounts,
    "payment_terms": _exists("account.payment.term", "conditions de paiement"),
    "lock_dates": _lock_dates,
    "warehouse": _exists("stock.warehouse", "entrepôts"),
    "locations": _exists("stock.location", "emplacements internes", [["usage", "=", "internal"]]),
    "routes": _exists("stock.route", "routes"),
    "units_of_measure": _exists("uom.uom", "unités de mesure"),
    "product_categories": _exists("product.category", "catégories d'articles"),
    "traceability": _exists("product.template", "articles suivis", [["tracking", "!=", "none"]]),
    "reordering_rules": _exists("stock.warehouse.orderpoint", "règles de réapprovisionnement"),
    "initial_quantities": _exists("stock.quant", "quantités en stock", [["quantity", ">", 0]]),
    "purchased_components": _exists("product.supplierinfo", "fournisseurs d'articles"),
    "work_centers": _exists("mrp.workcenter", "postes de travail"),
    "manufactured_products": _exists("mrp.bom", "articles avec nomenclature"),
    "bills_of_materials": _exists("mrp.bom", "nomenclatures"),
    "first_manufacturing_order": _exists(
        "mrp.production", "ordres de fabrication terminés", [["state", "=", "done"]]
    ),
}


def read_snapshot(client: ReadOnlyOdoo) -> Snapshot:
    client.connect()
    company_fields = [
        "name",
        "country_id",
        "country_code",
        "currency_id",
        "vat",
        "street",
        "fiscalyear_last_month",
        "fiscalyear_last_day",
        "fiscalyear_lock_date",
        "hard_lock_date",
    ]
    companies = client.records("res.company", [], company_fields, limit=1)
    return Snapshot(client, client.installed_modules(), companies[0] if companies else {})


def check_project(project: Project, catalog: Catalog, client: ReadOnlyOdoo) -> GapReport:
    snap = read_snapshot(client)
    report = GapReport(
        project_id=project.id,
        url=client.url,
        database=client.database,
        server_version=client.server_version,
        company=snap.company.get("name"),
    )
    for item in project.in_scope():
        step = catalog.step(item.step_id)
        check = CHECKS.get(step.parameter or "", _modules_only)
        status, detail = check(snap, project, step)
        if status is not GapStatus.GAP and step.modules and check is not _modules_only:
            missing = [m for m in step.modules if m not in snap.modules]
            if missing:
                status, detail = GapStatus.GAP, f"module(s) non installé(s) : {', '.join(missing)}"
        report.results.append(
            StepGap(
                step_id=step.id,
                title=step.title,
                plan_status=item.status.label,
                status=status,
                detail=detail,
                discrepancy=status is GapStatus.GAP and item.status.is_complete,
            )
        )
    return report
