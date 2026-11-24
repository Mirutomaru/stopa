"""P2-5 Threat Intelligence Workspace API.

Routy nad případem: IoC feed (``/intel/feed``, ``/intel/import``) a deterministické
matching × artefakty/entity (``/intel/match``, re-run = clear + insert). Logika žije
v ``domain/threat_intel`` + I/O v ``data/intel_repository``; tady je jen API hrana.

Konvence: 404 = neznámý případ (z ``ctx["open_db"]``); 400 = semantická chyba
domény/repotitáře (ValueError/TypeError); 201 = import proběhl.
"""

from __future__ import annotations

from fastapi import Body, HTTPException
from pydantic import BaseModel, Field

from stopa.data.intel_repository import IntelRepository, run_intel_match


class IoCIn(BaseModel):
    kind: str = Field(..., description="ip | domain | hash | url")
    value: str
    tlp: str = "GREEN"
    source: str | None = None


class ImportIn(BaseModel):
    iocs: list[IoCIn]


class MatchIn(BaseModel):
    """P3-5 volitelné parametry matchingu (bez těla = klasické IoC matching)."""

    yara_dir: str | None = Field(None, description="adresář YARA pravidel (.yar)")
    sigma_file: str | None = Field(None, description="Sigma šablony — JSON/YAML dokument")


def _repo(db) -> IntelRepository:
    return IntelRepository(db.conn)


def register(app, ctx) -> None:
    """Přidá P2-5 routy do aplikace (volá se z ``create_app``)."""
    open_db = ctx["open_db"]
    _require = ctx["_require"]  # B3a — per-case tenancy enforcement

    @app.get("/api/cases/{case_id}/intel/feed")
    def intel_feed(case_id: str):
        _require("case.read", "intel_feed", case_id=case_id)
        db = open_db(case_id)
        try:
            repo = _repo(db)
            return {
                "feed": repo.list_feed(case_id),
                "summary": repo.feed_summary(case_id),
            }
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/intel/import", status_code=201)
    def intel_import(case_id: str, body: ImportIn):
        _require("case.update", "intel_import", case_id=case_id)
        from stopa.domain.threat_intel import IoC

        db = open_db(case_id)
        try:
            # kanonizace + fail-closed validace v konstruktoru IoC (ValueError → 400 níže)
            iocs = [
                IoC(kind=i.kind, value=i.value, tlp=i.tlp, source=i.source or "")
                for i in body.iocs
            ]
            n = _repo(db).import_feed(case_id, iocs)
            return {"imported": n}
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/intel/match")
    def intel_match(case_id: str, body: MatchIn | None = Body(default=None)):
        """Matching IoC feedu × artefakty/entities (+ P3-5 YARA/Sigma), re-run = clear + insert."""
        _require("analysis.run", "intel_match", case_id=case_id)
        db = open_db(case_id)
        try:
            return run_intel_match(
                db,
                case_id,
                yara_dir=body.yara_dir if body else None,
                sigma_file=body.sigma_file if body else None,
            )  # ValueError → 400 níže
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
