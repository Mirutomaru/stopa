"""InvestigationRepository — poznámky, úkoly a revize hypotéz (P2-4).

Tabulky ``inv_notes``, ``inv_tasks``, ``hypothesis_revisions`` (schéma v23):
pracovní prostor znalce nad případem. Semantická validace + hash chain
řetězců žijí v čisté doménové vrstvě (``domain/investigation_workspace.py``);
tady je jen I/O.

Sdílená connection s facade (WAL, commit) — stejný pattern jako ostatní repozitáře
(``GraphRepository``, ``ProvenanceRepository``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stopa.domain.investigation_workspace import next_revision, validate_note, validate_task


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# druh ukotvení poznámky → tabulka s referencovaným objektem
_REF_TABLES = {
    "artifact": "artifacts",
    "entity": "entities",
    "timeline_event": "timeline_events",
}


class InvestigationRepository:
    """CRUD nad tabulkami investigation workspace (P2-4)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── poznámky ─────────────────────────────────────────────────────
    def add_note(
        self, case_id: str, ref_kind: str, ref_id: str, text: str, author: str | None = None
    ) -> int:
        """Přidá poznámku ukotvenou na artefakt/entity/timeline event. Vrací ID řádku.

        Typový nesoulad → TypeError, neplatné ukotvení nebo neexistující
        reference v případu → ValueError.
        """
        kind, rid, txt = validate_note(ref_kind, ref_id, text)
        self._assert_ref_exists(kind, rid)
        cur = self.conn.execute(
            "INSERT INTO inv_notes (case_id, ref_kind, ref_id, text, author, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, kind, rid, txt, author, _now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_notes(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, ref_kind, ref_id, text, author, created_at"
            " FROM inv_notes WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _assert_ref_exists(self, ref_kind: str, ref_id: str) -> None:
        table = _REF_TABLES[ref_kind]
        row = self.conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (ref_id,)).fetchone()
        if row is None:
            raise ValueError(f"{ref_kind} reference '{ref_id}' v případu neexistuje")

    # ── úkoly ────────────────────────────────────────────────────────
    def add_task(
        self,
        case_id: str,
        title: str,
        status: str = "open",
        assignee: str | None = None,
        due: str | None = None,
    ) -> int:
        """Přidá úkol (default open). Vrací ID řádku; chyby viz ``validate_task``."""
        t_title, st, assignee, parsed_due = validate_task(title, status=status, assignee=assignee, due=due)
        due_iso = parsed_due.isoformat() if parsed_due is not None else None
        now = _now_iso()
        cur = self.conn.execute(
            "INSERT INTO inv_tasks (case_id, title, status, assignee, due, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, t_title, st, assignee, due_iso, now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def set_task_status(self, case_id: str, task_id: int, status: str) -> dict:
        """Přepíše stav úkolu; vrací aktuální řádek. Neznámý úkol/stav → ValueError."""
        validate_task("t", status=status)  # jen validace stavu (title je placeholder)
        cur = self.conn.execute(
            "UPDATE inv_tasks SET status = ?, updated_at = ? WHERE id = ? AND case_id = ?",
            (status, _now_iso(), task_id, case_id),
        )
        if not cur.rowcount:
            raise ValueError(f"úkol {task_id} v případu neexistuje")
        self.conn.commit()
        updated = self.get_task(case_id, task_id)
        if updated is None:  # teoreticky nedosažitelné po UPDATE s rowcount>0
            raise ValueError(f"úkol {task_id} v případě zmizel během zápisu")
        return updated

    def get_task(self, case_id: str, task_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, title, status, assignee, due, created_at, updated_at"
            " FROM inv_tasks WHERE id = ? AND case_id = ?",
            (task_id, case_id),
        ).fetchone()
        return dict(row) if row else None

    def list_tasks(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, title, status, assignee, due, created_at, updated_at"
            " FROM inv_tasks WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── revize hypotéz (append-only hash chain) ──────────────────────
    def add_hypo_revision(
        self, case_id: str, hypothesis_id: str, claim: str, author: str | None = None
    ) -> dict:
        """Přidá příští revizi hypotézy; vrací kompletní uložený řádek.

        Neexistující hypotéza v případu → ValueError; semantické chyby claimu
        viz ``next_revision`` (doménová vrstva).
        """
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            raise ValueError("prázdné ID hypotézy")
        hyp = self.conn.execute(
            "SELECT id FROM hypotheses WHERE id = ? AND case_id = ?",
            (hypothesis_id.strip(), case_id),
        ).fetchone()
        if hyp is None:
            raise ValueError(f"hypotéza '{hypothesis_id}' v případu neexistuje")
        existing = self.list_hypo_revisions(case_id, hypothesis_id)
        row = next_revision(hypothesis_id.strip(), claim, author=author, existing=existing)
        cur = self.conn.execute(
            "INSERT INTO hypothesis_revisions"
            " (case_id, hypothesis_id, seq, content_json, author, prev_hash, hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id, row["hypothesis_id"], row["seq"], row["content_json"],
                author, row["prev_hash"], row["hash"], _now_iso(),
            ),
        )
        self.conn.commit()
        stored = self.get_hypo_revision(int(cur.lastrowid or 0))
        if stored is None:  # teoreticky nedosažitelné po INSERT s lastrowid>0
            raise ValueError("revize hypotézy zmizela během zápisu")
        return stored

    def get_hypo_revision(self, revision_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, case_id, hypothesis_id, seq, content_json, author,"
            " prev_hash, hash, created_at"
            " FROM hypothesis_revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_hypo_revisions(self, case_id: str, hypothesis_id: str | None = None) -> list[dict]:
        sql = (
            "SELECT id, case_id, hypothesis_id, seq, content_json, author,"
            " prev_hash, hash, created_at FROM hypothesis_revisions"
        )
        if hypothesis_id is None:
            rows = self.conn.execute(
                f"{sql} WHERE case_id = ? ORDER BY hypothesis_id, seq", (case_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"{sql} WHERE case_id = ? AND hypothesis_id = ? ORDER BY seq",
                (case_id, hypothesis_id),
            ).fetchall()
        return [dict(r) for r in rows]
