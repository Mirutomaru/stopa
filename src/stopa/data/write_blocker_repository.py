"""F5.4 — Write-blocker stavová vrstva (data): audit log ``wb_*`` akce + aktuální stav.

Orchestrace v :class:`WriteBlockerRepository` (stejné pravidlo jako F5.1
SealRepository) — db.py facade zůstává tenká a drží řádkový budget.
"""

from __future__ import annotations

import json as _json
import sqlite3

from stopa.data.audit_repository import AuditRepository
from stopa.domain.write_blocker import ACTION_ATTACHED, ACTION_REMOVED, compute_state


class WriteBlockerRepository:
    """WB stav v audit logu (append-only ``wb_*`` záznamy) + aktuální stav."""

    def __init__(self, conn: sqlite3.Connection, audit_repo: AuditRepository):
        self._conn = conn
        self._audit = audit_repo

    # ── zápis ────────────────────────────────────────────────
    def attach(
        self,
        vendor: str,
        product: str | None = None,
        device: str | None = None,
        notes: str | None = None,
        actor: str | None = None,
    ) -> int:
        """Zaznamenat připojení WB (audit ``wb_attached``). Vrací audit ID."""
        return self._audit.log_operation(
            ACTION_ATTACHED,
            actor=actor,
            details={
                "vendor": vendor,
                "product": product or None,
                "device": device or None,
                "notes": notes or None,
            },
        )

    def remove(self, reason: str | None = None, actor: str | None = None) -> int:
        """Zaznamenat odebrání WB (audit ``wb_removed``). Vrací audit ID."""
        return self._audit.log_operation(
            ACTION_REMOVED, actor=actor, details={"reason": reason or None}
        )

    # ── čtení ────────────────────────────────────────────────
    def history(self) -> list[dict]:
        """Všechny ``wb_*`` záznamy chronologicky (id vzestupně)."""
        rows = self._conn.execute(
            "SELECT ts, action, actor, details_json FROM audit_log"
            " WHERE action LIKE 'wb\\_%' ESCAPE '\\' ORDER BY id ASC"
        ).fetchall()
        out: list[dict] = []
        for row in rows:
            try:
                details = _json.loads(row["details_json"] or "{}")
            except ValueError:
                details = {}
            out.append(
                {
                    "ts": row["ts"],
                    "action": row["action"],
                    "actor": row["actor"],
                    "details": details,
                }
            )
        return out

    def latest_state(self) -> dict | None:
        """Aktuální WB stav (None = žádné ``wb_*`` záznamy)."""
        records = self.history()
        return compute_state(records) if records else None
