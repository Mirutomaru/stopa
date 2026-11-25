"""AuditRepository — neměnný audit trail + integrity (ETAPA C vlna 1).

Vyčleněno z monolitu ``db.py``: tabulky ``audit_log``,
``integrity_checkpoints`` (+ meta klíče Ed25519). Tenká SQLite vrstva bez
business logiky; sdílená ``sqlite3.Connection`` přichází od facade
:class:`CaseDB`. Hash chaining (P0 Core C4) a RBAC actor resolution zůstávají
v doménové vrstvě :mod:`stopa.domain.integrity` / :mod:`stopa.domain.rbac`.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime, timezone

from stopa.domain.integrity import (
    GENESIS,
    ChainRow,
    compute_audit_hash,
    generate_keypair,
    sign_hash,
    unwrap_private_key,
    verify_chain,
    wrap_private_key,
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
    def _append_audit_row(
        self, action: str, actor: str | None, details: dict | None
    ) -> int:
        """B9 — audit řádek **bez commitu** (transakci řídí volající).

        Vyčleněno z :meth:`log_operation` pro atomické operace (rotace klíčů);
        logika identická s původní implementací.
        """
        resolved = resolve_actor(actor, self._case_examiner())
        _, prev = self._last_audit_row()
        ts = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details or {}, ensure_ascii=False)
        h = compute_audit_hash(prev, ts, action, resolved, details_json)
        cur = self.conn.execute(
            "INSERT INTO audit_log (ts, action, actor, details_json, prev_hash, hash)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (ts, action, resolved, details_json, prev, h),
        )
        return int(cur.lastrowid)

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
        if strict and resolve_actor(actor, self._case_examiner()) is None:
            raise ActorError(f"Actor je povinný při '{action}' — explicitní actor nebo case examiner")
        row_id = self._append_audit_row(action, actor, details)
        self.conn.commit()  # BC — log_operation zůstává samostatně atomická
        return row_id

    def verify_audit_chain(self, *, collect_all: bool = False):
        """Ověří celý hash řetězec audit logu. Vrací :class:`ChainReport`.

        B9 — ``collect_all=True`` nashromáždí **všechny** defekty (nejen první)
        do ``report.defects``; výchozí ``False`` zachovává BC chování.
        """
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
        return verify_chain(rows, collect_all=collect_all)

    def list_audit_log(
        self, limit: int | None = 100, offset: int | None = None, actor: str | None = None
    ) -> list[dict]:
        """Audit trail — nejnovější operace první (chronologická stopa).

        F4.4: volitelný filtr ``actor`` (audit log per user).
        """
        q = "SELECT id, ts, action, actor, details_json FROM audit_log"
        params: list[object] = []
        if actor is not None:
            q += " WHERE actor = ?"
            params.append(actor)
        q += " ORDER BY id DESC"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        if offset:
            q += f" OFFSET {int(offset)}"
        rows = self.conn.execute(q, params).fetchall()
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

    # ── Ed25519 kontrolní body (P0 Core C4) + P0-2 správa klíčů ────
    def _integrity_master_secret(self) -> bytes | None:
        """P0-2: master secret z ``STOPA_INTEGRITY_MASTER_KEY`` (base64, 32 B).

        Není nastaven → ``None`` (klíč se ukládá jako legacy plaintext b64).
        Nesprávné base64 / špatná délka → ValueError (fail-fast při otevření).
        """
        raw = os.environ.get("STOPA_INTEGRITY_MASTER_KEY", "").strip()
        if not raw:
            return None
        try:
            secret = base64.b64decode(raw)
        except ValueError as e:  # binascii.Error ⊂ ValueError
            raise ValueError(f"STOPA_INTEGRITY_MASTER_KEY: neplatné base64 ({e})") from e
        if len(secret) != 32:
            raise ValueError(
                f"STOPA_INTEGRITY_MASTER_KEY musí být 32 bajtů (base64), má {len(secret)}"
            )
        return secret

    def _get_priv_raw(self) -> str | None:
        """P0-2: soukromý klíč z meta — dekoduje obal, legacy b64 vrací bez změny."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'integrity_priv'"
        ).fetchone()
        if row is None or not row["value"]:
            return None
        try:
            return unwrap_private_key(row["value"], self._integrity_master_secret())
        except ValueError as e:
            raise ValueError(f"dekódování soukromého klíče integrity selhalo: {e}") from e

    def ensure_integrity_key(self) -> tuple[str, str]:
        """Vygeneruje Ed25519 klíčový pár případu (idempotentní).

        Soukromý klíč v meta (case DB), veřejný do reportu. Vrací
        ``(private_b64_raw, public_b64)`` — raw b64 pro podpisování konzumenty
        (daubert/compliance/crypto_report). P0-2: s nastaveným master secretem se
        soukromý klíč ukládá AES-GCM obalený, bez něj legacy plaintext.
        Vyžaduje balík ``cryptography``.
        """
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'integrity_pub'"
        ).fetchone()
        if row is not None:
            priv_raw = self._get_priv_raw()
            return (priv_raw or "", row["value"])
        priv_b64, pub_b64 = generate_keypair()  # RuntimeError bez cryptography
        secret = self._integrity_master_secret()
        stored_priv = wrap_private_key(priv_b64, secret) if secret else priv_b64
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('integrity_priv', ?)",
            (stored_priv,),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('integrity_pub', ?)",
            (pub_b64,),
        )
        self.conn.commit()
        return priv_b64, pub_b64

    def rotate_integrity_key(self, reason: str = "key_rotation") -> dict | None:
        """P0-2: rotace Ed25519 páry — nová generace klíče s historií.

        Staré kontrolní body zůstávají ověřitelné (drží vlastní public key);
        kontinuitu ér ukazuje rotační bod podepsaný NOVÝM klíčem na stejném
        last_hash. Vrací ``{"old_public_key", "public_key_b64", "checkpoint_id"}``;
        ``None`` pokud ještě žádná pára neexistuje (volat ensure nejdřív).
        Bez cryptography → RuntimeError z generate_keypair.

        B9 — explicitní transakce: auditní záznam + výměna páry v meta + rotační
        kontrolní bod jsou all-or-nothing (dříve samostatné commity; crash uprostřed
        mohl nechat novou pub se starým priv). Rotace je součástí hash řetězce
        (``integrity_key_rotated``); chybějící kontrolní bod = ValueError místo
        tichého ``checkpoint_id=None``.
        """
        old_pub = self.integrity_public_key()
        if old_pub is None:
            return None
        priv_b64, pub_b64 = generate_keypair()  # RuntimeError bez cryptography
        secret = self._integrity_master_secret()
        stored_priv = wrap_private_key(priv_b64, secret) if secret else priv_b64
        with self.conn:  # B9 — jeden atomický blok; výjimka → rollback celého
            self._append_audit_row(
                "integrity_key_rotated",
                None,  # atribuce na case examinera (priorita resolve_actor)
                {
                    "old_public_key": old_pub,
                    "public_key_b64": pub_b64,
                    "reason": reason or "key_rotation",
                },
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('integrity_priv', ?)",
                (stored_priv,),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('integrity_pub', ?)",
                (pub_b64,),
            )
            # Rotační bod podepsaný NOVÝM klíčem: ve stejné transakci vidíme
            # vyměněnou páru → checkpoint vznikne vždy (fail-closed kontrola níže).
            cp_id = self._insert_checkpoint_row(reason or "key_rotation")
            if cp_id is None:  # B9 — prakticky nedosažitelné; fail-closed přesto
                raise ValueError("rotace integrity klíče: nevznikl rotační kontrolní bod")
        return {
            "old_public_key": old_pub,
            "public_key_b64": pub_b64,
            "checkpoint_id": cp_id,
        }

    def integrity_public_key(self) -> str | None:
        """Veřejný Ed25519 klíč případu (base64), pokud byl vygenerován."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'integrity_pub'"
        ).fetchone()
        return row["value"] if row else None

    def _insert_checkpoint_row(self, reason: str) -> int | None:
        """B9 — kontrolní bod **bez commitu** (transakci řídí volající).

        Vyčleněno z :meth:`add_integrity_checkpoint` pro atomické operace;
        ``None`` pokud klíč nebyl vygenerován (graceful degradation).
        """
        pub = self.integrity_public_key()
        if pub is None:
            return None
        priv_raw = self._get_priv_raw()
        if priv_raw is None:
            return None
        audit_id, last_hash = self._last_audit_row()
        sig_b64 = sign_hash(priv_raw, last_hash)
        cur = self.conn.execute(
            "INSERT INTO integrity_checkpoints"
            " (ts, audit_row_id, last_hash, signature_b64, reason, public_key_b64)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                audit_id or 0,
                last_hash,
                sig_b64,
                reason,
                pub,
            ),
        )
        return int(cur.lastrowid)

    def add_integrity_checkpoint(self, reason: str) -> int | None:
        """Podpisne hash posledního audit řádku a uloží kontrolní bod.

        Vrací ID kontrolního bodu; ``None`` pokud klíč nebyl vygenerován
        (graceful degradation — bez balíku ``cryptography``). P0-2: bod si
        ukládá i public key, kterým byl podepsán (rotace-safe ověření).
        """
        cp_id = self._insert_checkpoint_row(reason)
        if cp_id is not None:
            self.conn.commit()  # BC — commit jen při skutečně vloženém bodu
        return cp_id

    def list_integrity_checkpoints(self) -> list[dict]:
        """Kontrolní body (chronologicky) — pro report / nezávislou kontrolu.

        P0-2: každý bod nese ``public_key_b64`` (klíč podpisu); ``None`` u
        legacy řádků z éry před rotací (ověření pak s fallbackem na meta klíč).
        """
        rows = self.conn.execute(
            "SELECT id, ts, audit_row_id, last_hash, signature_b64, reason,"
            " public_key_b64 FROM integrity_checkpoints ORDER BY id ASC"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "audit_row_id": r["audit_row_id"],
                "last_hash": r["last_hash"],
                "signature_b64": r["signature_b64"],
                "reason": r["reason"],
                "public_key_b64": r["public_key_b64"],
            }
            for r in rows
        ]

    def verify_integrity_checkpoints(self) -> list[dict]:
        """Ověří kontrolní body (nezávislá kontrola).

        P0-2: každý bod se ověřuje klíčem, který je drží (``public_key_b64``);
        legacy řádky bez klíče fallback na aktuální meta public key (staré
        chování) a dostanou ``key_source="meta_fallback"``. Vrací seznam
        ``{"id", "ok"}`` per bod (stejné pořadí jako list_integrity_checkpoints).
        """
        from stopa.domain.integrity import verify_signature

        fallback_pub = self.integrity_public_key()
        cps = self.list_integrity_checkpoints()
        # Backward compat (před P0-2): žádný klíč nikde → legacy souhrnný záznam.
        if fallback_pub is None and not any(cp["public_key_b64"] for cp in cps):
            return [{"ok": False, "reason": "veřejný klíč nebyl vygenerován"}]
        out: list[dict] = []
        for cp in cps:
            pub = cp["public_key_b64"] or fallback_pub
            if pub is None:
                out.append({"id": cp["id"], "ok": False})
                continue
            ok = verify_signature(pub, cp["last_hash"], cp["signature_b64"])
            item: dict = {"id": cp["id"], "ok": ok}
            if not cp["public_key_b64"] and fallback_pub is not None:
                item["key_source"] = "meta_fallback"  # legacy řádek (před P0-2)
            out.append(item)
        return out
