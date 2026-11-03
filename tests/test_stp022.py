"""STP-022 — Security: SHA-512 integrity vrstva + RBAC minimální (actor povinný).

Pokrývá:
- SHA-512 v audit chain (compute_audit_hash / verify_chain, per-algorithm GENESIS)
- SHA-512 v exportních manifestech (opt-in, backward compat hash)
- RBAC minimální: normalize_actor / require_actor / resolve_actor + log_operation fallback
- Pipeline SHA-512 (forensic profil počítá, ediscovery/quick ne)
- DB migrace files.sha512 + upsert_file + search_by_hash
- Report CoC manifest — SHA-512 sloupec (jen když existuje)

Plně offline (tmp_path case DB), bez TSK/EWF.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.integrity import (
    GENESIS,
    ChainRow,
    build_manifest,
    compute_audit_hash,
    manifest_hash,
    verify_chain,
)
from stopa.domain.rbac import ActorError, normalize_actor, require_actor, resolve_actor

# ── fixtures ────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── SHA-512 audit chain ─────────────────────────────────────────

class TestSha512AuditChain:
    def test_compute_sha512_length(self):
        h = compute_audit_hash(GENESIS, "t", "case_created", "A", "{}", algo="sha512")
        assert len(h) == 128  # SHA-512 hexdigest
        assert h != hashlib.sha256(b"").hexdigest()

    def test_compute_sha256_default_backward_compat(self):
        # výchozí (bez algo) = SHA-256, 64 znaků — původní chování
        h = compute_audit_hash(GENESIS, "t", "case_created", "A", "{}")
        assert len(h) == 64

    def test_sha512_genesis(self):
        from stopa.domain.integrity import _genesis

        assert _genesis("sha512") == "0" * 128
        assert _genesis("sha256") == GENESIS

    def test_unknown_algo_raises(self):
        with pytest.raises(ValueError, match="Neznámý hash algoritmus"):
            compute_audit_hash(GENESIS, "t", "a", None, "{}", algo="md5")

    def test_verify_chain_sha512_ok(self):
        g = "0" * 128
        ts1, ts2 = "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"
        h1 = compute_audit_hash(g, ts1, "case_created", "A", "{}", algo="sha512")
        row1 = ChainRow(id=1, ts=ts1, action="case_created", actor="A", details_json="{}", prev_hash=g, hash=h1)
        h2 = compute_audit_hash(h1, ts2, "source_added", None, "{}", algo="sha512")
        row2 = ChainRow(id=2, ts=ts2, action="source_added", actor=None, details_json="{}", prev_hash=h1, hash=h2)
        rep = verify_chain([row1, row2], algo="sha512")
        assert rep.ok is True
        assert rep.rows_checked == 2

    def test_verify_chain_sha512_cross_algo_broken(self):
        # SHA-512 řetězec ověřený jako SHA-256 → rozbitý (jiná délka hashů)
        g = "0" * 128
        ts = "2026-01-01T00:00:00+00:00"
        h1 = compute_audit_hash(g, ts, "case_created", "A", "{}", algo="sha512")
        row1 = ChainRow(id=1, ts=ts, action="case_created", actor="A", details_json="{}", prev_hash=g, hash=h1)
        rep = verify_chain([row1], algo="sha256")  # špatný algoritmus
        assert rep.ok is False

    def test_verify_chain_sha512_tampered(self):
        g = "0" * 128
        ts = "2026-01-01T00:00:00+00:00"
        h1 = compute_audit_hash(g, ts, "case_created", "A", "{}", algo="sha512")
        # tamper: změna detailů → přepočtený hash se neshoduje
        row_tampered = ChainRow(
            id=1, ts=ts, action="case_created", actor="A", details_json='{"x": 9}', prev_hash=g, hash=h1
        )
        rep = verify_chain([row_tampered], algo="sha512")
        assert rep.ok is False
        assert rep.broken_at_id == 1


# ── SHA-512 manifesty (opt-in) ──────────────────────────────────

class TestSha512Manifest:
    def test_build_manifest_default_no_sha512(self):
        m = build_manifest("case-1", "0.1.0", [("a.txt", b"hello")])
        assert m.entries[0].sha512 is None  # backward compat — default bez SHA-512

    def test_build_manifest_with_sha512(self):
        content = b"forensic evidence"
        expected = hashlib.sha512(content).hexdigest()
        m = build_manifest("case-1", "0.1.0", [("a.txt", content)], include_sha512=True)
        assert m.entries[0].sha512 == expected
        assert len(m.entries[0].sha512) == 128

    def test_manifest_hash_differs_with_sha512(self):
        files = [("a.txt", b"data")]
        h_plain = manifest_hash(build_manifest("c", "v", files))
        h_512 = manifest_hash(build_manifest("c", "v", files, include_sha512=True))
        assert h_plain != h_512  # SHA-512 entry se počítá do kanonického payloadu

    def test_manifest_hash_backward_compat(self):
        # default (bez sha512) → stejný hash jako kdybychom stavěli bez parametru
        files = [("a.txt", b"x"), ("b.txt", b"y")]
        h1 = manifest_hash(build_manifest("c", "v", files))
        h2 = manifest_hash(build_manifest("c", "v", files, include_sha512=False))
        assert h1 == h2


# ── RBAC minimální (čistá logika) ───────────────────────────────

class TestRbacLogic:
    def test_normalize_actor_strip(self):
        assert normalize_actor("  Miroslav Matúš  ") == "Miroslav Matúš"
        assert normalize_actor("a   b") == "a b"  # kolaps vnitřních mezer

    def test_normalize_actor_empty_to_none(self):
        assert normalize_actor(None) is None
        assert normalize_actor("") is None
        assert normalize_actor("   ") is None

    def test_require_actor_ok(self):
        assert require_actor("JUDr. M.") == "JUDr. M."

    def test_require_actor_empty_raises(self):
        with pytest.raises(ActorError, match="Actor je povinný"):
            require_actor(None)

    def test_require_actor_context_in_message(self):
        with pytest.raises(ActorError, match="report_generated"):
            require_actor("  ", context="report_generated")

    def test_resolve_actor_explicit_wins(self):
        assert resolve_actor("explicit", "examiner") == "explicit"

    def test_resolve_actor_fallback_examiner(self):
        assert resolve_actor(None, "JUDr. M.") == "JUDr. M."
        assert resolve_actor("", "JUDr. M.") == "JUDr. M."  # prázdný explicit → fallback

    def test_resolve_actor_both_none(self):
        assert resolve_actor(None, None) is None


# ── RBAC v log_operation (fallback + strict) ────────────────────

class TestLogOperationRbac:
    def _case_with_examiner(self, d: CaseDB, examiner: str | None = "JUDr. M.") -> str:
        from stopa.models import Case

        c = Case(name="T", examiner=examiner)
        d.add_case(c)
        return c.id

    def test_fallback_to_examiner(self, db: CaseDB):
        self._case_with_examiner(db, "JUDr. M.")
        # bez explicitního actora → atribuce na examinera (backward compat)
        db.log_operation("source_added")
        entries = db.list_audit_log()
        added = next(e for e in entries if e["action"] == "source_added")
        assert added["actor"] == "JUDr. M."

    def test_explicit_actor_wins(self, db: CaseDB):
        self._case_with_examiner(db, "JUDr. M.")
        db.log_operation("report_generated", actor="A. B.")
        entries = db.list_audit_log()
        added = next(e for e in entries if e["action"] == "report_generated")
        assert added["actor"] == "A. B."

    def test_strict_without_examiner_raises(self, db: CaseDB):
        self._case_with_examiner(db, examiner=None)  # case bez examinera
        with pytest.raises(ActorError, match="Actor je povinný"):
            db.log_operation("source_added", strict=True)

    def test_strict_with_explicit_ok(self, db: CaseDB):
        self._case_with_examiner(db, examiner=None)
        row_id = db.log_operation("source_added", actor="A. B.", strict=True)
        assert isinstance(row_id, int) and row_id > 0

    def test_default_not_strict_allows_none(self, db: CaseDB):
        self._case_with_examiner(db, examiner=None)
        # default strict=False → bez actora i examinera = None (původní chování)
        row_id = db.log_operation("source_added")
        assert isinstance(row_id, int) and row_id > 0
        entries = db.list_audit_log()
        added = next(e for e in entries if e["action"] == "source_added")
        assert added["actor"] is None


# ── Pipeline SHA-512 (forensic vs. ostatní profily) ─────────────

class TestPipelineSha512:
    def _worker(self, tmp_path: Path, profile):
        from stopa.data.ingest import WalkedFile
        from stopa.pipeline import _process_file_worker

        p = tmp_path / "evidence.bin"
        content = b"\x00\x01\x02forensic payload" * 64
        p.write_bytes(content)
        wf = WalkedFile(rel_path="evidence.bin", name="evidence.bin", size_bytes=len(content))
        return _process_file_worker(wf, p, "src-1", profile, {})

    def test_forensic_computes_sha512(self, tmp_path: Path):
        from stopa.domain.profiles import FORENSIC

        work = self._worker(tmp_path, FORENSIC)
        assert work.rec.sha512 is not None
        assert len(work.rec.sha512) == 128
        # kontrola proti hashlib (ground truth)
        expected = hashlib.sha512(b"\x00\x01\x02forensic payload" * 64).hexdigest()
        assert work.rec.sha512 == expected

    def test_ediscovery_no_sha512(self, tmp_path: Path):
        from stopa.domain.profiles import EDISCOVERY

        work = self._worker(tmp_path, EDISCOVERY)
        assert work.rec.sha512 is None  # ediscovery = MD5 jen pro deduplikaci

    def test_quick_no_sha512(self, tmp_path: Path):
        from stopa.domain.profiles import QUICK

        work = self._worker(tmp_path, QUICK)
        assert work.rec.sha512 is None  # quick = SHA-256 jen


# ── DB migrace + upsert + search_by_hash (SHA-512) ──────────────

class TestDbSha512:
    def test_migration_adds_sha512_column(self, tmp_path: Path):
        # simulace staré case DB bez sloupce sha512 → migrace ho doplní
        d = CaseDB(tmp_path / "case.db")
        d.conn.execute("ALTER TABLE files DROP COLUMN sha512")  # SQLite ≥3.35
        d.conn.commit()
        cols_before = {r["name"] for r in d.conn.execute("PRAGMA table_info(files)").fetchall()}
        assert "sha512" not in cols_before
        d.close()

        d2 = CaseDB(tmp_path / "case.db")  # reopen → migrace
        cols_after = {r["name"] for r in d2.conn.execute("PRAGMA table_info(files)").fetchall()}
        assert "sha512" in cols_after
        d2.close()

    def test_upsert_file_stores_sha512(self, db: CaseDB):
        from stopa.models import Case, EvidenceSource, FileRecord

        c = Case(name="T", examiner="JUDr. M.")
        db.add_case(c)
        src = EvidenceSource(case_id=c.id, kind="folder", path="/evid")
        db.add_source(src)
        rec = FileRecord(
            source_id=src.id,
            rel_path="a.txt",
            name="a.txt",
            size_bytes=5,
            sha256="ab" * 32,
            md5=None,
            sha512="cd" * 64,
        )
        db.upsert_file(rec)
        row = db.conn.execute("SELECT sha512 FROM files WHERE rel_path='a.txt'").fetchone()
        assert row["sha512"] == "cd" * 64

    def test_search_by_hash_sha512(self, db: CaseDB):
        from stopa.models import Case, EvidenceSource, FileRecord

        c = Case(name="T", examiner="JUDr. M.")
        db.add_case(c)
        src = EvidenceSource(case_id=c.id, kind="folder", path="/evid")
        db.add_source(src)
        sha512_val = "ef" * 64
        rec = FileRecord(
            source_id=src.id, rel_path="b.txt", name="b.txt", size_bytes=3, sha512=sha512_val
        )
        db.upsert_file(rec)
        hits = db.search_by_hash(sha512_val)
        assert len(hits) == 1
        assert hits[0].rel_path == "b.txt"


# ── Report CoC manifest — SHA-512 sloupec ───────────────────────

class TestReportSha512:
    def _data(self, with_sha512: bool):
        from stopa.domain.report import CustodyItem, ReportData, SourceInfo

        sha512 = "ab" * 64 if with_sha512 else None
        return ReportData(
            case_id="case-1",
            case_name="Test",
            examiner="JUDr. M.",
            created_at=_now(),
            sources=(SourceInfo(id="s1", kind="folder", path="/evid", added_at=_now()),),
            custody_items=(
                CustodyItem(
                    source_id="s1", rel_path="a.txt", size_bytes=10, sha256="cd" * 32, md5=None, sha512=sha512
                ),
            ),
        )

    def test_report_with_sha512_column(self):
        from stopa.domain.report import build_html

        html = build_html(self._data(with_sha512=True))
        assert "SHA-512" in html  # hlavička sloupce
        assert ("ab" * 64) in html  # hodnota SHA-512 v manifestu

    def test_report_without_sha512_no_column(self):
        from stopa.domain.report import build_html

        html = build_html(self._data(with_sha512=False))
        assert "SHA-512" not in html  # sloupec se nevykreslí, když SHA-512 není
