"""CaseRepository — případy, zdroje důkazů a custody metadata (ETAPA C vlna 1).

Vyčleněno z monolitu ``db.py``: tabulky ``cases``, ``sources``,
``custody_items``. Tenká SQLite vrstva bez business logiky; sdílená
``sqlite3.Connection`` přichází od facade :class:`CaseDB`.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from stopa.domain import source_manifest as sm  # P0.4/P1 — zdrojový manifest (čistá logika)
from stopa.models import Case, EvidenceSource

logger = logging.getLogger(__name__)


class CaseRepository:
    """CRUD případů + zdrojů důkazů + custody items (E1 Evidence Manager)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── cases ────────────────────────────────────────────────
    def add_case(self, case: Case) -> None:
        self.conn.execute(
            "INSERT INTO cases (id, name, created_at, examiner, notes, timezone_name,"
            " auto_export_enabled, auto_export_interval_minutes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case.id,
                case.name,
                case.created_at.isoformat(),
                case.examiner,
                case.notes,
                case.timezone_name,
                1 if case.auto_export_enabled else 0,
                case.auto_export_interval_minutes,
            ),
        )
        self.conn.commit()

    def list_cases(self) -> list[Case]:
        """Všechny případy v case DB (pro web GUI přehled)."""
        rows = self.conn.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
        out: list[Case] = []
        for r in rows:
            c = Case(
                id=r["id"], name=r["name"], examiner=r["examiner"], notes=r["notes"]
            )
            cols = r.keys()  # E2: staré DB bez sloupce → default
            if "timezone_name" in cols:
                c.timezone_name = r["timezone_name"] or "Europe/Prague"
            # STP-069: stará DB (schéma ≤ v12) bez sloupců auto-exportu → default off.
            if "auto_export_enabled" in cols:
                c.auto_export_enabled = bool(r["auto_export_enabled"])
            if "last_auto_export_path" in cols:
                c.last_auto_export_path = r["last_auto_export_path"]
            # STP-070: stará DB (schéma ≤ v13) bez sloupců plánovače → defaulty.
            if "auto_export_interval_minutes" in cols:
                c.auto_export_interval_minutes = r["auto_export_interval_minutes"]
            if "last_auto_export_at" in cols and r["last_auto_export_at"]:
                try:
                    c.last_auto_export_at = datetime.fromisoformat(
                        r["last_auto_export_at"]
                    )
                except ValueError:
                    # poškozený timestamp → None (scheduler spustí znovu) — H1
                    logger.warning(
                        "case %s: poškozený last_auto_export_at=%r → None",
                        c.id, r["last_auto_export_at"],
                    )
            if r["created_at"]:
                try:
                    c.created_at = datetime.fromisoformat(r["created_at"])
                except ValueError:
                    # poškozený created_at → default modelu — H1 (trvalá data)
                    logger.warning(
                        "case %s: poškozený created_at=%r → default",
                        c.id, r["created_at"],
                    )
            out.append(c)
        return out

    def get_case(self, case_id: str) -> Case | None:
        """E12 — načte případ podle ID."""
        row = self.conn.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_case(row)

    def update_case(
        self,
        case_id: str,
        name: str | None = None,
        examiner: str | None = None,
        notes: str | None = None,
        timezone_name: str | None = None,
        auto_export_enabled: bool | None = None,
    ) -> bool:
        """E12 — aktualizace metadat případu (jen zadaná pole). True pokud existoval."""
        sets: list[str] = []
        vals: list[object] = []
        for col, val in (
            ("name", name),
            ("examiner", examiner),
            ("notes", notes),
            ("timezone_name", timezone_name),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                vals.append(val)
        # STP-069: bool se liší od str — explicitní větev (False je platná hodnota).
        if auto_export_enabled is not None:
            sets.append("auto_export_enabled = ?")
            vals.append(1 if auto_export_enabled else 0)
        if not sets:
            return self.get_case(case_id) is not None
        vals.append(case_id)
        cur = self.conn.execute(
            f"UPDATE cases SET {', '.join(sets)} WHERE id = ?", vals
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_last_auto_export(self, case_id: str, path: str) -> None:
        """STP-069 — zapíše cestu k poslednímu automatickému ZIP bundle."""
        self.conn.execute(
            "UPDATE cases SET last_auto_export_path = ? WHERE id = ?", (path, case_id)
        )
        self.conn.commit()

    def set_auto_export_interval(self, case_id: str, minutes: int | None) -> bool:
        """STP-070 — nastaví interval periodického auto-bundle (None = vypnuto).

        Liší se od ``update_case`` tím, že explicitně umí i *vymazat* interval
        (None), což by v update_case kolizovalo s „pole nezadáno“. Vrací True
        pokud případ existoval.
        """
        cur = self.conn.execute(
            "UPDATE cases SET auto_export_interval_minutes = ? WHERE id = ?",
            (minutes, case_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_auto_export_ran(self, case_id: str, ts_iso: str) -> None:
        """STP-070 — zapíše UTC čas posledního spuštění periodického auto-exportu."""
        self.conn.execute(
            "UPDATE cases SET last_auto_export_at = ? WHERE id = ?", (ts_iso, case_id)
        )
        self.conn.commit()

    def list_scheduled_cases(self) -> list[Case]:
        """STP-070 — případy se zapnutým auto-expor­tem a nastaveným intervalem.

        Scheduler prochází jen tyto případy (interval NULL = nenastaveno → přeskočí).
        """
        rows = self.conn.execute(
            "SELECT * FROM cases WHERE auto_export_enabled = 1"
            " AND auto_export_interval_minutes IS NOT NULL ORDER BY id"
        ).fetchall()
        return [self._row_to_case(r) for r in rows]

    def _row_to_case(self, row: sqlite3.Row) -> Case:
        """STP-070 — sdílený mapping řádku → Case (get_case + list_scheduled_cases)."""
        cols = set(row.keys())  # staré DB bez sloupců → defaulty
        return Case(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            examiner=row["examiner"],
            notes=row["notes"],
            timezone_name=row["timezone_name"] or "Europe/Prague",
            auto_export_enabled=(
                bool(row["auto_export_enabled"]) if "auto_export_enabled" in cols else False
            ),
            last_auto_export_path=(
                row["last_auto_export_path"] if "last_auto_export_path" in cols else None
            ),
            auto_export_interval_minutes=(
                row["auto_export_interval_minutes"]
                if "auto_export_interval_minutes" in cols
                else None
            ),
            last_auto_export_at=_parse_ts(
                row["last_auto_export_at"] if "last_auto_export_at" in cols else None
            ),
        )

    def delete_case(self, case_id: str) -> bool:
        """E12 — smaže případ i všechny jeho zdroje (kaskáda na files/artifacts/timeline).

        `sources` nemá ON DELETE CASCADE na cases(id), takže je nutné smazat
        zdroje explicitně; entities/correlations mají vlastní CASCADE.
        Vrací True pokud případ existoval.
        """
        existing = self.get_case(case_id) is not None
        if not existing:
            return False
        # zdroje → kaskáda na files/artifacts/timeline_events/evidence_marks/custody_items
        self.conn.execute("DELETE FROM sources WHERE case_id = ?", (case_id,))
        # entities + correlations mají ON DELETE CASCADE, ale explicitně pro jistotu
        self.conn.execute("DELETE FROM entities WHERE case_id = ?", (case_id,))
        self.conn.execute(
            "DELETE FROM correlations WHERE case_id = ?", (case_id,)
        )
        self.conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        self.conn.commit()
        return True

    # ── sources ──────────────────────────────────────────────
    def add_source(self, source: EvidenceSource) -> None:
        self.conn.execute(
            "INSERT INTO sources (id, case_id, kind, path, size_bytes, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.case_id,
                source.kind,
                source.path,
                source.size_bytes,
                source.added_at.isoformat(),
            ),
        )
        self.conn.commit()

    def update_source_manifest(self, source_id: str, rows: list[dict]) -> dict:
        """P0.4/P1 — zdrojový manifest z aktuálního stavu tabulky ``files``.

        Přepočítá kanonickou serializace + SHA-256 a uloží do sloupců
        ``sources.manifest_*``; původní čas vytvoření (created_at_utc) se u
        změn nepřepisuje. Historii starých hodnot drží volající v audit chain
        (details události). Vrací status dict pro audit:
        ``{"status": "created"|"unchanged"|"changed", "old_sha256",
        "new_sha256", "file_count"}``.

        rows — dicts s klíči rel_path/size_bytes/mtime/sha256 (SELECT z files).
        """
        entries = sm.entries_from_rows(rows)
        new_json = sm.canonical_json(entries).decode("utf-8")
        new_sha = sm.manifest_sha256(entries)
        row = self.conn.execute(
            "SELECT manifest_sha256 FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        old_sha = row["manifest_sha256"] if row is not None else None
        total_size = sum(e.size_bytes or 0 for e in entries)
        now_utc = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE sources SET manifest_sha256 = ?, manifest_version = ?,"
            " manifest_json = ?, created_at_utc = COALESCE(created_at_utc, ?),"
            " file_count = ?, total_size_bytes = ? WHERE id = ?",
            (new_sha, sm.MANIFEST_VERSION, new_json, now_utc, len(entries), total_size, source_id),
        )
        self.conn.commit()
        status = "created" if old_sha is None else ("unchanged" if old_sha == new_sha else "changed")
        return {
            "status": status,
            "old_sha256": old_sha,
            "new_sha256": new_sha,
            "file_count": len(entries),
        }

    def get_source(self, source_id: str) -> EvidenceSource | None:
        row = self.conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return None
        return EvidenceSource(
            id=row["id"],
            case_id=row["case_id"],
            kind=row["kind"],  # type: ignore[arg-type]
            path=row["path"],
            size_bytes=row["size_bytes"],
            added_at=datetime.fromisoformat(row["added_at"]),
        )

    def list_sources(self, case_id: str) -> list[EvidenceSource]:
        rows = self.conn.execute(
            "SELECT * FROM sources WHERE case_id = ? ORDER BY added_at", (case_id,)
        ).fetchall()
        return [
            EvidenceSource(
                id=r["id"],
                case_id=r["case_id"],
                kind=r["kind"],  # type: ignore[arg-type]
                path=r["path"],
                size_bytes=r["size_bytes"],
                added_at=datetime.fromisoformat(r["added_at"]),
            )
            for r in rows
        ]

    # ── E1 Evidence Manager: custody items ───────────────────
    def set_custody_item(
        self,
        source_id: str,
        acquired_at: datetime | None = None,
        method: str | None = None,
        custodian: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Metadata nabytí důkazu pro jeden source (idempotentní upsert)."""
        ts = acquired_at or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self.conn.execute(
            "INSERT INTO custody_items (source_id, acquired_at, method, custodian, notes)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (source_id) DO UPDATE SET"
            " acquired_at = excluded.acquired_at,"
            " method = COALESCE(excluded.method, custody_items.method),"
            " custodian = COALESCE(excluded.custodian, custody_items.custodian),"
            " notes = COALESCE(excluded.notes, custody_items.notes)",
            (source_id, ts.isoformat(), method, custodian, notes),
        )
        self.conn.commit()

    def get_custody_item(self, source_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM custody_items WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "source_id": row["source_id"],
            "acquired_at": row["acquired_at"],
            "method": row["method"],
            "custodian": row["custodian"],
            "notes": row["notes"],
        }

    def list_custody_items(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.* FROM custody_items c ORDER BY c.acquired_at"
        ).fetchall()
        return [
            {
                "source_id": r["source_id"],
                "acquired_at": r["acquired_at"],
                "method": r["method"],
                "custodian": r["custodian"],
                "notes": r["notes"],
            }
            for r in rows
        ]


def _parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp from SQLite (naive UTC assumed)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
