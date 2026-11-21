"""SealRepository — F5.1 Merkle Tree Case Sealing (case DB vrstva).

Tenká SQLite vrstva nad tabulkou ``case_seals``: pečeť = snapshot stavu
případu (artifacts + timeline_events + audit_log prefix) zamknutý jedním
Merkle kořenem podepsaným Ed25519 klíčem případu. Čistá logika stromu a
kanonizace řádků je v :mod:`stopa.domain.case_seal`; Ed25519 operace v
:mod:`stopa.domain.integrity` (lazy ``cryptography`` — graceful degradation).

Semantika snapshot s předponou: pečeť fixuje první N řádků každé tabulky
v pořadí vložení (artifacts/timeline_events = rowid, audit_log = id);
pozdní append neruší pečet', změna/smazání fixovaného řádku ano. Detaily:
docstring :mod:`stopa.domain.case_seal`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from stopa.domain.case_seal import (
    DOMAIN_TAG,  # noqa: F401 — backward compat pro testy formátu
    SEAL_FORMAT_VERSION,
    build_merkle_root,
    leaf_hash,
    root_hex,
)
from stopa.domain.integrity import sign_hash, verify_signature
from stopa.domain.rbac import resolve_actor  # actor pečetě (resolve jako audit log)
from stopa.domain.seal_chain import (
    SealChainRecord,
)
from stopa.domain.seal_chain import (
    build_record as _build_chain_record,
)
from stopa.domain.seal_chain import (
    verify_chain as _verify_chain_domain,
)

#: Tabulky spadající pod pečet' v globálním pořadí leafů (domain.case_seal).
SEALED_TABLES: tuple[str, ...] = ("artifacts", "timeline_events", "audit_log")


def _stopa_version() -> str:
    try:  # importlib metadata (instalovaný balík); fallback dev
        from importlib.metadata import version

        return version("stopa")
    except Exception:  # noqa: BLE001 — sdist/venv bez metadata → "dev"
        return "dev"


class SealRepository:
    """Pečetě případu (Merkle root + Ed25519 podpis) v case DB."""

    def __init__(self, conn: sqlite3.Connection, audit_repo=None):
        self.conn = conn
        # F5.1 — volitelná audit vrstva: zajistí Ed25519 klíč (graceful
        # degradation bez cryptography) + zapíše "case_sealed" do audit logu.
        self._audit_repo = audit_repo

    # ── kanonické čtení řádků zamčených tabulek ─────────────────────
    @staticmethod
    def _order_clause(table: str) -> str:
        """Pořadí vložení: audit_log má id == rowid; ostatní ORDER BY rowid."""
        return "ORDER BY id" if table == "audit_log" else "ORDER BY rowid"

    def _table_columns(self, table: str) -> list[str]:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r["name"] for r in rows]

    def _columns_hash(self, table: str) -> str:
        """Fingerprint sloupcového schématu tabulky (detekce schema driftu)."""
        return hashlib.sha256("|".join(self._table_columns(table)).encode("utf-8")).hexdigest()

    def _iter_values(self, table: str, limit: int | None = None):
        """Hodnoty řádků v pořadí vložení (tuply dle PRAGMA sloupců).

        ``limit`` — max. počet řádků (None = vše); audit_log alternativně
        omezuje ``id <= limit`` přes volající kód (předpona pečetě).
        """
        q = f"SELECT * FROM {table} {self._order_clause(table)}"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        for row in self.conn.execute(q):
            yield tuple(row)

    def _iter_audit_prefix(self, audit_row_id: int | None = None):
        """Audit prefix: id <= audit_row_id (None = vše), chronologicky."""
        if audit_row_id is None:
            q = "SELECT * FROM audit_log ORDER BY id"
        else:
            q = "SELECT * FROM audit_log WHERE id <= ? ORDER BY id"
            rows = self.conn.execute(q, (int(audit_row_id),)).fetchall()
            for row in rows:
                yield tuple(row)
            return
        for row in self.conn.execute(q):
            yield tuple(row)

    # ── výpočet kořenů ───────────────────────────────────────────────
    def compute_roots(
        self,
        *,
        artifact_count: int | None = None,
        timeline_count: int | None = None,
        audit_row_id: int | None = None,
    ) -> dict:
        """Přepočítá Merkle kořeny pro zadaný (fixovaný) rozsah.

        ``None`` = celá tabulka; jinak první N řádků v pořadí vložení
        (audit_log: id <= N). Vrací slovník s kombinovaným rootem,
        per-tabulkovými sub-rooty (diagnostika „která tabulka se změnila")
        a počty leafů. Globální pořadí leafů: artifacts → timeline_events
        → audit_log (domain.case_seal).
        """
        leaves_art = [leaf_hash("artifacts", row) for row in self._iter_values("artifacts", artifact_count)]
        leaves_tl = [leaf_hash("timeline_events", row) for row in self._iter_values("timeline_events", timeline_count)]
        leaves_aud = [leaf_hash("audit_log", row) for row in self._iter_audit_prefix(audit_row_id)]

        sub_roots = {
            "artifacts": root_hex(build_merkle_root(leaves_art)),
            "timeline_events": root_hex(build_merkle_root(leaves_tl)),
            "audit_log": root_hex(build_merkle_root(leaves_aud)),
        }
        combined = build_merkle_root(leaves_art + leaves_tl + leaves_aud)
        return {
            "root": combined,
            "sub_roots": sub_roots,
            "counts": {
                "artifacts": len(leaves_art),
                "timeline_events": len(leaves_tl),
                "audit_log": len(leaves_aud),
            },
            "columns_hash": {t: self._columns_hash(t) for t in SEALED_TABLES},
        }

    # ── CRUD pečetí ──────────────────────────────────────────────────
    def seal_case(
        self, *, case_id: str | None = None, actor: str | None = None, reason: str | None = None
    ) -> dict | None:
        """Vytvoří novou pečeť (snapshot celého aktuálního stavu případu).

        Ed25519 klíč případu zajistí přes audit vrstvu (vygeneruje ho, pokud
        neexistuje); vrací ``None``, pokud není k dispozici — selže jen bez
        volitelného balíku ``cryptography`` (graceful degradation). Actor se
        resolvuje jako jinde v audit logu: explicitní > znalec případu
        (cases.examiner podle ``case_id``) > None. Zaznamená audit řádek
        "case_sealed" (po výpočtu rootu → snapshot s předponou ho neobsahuje).
        """
        if self._audit_repo is not None and self._audit_repo.integrity_public_key() is None:
            try:
                self._audit_repo.ensure_integrity_key()
            except RuntimeError:  # chybí cryptography → graceful degradation
                return None
        examiner = None
        if case_id is not None:
            row = self.conn.execute("SELECT examiner FROM cases WHERE id = ?", (case_id,)).fetchone()
            if row is not None:
                examiner = row["examiner"]
        sealed_by = resolve_actor(actor, examiner)
        seal = self._create_seal(sealed_by=sealed_by, reason=reason, case_id=case_id)
        if self._audit_repo is not None:
            self._audit_repo.log_operation(
                "case_sealed",
                actor=sealed_by,
                details={
                    "seal_id": seal["id"],
                    "root_hash": seal["root_hash"][:16] + "…",
                    "artifacts": seal["artifacts"],
                    "timeline_events": seal["timeline_events"],
                    "audit_rows": seal["audit_log"],
                },
            )
        return seal

    def _create_seal(
        self, *, sealed_by: str | None = None, reason: str | None = None, case_id: str | None = None
    ) -> dict:
        """Jádro pečetění (bez klíčové/actor orchestrace): vyžaduje Ed25519 klíč.

        Klíč případu v ``meta`` (integrity_pub/integrity_priv); jinak
        :class:`KeyError`. Vrací info o uložené pečetí; P4-6 navíc vždy
        připojí řetězový záznam Sealing v2 (tabulka ``seal_chain``, klíče
        ``seq``/``chain_hash``), pokud je v DB identifikátor případu.
        """
        pub_row = self.conn.execute("SELECT value FROM meta WHERE key = 'integrity_pub'").fetchone()
        priv_row = self.conn.execute("SELECT value FROM meta WHERE key = 'integrity_priv'").fetchone()
        if pub_row is None or not priv_row or not priv_row["value"]:
            raise KeyError("Ed25519 klíč případu nebyl vygenerován (meta: integrity_pub/integrity_priv)")

        res = self.compute_roots()  # celá aktuální data = fixovaný rozsah pečetě
        root_hex_str = root_hex(res["root"])
        sig_b64 = sign_hash(priv_row["value"], root_hex_str)
        ts = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(
            {
                "format": SEAL_FORMAT_VERSION,
                "stopa_version": _stopa_version(),
                "sub_roots": res["sub_roots"],
                "columns_hash": res["columns_hash"],
            },
            sort_keys=True,
        )
        cur = self.conn.execute(
            "INSERT INTO case_seals"
            " (ts, sealed_by, reason, artifacts_count, timeline_count, audit_row_id,"
            "  root_hash, signature_b64, public_key_b64, meta_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                sealed_by,
                reason,
                res["counts"]["artifacts"],
                res["counts"]["timeline_events"],
                res["counts"]["audit_log"],  # audit prefix = všechny řádky v okamžiku pečetě
                root_hex_str,
                sig_b64,
                pub_row["value"],
                meta_json,
            ),
        )
        out: dict = {
            "id": int(cur.lastrowid),
            "ts": ts,
            "sealed_by": sealed_by,
            "reason": reason,
            "root_hash": root_hex_str,
            **res["counts"],
        }
        # P4-6 — Sealing v2: řetězový záznam 1:1 s touto pečetí (stejná transakce).
        # prev = poslední root v řetězci; genesis = self-binding vlastní root.
        cid = case_id or self._resolve_case_id()
        if cid is not None:
            last = self.conn.execute(
                "SELECT seq, merkle_root FROM seal_chain WHERE case_id = ? ORDER BY seq DESC LIMIT 1",
                (cid,),
            ).fetchone()
            prev_root = last["merkle_root"] if last is not None else None
            seq = int(last["seq"]) + 1 if last is not None else 1
            rec = _build_chain_record(seq, cid, ts, root_hex_str, prev_root)
            self.conn.execute(
                "INSERT INTO seal_chain"
                " (case_id, seq, seal_id, ts, merkle_root, prev_merkle_root, chain_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, rec.seq, out["id"], rec.ts_iso, rec.merkle_root_hex,
                 rec.prev_merkle_root_hex, rec.chain_hash_hex),
            )
            out["seq"] = rec.seq
            out["chain_hash"] = rec.chain_hash_hex
        self.conn.commit()
        return out

    def _resolve_case_id(self) -> str | None:
        """Identifikátor případu v této case DB (konvence: jeden příklad na soubor)."""
        row = self.conn.execute("SELECT id FROM cases ORDER BY rowid LIMIT 1").fetchone()
        return row["id"] if row is not None else None

    def list_seals(self) -> list[dict]:
        """Pečetě chronologicky (id ASC) — pro report / nezávislou kontrolu."""
        rows = self.conn.execute(
            "SELECT id, ts, sealed_by, reason, artifacts_count, timeline_count,"
            " audit_row_id, root_hash, signature_b64, public_key_b64, meta_json"
            " FROM case_seals ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def verify_all(self) -> list[dict]:
        """Ověří všechny pečeti; vrací report per pečeť (id ASC).

        Závěr ``ok`` = shoda přepočteného rootu s uloženým **a** platný
        Ed25519 podpis (veřejným klíčem uloženým v pečetí — nezávislá
        kontrola bez soukromého klíče). ``changed_tables`` = tabulky, jejichž
        sub-root neodpovídá (diagnostika); ``schema_drift`` — schéma sloupců
        se mezitím změnilo (migrační kontext pro soudní report).
        """
        reports: list[dict] = []
        for seal in self.list_seals():
            stored_meta = json.loads(seal["meta_json"] or "{}")
            stored_sub = stored_meta.get("sub_roots", {})
            stored_cols = stored_meta.get("columns_hash", {})

            res = self.compute_roots(
                artifact_count=seal["artifacts_count"],
                timeline_count=seal["timeline_count"],
                audit_row_id=seal["audit_row_id"],
            )
            root_ok = root_hex(res["root"]) == seal["root_hash"]
            sig_ok = verify_signature(seal["public_key_b64"], seal["root_hash"], seal["signature_b64"])
            changed = [t for t in SEALED_TABLES if res["sub_roots"][t] != stored_sub.get(t)]
            drift = [t for t in SEALED_TABLES if stored_cols.get(t) is not None and stored_cols[t] != res["columns_hash"][t]]

            reports.append(
                {
                    "id": seal["id"],
                    "ts": seal["ts"],
                    "sealed_by": seal["sealed_by"],
                    "reason": seal["reason"],
                    "ok": bool(root_ok and sig_ok),
                    "root_ok": bool(root_ok),
                    "sig_ok": bool(sig_ok),
                    "changed_tables": changed,
                    "schema_drift": drift,
                    "counts": {
                        "artifacts": seal["artifacts_count"],
                        "timeline_events": seal["timeline_count"],
                        "audit_log": seal["audit_row_id"],
                    },
                    "root_hash": seal["root_hash"],
                }
            )
        return reports

    # ── P4-6 — Sealing v2: time hash chain + externí witness ────────────────

    def _load_chain_rows(self, case_id: str) -> list[dict]:
        """Řetězové záznamy případu chronologicky (seq ASC)."""
        rows = self.conn.execute(
            "SELECT id, seq, seal_id, ts, merkle_root, prev_merkle_root,"
            " chain_hash, witness_json FROM seal_chain WHERE case_id = ? ORDER BY seq ASC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_chain(self, case_id: str) -> list[dict]:
        """Řetěz pečetí v2 pro report (witness_json rozbaleno na ``witness``)."""
        out: list[dict] = []
        for r in self._load_chain_rows(case_id):
            w = json.loads(r["witness_json"]) if r.get("witness_json") else None
            out.append({**r, "witness": w})
        return out

    def verify_chain(self, case_id: str) -> dict:
        """Ověří celý řetěz pečetí v2 (fail-closed); vrací report.

        Dvě nezávislé rovnice: (1) doménová linka hashů — sekvence 1..N,
        každý ``prev`` = root předchozí pečetě, přepočet ``chain_hash``;
        (2) vazba na F5.1 pečeť přes ``seal_id`` — shoda ``merkle_root`` s
        ``case_seals.root_hash`` a platný Ed25519 podpis (uloženým veřejným
        klíčem). Jakákoli odchylka → ``verified=False`` + popis chyby.
        """
        rows = self._load_chain_rows(case_id)
        records = [
            SealChainRecord(
                seq=r["seq"],
                ts_iso=r["ts"],
                merkle_root_hex=r["merkle_root"],
                prev_merkle_root_hex=r["prev_merkle_root"],
                chain_hash_hex=r["chain_hash"],
            )
            for r in rows
        ]
        error: str | None = None
        try:
            _verify_chain_domain(case_id, records)
        except ValueError as exc:  # fail-closed — popisná chyba pro report
            error = f"řetěz: {exc}"

        detail: list[dict] = []
        for r in rows:
            seal_ok = True
            note: str | None = None
            srow = self.conn.execute(
                "SELECT root_hash, signature_b64, public_key_b64 FROM case_seals WHERE id = ?",
                (r["seal_id"],),
            ).fetchone()
            if srow is None:
                seal_ok, note = False, f"chybí pečeť #{r['seal_id']} v case_seals"
            elif r["merkle_root"] != srow["root_hash"]:
                seal_ok, note = False, "merkle_root se liší od case_seals.root_hash (tampering)"
            elif not verify_signature(srow["public_key_b64"], srow["root_hash"], srow["signature_b64"]):
                seal_ok, note = False, "neplatný Ed25519 podpis F5.1 pečetě"
            if error is None and not seal_ok:
                error = f"seq={r['seq']}: {note}"
            detail.append({**r, "witness": json.loads(r["witness_json"]) if r.get("witness_json") else None,
                          "seal_ok": seal_ok, "note": note})

        return {
            "case_id": case_id,
            "count": len(rows),
            "verified": error is None and all(d["seal_ok"] for d in detail),
            "error": error,
            "records": detail,
        }

    def attach_witness(self, case_id: str, seq: int, witness: dict) -> None:
        """Uloží externí witness u řetězového záznamu (fail-closed na neexistující)."""
        cur = self.conn.execute(
            "UPDATE seal_chain SET witness_json = ? WHERE case_id = ? AND seq = ?",
            (json.dumps(witness, sort_keys=True, separators=(",", ":")), case_id, seq),
        )
        if cur.rowcount != 1:
            raise ValueError(f"seal_chain: neexistuje záznam case={case_id!r} seq={seq}")
        self.conn.commit()
