"""IntelRepository — IoC feed + matching (P2-5).

Tabulky ``ioc_feed_items`` / ``intel_matches`` (schéma v24): threat intel nad
případem. Kanonizace, STIX 2.1 import/export, klasifikace stáří a deterministický
matching žijí v čisté doménové vrstvě (``domain/threat_intel.py``); tady je jen I/O.

Sdílená connection s facade (WAL, commit) — stejný pattern jako ostatní repozitáře
(``InvestigationRepository``, ``ArtifactRepository``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stopa.domain.entities import collect_occurrences
from stopa.domain.threat_intel import (
    IoC,
    classify_age,
    feed_summary,
    ioc_id,
    match_iocs,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IntelRepository:
    """CRUD nad intel tabulkami (P2-5): idempotentní import feedu + re-runnable matching."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── feed ────────────────────────────────────────────────────────
    def import_feed(self, case_id: str, iocs: list[IoC]) -> int:
        """Idempotentní upsert IoC do feedu (stejný UUIDv5 ID → 1 řádek).

        Vrací počet zapsaných řádků. ``acquired_at=None`` se uloží jako aktuální
        čas (sloupec NOT NULL — základ klasifikace stáří).
        """
        now = _now_iso()
        for ioc in iocs:
            self.conn.execute(
                "INSERT OR REPLACE INTO ioc_feed_items"
                " (id, case_id, kind, value, raw_value, tlp, source,"
                "  acquired_at, imported_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ioc_id(ioc),
                    case_id,
                    ioc.kind,
                    ioc.value,
                    ioc.raw_value or None,
                    ioc.tlp,
                    ioc.source or None,
                    ioc.acquired_at.isoformat() if ioc.acquired_at else now,
                    now,
                ),
            )
        self.conn.commit()
        return len(iocs)

    def _load_iocs(self, case_id: str) -> list[IoC]:
        rows = self.conn.execute(
            "SELECT kind, value, raw_value, tlp, source, acquired_at"
            " FROM ioc_feed_items WHERE case_id = ? ORDER BY kind, value",
            (case_id,),
        ).fetchall()
        out: list[IoC] = []
        for r in rows:
            d = dict(r)
            out.append(
                IoC(
                    kind=d["kind"],
                    value=d["value"],
                    raw_value=d.get("raw_value") or "",
                    tlp=d["tlp"],
                    source=d.get("source") or "",
                    acquired_at=datetime.fromisoformat(d["acquired_at"]),
                )
            )
        return out

    def list_feed(self, case_id: str) -> list[dict]:
        """Položky feedu seřazené (kind, value), každá s klasifikací stáří."""
        now = datetime.now(timezone.utc)
        rows = self.conn.execute(
            "SELECT id, kind, value, raw_value, tlp, source, acquired_at, imported_at"
            " FROM ioc_feed_items WHERE case_id = ? ORDER BY kind, value",
            (case_id,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["age"] = classify_age(datetime.fromisoformat(d["acquired_at"]), now)
            out.append(d)
        return out

    def feed_summary(self, case_id: str) -> dict:
        """Shrnutí feedu (doménové ``feed_summary``) pro CLI/Web."""
        return feed_summary(self._load_iocs(case_id))

    # ── matching ────────────────────────────────────────────────────
    def clear_matches(self, case_id: str) -> int:
        cur = self.conn.execute("DELETE FROM intel_matches WHERE case_id = ?", (case_id,))
        return cur.rowcount or 0

    def save_matches(self, case_id: str, matches) -> list[int]:
        """Re-run matching = clear + insert (deterministický stav, bez duplicit)."""
        now = _now_iso()
        self.clear_matches(case_id)
        ids: list[int] = []
        for m in matches:
            cur = self.conn.execute(
                "INSERT INTO intel_matches"
                " (case_id, ioc_id, match_kind, evidence_json,"
                "  first_seen, last_seen, matched_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    m.ioc_id,
                    m.match_kind,
                    json.dumps(list(m.evidence), ensure_ascii=False),
                    m.first_seen,
                    m.last_seen,
                    now,
                ),
            )
            ids.append(int(cur.lastrowid or 0))
        self.conn.commit()
        return ids

    def list_matches(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, ioc_id, match_kind, evidence_json,"
            " first_seen, last_seen, matched_at"
            " FROM intel_matches WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
            out.append(d)
        return out


def run_intel_match(db, case_id: str) -> dict:
    """Deterministické matching IoC feedu případu × artefakty/entity.

    Tenká IO vrstva nad CaseDB (pattern ``run_correlation``):
    1. načtení feedu z ``ioc_feed_items`` (prázdný → ValueError),
    2. extrakce výskytů entit z artefaktů + záznamy souborů,
    3. deterministické matching → re-run = clear + insert do ``intel_matches``,
    4. shrnutí pro CLI/Web: summary feedu + počty per match_kind + list hitů.
    """
    repo = IntelRepository(db.conn)
    iocs = repo._load_iocs(case_id)
    if not iocs:
        raise ValueError(
            f"případ {case_id!r} nemá IoC feed — nejdřív `stopa intel import`"
        )
    artifacts = db.list_artifacts()
    files = db.list_files()
    occurrences = collect_occurrences(artifacts)
    matches = match_iocs(iocs, occurrences, files, artifacts)
    repo.save_matches(case_id, matches)
    by_kind: dict[str, int] = {}
    for m in matches:
        by_kind[m.match_kind] = by_kind.get(m.match_kind, 0) + 1
    return {
        "summary": feed_summary(iocs),
        "matches_total": len(matches),
        "by_match_kind": dict(sorted(by_kind.items())),
        "matches": [
            {
                "ioc_id": m.ioc_id,
                "kind": m.kind,
                "value": m.value,
                "tlp": m.tlp,
                "match_kind": m.match_kind,
                "evidence_count": len(m.evidence),
                "first_seen": m.first_seen,
                "last_seen": m.last_seen,
            }
            for m in matches
        ],
    }
