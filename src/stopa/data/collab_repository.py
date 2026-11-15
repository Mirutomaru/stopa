"""STOPA — CollabRepository: comments na artefaktech + in-app notifikace (F4.5).

Čistý CRUD bez doménové logiky (ETAPA C pattern jako ``UserRepository``):
mutace commitují, integrity chyby propagují; doménová pravidla (mentions,
read/write úroveň) žijí v ``domain/collab.py``.

Tabulky ``artifact_comments`` + ``notifications`` jsou v case DB (schéma v18).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


def _utc_now() -> str:
    """ISO-8601 UTC timestamp (stejný formát jako ostatní repozitáře)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CollabRepository:
    """Comments na artefaktech + in-app notifikace (case DB, schéma v18)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── Comments (F4.5 — sdílení a kolaborace na artefaktech) ────────────

    def add_comment(
        self, case_id: str, artifact_id: str, author: str, body: str, mentions: list[str]
    ) -> dict:
        """Přidá komentář (append-only); vrací uložený řádek."""
        cid = f"cmt-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            "INSERT INTO artifact_comments"
            " (id, case_id, artifact_id, author, body, mentions_json, ts_utc)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, case_id, artifact_id, author, body, json.dumps(mentions), _utc_now()),
        )
        self.conn.commit()
        return self.get_comment(cid) or {}

    def get_comment(self, comment_id: str) -> dict | None:
        """Komentář podle ID; neexistuje → None."""
        row = self.conn.execute(
            "SELECT * FROM artifact_comments WHERE id=?", (comment_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_comments(self, case_id: str, artifact_id: str | None = None) -> list[dict]:
        """Komentáře případu (volitelně jen jednoho artefaktu), chronologicky."""
        if artifact_id is None:
            rows = self.conn.execute(
                "SELECT * FROM artifact_comments WHERE case_id=? ORDER BY ts_utc, id",
                (case_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM artifact_comments"
                " WHERE case_id=? AND artifact_id=? ORDER BY ts_utc, id",
                (case_id, artifact_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_comment(
        self,
        comment_id: str,
        body: str,
        mentions: list[str],
        expected_revision: int | None = None,
    ) -> dict:
        """Upraví komentář; ``expected_revision`` = optimistické zamykání.

        Verze ne odpovídá aktuální → :class:`ValueError` (souběžná editace —
        web vrstva mapuje na 409 Conflict). Bez parametru = slepý zápis.
        """
        cur = self.get_comment(comment_id)
        if cur is None:
            raise KeyError(f"komentář {comment_id} nenalezen")
        actual = int(cur["revision"])
        if expected_revision is not None and actual != int(expected_revision):
            raise ValueError(
                f"verze se změnila (aktuálně {actual}, očekáváno {expected_revision})"
            )
        self.conn.execute(
            "UPDATE artifact_comments SET body=?, mentions_json=?,"
            " revision=revision+1, edited_at=? WHERE id=?",
            (body, json.dumps(mentions), _utc_now(), comment_id),
        )
        self.conn.commit()
        return self.get_comment(comment_id) or {}

    def delete_comment(self, comment_id: str) -> bool:
        """Smaže komentář; True pokud řádek existoval."""
        cur = self.conn.execute(
            "DELETE FROM artifact_comments WHERE id=?", (comment_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ── Notifikace (in-app inbox) ────────────────────────────────────────

    def add_notification(
        self,
        username: str,
        kind: str,
        body: str,
        case_id: str | None = None,
        artifact_id: str | None = None,
    ) -> dict:
        """Přidá notifikaci pro uživatele (kind ∈ mention|comment|shared)."""
        nid = f"ntf-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            "INSERT INTO notifications"
            " (id, username, kind, body, case_id, artifact_id, ts_utc)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, username, kind, body, case_id, artifact_id, _utc_now()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
        return dict(row) if row is not None else {}

    def list_notifications(
        self, username: str, unread_only: bool = False, limit: int = 100
    ) -> list[dict]:
        """Inbox uživatele (nejnovější první); volitelně jen nečtené."""
        sql = "SELECT * FROM notifications WHERE username=?"
        if unread_only:
            sql += " AND read=0"
        rows = self.conn.execute(
            sql + " ORDER BY ts_utc DESC, id LIMIT ?", (username, max(1, min(int(limit), 500)))
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, notification_id: str, username: str | None = None) -> bool:
        """Označí notifikaci jako přečtenou; True pokud řádek existoval."""
        if username is None:
            cur = self.conn.execute(
                "UPDATE notifications SET read=1 WHERE id=?", (notification_id,)
            )
        else:
            cur = self.conn.execute(
                "UPDATE notifications SET read=1 WHERE id=? AND username=?",
                (notification_id, username),
            )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_all_read(self, username: str) -> int:
        """Označí všechny notifikace uživatele jako přečtené; počet změněných."""
        cur = self.conn.execute(
            "UPDATE notifications SET read=1 WHERE username=? AND read=0", (username,)
        )
        self.conn.commit()
        return cur.rowcount
