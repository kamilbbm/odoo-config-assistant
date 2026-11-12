"""Read-only access to a client's Odoo instance (phase 2, F-014, RG-016).

External API of Odoo (XML-RPC, ``/xmlrpc/2/common`` and ``/xmlrpc/2/object``), authenticated with
the user's login and API key. RG-016: only reading methods are allowed; any other method is
refused before a request is sent. The API key is used for the session only, never stored.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any

READ_METHODS = frozenset({"search_read", "search_count", "read", "fields_get", "search"})


class ReadOnlyViolation(PermissionError):
    """RG-016: the application never writes into the client instance."""


class OdooConnectionError(RuntimeError):
    pass


class ReadOnlyOdoo:
    def __init__(self, url: str, database: str, login: str, api_key: str, timeout: float = 30):
        if not url.startswith(("https://", "http://")):
            raise ValueError("adresse de l'instance invalide (https://…)")
        self.url = url.rstrip("/")
        self.database = database
        self.login = login
        self._key = api_key
        self._timeout = timeout
        self.uid: int | None = None
        self.server_version: str | None = None
        self._fields: dict[str, set[str]] = {}

    def _proxy(self, endpoint: str) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/{endpoint}", allow_none=True)

    def connect(self) -> ReadOnlyOdoo:
        try:
            common = self._proxy("common")
            self.server_version = str(common.version().get("server_version", ""))
            uid = common.authenticate(self.database, self.login, self._key, {})
        except (OSError, xmlrpc.client.Error) as exc:
            raise OdooConnectionError(f"instance injoignable : {exc}") from exc
        if not uid:
            raise OdooConnectionError("authentification refusée (identifiant ou clé d'API)")
        self.uid = int(uid)
        return self

    def call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        if method not in READ_METHODS:
            raise ReadOnlyViolation(f"RG-016 : méthode {method} interdite, accès en lecture seule")
        if self.uid is None:
            self.connect()
        try:
            return self._proxy("object").execute_kw(
                self.database, self.uid, self._key, model, method, list(args), kwargs
            )
        except (OSError, xmlrpc.client.Error) as exc:
            raise OdooConnectionError(f"{model}.{method} : {exc}") from exc

    # ----------------------------------------------------------------------- helpers

    def fields(self, model: str) -> set[str]:
        if model not in self._fields:
            try:
                self._fields[model] = set(self.call(model, "fields_get", attributes=["type"]))
            except OdooConnectionError:
                self._fields[model] = set()  # modèle absent (module non installé)
        return self._fields[model]

    def has_model(self, model: str) -> bool:
        return bool(self.fields(model))

    def count(self, model: str, domain: list | None = None) -> int | None:
        if not self.has_model(model):
            return None
        return int(self.call(model, "search_count", domain or []))

    def records(self, model: str, domain: list, fields: list[str], limit: int = 0) -> list[dict]:
        if not self.has_model(model):
            return []
        wanted = [f for f in fields if f in self.fields(model)]
        return self.call(model, "search_read", domain, fields=wanted, limit=limit)

    def installed_modules(self) -> set[str]:
        rows = self.records("ir.module.module", [["state", "=", "installed"]], ["name"])
        return {r["name"] for r in rows}
