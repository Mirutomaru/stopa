"""P3-3 Automated Classification API.

Routy nad případem: výpis klasifikací, spuštění pravidlového klasifikátoru a
lidský override (audit + reverzibilní). Logika žije v ``domain/classification``
+ I/O v ``data/classification_repository``; tady je jen API hrana.

Konvence (stejné jako P2-5): 404 = neznámý případ (z ``ctx["open_db"]``) nebo
neexistující klasifikace; 400 = semantická chyba domény/repotitáře
(ValueError/TypeError).
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stopa.data.classification_repository import ClassificationRepository


class OverrideIn(BaseModel):
    classification_id: int = Field(..., description="ID řádku classifications")
    category: str = Field(..., description="cílová kategorie (taxonomie 11 kategorií)")
    reason: str | None = Field(None, description="důvod override (povinný, neprázdný)")
    actor: str | None = Field(None, description="explicitní actor (default: case examiner)")


def register(app, ctx) -> None:
    """Přidá P3-3 routy do aplikace (volá se z ``create_app``)."""
    open_db = ctx["open_db"]
    _require = ctx["_require"]  # B3a — per-case tenancy enforcement

    @app.get("/api/cases/{case_id}/classifications")
    def list_classifications(case_id: str, needs_review: bool = False) -> dict:
        """Výsledek klasifikace per soubor (+ efektivní kategorie po override)."""
        _require("case.read", "list_classifications", case_id=case_id)
        db = open_db(case_id)
        try:
            repo = ClassificationRepository(db.conn)
            rows = repo.list_classifications(case_id)
            if needs_review:
                rows = [r for r in rows if r["needs_review"]]
            return {"classifications": rows}
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/classifications/classify")
    def run_classification(case_id: str) -> dict:
        """Spustí pravidlový klasifikátor nad všemi soubory (re-run deterministický)."""
        _require("analysis.run", "run_classification", case_id=case_id)
        db = open_db(case_id)
        try:
            repo = ClassificationRepository(db.conn)
            summary = repo.classify_case(case_id)
            return {"ok": True, "summary": summary}
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/classifications/override")
    def override_classification(case_id: str, body: OverrideIn) -> dict:
        """Lidský override klasifikace (append-only audit; auto hodnota zůstává)."""
        _require("case.update", "override_classification", case_id=case_id)
        db = open_db(case_id)
        try:
            repo = ClassificationRepository(db.conn)
            result = repo.override(
                case_id,
                body.classification_id,
                body.category,
                actor=body.actor,
                reason=body.reason,
            )
            if result is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"klasifikace neexistuje v případě: {body.classification_id}",
                )
            return {"ok": True, "classification": result}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            db.close()
