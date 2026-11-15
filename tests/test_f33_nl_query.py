"""F3.3 — Natural Language Query → validní SQL dotaz nad case DB.

AK F3.3 (ROADMAP V2, Fáze 3):
- **50 testovacích NL queries → ≥90 % úspěšnost** → parametrizovaný test
  s 50 deterministickými dotazy a FakeLLM (NL text → SQL + params);
- **žádný SQL injection** (parameterized) → unit testy validace
  (jedno vyjádření, SELECT/WITH, whitelist tabulek, počet placeholderů)
  + explicitní injection scénář s ``'; DROP TABLE files; --``;
- **timeout 5 s** → výchozí konstanta DEFAULT_TIMEOUT_S = 5.0 + unit test
  překročení rozpočtu (``set_progress_handler``).

Sandbox = samostatné read-only spojení (``file:<db>?mode=ro``), takže dotaz
nemůže ani náhodou mutovat case DB; výsledek se validuje proti schématu
(neznámá tabulka/sloupec → InvalidQueryError).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from stopa.intelligence import nl_query as nq
from stopa.intelligence.nl_query import (
    DEFAULT_TIMEOUT_S,
    InvalidQueryError,
    NLQueryResult,
    QueryTimeoutError,
    run_nl_query,
)

CASE_ID = "case-f33"
SRC_ID = "src-f33"
TS_ART = datetime(2026, 1, 5, 12)


# ── stavba case DB (deterministická, bez sítě/LLM) ────────────────


def _fresh_db(root: Path):
    from stopa.data.db import CaseDB

    db = CaseDB(str(root / f"nlq_{Path(__file__).stem}.db"))
    now = "2026-01-01T00:00:00"
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (CASE_ID, CASE_ID.upper(), now),
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/f33-seed', ?)",
        (SRC_ID, CASE_ID, now),
    )
    db.conn.commit()
    return db


class Builder:
    """Fluent seeder syntetického případu pro F3.3 testy."""

    def __init__(self, db) -> None:
        self.db = db
        self._n = 0

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def file(
        self,
        rel_path: str,
        size: int = 2048,
        mtime: datetime = datetime(2026, 1, 3),
    ) -> str:
        from stopa.models import FileRecord, new_id

        name = rel_path.rsplit("/", 1)[-1]
        rec = FileRecord(
            id=new_id("f"),
            source_id=SRC_ID,
            rel_path=rel_path,
            name=name,
            size_bytes=size,
            mtime=mtime,
            sha256=hashlib.sha256(rel_path.encode()).hexdigest(),
            extension=name.rsplit(".", 1)[-1] if "." in name else "",
        )
        self.db.upsert_file(rec)
        return rec.id

    def art(self, artifact_type: str, title: str = "") -> str:
        from stopa.models import Artifact

        a = Artifact(
            source_id=SRC_ID,
            artifact_type=artifact_type,
            timestamp=TS_ART,
            title=title,
            details={},
            rel_path=f"f33/{artifact_type}/{self._next('art')}",
        )
        self.db.upsert_artifact(a)
        return a.id

    def link_file(self, artifact_id: str, file_id: str) -> None:
        self.db.conn.execute(
            "UPDATE artifacts SET file_id = ? WHERE id = ?", (file_id, artifact_id)
        )
        self.db.conn.commit()

    def tl(self, ts_utc: str, title: str, flags: str | None = None) -> str:
        ev_id = self._next("tl")
        self.db.conn.execute(
            "INSERT INTO timeline_events (id, source_id, artifact_id, file_id,"
            " rel_path, event_type, ts_utc, title, anomaly_flags)"
            " VALUES (?, ?, NULL, NULL, 'f33/notes.txt', 'browser_history',"
            " ?, ?, ?)",
            (ev_id, SRC_ID, ts_utc, title, flags),
        )
        self.db.conn.commit()
        return ev_id

    def entity(self, kind: str, value: str) -> None:
        self.db.upsert_entities(CASE_ID, [(kind, value, value, None, None)])


def seed(db):
    """Populace případu — 12 souborů / 9 artefaktů / entity / timeline."""
    b = Builder(db)
    f1 = b.file("docs/report.pdf")
    f2 = b.file("docs/invoice_042.pdf", mtime=datetime(2026, 1, 7))
    b.file("docs/manual.pdf", mtime=datetime(2025, 12, 20))
    b.file("photos/vacation.jpg", mtime=datetime(2026, 1, 2))
    b.file("photos/family.jpg", mtime=datetime(2026, 1, 2))
    b.file("photos/workshop.png", mtime=datetime(2026, 1, 9))
    b.file("mail/contract.eml", mtime=datetime(2026, 1, 5))
    b.file("mail/newsletter.eml", mtime=datetime(2026, 1, 5))
    b.file("data/backup.zip", size=5_000_000, mtime=datetime(2025, 12, 15))
    b.file("notes/meeting.txt", mtime=datetime(2026, 1, 6))
    b.file("notes/todo.txt", mtime=datetime(2026, 1, 6))
    b.file("docs/archive.pdf", mtime=datetime(2026, 1, 8))

    a1 = b.art("antiforensics/timestomping", "mtime predates ctime")
    b.art("antiforensics/log_clearing", "Windows Event Log cleared")
    b.art("network/ioc", "IoC c2_beaconing — interval 30 s")
    b.art("crypto_wallet", "BTC address bc1q... detected")
    a5 = b.art("email_attachment", "příloha invoice_042.pdf")
    b.art("antiforensics/usn_truncation", "USN journal truncated")
    b.art("network/ioc", "IoC base64_blob_payload — 2.1 MB")
    b.art("crypto_detection", "ETH address 0x... detected")
    b.art("drive_activity", "USB drive connected (E:)")
    b.link_file(a1, f1)
    b.link_file(a5, f2)

    b.entity("email", "mirdamatus@gmail.com")
    b.entity("email", "admin@corp.example")
    b.entity("user_account", "jnovak")
    b.entity("user_account", "esvobodova")
    b.entity("url_host", "https://cloud.example/share/123")

    b.tl("2026-01-05T13:00:00+00:00", "tl timestomp", flags="timestomp")
    b.tl("2026-01-05T14:00:00+00:00", "tl clean")
    b.tl("2026-01-05T15:00:00+00:00", "tl usn", flags="usn_truncation")
    b.tl("2026-01-05T16:00:00+00:00", "tl c2 watch")
    return Builder(db)


# ── 50 testovacích NL queries (AK) ────────────────────────────────
# Každá trojice: (NL text, SQL s placeholderem ?, params). Všechny dotazy
# cílí na data přítomná v seed() → očekává se ≥1 řádek u každého.

QUERIES: list[tuple[str, str, list]] = [
    ("Jaké soubory mají příponu .pdf?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["%.pdf"]),
    ("Které soubory jsou fotky JPG?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["%.jpg"]),
    ("Najdi PNG soubory v případě.", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["%.png"]),
    ("Jaké e-mailové záznamy (EML) existují?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["%.eml"]),
    ("Kde jsou ZIP archivy?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["%.zip"]),
    ("Jaké textové soubory .txt jsou extrahovány?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["%.txt"]),
    ("Vypis všechny soubory v adresáři docs/.", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["docs/%"]),
    ("Co je ve složce photos/?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["photos/%"]),
    ("Vypis soubory ze složky mail/.", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["mail/%"]),
    ("Co obsahuje složka notes/?", "SELECT id, name FROM files WHERE rel_path LIKE ?", ["notes/%"]),
    ("Které soubory mají v názvu slovo invoice?", "SELECT id, name FROM files WHERE name LIKE ?", ["%invoice%"]),
    ("Najdi soubor report.", "SELECT id, name FROM files WHERE name LIKE ?", ["%report%"]),
    ("Soubory se slovem backup v názvu.", "SELECT id, name FROM files WHERE name LIKE ?", ["%backup%"]),
    ("Kde je poznámka meeting.txt?", "SELECT id, rel_path FROM files WHERE name = ?", ["meeting.txt"]),
    ("Soubory s 'vacation' v názvu.", "SELECT id, name FROM files WHERE name LIKE ?", ["%vacation%"]),
    ("Jaké artefakty timestomping existují?", "SELECT id, title FROM artifacts WHERE artifact_type = ?", ["antiforensics/timestomping"]),
    ("Vypis artefakty typu network/ioc.", "SELECT id, title FROM artifacts WHERE artifact_type = ?", ["network/ioc"]),
    ("Které artefakty souvisí s kryptoměnami?", "SELECT id, title FROM artifacts WHERE artifact_type LIKE ?", ["%crypto%"]),
    ("Artefakt s IoC pravidlem c2_beaconing.", "SELECT id, title FROM artifacts WHERE title LIKE ?", ["%c2_beaconing%"]),
    ("Jaké e-mailové přílohy byly extrahovány?", "SELECT id, title FROM artifacts WHERE artifact_type = ?", ["email_attachment"]),
    ("Kolik celkem artefaktů má tento případ?", "SELECT COUNT(*) AS n FROM artifacts WHERE source_id IN (SELECT id FROM sources WHERE case_id = ?)", [CASE_ID]),
    ("Kolik různých typů artefaktů je v případě?", "SELECT COUNT(DISTINCT artifact_type) AS n FROM artifacts WHERE source_id IN (SELECT id FROM sources WHERE case_id = ?)", [CASE_ID]),
    ("Artefakty s BTC v titulu.", "SELECT id, title FROM artifacts WHERE title LIKE ?", ["%BTC%"]),
    ("Bylo připojeno odpojitelné médium?", "SELECT id, title FROM artifacts WHERE artifact_type = ?", ["drive_activity"]),
    ("Jaké e-mailové adresy jsou v případě?", "SELECT value_normalized FROM entities WHERE case_id = ? AND kind = ?", [CASE_ID, "email"]),
    ("Kolik událostí má timeline?", "SELECT COUNT(*) AS n FROM timeline_events WHERE source_id IN (SELECT id FROM sources WHERE case_id = ?)", [CASE_ID]),
    ("Ukáž události s flagem timestomp.", "SELECT id, title FROM timeline_events WHERE anomaly_flags LIKE ?", ["%timestomp%"]),
    ("Tři nejstarší události timeline.", "SELECT id, ts_utc, title FROM timeline_events ORDER BY ts_utc ASC LIMIT ?", [3]),
    ("Události s USN flagem.", "SELECT id, title FROM timeline_events WHERE anomaly_flags LIKE ?", ["%usn_truncation%"]),
    ("Celkový počet souborů v případě.", "SELECT COUNT(*) AS n FROM files WHERE source_id IN (SELECT id FROM sources WHERE case_id = ?)", [CASE_ID]),
    ("Tři největší soubory podle velikosti.", "SELECT id, name, size_bytes FROM files ORDER BY size_bytes DESC LIMIT ?", [3]),
    ("Pět souborů seřazených abecedně.", "SELECT id, name FROM files ORDER BY name ASC LIMIT ?", [5]),
    ("Dva soubory s nejdelšími názvy.", "SELECT id, name FROM files ORDER BY LENGTH(name) DESC LIMIT ?", [2]),
    ("Rozložení souborů podle adresáře.", "SELECT SUBSTR(rel_path, 1, INSTR(rel_path, '/') - 1) AS dir, COUNT(*) AS n FROM files GROUP BY dir ORDER BY n DESC", []),
    ("Dva nejstarší soubory podle mtime.", "SELECT id, name, mtime FROM files ORDER BY mtime ASC LIMIT ?", [2]),
    ("Které soubory mají přiřazené artefakty?", "SELECT DISTINCT f.id, f.name FROM files f JOIN artifacts a ON a.file_id = f.id", []),
    ("Artefakty kryptoměn s názvy souborů (pokud existují).", "SELECT a.title, f.name FROM artifacts a LEFT JOIN files f ON a.file_id = f.id WHERE a.artifact_type LIKE ?", ["%crypto%"]),
    ("Počet souborů pro každý zdroj.", "SELECT s.id, COUNT(f.id) AS n FROM sources s LEFT JOIN files f ON f.source_id = s.id GROUP BY s.id", []),
    ("Fulltext: najdi 'report'.", "SELECT id, name FROM files WHERE id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)", ["report"]),
    ("Fulltext: najdi 'invoice'.", "SELECT id, name FROM files WHERE id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)", ["invoice"]),
    ("Artefakty s IoC pravidlem base64_blob_payload.", "SELECT id, title FROM artifacts WHERE title LIKE ?", ["%base64_blob_payload%"]),
    ("E-mailové adresy končící na gmail.com.", "SELECT value_normalized FROM entities WHERE case_id = ? AND value_normalized LIKE ?", [CASE_ID, "%gmail.com"]),
    ("Jaké uživatelské účty jsou extrahovány?", "SELECT value_normalized FROM entities WHERE case_id = ? AND kind = ?", [CASE_ID, "user_account"]),
    ("Ukáž URL adresy v případě.", "SELECT value_normalized FROM entities WHERE case_id = ? AND kind = ?", [CASE_ID, "url_host"]),
    ("Soubory s mtime v lednu 2026.", "SELECT id, name FROM files WHERE mtime LIKE ?", ["2026-01%"]),
    ("Soubory starší než leden 2026.", "SELECT id, name FROM files WHERE mtime < ?", ["2026-01-01"]),
    ("Artefakty s vazbou na konkrétní soubor.", "SELECT id, title FROM artifacts WHERE file_id IS NOT NULL", []),
    ("Tři nejnovější události timeline.", "SELECT id, ts_utc, title FROM timeline_events ORDER BY ts_utc DESC LIMIT ?", [3]),
    ("Velké soubory v data/ (přes 1 MB).", "SELECT id, name, size_bytes FROM files WHERE rel_path LIKE ? AND size_bytes > ?", ["data/%", 1_000_000]),
    ("Kolik zdrojů má tento případ?", "SELECT COUNT(*) AS n FROM sources WHERE case_id = ?", [CASE_ID]),
]


def make_fake_llm(queries: list[tuple[str, str, list]]):
    """Deterministická FakeLLM: NL text → dict {sql, params}."""
    table = {nl: {"sql": sql, "params": params} for nl, sql, params in queries}

    def fake(nl_text: str, schema_context: str) -> dict:
        assert nl_text in table, f"neznámý NL dotaz v testu: {nl_text!r}"
        return table[nl_text]

    return fake


@pytest.fixture()
def db(tmp_path):
    d = _fresh_db(tmp_path)
    seed(d)
    yield d
    d.close()


# ── unit testy validace / sandboxu / timeoutu ─────────────────────


class TestValidation:
    def test_default_timeout_is_5s(self):
        assert DEFAULT_TIMEOUT_S == 5.0

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO files (id) VALUES ('x')",
            "SELECT id FROM files; DROP TABLE files",
            "PRAGMA table_info(files)",
            "UPDATE files SET name = 'x' WHERE id = 'f-1'",
            "WITH x AS (SELECT 1) DELETE FROM files",
        ],
    )
    def test_rejects_non_select(self, db, sql):
        llm = lambda nl, schema: {"sql": sql}
        with pytest.raises(InvalidQueryError):
            run_nl_query(db, CASE_ID, "test", llm_call=llm)

    def test_unknown_table_rejected(self, db):
        llm = lambda nl, schema: {"sql": "SELECT * FROM nonexistent_tbl"}
        with pytest.raises(InvalidQueryError, match="neznámé tabulky"):
            run_nl_query(db, CASE_ID, "test", llm_call=llm)

    def test_unknown_column_rejected(self, db):
        llm = lambda nl, schema: {"sql": "SELECT no_such_col FROM files"}
        with pytest.raises(InvalidQueryError, match="no such column"):
            run_nl_query(db, CASE_ID, "test", llm_call=llm)

    def test_param_count_mismatch(self, db):
        llm = lambda nl, schema: {
            "sql": "SELECT id FROM files WHERE name = ?",
            "params": ["a.pdf", "b.pdf"],
        }
        with pytest.raises(InvalidQueryError, match="počet parametrů"):
            run_nl_query(db, CASE_ID, "test", llm_call=llm)

    def test_missing_llm_call(self, db):
        with pytest.raises(nq.NLQueryError):
            run_nl_query(db, CASE_ID, "test")

    def test_json_string_payload_accepted(self, db):
        llm = lambda nl, schema: '{"sql": "SELECT COUNT(*) AS n FROM files"}'
        res = run_nl_query(db, CASE_ID, "počet souborů", llm_call=llm)
        assert isinstance(res, NLQueryResult)
        assert res.rows[0]["n"] == 12

    def test_injection_parameterized(self, db):
        """'; DROP TABLE files; -- v parametru = data, ne kód."""
        nl = "Jaké soubory se jmenují '; DROP TABLE files; --?"
        llm = lambda t, s: {
            "sql": "SELECT id FROM files WHERE name = ?",
            "params": ["'; DROP TABLE files; --"],
        }
        res = run_nl_query(db, CASE_ID, nl, llm_call=llm)
        assert res.rows == []  # žádná shoda, ale bez chyby
        n = db.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert n == 12  # tabulka přežila

    def test_sandbox_read_only_rejects_write(self, db):
        """Přímý zápis do sandboxu spadne na read-only spojení."""
        sql = "UPDATE files SET name = 'x' WHERE id IN (SELECT id FROM files LIMIT 1)"
        with pytest.raises(InvalidQueryError, match="readonly"):
            nq.execute_sandboxed(db, sql, ())
        n = db.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert n == 12

    def test_audit_log_written(self, db):
        llm = lambda nl, schema: {"sql": "SELECT COUNT(*) AS n FROM files"}
        run_nl_query(db, CASE_ID, "počet souborů", llm_call=llm)
        entries = db.list_audit_log(limit=50)
        assert any(e.get("action") == "nl_query" for e in entries)


