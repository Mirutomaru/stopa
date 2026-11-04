"""AuditRepository — neměnný audit trail + integrity (ETAPA C vlna 1).

Vyčleněno z monolitu ``db.py``: tabulky ``audit_log``,
``integrity_checkpoints`` (+ meta klíče Ed25519). Tenká SQLite vrstva bez
business logiky; sdílená ``sqlite3.Connection`` přichází od facade
:class:`CaseDB`. Hash chaining (P0 Core C4) a RBAC actor resolution zůstávají
v doménové vrstvě :mod:`stopa.domain.integrity` / :mod:`stopa.domain.rbac`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stopa.domain.integrity import (
    GENESIS,
    ChainRow,
    compute_audit_hash,
    generate_keypair,
    sign_hash,
    verify_chain,
)
from stopa.domain.rbac import ActorError, resolve_actor  # STP-022 — RBAC minimální


class AuditRepository:
    """Append-only audit log + hash chaining + Ed25519 kontrolní body."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── interní pomocníci (sdílené s integrity checkpointy) ────────
    def _last_audit_row(self) -> tuple[int | None, str]:
        """ID posledního audit řádku + jeho hash (GENESIS pokud log prázdný)."""
        row = self.conn.execute(
            "SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None, GENESIS
        return int(row["id"]), str(row["hash"] or "")

    def _case_examiner(self) -> str | None:
        """Examiner případu (fallback actor pro audit trail). Case DB = jeden případ."""
        row = self.conn.execute("SELECT examiner FROM cases LIMIT 1").fetchone()
        return row["examiner"] if row is not None else None

    # ── audit log (append-only + hash chaining) ─────────────────────
    def log_operation(
        self,
        action: str,
        actor: str | None = None,
        details: dict | None = None,
        *,
        strict: bool = False,  # STP-022 — RBAC minimální (actor povinný)
    ) -> int:
        """Neměnný záznam operace (append-only) + hash chaining (P0 Core C4). Vrací ID řádku.

        `action` — kanonický verb: case_created / source_added / file_processed /
        artifact_extracted / report_generated / hash_verified …
        Každý řádek nese ``prev_hash`` (hash předchozího) a vlastní ``hash`` →
        jakákoli změna starého řádku rozbití řetězec (ověřitelné bez klíče).

        STP-022 RBAC minimální: actor se řeší prioritou **explicitní > case
        examiner** (backward compat — volající bez explicitního actora dostanou
        atribuci na examinera). ``strict=True`` vyžaduje vyřešeného actora,
        jinak :class:`ActorError` (default False = původní chování).
        """
        resolved = resolve_actor(actor, self._case_examiner())
        if strict and resolved is None:
            raise ActorError(f"Actor je povinný při '{action}' — explicitní actor nebo case examiner")
        _, prev = self._last_audit_row()
        ts = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details or {}, ensure_ascii=False)
        h = compute_audit_hash(prev, ts, action, resolved, details_json)
        cur = self.conn.execute(
            "INSERT INTO audit_log (ts, action, actor, details_json, prev_hash, hash)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (ts, action, resolved, details_json, prev, h),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def verify_audit_chain(self):
        """Ověří celý hash řetězec audit logu. Vrací :class:`ChainReport`."""
        rows = [
            ChainRow(
                id=int(r["id"]),
                ts=r["ts"],
                action=r["action"],
                actor=r["actor"],
                details_json=r["details_json"] or "{}",
                prev_hash=r["prev_hash"] or GENESIS,
                hash=r["hash"] or "",
            )
            for r in self.conn.execute(
                "SELECT id, ts, action, actor, details_json, prev_hash, hash"
                " FROM audit_log ORDER BY id ASC"
            ).fetchall()
        ]
        return verify_chain(rows)

    def list_audit_log(
        self, limit: int | None = 100, offset: int | None = None
    ) -> list[dict]:
        """Audit trail — nejnovější operace první (chronologická stopa)."""
        q = "SELECT id, ts, action, actor, details_json FROM audit_log ORDER BY id DESC"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        if offset:
            q += f" OFFSET {int(offset)}"
        rows = self.conn.execute(q).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "action": r["action"],
                "actor": r["actor"],
                "details": json.loads(r["details_json"] or "{}"),
            }
            for r in rows
        ]

    # ── E1 Evidence Manager: custody items ───────────────────────
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

    # ── Ed25519 kontrolní body (P0 Core C4) ───────────────────
    def ensure_integrity_key(self) -> tuple[str, str]:
        """Vygeneruje Ed25519 klíčový pár případu (idempotentní).

        Soukromý klíč v meta (case DB), veřejný do reportu. Vrací
        ``(private_b64, public_b64)``. Vyžaduje balík ``cryptography``.
        """
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'integrity_pub'"
        ).fetchone()
        if row is not None:
            priv_row = self.conn.execute(
                "SELECT value FROM meta WHERE key = 'integrity_priv'"
            ).fetchone()
            return (priv_row["value"] if priv_row else "", row["value"])
        priv_b64, pub_b64 = generate_keypair()
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('integrity_priv', ?)",
            (priv_b64,),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('integrity_pub', ?)",
            (pub_b64,),
        )
        self.conn.commit()
        return priv_b64, pub_b64

    def integrity_public_key(self) -> str | None:
        """Veřejný Ed25519 klíč případu (base64), pokud byl vygenerován."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'integrity_pub'"
        ).fetchone()
        return row["value"] if row else None

    def add_integrity_checkpoint(self, reason: str) -> int | None:
        """Podpisne hash posledního audit řádku a uloží kontrolní bod.

        Vrací ID kontrolního bodu; ``None`` pokud klíč nebyl vygenerován
        (graceful degradation — bez balíku ``cryptography``).
        """
        pub = self.integrity_public_key()
        if pub is None:
            return None
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'integrity_priv'"
        ).fetchone()
        if row is None or not row["value"]:
            return None
        audit_id, last_hash = self._last_audit_row()
        sig_b64 = sign_hash(row["value"], last_hash)
        cur = self.conn.execute(
            "INSERT INTO integrity_checkpoints (ts, audit_row_id, last_hash, signature_b64, reason)"
            " VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), audit_id or 0, last_hash, sig_b64, reason),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_integrity_checkpoints(self) -> list[dict]:
        """Kontrolní body (chronologicky) — pro report / nezávislou kontrolu."""
        rows = self.conn.execute(
            "SELECT id, ts, audit_row_id, last_hash, signature_b64, reason"
            " FROM integrity_checkpoints ORDER BY id ASC"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "audit_row_id": r["audit_row_id"],
                "last_hash": r["last_hash"],
                "signature_b64": r["signature_b64"],
                "reason": r["reason"],
            }
            for r in rows
        ]

    def verify_integrity_checkpoints(self) -> list[dict]:
        """Ověří kontrolní body veřejným klíčem (nezávislá kontrola).

        Každý bod: ``verify_signature(pub, last_hash, signature_b64)``. Vrací
        seznam s ``ok`` per bod + souhrn.
        """
        pub = self.integrity_public_key()
        from stopa.domain.integrity import verify_signature

        out: list[dict] = []
        if pub is None:
            return [{"ok": False, "reason": "veřejný klíč nebyl vygenerován"}]
        for cp in self.list_integrity_checkpoints():
            ok = verify_signature(pub, cp["last_hash"], cp["signature_b64"])
            out.append({"id": cp["id"], "ok": ok})
        return out
