"""P2-5 Threat Intelligence Workspace API.

Routy nad případem: IoC feed (``/intel/feed``, ``/intel/import``) a deterministické
matching × artefakty/entity (``/intel/match``, re-run = clear + insert). Logika žije
v ``domain/threat_intel`` + I/O v ``data/intel_repository``; tady je jen API hrana.

Konvence: 404 = neznámý případ (z ``ctx["open_db"]``); 400 = semantická chyba
domény/repotitáře (ValueError/TypeError); 201 = import proběhl.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stopa.data.intel_repository import IntelRepository, run_intel_match


class IoCIn(BaseModel):
    kind: str = Field(..., description="ip | domain | hash | url")
    value: str
    tlp: str = "GREEN"
    source: str | None = None


class ImportIn(BaseModel):
    iocs: list[IoCIn]


def _repo(db) -> IntelRepository:
    return IntelRepository(db.conn)


def register(app, ctx) -> None:
    """Přidá P2-5 routy do aplikace (volá se z ``create_app``)."""
    open_db = ctx["open_db"]

    @app.get("/api/cases/{case_id}/intel/feed")
    def intel_feed(case_id: str):
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
    def intel_match(case_id: str):
        """Matching IoC feedu případu × artefakty/entity (re-run = clear + insert)."""
        db = open_db(case_id)
        try:
            return run_intel_match(db, case_id)  # ValueError → 400 níže
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
