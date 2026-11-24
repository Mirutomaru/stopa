"""P2-2 — Centrální registr případů API (instance DB).

Routy nad :mod:`stopa.data.case_registry_repository` + :mod:`stopa.domain.case_registry`:
seznam záznamů registru s tenancy filtrem, idempotentní sync jednotlivého případu,
změna stavu a odebrání záznamu. Logika žije v domain/data vrstvě; tady je jen API hrana.

Konvence: 404 = neznámý případ / záznam není v registru; 400 = semantická chyba
domény/repotitáře; 201 = sync hotov. Tenancy viditelnost řeší domain
``is_visible`` (multi-user off = vše, admin = vše, jinak stejná organizace).

Oprávnění: čtení = ``cross_case_query`` (F4.4; analyst zamčený), zápis do registru
(sync/status/delete) = ``settings.write`` (instance-level správa).
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stopa.data.case_registry_repository import (
    list_entries,
    remove_case_entry,
    set_status,
    sync_case_entry,
)
from stopa.data.cross_case_repository import list_case_ids, open_instance, user_org
from stopa.domain.case_registry import lease_status  # P4-7 — liveness výpočet (čistá funkce)


class StatusIn(BaseModel):
    status: str = Field(..., description="open | closed | archived")


def register(app, ctx) -> None:
    """Přidá P2-2 routy do aplikace (volá se z ``create_app``)."""
    base = ctx["base"]
    _require = ctx["_require"]
    _current_user = ctx["_current_user"]

    def _identity() -> dict:
        """Efektivní identita pro tenancy výpočet (role + org; bez grantů — registr
        používá konzervativní viditelnost, explicitní cross-tenant granty nebereme)."""
        status, user = _current_user()
        if status == "ok":
            inst = open_instance(base)
            try:
                return {
                    "legacy": False,
                    "uorg": user_org(inst, user["id"]),
                    "role": str(user["role"]),
                }
            finally:
                inst.close()
        return {"legacy": True, "uorg": None, "role": ctx["_current_role"]()}

    @app.get("/api/registry")
    def registry_list(tenant: str | None = None):
        """P2-2 — seznam případů z centrálního registru (tenancy filtr, volitelné
        ``tenant``). Pořadí deterministické: created_at ASC, case_id."""
        _require("cross_case_query", "registry")
        ident = _identity()
        inst = open_instance(base)
        try:
            entries = list_entries(
                inst,
                tenant=tenant,
                user_org=ident["uorg"],
                multi_user=not ident["legacy"],
                role=ident["role"],
            )
            # P4-7 — lease liveness (domain čistá funkce; stav alive/expired/unknown)
            return {"entries": entries, "lease": lease_status(entries)}
        finally:
            inst.close()

    @app.post("/api/registry/{case_id}/sync", status_code=201)
    def registry_sync(case_id: str):
        """Idempotentní sync jednoho případu do registru (404 = neznámý případ)."""
        _require("settings.write", "registry-sync", case_id=case_id)  # B3a — NOCTX fix: tenancy per case
        if case_id not in list_case_ids(base):
            raise HTTPException(404, f"Případ {case_id!r} neexistuje")
        inst = open_instance(base)
        try:
            return sync_case_entry(inst, base, case_id)  # ValueError → 400 níže
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            inst.close()

    @app.post("/api/registry/{case_id}/status")
    def registry_status(case_id: str, body: StatusIn):
        """Změna stavu záznamu registru; 404 = není v registru, 400 = neplatný status."""
        _require("settings.write", "registry-status", case_id=case_id)  # B3a — NOCTX fix: tenancy per case
        inst = open_instance(base)
        try:
            return set_status(inst, case_id, body.status)  # ValueError → 400 níže
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            inst.close()

    @app.delete("/api/registry/{case_id}")
    def registry_delete(case_id: str):
        """Odebrání záznamu registru; 404 = není v registru."""
        _require("settings.write", "registry-delete", case_id=case_id)  # B3a — NOCTX fix: tenancy per case
        inst = open_instance(base)
        try:
            if not remove_case_entry(inst, case_id):
                raise HTTPException(404, f"Případ {case_id!r} není v registru")
            return {"removed": case_id}
        finally:
            inst.close()
