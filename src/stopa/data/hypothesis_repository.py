"""HypothesisRepository — graf hypotéz (F3.5).

Tabulka ``hypotheses``: AI generuje uzly (claim + důkazy pro/proti jako ID
artefaktů + confidence), člověk ručně potvrzuje/vyvrací (status přechody).
Strom podhypotéz přes ``parent_id``; citace = lineage k artefaktům.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stopa.models import new_id

#: Platné stavy hypotézy (ruční potvrzení/vyvrácení dle AK F3.5).
HYPOTHESIS_STATUSES = ("pending", "confirmed", "refuted")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HypothesisRepository:
    """CRUD nad tabulkou ``hypotheses`` (sdílená connection s facade)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── zápis ────────────────────────────────────────────────────────
    def add(
        self,
        case_id: str,
        claim: str,
        confidence: float = 0.5,
        support: list[str] | None = None,
        against: list[str] | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Přidá uzel grafu; vrací jeho ID.

        ``support``/``against`` = ID artefaktů (důkazy pro/proti). Confidence je
        omezeno CHECKem 0.1–0.9 (interval interpretace, ne „jistota“).
        """
        if not claim or not claim.strip():
            raise ValueError("hypothésa bez claimu")
        hyp_id = new_id("hyp")
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO hypotheses (id, case_id, claim, confidence, status,"
            " support_json, against_json, parent_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
            (
                hyp_id,
                case_id,
                claim.strip(),
                float(confidence),
                json.dumps(support or [], ensure_ascii=False),
                json.dumps(against or [], ensure_ascii=False),
                parent_id,
                now,
                now,
            ),
        )
        self.conn.commit()
        return hyp_id

    def set_status(self, hyp_id: str, status: str) -> bool:
        """Ruční potvrzení/vyvrácení (i zpět na pending = „znovu zvážit“). True pokud existovala."""
        if status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"neplatný stav hypotézy: {status!r}")
        cur = self.conn.execute(
            "UPDATE hypotheses SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), hyp_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── čtení ────────────────────────────────────────────────────────
    def get(self, hyp_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, case_id, claim, confidence, status, support_json,"
            " against_json, parent_id, created_at, updated_at"
            " FROM hypotheses WHERE id = ?",
            (hyp_id,),
        ).fetchone()
        return self._row(row) if row else None

    def list_by_case(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, case_id, claim, confidence, status, support_json,"
            " against_json, parent_id, created_at, updated_at"
            " FROM hypotheses WHERE case_id = ? ORDER BY rowid",
            (case_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["support"] = json.loads(d.pop("support_json") or "[]")
        d["against"] = json.loads(d.pop("against_json") or "[]")
        return d
