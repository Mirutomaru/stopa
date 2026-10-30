"""Testy full-text search (FTS5) — FÁZE 3."""

from __future__ import annotations

from pathlib import Path

import pytest

from stopa.data.db import CaseDB, _fts_query
from stopa.models import Case, EvidenceSource, FileRecord
from stopa.pipeline import process_source


@pytest.fixture()
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "case.db")
    db.add_case(Case(id="case-test", name="Test case"))
    return db


CASE_ID = "case-test"


def _add_source(db: CaseDB, root: Path) -> EvidenceSource:
    src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(root))
    db.add_source(src)
    return src


class TestFtsQueryNormalization:
    def test_plain_words_quoted(self):
        assert _fts_query("report pdf") == '"report" "pdf"'

    def test_single_word(self):
        assert _fts_query("jpg") == '"jpg"'

    def test_dots_stay_in_phrase(self):
        # tečka je pro FTS5 token separator — fráze zachová sousedství tokenů
        assert _fts_query("report.pdf") == '"report.pdf"'

    def test_operators_passthrough(self):
        assert _fts_query('png OR pdf') == "png OR pdf"
        assert _fts_query("fake*") == "fake*"


class TestSearch:
    @pytest.fixture(autouse=True)
    def _processed(self, case_db: CaseDB, evidence_tree: Path):
        src = _add_source(case_db, evidence_tree)
        process_source(case_db, src.id, evidence_tree, "forensic")
        self.db = case_db

    def test_search_by_name_token(self):
        hits = self.db.search("report")
        assert [r.rel_path for r in hits] == ["docs/report.pdf"]

    def test_search_by_signature_type(self):
        # 'pdf' sekyne přes signature_type i name — report.pdf jednou (JOIN dedupe)
        hits = self.db.search("pdf")
        paths = {r.rel_path for r in hits}
        assert "docs/report.pdf" in paths

    def test_search_or_operator(self):
        hits = self.db.search("png OR pdf")
        paths = {r.rel_path for r in hits}
        assert {"photo.png", "docs/report.pdf"} <= paths

    def test_prefix_query(self):
        # raw FTS5 syntaxe — prefix na token 'fake'
        hits = self.db.search("fake*")
        assert [r.rel_path for r in hits] == ["fake.jpg"]

    def test_phrase_with_dot(self):
        hits = self.db.search('"report.pdf"')
        assert [r.rel_path for r in hits] == ["docs/report.pdf"]

    def test_no_match_returns_empty(self):
        assert self.db.search("neexistujici") == []

    def test_empty_query_returns_empty(self):
        assert self.db.search("   ") == []

    def test_limit_respected(self):
        # 'bin' sekyne dup_a.bin + media/dup_b.bin — limit 1 → jen první
        hits = self.db.search("bin", limit=1)
        assert len(hits) == 1


class TestFtsBackfill:
    """Staré case DB (bez FTS indexu) se při reopen doindexují."""

    def test_rebuild_on_open(self, tmp_path: Path):
        path = tmp_path / "old.db"
        db = CaseDB(path)
        db.add_case(Case(id="case-old", name="Old case"))
        src = EvidenceSource(case_id="case-old", kind="folder", path="/x")
        db.add_source(src)
        rec = FileRecord(
            source_id=src.id,
            rel_path="docs/starosta.docx",
            name="starosta.docx",
            size_bytes=10,
        )
        db.upsert_file(rec)
        db.commit()

        # simulace starého DB: FTS index prázdný (triggery tehdy neexistovaly)
        # external-content FTS5 se čistí jen přes speciální 'delete' příkaz
        row = db.conn.execute(
            "SELECT rowid, rel_path, name, signature_type, hash_set_hit FROM files"
        ).fetchone()
        db.conn.execute(
            "INSERT INTO files_fts(files_fts, rowid, rel_path, name,"
            " signature_type, hash_set_hit) VALUES ('delete', ?, ?, ?, ?, ?)",
            (row["rowid"], row["rel_path"], row["name"], row["signature_type"], row["hash_set_hit"]),
        )
        db.conn.commit()
        # COUNT v external-content tabulce je nespolehlivý (stíny) — ověřit přes MATCH
        assert db.conn.execute(
            "SELECT rowid FROM files_fts WHERE files_fts MATCH ?", ('"starosta"',)
        ).fetchall() == []
        # staré DB nemělo ani meta-flagu → smaž, ať reopen spustí backfill
        db.conn.execute("DELETE FROM meta WHERE key = 'fts_backfilled'")
        db.conn.commit()
        db.close()

        # reopen → backfill 'rebuild'
        db2 = CaseDB(path)
        hits = db2.search("starosta")
        assert [r.rel_path for r in hits] == ["docs/starosta.docx"]
        db2.close()


class TestFtsSync:
    """Triggery drží FTS index v sync s tabulkou files."""

    def test_update_syncs(self, tmp_path: Path):
        path = tmp_path / "sync.db"
        db = CaseDB(path)
        db.add_case(Case(id="case-sync", name="Sync"))
        src = EvidenceSource(case_id="case-sync", kind="folder", path="/x")
        db.add_source(src)

        rec = FileRecord(source_id=src.id, rel_path="a/one.txt", name="one.txt", size_bytes=1)
        db.upsert_file(rec)
        assert len(db.search("one")) == 1

        # upsert se stejným (source_id, rel_path) → UPDATE branch → trigger files_au
        rec2 = FileRecord(
            source_id=src.id, rel_path="a/one.txt", name="one-renamed.txt", size_bytes=2
        )
        db.upsert_file(rec2)
        assert len(db.search("one")) == 1  # stále najde (token 'one' v novém jméně)
        assert len(db.search("renamed")) == 1  # nové slovo je indexované
        db.close()
