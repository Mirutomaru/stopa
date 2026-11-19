"""P2-6 — Cross-case correlation API (instance DB).

Routy nad :mod:`stopa.data.cross_case_repository` + :mod:`stopa.domain.cross_case`:
sdílené entity napříč případy (read-only case DB), tenancy pravidla, audit trail
(hash chain) a explicitní cross-tenant granty. Logika žije v domain/data vrstvě;
tady je jen API hrana.

Konvence: 404 = neznámý případ; 403 = bez oprávnění (tenancy/role, ``detail``);
400 = semantická chyba domény/repotitáře; 201 = vytvořen grant.

Oprávnění: dotazy i audit = ``cross_case_query`` (F4.4; analyst zamčený),
správa grantů = ``settings.write`` (instance-level konfigurace).
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stopa.data.cross_case_repository import (
    add_xcorr_grant,
    audit_chain_ok,
    case_orgs,
    collect_cases_data,
    list_audit,
    list_xcorr_grants,
    log_xcorr_query,
    open_case_readonly,
    open_instance,
    user_grants,
    user_org,
)
from stopa.domain.cross_case import find_shared_entities, xcorr_allowed

#: Web filtr → druh entity v tabulce ``entities`` (design: email|tel|hash).
_ENTITY_KINDS = {"email": "email", "tel": "phone", "hash": "hash"}


class GrantIn(BaseModel):
    user_id: str
    org_id: str
    granted_by: str | None = Field(None, description="username dárce oprávnění (volitelné)")


def register(app, ctx) -> None:
    """Přidá P2-6 routy do aplikace (volá se z ``create_app``)."""
    base = ctx["base"]
    _require = ctx["_require"]
    _current_user = ctx["_current_user"]

    def _identity() -> dict:
        """Efektivní identita pro tenancy výpočet (po projití ``_require``).

        Session uživatel → globální role + org/granty z instance DB; bez tokenu
        → legacy single-operator (multi-user režim už vrátil 401 v ``_require``).
        """
        status, user = _current_user()
        if status == "ok":
            inst = open_instance(base)
            try:
                uid = user["id"]
                return {
                    "legacy": False,
                    "username": user["username"],
                    "uorg": user_org(inst, uid),
                    "grants": user_grants(inst, uid),
                    "role": str(user["role"]),
                }
            finally:
                inst.close()
        return {
            "legacy": True,
            "username": None,
            "uorg": None,
            "grants": frozenset(),  # type: ignore[type-arg]
            "role": ctx["_current_role"](),
        }

    @app.get("/api/xcorr/correlate")
    def xcorr_correlate(case_a: str, case_b: str, entity: str | None = None):
        """Sdílené entity mezi dvěma případy (read-only) + tenancy verdikt + audit.

        403 s ``detail`` = důvod omezení; výsledek je prázdný, ale dotaz se do
        audit trailu zapíše (hash chain — jeden záznam na dotaz).
        """
        _require("cross_case_query", "xcorr")
        kind = None if entity is None else _ENTITY_KINDS.get(entity)
        if kind is None and entity is not None:
            raise HTTPException(400, f"entity musí být email|tel|hash (zadáno {entity!r})")

        ident = _identity()
        inst = open_instance(base)
        conns = {}
        try:
            for cid in sorted({case_a, case_b}):
                try:
                    conns[cid] = open_case_readonly(base, cid)
                except ValueError as exc:  # neznámý případ → 404
                    raise HTTPException(404, str(exc)) from exc

            shared = find_shared_entities(collect_cases_data(conns), kind=kind)
            verdict = xcorr_allowed(
                role=ident["role"],
                case_a_orgs=case_orgs(inst, case_a),
                case_b_orgs=case_orgs(inst, case_b),
                user_org=ident["uorg"],
                grants=ident["grants"],
                legacy=bool(ident["legacy"]),
            )
            audit_row = log_xcorr_query(
                inst, actor=ident["username"], case_ids=[case_a, case_b], scope={"entity": entity}
            )
            payload = {
                "cases": [case_a, case_b],
                "shared": shared if verdict[0] else [],
                "tenancy": verdict[1],
                "audit_id": audit_row["id"],
            }
            if not verdict[0]:
                return JSONResponse(status_code=403, content=payload)
            return payload
        except (ValueError, TypeError) as exc:  # semantická chyba → 400
            raise HTTPException(400, str(exc)) from exc
        finally:
            for conn in conns.values():
                conn.close()
            inst.close()

    @app.get("/api/xcorr/audit")
    def xcorr_audit(limit: int = 100):
        """Audit trail cross-case dotazů (nejnovější první) + stav hash chainu."""
        _require("cross_case_query", "xcorr-audit")
        inst = open_instance(base)
        try:
            return {
                "records": list_audit(inst, limit=limit),
                "chain_ok": audit_chain_ok(inst),
            }
        finally:
            inst.close()

    @app.get("/api/xcorr/grants")
    def xcorr_grants_list():
        """Explicitní cross-tenant granty (xcorr_grants + usernames/org names)."""
        _require("cross_case_query", "xcorr-grants")
        inst = open_instance(base)
        try:
            return list_xcorr_grants(inst)
        finally:
            inst.close()

    @app.post("/api/xcorr/grants", status_code=201)
    def xcorr_grant_add(body: GrantIn):
        """Přidá explicitní cross-tenant grant; 400 = neznámý uživatel/org."""
        _require("settings.write", "xcorr-grant")
        inst = open_instance(base)
        try:
            return add_xcorr_grant(
                inst, user_id=body.user_id, org_id=body.org_id, granted_by=body.granted_by
            )  # ValueError → 400 níže
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            inst.close()
