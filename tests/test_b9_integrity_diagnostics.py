"""B9 — Diagnostické mechanismy integrity (přesná lokalizace selhání).

Pokrytí nálezů F-1 až F-4 z auditu (PLAN_BACKLOG 2026-11-25):

- **F-1** audit hash řetězec — strojově čitelné typy defektů
  (``CHAIN_*``), všechny defekty najednou (``collect_all=True``) a viditelné
  mezery v ID; BC: výchozí chování na prvním defektu + text zprav.
- **F-2** seal v2 řetězec — ``collect_chain_defects`` nese kompletní seznam
  defektů (BC fail-closed ``verify_chain`` sdílí pravidla a zprávy).
- **F-3** rotace klíčů — atomická transakce (audit + výměna páry + kontrolní
  bod), auditní záznam ``integrity_key_rotated``, fail-closed místo tichého
  ``checkpoint_id=None``.
- **F-4** CLI ``integrity check --json`` a web ``/api/cases/<id>/audit`` —
  exponují typ + všechny defekty (aditivní pole).

Plně offline; ``cryptography`` volitelná (importorskip pattern u F-3/F-4).
"""

from __future__ import annotations

import argparse
import io
import json as _json
from collections.abc import Iterator
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.integrity import (
    CHAIN_GENESIS_MISMATCH,
    CHAIN_HASH_MISMATCH,
    CHAIN_LINK_BROKEN,
    CHAIN_ROW_MISSING,
    GENESIS,
    ChainRow,
    compute_audit_hash,
    verify_chain,
)
from stopa.domain.seal_chain import (
    SEAL_CHAIN_HASH_MISMATCH,
    SEAL_CHAIN_LINK_BROKEN,
    SEAL_CHAIN_SEQ_GAP,
    build_record,
    collect_chain_defects,
)
from stopa.domain.seal_chain import (
    verify_chain as verify_seal_chain,
)
from stopa.models import Artifact, Case, EvidenceSource

try:  # cryptography je volitelná závislost (extra 'fde') — v .venv nainstalovaná
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False


# ── pomůcky ────────────────────────────────────────────────────────────────
def _audit_rows(n: int = 3) -> list[ChainRow]:
    """Validní audit řetězec n řádků (čistá doménová data)."""
    rows: list[ChainRow] = []
    prev = GENESIS
    for i in range(1, n + 1):
        ts = f"2026-11-25T00:00:{i:02d}+00:00"
        h = compute_audit_hash(prev, ts, "op", "actor", "{}")
        rows.append(ChainRow(id=i, ts=ts, action="op", actor="actor", details_json="{}", prev_hash=prev, hash=h))
        prev = h
    return rows


def _consistent_row(i: int, prev: str) -> ChainRow:
    """Řádek interně konzistentní (hash odpovídá polím), ale s libovolným ``prev``.

    Nutné pro izolované LINK/GENESIS defekty bez doprovodného hash mismatchu —
    přepočet hashu bere ``prev_hash`` jako vstup, takže tamper pole = i hash nesejde.
    """
    ts = f"2026-11-25T00:00:{i:02d}+00:00"
    h = compute_audit_hash(prev, ts, "op", "actor", "{}")
    return ChainRow(id=i, ts=ts, action="op", actor="actor", details_json="{}", prev_hash=prev, hash=h)


