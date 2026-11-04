"""EntityRepository — kanonické entity + korelace (ETAPA C vlna 2).

Vyčleněno z monolitu ``db.py``: tabulky ``entities``, ``correlations``.
Sdílená connection s facade (WAL, commit).

Vlna 2 ETAPY C — rozklad monolitu ``db.py`` na doménová repozitáře.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stopa.models import new_id


class EntityRepository:
    """Kanonické entity + korelace (E4 Entity + Correlation Engine)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── E4 Entity + Correlation Engine ────────────────────────────────
    def upsert_entities(self, case_id: str, rows) -> int:
        """Idempotentní upsert kanonických entit (UNIQUE case+kind+value).

        ``rows`` = iterace ``(kind, value_normalized, raw_value, first_seen, last_seen)``,
        kde časy jsou ISO UTC stringy nebo None. Při re-runu se first/last_seen
        agregují přes MIN/MAX a raw_value doplní jen pokud chybí. Vrací počet zapsaných řádků.
        """
        count = 0
        for kind, value, raw_value, first_seen, last_seen in rows:
            self.conn.execute(
                "INSERT INTO entities (id, case_id, kind, value_normalized,"
                " raw_value, first_seen, last_seen)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (case_id, kind, value_normalized) DO UPDATE SET"
                "   raw_value = COALESCE(entities.raw_value, excluded.raw_value),"
                "   first_seen = COALESCE("
                "     CASE WHEN entities.first_seen IS NOT NULL AND excluded.first_seen IS NOT NULL"
                "          THEN MIN(entities.first_seen, excluded.first_seen) END,"
                "     COALESCE(excluded.first_seen, entities.first_seen)),"
                "   last_seen  = COALESCE("
                "     CASE WHEN entities.last_seen IS NOT NULL AND excluded.last_seen IS NOT NULL"
                "          THEN MAX(entities.last_seen, excluded.last_seen) END,"
                "     COALESCE(excluded.last_seen, entities.last_seen))",
                (new_id("ent"), case_id, kind, value, raw_value, first_seen, last_seen),
            )
            count += 1
        self.conn.commit()
        return count

    def list_entities(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM entities WHERE case_id = ? ORDER BY kind, value_normalized",
            (case_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "kind": r["kind"],
                "value": r["value_normalized"],
                "raw_value": r["raw_value"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            }
            for r in rows
        ]

    def clear_correlations(self, case_id: str) -> int:
        """Vymaže propojení případu (re-run korelace = explicitní krok)."""
        cur = self.conn.execute(
            "DELETE FROM correlations WHERE case_id = ?", (case_id,)
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    def add_correlation(
        self,
        case_id: str,
        entity_a: str,
        entity_b: str,
        relation: str,
        confidence: str,
        evidence: list[dict],
        first_seen: str | None = None,
        last_seen: str | None = None,
    ) -> int:
        """Vloží jedno propojení s evidence listem. Vrací ID řádku.

        P0 I3: ``first_seen``/``last_seen`` = časové rozmezí vztahu (ISO UTC).
        """
        cur = self.conn.execute(
            "INSERT INTO correlations (case_id, entity_a, entity_b, relation,"
            " confidence, evidence_json, first_seen, last_seen, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                entity_a,
                entity_b,
                relation,
                confidence,
                json.dumps(evidence, ensure_ascii=False),
                first_seen,
                last_seen,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_correlations(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM correlations WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                evidence = json.loads(r["evidence_json"] or "[]")
            except json.JSONDecodeError:
                evidence = []
            out.append(
                {
                    "id": int(r["id"]),
                    "entity_a": r["entity_a"],
                    "entity_b": r["entity_b"],
                    "relation": r["relation"],
                    "confidence": r["confidence"],
                    "evidence": evidence,
                    # P0 I3: migrace _migrate_entity_resolution() v __init__ vždy
                    # přidá sloupce first_seen/last_seen → přímý přístup je bezpečný.
                    "first_seen": r["first_seen"],
                    "last_seen": r["last_seen"],
                    "created_at": r["created_at"],
                }
            )
        return out
