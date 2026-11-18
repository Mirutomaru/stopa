"""GraphRepository — ruční/AI hrany Evidence Graph (P1-3).

Tabulka ``graph_edges``: explicitní vztahy mezi uzly grafu důkazů, kde je
důvod vzniku (``reason``) povinný. Derived hrany se počítají na letě
(``domain/evidence_graph.py``), tady se ukládá jen to, co data přímo
neobsahují (AI role, ruční anotace znalce).

Sdílená connection s facade (WAL, commit) — stejný pattern jako ostatní repozitáře.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stopa.domain.evidence_graph import NODE_TYPES, POLARITIES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GraphRepository:
    """CRUD nad tabulkou ``graph_edges`` (P1-3 Evidence Graph)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── zápis ────────────────────────────────────────────────────────
    def upsert_edge(
        self,
        case_id: str,
        *,
        src_type: str,
        src_id: str,
        dst_type: str,
        dst_id: str,
        relation: str,
        polarity: str = "neutral",
        reason: str,
        confidence: float = 0.5,
    ) -> int:
        """Idempotentní upsert hrany (UNIQUE case+src+dst+relation). Vrací ID řádku.

        Semantické chyby → ValueError (typy/polarity), nesprávné typy → TypeError.
        ``reason`` je povinný — bez vysvětlení vznik hrana do grafu nevstoupí.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("hrana bez důvodu vzniku (reason)")
        for t in (src_type, dst_type):
            if t not in NODE_TYPES:
                raise ValueError(f"neplatný typ uzlu: {t!r}")
        if polarity not in POLARITIES:
            raise ValueError(f"neplatná polarita: {polarity!r}")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise TypeError("confidence musí být číslo")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(f"confidence mimo 0..1: {confidence!r}")

        cur = self.conn.execute(
            "INSERT INTO graph_edges (case_id, src_type, src_id, dst_type, dst_id,"
            " relation, polarity, reason, confidence, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (case_id, src_type, src_id, dst_type, dst_id, relation) DO UPDATE SET"
            "   polarity = excluded.polarity,"
            "   reason = excluded.reason,"
            "   confidence = excluded.confidence",
            (
                case_id, src_type, src_id, dst_type, dst_id,
                relation, polarity, reason.strip(), float(confidence), _now_iso(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def clear_edges(self, case_id: str) -> int:
        """Vymaže hrany případu (re-run / explicitní reset). Vrací počet."""
        cur = self.conn.execute(
            "DELETE FROM graph_edges WHERE case_id = ?", (case_id,)
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    # ── čtení ────────────────────────────────────────────────────────
    def list_edges(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, src_type, src_id, dst_type, dst_id, relation,"
            " polarity, reason, confidence, created_at"
            " FROM graph_edges WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]