def _tamper(rows: list[ChainRow], idx: int, **fields: object) -> list[ChainRow]:
    """Kopie řetězce s upraveným polem na pozici ``idx`` (0-based)."""
    out = list(rows)
    r = out[idx]
    kwargs = {f.name: getattr(r, f.name) for f in r.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs.update(fields)
    out[idx] = ChainRow(**kwargs)  # type: ignore[arg-type]
    return out


def _seal_chain(n: int = 3, case_id: str = "case-x") -> list:
    """Validní seal v2 řetězec n pečetí (čistá doménová data)."""
    recs = []
    for i in range(1, n + 1):
        root = f"{i:04x}" * 8
        prev = None if i == 1 else f"{i - 1:04x}" * 8
        recs.append(build_record(i, case_id, f"2026-11-25T00:00:{i:02d}+00:00", root, prev))
    return recs


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[CaseDB]:
    d = CaseDB(tmp_path / "case-x.db")
    yield d
    d.close()


def _seed(db: CaseDB) -> None:
    """Minimum dat pro audit log (případ + zdroj + artifacty + explicitní operace)."""
    db.add_case(Case(id="case-x", name="Test case B9"))
    src = EvidenceSource(case_id="case-x", kind="folder", path="/tmp/x")
    db.add_source(src)
    for i in range(2):
        db.artifact_repo.upsert_artifact(
            Artifact(source_id=src.id, artifact_type="chat_message", title=f"msg-{i}")
        )
    # Explicitní audit řádky (deterministický řetězec pro tamper testy).
    for i in range(4):
        db.log_operation(f"b9_op_{i}", details={"i": i})


def _audit_ids(db: CaseDB) -> list[int]:
    return [r["id"] for r in db.conn.execute("SELECT id FROM audit_log ORDER BY id ASC")]


def _db_link_tamper_last_row(db: CaseDB) -> int:
    """Interně konzistentní tamper ``prev_hash`` posledního řádku → čistý link_broken.

    Hash se přepočítá z nových polí (přepočet bere prev_hash jako vstup), takže
    jediná chyba v řetězci = rozbitá linka na tomto řádku, bez kaskády.
    """
    # Forenzní imutabilita: UPDATE ticho ignorován bez dropu triggeru (BC konvence).
    db.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    row = db.conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    new_prev = "aa" * 32
    new_hash = compute_audit_hash(
        new_prev, row["ts"], row["action"], row["actor"], row["details_json"] or "{}"
    )
    db.conn.execute(
        "UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?",
        (new_prev, new_hash, int(row["id"])),
    )
    db.conn.commit()
    return int(row["id"])


# ── F-1: audit hash řetězec — typy defektů + collect_all ─────────────────
class TestAuditChainDefects:
    def test_clean_chain_ok(self):
        report = verify_chain(_audit_rows(3))
        assert report.ok is True
        assert report.rows_checked == 3
        assert report.broken_at_id is None and report.reason is None
        # B9 — aditivní pole: žádný typ, prázdné defekty
        assert report.kind is None
        assert report.defects == ()

    def test_hash_mismatch_kind_and_bc_fields(self):
        rows = _tamper(_audit_rows(3), 1, hash="ff" * 32)  # řádek 2
        report = verify_chain(rows)
        assert report.ok is False
        assert report.broken_at_id == 2
        assert report.kind == CHAIN_HASH_MISMATCH
        assert "hash řádku 2 neodpovídá přepočtu" in (report.reason or "")
        # B9 — i výchozí režim nese první defekt se strojově čitelným typem
        assert len(report.defects) == 1
        d = report.defects[0]
        assert d.row_id == 2 and d.kind == CHAIN_HASH_MISMATCH and d.message

    def test_link_broken_kind(self):
        # Interně konzistentní řádek s cizím prev → čistý link_broken (bez hash mismatchu)
        rows = _audit_rows(1)[:1] + [_consistent_row(2, "aa" * 32)]
        report = verify_chain(rows)
        assert report.ok is False
        assert report.broken_at_id == 2
        assert report.kind == CHAIN_LINK_BROKEN
        assert "prev_hash řádku 2 nesejde s hash předchozího řádku" in (report.reason or "")

    def test_row_gap_is_own_kind(self):
        # Smazání prostředního řádku → mezera v ID. BC režim ji maskuje LINK_BROKENem;
        # collect_all hlásí obě skutečnosti (rozbitá linka + chybějící záznam).
        rows = _audit_rows(3)[:1] + _audit_rows(3)[2:]  # [1, 3]
        bc = verify_chain(rows)
        assert bc.ok is False and bc.kind == CHAIN_LINK_BROKEN  # BC — jako dříve
        full = verify_chain(rows, collect_all=True)
        kinds = {d.kind for d in full.defects}
        assert CHAIN_ROW_MISSING in kinds and CHAIN_LINK_BROKEN in kinds
        missing = next(d for d in full.defects if d.kind == CHAIN_ROW_MISSING)
        assert "po řádku 1 chybí řádek(y) do id 2" in missing.message

    def test_genesis_mismatch_kind(self):
        # Interně konzistentní první řádek neodkazující na GENESIS (dříve mrtvá větev)
        rows = [_consistent_row(1, "bb" * 32)]
        report = verify_chain(rows)
        assert report.ok is False
        assert report.broken_at_id == 1
        assert report.kind == CHAIN_GENESIS_MISMATCH
        assert "GENESIS" in (report.reason or "")

    def test_collect_all_multiple_defects(self):
        # Tamper uloženého hashu řádku 2: vlastní mismatch + kaskádová linka na řádku 3.
        rows = _tamper(_audit_rows(4), 1, hash="ff" * 32)
        report = verify_chain(rows, collect_all=True)
        assert report.ok is False
        assert report.broken_at_id == 2  # BC — první defekt určuje BC pole
        assert report.kind == CHAIN_HASH_MISMATCH
        assert [(d.row_id, d.kind) for d in report.defects] == [
            (2, CHAIN_HASH_MISMATCH),
            (3, CHAIN_LINK_BROKEN),
        ]

    def test_collect_all_bc_first_fields_identical(self):
        rows = _tamper(_audit_rows(4), 1, hash="ff" * 32)
        bc = verify_chain(rows)  # výchozí (BC režim)
        full = verify_chain(rows, collect_all=True)
        assert (bc.ok, bc.broken_at_id, bc.reason, bc.kind) == (
            full.ok, full.broken_at_id, full.reason, full.kind
        )
        assert len(bc.defects) == 1 and bc.defects[0] == full.defects[0]


# ── F-2: seal v2 řetězec — kompletní seznam defektů ───────────────────────
class TestSealChainDefects:
    def test_clean_chain_ok(self):
        recs = _seal_chain(3)
        assert verify_seal_chain("case-x", recs) == 3
        assert collect_chain_defects("case-x", recs) == []

    def test_tampered_root_localizes_all_defects(self):
        # Tamper rootu pečetě 2: vlastní hash nesejde + linka pečetě 3 se láme
        recs = _seal_chain(3)
        tampered = list(recs)
        r = tampered[1]
        tampered[1] = type(r)(**{**r.__dict__, "merkle_root_hex": "ee" * 16})  # type: ignore[misc]
        defects = collect_chain_defects("case-x", tampered)
        assert [(d.seq, d.kind) for d in defects] == [
            (2, SEAL_CHAIN_HASH_MISMATCH),
            (3, SEAL_CHAIN_LINK_BROKEN),
        ]

    def test_verify_chain_bc_first_message(self):
        recs = _seal_chain(3)
        tampered = list(recs)
        r = tampered[1]
        tampered[1] = type(r)(**{**r.__dict__, "merkle_root_hex": "ee" * 16})  # type: ignore[misc]
        first = collect_chain_defects("case-x", tampered)[0]
        with pytest.raises(ValueError) as exc:
            verify_seal_chain("case-x", tampered)
        assert str(exc.value) == first.message  # BC — identická zpráva jako dříve

    def test_genesis_selfbinding_violation(self):
        # Interně konzistentní záznam s cizím prev → čistý link_broken na seq 1.
        recs = _seal_chain(2)
        bad = build_record(1, "case-x", recs[0].ts_iso, recs[0].merkle_root_hex, "bb" * 16)
        defects = collect_chain_defects("case-x", [bad, recs[1]])
        assert [(d.seq, d.kind) for d in defects] == [(1, SEAL_CHAIN_LINK_BROKEN)]

    def test_seq_gap_kind(self):
        recs = _seal_chain(3)[:1] + _seal_chain(3)[2:]  # [seq1, seq3]
        defects = collect_chain_defects("case-x", recs)
        assert defects and defects[0].kind == SEAL_CHAIN_SEQ_GAP
        assert "pozice 2" in defects[0].message

    def test_case_id_type_error(self):
        with pytest.raises(TypeError):
            collect_chain_defects(42, _seal_chain(1))  # type: ignore[arg-type]


# ── F-3: rotace klíčů — atomarita + audit + fail-closed ───────────────────
@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestKeyRotationAtomicity:
    def test_rotation_returns_new_pair_and_checkpoint(self, db: CaseDB):
        _seed(db)
        _, old_pub = db.ensure_integrity_key()
        assert db.add_integrity_checkpoint("pre-rotation") is not None

        out = db.audit_repo.rotate_integrity_key(reason="test B9")
        assert out is not None
        assert out["old_public_key"] == old_pub
        assert out["public_key_b64"] != old_pub
        assert isinstance(out["checkpoint_id"], int) and out["checkpoint_id"] > 0

        # Nový bod podepsaný NOVÝM klíčem; všechny body (staré + nový) platné.
        results = db.verify_integrity_checkpoints()
        assert len(results) == 2 and all(r["ok"] for r in results)

    def test_rotation_writes_audit_entry_and_chain_stays_valid(self, db: CaseDB):
        _seed(db)
        _, old_pub = db.ensure_integrity_key()
        out = db.audit_repo.rotate_integrity_key(reason="test B9")
        assert out is not None

        latest = db.list_audit_log(limit=1)[0]
        assert latest["action"] == "integrity_key_rotated"
        # list_audit_log vrací parzovaný dict pod klíčem „details".
        details = latest["details"]
        assert details["old_public_key"] == old_pub
        assert details["public_key_b64"] == out["public_key_b64"]

        # Rotace je součást hash řetězce → řetězec zůstává validní.
        assert db.verify_audit_chain().ok is True

    def test_rotation_without_key_returns_none(self, db: CaseDB):
        _seed(db)
        assert db.audit_repo.rotate_integrity_key() is None  # BC — žádná pára ještě neexistuje

    def test_rotation_fail_closed_rolls_back(self, db: CaseDB, monkeypatch: pytest.MonkeyPatch):
        from stopa.data.audit_repository import AuditRepository

        _seed(db)
        _, old_pub = db.ensure_integrity_key()
        # Úvodní checkpoint (aby existoval last audit hash), pak rotaci
        # zmažeme soukromým klíčem → kontrolní bod nevznikne → ValueError.
        assert db.add_integrity_checkpoint("pre") is not None
        monkeypatch.setattr(AuditRepository, "_get_priv_raw", lambda self: None)

        with pytest.raises(ValueError, match="nevznikl rotační kontrolní bod"):
            db.audit_repo.rotate_integrity_key(reason="test B9")

        # Rollback: meta drží STAROU páru a audit log bez rotačního záznamu.
        assert db.integrity_public_key() == old_pub
        actions = [e["action"] for e in db.list_audit_log(limit=100)]
        assert "integrity_key_rotated" not in actions


# ── F-4: CLI integrity check — typ + všechny defekty v JSON i na stderr ───
@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestCliIntegrityDiagnostics:
    @pytest.fixture()
    def broken_db(self, tmp_path: Path) -> Iterator[CaseDB]:
        """Případ se dvěma nezávislými link_broken tamperacemi (řádky 2 a 4)."""
        monkey = pytest.MonkeyPatch()
        monkey.setenv("STOPA_DB_DIR", str(tmp_path))
        d = CaseDB(tmp_path / "case-x.db")
        _seed(d)
        ids = [r["id"] for r in d.conn.execute("SELECT id FROM audit_log ORDER BY id ASC")]
        assert len(ids) >= 4, f"očekáván minimálně 4 audit řádky (fakt {len(ids)})"
        # Tamper uloženého hashu řádku 2 → vlastní hash_mismatch + kaskádová
        # link_broken na řádku 3 (přepočet bere prev_hash jako vstup; čistý link
        # tamper by dal na stejný řádek druhý defekt navíc).
        # Forenzní imutabilita: UPDATE ticho ignorován bez dropu triggeru (BC konvence).
        d.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        d.conn.execute("UPDATE audit_log SET hash = ? WHERE id = ?", ("ff" * 32, ids[1]))
        d.conn.commit()
        yield d
        d.close()
        monkey.undo()

    def test_json_payload_exposes_kind_and_all_defects(self, broken_db: CaseDB):
        from stopa.cli import cmd_integrity

        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            rc = cmd_integrity(
                argparse.Namespace(case_id="case-x", json=True, init_key=False, checkpoint=None)
            )
        assert rc == 1  # rozbitý řetězec → exit code 1 (BC)
        out = _json.loads(buf.getvalue())
        ids = _audit_ids(broken_db)
        assert out["audit_chain_ok"] is False
        assert out["kind"] == CHAIN_HASH_MISMATCH  # B9 — typ prvního defektu
        assert [(d["row_id"], d["kind"]) for d in out["defects"]] == [
            (ids[1], CHAIN_HASH_MISMATCH),
            (ids[2], CHAIN_LINK_BROKEN),
        ]

    def test_human_mode_lists_all_defects_on_stderr(self, broken_db: CaseDB):
        from stopa.cli import cmd_integrity

        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cmd_integrity(
                argparse.Namespace(case_id="case-x", json=False, init_key=False, checkpoint=None)
            )
        assert rc == 1
        ids = _audit_ids(broken_db)
        lines = err.getvalue().splitlines()
        first = next(l for l in lines if "ROZBITÝ" in l)
        assert f"řádku {ids[1]}" in first
        # B9 — další defekt explicitně vyjmenován (dříve ztracený)
        extra = [l for l in lines if "+ defekt" in l]
        assert len(extra) == 1 and "[link_broken]" in extra[0] and f"řádek {ids[2]}" in extra[0]


# ── F-4: web /api/cases/<id>/audit — typ + všechny defekty (aditivní) ─────
@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestWebAuditDiagnostics:
    def test_audit_endpoint_exposes_kind_and_defects(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        d = CaseDB(tmp_path / "case-x.db")
        _seed(d)
        last_id = _db_link_tamper_last_row(d)  # interně konzistentní tamper → čistý link_broken
        d.close()

        app = create_app(db_dir=tmp_path)
        with TestClient(app) as c:
            rep = c.get("/api/cases/case-x/audit")
        assert rep.status_code == 200
        chain = rep.json()["chain"]
        # BC pole zůstávají; B9 přidává typ + kompletní seznam defektů.
        assert chain["ok"] is False and chain["broken_at_id"] == last_id
        assert "reason" in chain
        assert chain["kind"] == CHAIN_LINK_BROKEN
        assert [x["row_id"] for x in chain["defects"]] == [last_id]
