"""Gap control against a client instance, read only (phase 2, F-014, RG-016).

A fake Odoo answers the external API (XML-RPC) on localhost and records every method called."""

import threading
from pathlib import Path
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

import pytest

from odoo_config_assistant.gap import GapStatus, check_project
from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.odoo_client import (
    OdooConnectionError,
    ReadOnlyOdoo,
    ReadOnlyViolation,
)
from odoo_config_assistant.storage import load_project

CATALOG = load_catalog()
PROJECT = load_project("exemple-fr", Path(__file__).parents[1] / "projects")
API_KEY = "cle-api-de-test"


def matches(record, domain):
    for field, op, value in domain:
        actual = record.get(field)
        if op == "=" and actual != value:
            return False
        if op == "!=" and actual == value:
            return False
        if op == "in" and actual not in value:
            return False
        if op == ">" and not (actual or 0) > value:
            return False
    return True


class FakeOdoo:
    def __init__(self):
        self.calls = []
        self.data = {
            "ir.module.module": [
                {"name": m, "state": "installed"}
                for m in ["base", "account", "l10n_fr_account", "l10n_fr_pdp", "sale"]
            ],
            "res.company": [
                {
                    "name": "Cabinet Vauban Conseil SAS",
                    "country_id": [75, "France"],
                    "country_code": "FR",
                    "currency_id": [1, "EUR"],
                    "vat": "FR00000000000",
                    "street": "12 rue des Remparts",
                    "fiscalyear_last_month": "12",
                    "fiscalyear_last_day": 31,
                    "fiscalyear_lock_date": False,
                    "hard_lock_date": False,
                }
            ],
            "res.currency": [{"name": "USD", "active": True}],
            "account.account": [{"code": "411100"}],
            "account.journal": [
                {"type": "sale"},
                {"type": "purchase"},
                {"type": "general"},
                {"type": "bank", "bank_account_id": False},
            ],
            "account.tax": [
                {"type_tax_use": "sale", "active": True},
                {"type_tax_use": "purchase", "active": True},
            ],
            "account.fiscal.position": [{"name": "Intra-EU"}],
            "account.payment.term": [{"name": "30 Days"}],
            "account.move": [],
        }

    def version(self):
        return {"server_version": "18.0"}

    def authenticate(self, db, login, key, context):
        return 2 if (db, login, key) == ("client", "admin@client.example", API_KEY) else False

    def execute_kw(self, db, uid, key, model, method, args, kwargs):
        self.calls.append((model, method))
        if model not in self.data:
            raise ValueError(f"Object {model} doesn't exist")
        records = self.data[model]
        if method == "fields_get":
            keys = set().union(*records) if records else {"name"}
            return {k: {"type": "char"} for k in keys}
        domain = args[0] if args else []
        found = [r for r in records if matches(r, domain)]
        if method == "search_count":
            return len(found)
        if method == "search_read":
            fields = kwargs.get("fields") or []
            limit = kwargs.get("limit") or len(found)
            return [{f: r.get(f, False) for f in fields} for r in found[:limit]]
        raise ValueError(f"méthode inattendue {method}")


class Handler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/xmlrpc/2/common", "/xmlrpc/2/object")

    def log_message(self, *args):
        pass


@pytest.fixture
def odoo():
    fake = FakeOdoo()
    server = SimpleXMLRPCServer(("127.0.0.1", 0), requestHandler=Handler, allow_none=True)
    server.register_instance(fake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield fake
    server.shutdown()
    server.server_close()


def client(odoo, key=API_KEY):
    return ReadOnlyOdoo(odoo.url, "client", "admin@client.example", key)


def test_rg016_write_methods_are_refused_before_any_request(odoo):
    instance = client(odoo).connect()
    for method in ("write", "create", "unlink", "button_immediate_install", "execute"):
        with pytest.raises(ReadOnlyViolation, match="RG-016"):
            instance.call("res.company", method, [1], {"name": "x"})
    assert odoo.calls == []


def test_gap_report_compares_the_instance_with_the_plan(odoo):
    report = check_project(PROJECT, CATALOG, client(odoo))
    by_step = {r.step_id: r for r in report.results}
    assert report.company == "Cabinet Vauban Conseil SAS" and report.server_version == "18.0"
    assert by_step["frf_company"].status is GapStatus.OK
    assert by_step["frf_localization"].status is GapStatus.OK
    assert by_step["frf_main_currency"].status is GapStatus.OK
    assert by_step["frf_taxes"].status is GapStatus.OK
    assert by_step["frf_journals"].status is GapStatus.OK
    assert by_step["frf_bank_account"].status is GapStatus.GAP
    # Chorus Pro : module non installé alors que l'étape est au plan.
    assert by_step["frf_chorus_pro"].status is GapStatus.GAP
    assert "l10n_fr_facturx_chorus_pro" in by_step["frf_chorus_pro"].detail
    assert {r.step_id for r in report.results} == {i.step_id for i in PROJECT.in_scope()}


def test_done_step_with_missing_configuration_is_flagged(odoo):
    odoo.data["account.fiscal.position"] = []
    report = check_project(PROJECT, CATALOG, client(odoo))
    by_step = {r.step_id: r for r in report.results}
    fiscal = by_step["frf_fiscal_positions"]
    assert fiscal.status is GapStatus.GAP
    assert not fiscal.discrepancy  # étape En cours dans le plan
    odoo.data["account.account"] = []
    report = check_project(PROJECT, CATALOG, client(odoo))
    coa = next(r for r in report.results if r.step_id == "frf_chart_of_accounts")
    assert coa.status is GapStatus.GAP and coa.discrepancy  # étape Faite, aucun compte
    assert coa in report.discrepancies


def test_only_reading_methods_reach_the_instance(odoo):
    check_project(PROJECT, CATALOG, client(odoo))
    assert odoo.calls and {method for _, method in odoo.calls} <= {
        "search_read",
        "search_count",
        "fields_get",
    }


def test_wrong_key_or_address_is_reported(odoo):
    with pytest.raises(OdooConnectionError, match="authentification"):
        client(odoo, key="mauvaise").connect()
    with pytest.raises(OdooConnectionError):
        ReadOnlyOdoo("http://127.0.0.1:9", "client", "x", "y").connect()
    with pytest.raises(ValueError):
        ReadOnlyOdoo("ftp://exemple", "client", "x", "y")
