"""F5.1 — Merkle Tree Case Sealing (Compliance & Court-Readiness).

Testy: čistá doménová logika (kanonizace řádků, deterministický root,
cross-table tag, 1-bit flip) + DB integrace (seal/verify cyklus, detekce
tamperingu per tabulka, snapshot s předponou — append pečeť neruší, Ed25519
podpis s uloženým veřejným klíčem, graceful degradation bez cryptography).
Plně offline.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.case_seal import (
    DOMAIN_TAG,
    EMPTY_ROOT,
    SEAL_FORMAT_VERSION,
    build_merkle_root,
    canonical_row_payload,
    leaf_hash,
    root_hex,
)
from stopa.models import Artifact, Case, EvidenceSource

try:  # cryptography je volitelná závislost (extra 'fde') — v .venv nainstalovaná
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[CaseDB]:
    # jméno souboru == case id (konvence _open_db) → facade/repo resolvuje examinera ze stemu
    d = CaseDB(tmp_path / "case-x.db")
    yield d
    d.close()


def _seed(db: CaseDB, n_art: int = 2, n_ev: int = 2, examiner: str | None = None) -> str:
    """Data pro pečet': případ + zdroj + artifacty + timeline události.

    Vrací source_id. ``examiner`` — pro test actor fallbacku (None → sealed_by NULL).
    """
    db.add_case(Case(id="case-x", name="Test case F5.1", examiner=examiner))
    src = EvidenceSource(case_id="case-x", kind="folder", path="/tmp/x")
    db.add_source(src)
    for i in range(n_art):
        db.artifact_repo.upsert_artifact(
            Artifact(
                source_id=src.id,
                artifact_type="chat_message",
                rel_path=f"chat/{i}.msg",  # unikátní → upsert nededuplikuje
                title=f"msg-{i}",
                details={"body": f"text {i}"},
            )
        )
    for i in range(n_ev):
        db.artifact_repo.add_timeline_event(
            source_id=src.id,
            ts_utc=dt.datetime(2026, 1, i + 1, tzinfo=dt.timezone.utc),
            event_type="chat_message",
            title=f"ev-{i}",
        )
    db.conn.commit()
    # audit řádky PŘED pečetí (add_case/add_source/upsert nelogují) — tampering testy
    db.log_operation("session_start")
    db.log_operation("ingest_done", details={"files": n_art})
    return src.id


# ── čistá doménová logika: kanonizace + Merkle strom ────────────────────────

class TestMerkleDomain:
    def test_root_deterministic(self):
        """Stejný stav → stejný root; pořadí leafů je významné."""
        leaves = [leaf_hash("artifacts", ("a", i, None)) for i in range(3)]
        r1 = root_hex(build_merkle_root(leaves))
        assert root_hex(build_merkle_root(list(leaves))) == r1  # determinismus
        r2 = root_hex(build_merkle_root(list(reversed(leaves))))
        assert r2 != r1  # globální kanonické pořadí (artifacts → timeline → audit)

    def test_single_leaf_is_identity(self):
        """Jeden řádek → root = leaf digest (bez zbytečného levelu)."""
        leaf = leaf_hash("artifacts", ("a",))
        assert build_merkle_root([leaf]) == leaf

    def test_empty_root_deterministic_constant(self):
        """Prázdný případ je zamknutelný — root prázdné množiny je konstanta."""
        r = build_merkle_root([])
        assert r == EMPTY_ROOT and len(r) == 32
        assert build_merkle_root([]) == r

    def test_one_bit_flip_changes_root(self):
        """Akceptanční kritérium: změna i 1 bitu v zamčeném řádku → jiný root."""
        rows = [("a", str(i), None) for i in range(8)]
        base = build_merkle_root([leaf_hash("artifacts", r) for r in rows])
        tampered = [r if i != 3 else ("a", "2", None) for i, r in enumerate(rows)]  # '3'→'2' (1 bit)
        assert build_merkle_root([leaf_hash("artifacts", r) for r in tampered]) != base

    def test_cross_table_tag(self):
        """Totéž datum v jiné tabulce ≠ stejný leaf (domain tag + jméno tabulky)."""
        a = leaf_hash("artifacts", ("x", 1))
        b = leaf_hash("timeline_events", ("x", 1))
        assert a != b

    def test_payload_contains_tag_and_table(self):
        payload = canonical_row_payload("audit_log", ("y", None, 3.5))
        assert DOMAIN_TAG in payload
        assert b"audit_log" in payload

    def test_canonical_json_key_order_independent(self):
        """Klíče dictů se řadí (sort_keys) → pořadí v Pythonu není významné."""
        p1 = canonical_row_payload("artifacts", ({"b": 1, "a": 2},))
        p2 = canonical_row_payload("artifacts", ({"a": 2, "b": 1},))
        assert p1 == p2

    def test_canonical_unicode_utf8(self):
        """ensure_ascii=False → české znaky jako UTF-8 bajty (deterministicky)."""
        payload = canonical_row_payload("artifacts", ("žluťoučký",))
        assert "žluťoučký".encode() in payload

    def test_root_hex_format(self):
        r = root_hex(build_merkle_root([leaf_hash("artifacts", (i,)) for i in range(5)]))
        assert len(r) == 64 and all(c in "0123456789abcdef" for c in r)

    def test_format_version_constant(self):
        """Pečetě nesou verzi formátu — soudní report musí znát interpretaci."""
        assert SEAL_FORMAT_VERSION >= 1


# ── DB integrace: seal / verify cyklus ───────────────────────────────────────

@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestSealIntegration:
    def test_seal_and_verify_ok(self, db: CaseDB):
        _seed(db)
        seal = db.seal_case(reason="test", actor="znalec@x.cz")
        assert seal is not None and seal["id"] == 1
        assert len(seal["root_hash"]) == 64
        assert seal["sealed_by"] == "znalec@x.cz"
        reports = db.seal_repo.verify_all()
        assert len(reports) == 1
        r = reports[0]
        assert r["ok"] and r["root_ok"] and r["sig_ok"]
        assert not r["changed_tables"]

    def test_tamper_artifact_detected(self, db: CaseDB):
        _seed(db)
        db.seal_case()
        db.conn.execute("UPDATE artifacts SET title = 'POPRAVENO' WHERE rowid = 1")
        db.conn.commit()
        r = db.seal_repo.verify_all()[0]
        assert not r["ok"] and not r["root_ok"]
        assert r["changed_tables"] == ["artifacts"]

    def test_tamper_timeline_detected(self, db: CaseDB):
        _seed(db)
        db.seal_case()
        db.conn.execute("UPDATE timeline_events SET title = 'X' WHERE rowid = 1")
        db.conn.commit()
        r = db.seal_repo.verify_all()[0]
        assert not r["ok"] and r["changed_tables"] == ["timeline_events"]

    def test_tamper_audit_detected(self, db: CaseDB):
        _seed(db)
        db.seal_case()
        # audit_log má append-only triggery — ruční tampering je zruší (jako v C4 testech)
        db.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        db.conn.execute("UPDATE audit_log SET action = 'tampered' WHERE id = 1")
        db.conn.commit()
        r = db.seal_repo.verify_all()[0]
        assert not r["ok"] and r["changed_tables"] == ["audit_log"]

    def test_append_does_not_break_seal(self, db: CaseDB):
        """Snapshot s předponou: nové řádky po pečetí ji neruší (audit roste dál)."""
        _seed(db)
        seal = db.seal_case()
        assert seal is not None
        # nová data PO pečetí: artifact + timeline event + audit záznam
        src_id = db.conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
        db.artifact_repo.upsert_artifact(
            Artifact(source_id=src_id, artifact_type="chat_message",
                     rel_path="chat/99.msg", title="novy")
        )
        db.artifact_repo.add_timeline_event(
            source_id=src_id, ts_utc=dt.datetime(2026, 1, 31, tzinfo=dt.timezone.utc),
            event_type="chat_message", title="ev-99",
        )
        db.conn.commit()
        db.log_operation("post_seal_action")
        r = db.seal_repo.verify_all()[0]
        assert r["ok"], f"append po pečetí nesmí rušit: {r}"

    def test_delete_row_detected(self, db: CaseDB):
        _seed(db)
        db.seal_case()
        db.conn.execute("DELETE FROM artifacts WHERE rowid = 1")
        db.conn.commit()
        r = db.seal_repo.verify_all()[0]
        assert not r["ok"] and "artifacts" in r["changed_tables"]

    def test_signature_uses_stored_public_key(self, db: CaseDB):
        """Podpis se ověřuje veřejným klíčem ULOŽENÝM V PEČETI (nezávislost)."""
        _seed(db)
        db.seal_case()
        bogus = base64.b64encode(b"\x00" * 64).decode("ascii")
        db.conn.execute("UPDATE case_seals SET signature_b64 = ? WHERE id = 1", (bogus,))
        db.conn.commit()
        r = db.seal_repo.verify_all()[0]
        assert not r["ok"] and r["root_ok"] and not r["sig_ok"]

    def test_multiple_seals_history(self, db: CaseDB):
        """Druhá pečeť po změně dat — prefix semantika (stará i nová platné)."""
        _seed(db)
        s1 = db.seal_case()
        assert s1 is not None
        src_id = db.conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
        db.artifact_repo.upsert_artifact(
            Artifact(source_id=src_id, artifact_type="chat_message",
                     rel_path="chat/77.msg", title="mezitimovy")
        )
        s2 = db.seal_case()
        assert s2 is not None and s1["root_hash"] != s2["root_hash"]  # jiný stav → jiný root
        reports = {r["id"]: r for r in db.seal_repo.verify_all()}
        assert len(reports) == 2
        # stará pečeť fixuje prefix: novy artifact (přidaný později) ji neruší…
        assert reports[s1["id"]]["ok"], "prefix semantika — append nezkazí starou pečeť"
        assert reports[s2["id"]]["ok"]

    def test_no_key_graceful_degradation(self, db: CaseDB):
        """Bez cryptography (RuntimeError z ensure) → None, žádná výjimka."""
        _seed(db)
        def _raise(*_a, **_k):
            raise RuntimeError("cryptography není nainstalována")
        db.audit_repo.ensure_integrity_key = _raise  # type: ignore[method-assign]
        assert db.seal_case() is None

    def test_actor_resolution(self, tmp_path: Path):
        """Actor priority: explicitní > case examiner > None (NULL v DB).

        Facade řeší examinera z názvu souboru DB (stem == case_id — konvence
        ``_open_db``), proto každé DB má vlastní podadresář se stejným stemem.
        """
        (tmp_path / "a").mkdir(exist_ok=True)
        d1 = CaseDB(tmp_path / "a" / "case-x.db")
        _seed(d1)  # examiner=None → nikdo nevyřešen → NULL
        s1 = d1.seal_case()
        assert s1 is not None and s1["sealed_by"] is None
        d1.close()

        (tmp_path / "b").mkdir(exist_ok=True)
        d2 = CaseDB(tmp_path / "b" / "case-x.db")
        _seed(d2, examiner="znalec@x.cz")
        s2 = d2.seal_case()
        assert s2 is not None and s2["sealed_by"] == "znalec@x.cz"  # fallback na examinera

        (tmp_path / "c").mkdir(exist_ok=True)
        d3 = CaseDB(tmp_path / "c" / "case-x.db")
        _seed(d3, examiner="znalec@x.cz")
        s3 = d3.seal_case(actor="system")
        assert s3 is not None and s3["sealed_by"] == "system"  # explicitní vítězí
        for d in (d2, d3):
            d.close()

    def test_repo_without_key_raises(self, tmp_path: Path):
        """Přímé použití repozitáře bez klíče → explicitní KeyError (ne silent)."""
        from stopa.data.seal_repository import SealRepository

        d = CaseDB(tmp_path / "c.db")
        with pytest.raises(KeyError):
            SealRepository(d.conn).seal_case()
        d.close()


# ── CLI: stopa seal + rozšířené stopa verify ────────────────────────────────

@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestSealCli:
    def test_cli_seal_and_verify(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_seal, cmd_verify

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-x.db")
        _seed(db)
        db.close()

        rc = cmd_seal(argparse.Namespace(case_id="case-x", reason="před soudem"))
        assert rc == 0

        # verify bez tamperingu → 0 + Merkle sekce v JSON výstupu
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_verify(argparse.Namespace(case_id="case-x", limit=20, json=True))
        assert rc == 0
        out = buf.getvalue()
        assert '"merkle_seal"' in out and '"valid": 1' in out

    def test_cli_verify_fails_on_tamper(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_seal, cmd_verify

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-x.db")
        _seed(db)
        db.close()
        assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None)) == 0

        # tampering zamčeného artifactu → verify exit 1
        d2 = CaseDB(tmp_path / "case-x.db")
        d2.conn.execute("UPDATE artifacts SET title = 'X' WHERE rowid = 1")
        d2.conn.commit()
        d2.close()
        assert cmd_verify(argparse.Namespace(case_id="case-x", limit=20, json=False)) == 1