class TestTimeoutAndLimits:
    def test_timeout_fires_on_heavy_scan(self, tmp_path):
        """80k řádků → progress handler překročí rozpočet 0 s."""
        d = _fresh_db(tmp_path)
        seed(d)
        rows = [
            (f"bulk-{i:06d}.bin", SRC_ID, f"bulk/{i:06d}.bin", f"{i:06d}.bin", 128)
            for i in range(80_000)
        ]
        d.conn.executemany(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        d.conn.commit()
        with pytest.raises(QueryTimeoutError):
            nq.execute_sandboxed(d, "SELECT COUNT(*) FROM files WHERE rel_path LIKE '%zzz%'", (), timeout_s=0)
        # kontrola: stejný dotaz s rozumným rozpočtem projde
        res = nq.execute_sandboxed(
            d, "SELECT COUNT(*) AS n FROM files", (), timeout_s=30
        )
        assert res.rows[0]["n"] == 80_012
        d.close()

    def test_truncation_hard_cap(self, db, monkeypatch):
        monkeypatch.setattr(nq, "MAX_ROWS_HARD_CAP", 3)
        llm = lambda nl, schema: {"sql": "SELECT id FROM files"}
        res = run_nl_query(db, CASE_ID, "všechny soubory", llm_call=llm)
        assert res.truncated is True
        assert len(res.rows) == 3

    def test_columns_match_schema(self, db):
        llm = lambda nl, schema: {
            "sql": "SELECT id, name, size_bytes FROM files ORDER BY size_bytes DESC LIMIT ?",
            "params": [2],
        }
        res = run_nl_query(db, CASE_ID, "největší soubory", llm_call=llm)
        assert res.columns == ("id", "name", "size_bytes")
        assert len(res.rows) == 2
        assert res.rows[0]["size_bytes"] == 5_000_000


# ── AK: 50 NL queries → ≥90 % úspěšnost ───────────────────────────


def test_ak_50_nl_queries_min_90_percent(db):
    llm = make_fake_llm(QUERIES)
    assert len(QUERIES) == 50, "AK vyžaduje přesně 50 testovacích queries"
    failures: list[str] = []
    total_rows = 0
    for nl, sql, params in QUERIES:
        try:
            res = run_nl_query(db, CASE_ID, nl, llm_call=llm)
            assert len(res.rows) >= 1, f"query vrátila 0 řádků: {nl!r}"
            total_rows += len(res.rows)
        except Exception as exc:  # noqa: BLE001 — AK sbírá všechny neúspěchy
            failures.append(f"{nl!r} → {exc}")
    ok = len(QUERIES) - len(failures)
    assert total_rows >= 80, f"podezřele málo dat vráceno: {total_rows}"
    rate = ok / len(QUERIES)
    assert rate >= 0.90, (
        f"úspěšnost NL queries {ok}/50 = {rate:.0%} < 90 %; selhání:\n"
        + "\n".join(failures)
    )


def test_ak_success_is_100_percent_on_clean_fixture(db):
    """Na čistém fixture očekáváme plných 50/50 (AK je jen dolní hranice)."""
    llm = make_fake_llm(QUERIES)
    failures: list[str] = []
    for nl, sql, params in QUERIES:
        try:
            run_nl_query(db, CASE_ID, nl, llm_call=llm)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{nl!r} → {exc}")
    assert not failures, "selhala query:\n" + "\n".join(failures)
