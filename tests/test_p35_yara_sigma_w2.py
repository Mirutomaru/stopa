"""STOPA P3-5 Wave 2 — YARA/Sigma matching: migrace v25 + data vrstva + CLI + Web.

Doménová coverage (enginy, kanonické názvy, semantika) je v
``tests/test_p35_yara_sigma_domain.py`` (Wave 1); tady je hrana:

- ``apply_rule_matching_migration``: rozšíření CHECK ``intel_matches.match_kind``
  o yara/sigma (v24→v25, data + index zachovány), idempotence na nové DB, fail-closed;
- ``run_intel_match(yara_dir=… / sigma_file=…)``: dedikované enginy → match_kind
  yara/sigma, pravidla viditelná ve feedu jako IoC druhů yara_rule/sigma_tpl,
  deterministický re-run (clear + insert), chybějící soubor na disku nekrachne;
- CLI ``stopa intel match <case> --yara DIR | --sigma FILE`` — exit kódy a JSON;
- Web ``POST /api/cases/{id}/intel/match`` s volitelným tělem
  ``{yara_dir, sigma_file}`` (bez těla = původní chování).

Offline a deterministické: dočasná CaseDB ve standardním layoutu {db_dir}/{case}.db;
FastAPI TestClient bez spuštění serveru. yara-python přes importorskip — Sigma
šablony jsou JSON (fungují i bez PyYAML).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.threat_intel import IoC, ioc_id

CASE_ID = "p35-case"
NOW_ISO = "2026-11-18T12:00:00+00:00"
SHA_A = "a" * 64
NEEDLE_FILE = "a.txt"  # obsahuje řetězec, na který cílí YARA pravidlo

YARA_RULE_NEEDLE = (
    'rule P35_Needle {\n'
    '    strings:\n'
    '        $a = "needle"\n'
    '    condition:\n'
    '        any of them\n'
    "}\n"
)
SIGMA_DOC = json.dumps(
    [
        {
            "name": "P35_Beacon",
            "tlp": "AMBER",
            "detection": {"title_contains": ["beacon"], "event_type": ["network"]},
        }
    ]
)


# ── fixture: case DB se soubory na disku + timeline eventem ─────────────────


@pytest.fixture()
def file_root(tmp_path: Path) -> Path:
    """Adresář reálných souborů — cíl YARA skenu (sources.path)."""
    root = tmp_path / "files"
    root.mkdir()
    (root / NEEDLE_FILE).write_text("prefix needle suffix", encoding="utf-8")
    return root


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch, file_root: Path) -> Path:
    d = tmp_path / "cases"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    seeded = CaseDB(d / f"{CASE_ID}.db")
    _seed_case(seeded, file_root)
    seeded.close()
    return d


def _seed_case(d: CaseDB, file_root: Path) -> None:
    """Minimální případ: zdroj s reálným souborem + IoC artefakt + timeline event.

    - files f1 → a.txt na disku (YARA target);
    - art-hash: generic_log se SHA-256 v titulu (klasický entity matching);
    - timeline event 'network' / title 'C2 beacon …' (Sigma target).
    """
    c = d.conn
    c.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (CASE_ID, "P3-5", NOW_ISO),
    )
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', ?, ?)",
        (CASE_ID, str(file_root), NOW_ISO),
    )
    content = (file_root / NEEDLE_FILE).read_bytes()
    c.execute(
        "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
        " VALUES ('f1', 's1', ?, ?, ?)",
        (NEEDLE_FILE, NEEDLE_FILE, len(content)),
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, artifact_type, title)"
        f" VALUES ('art-hash', 's1', 'generic_log', 'found file sha256 {SHA_A}')"
    )
    d.add_timeline_event(
        source_id="s1",
        ts_utc=datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc),
        event_type="network",
        title="C2 beacon to 10.0.0.5",
        rel_path="logs/app.log",
    )


@pytest.fixture()
def db(dbdir: Path) -> CaseDB:
    d = CaseDB(dbdir / f"{CASE_ID}.db")
    yield d
    d.close()


@pytest.fixture()
def yara_dir(tmp_path: Path) -> Path:
    rdir = tmp_path / "rules"
    rdir.mkdir()
    (rdir / "needle.yar").write_text(YARA_RULE_NEEDLE, encoding="utf-8")
    return rdir


@pytest.fixture()
def sigma_file(tmp_path: Path) -> Path:
    p = tmp_path / "tpl.json"
    p.write_text(SIGMA_DOC, encoding="utf-8")
    return p


# ── migrace v25: CHECK rozšíření intel_matches.match_kind ───────────────────

V24_MATCH_CHECK = "CHECK (match_kind IN ('entity', 'file_hash', 'artifact_text'))"
V25_MATCH_CHECK = "CHECK (match_kind IN ('entity', 'file_hash', 'artifact_text', 'yara', 'sigma'))"
V24_FEED_CHECK = "CHECK (kind IN ('ip', 'domain', 'hash', 'url'))"
V25_FEED_CHECK = "CHECK (kind IN ('ip', 'domain', 'hash', 'url', 'yara_rule', 'sigma_tpl'))"


def _v24_intel_ddl() -> str:
    """INTEL_DDL s původními v24 CHECKy (vrácením stringové výměny)."""
    from stopa.data.schema import INTEL_DDL

    ddl = INTEL_DDL.replace(V25_MATCH_CHECK, V24_MATCH_CHECK).replace(
        V25_FEED_CHECK, V24_FEED_CHECK
    )
    assert ddl != INTEL_DDL  # výměna se musela projevit — jinak by test mlčel
    return ddl


def _insert_match(conn: sqlite3.Connection, case_id: str, ioc_id_val: str, match_kind: str) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(intel_matches)")]
    defaults = {
        "case_id": case_id,
        "ioc_id": ioc_id_val,
        "match_kind": match_kind,
        "evidence_json": "[]",
        "matched_at": NOW_ISO,
    }
    vals = [defaults.get(col) for col in cols]
    conn.execute(
        f"INSERT INTO intel_matches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        vals,
    )


class TestMigrationV25:
    def test_v24_to_v25_preserves_data_and_extends_check(self):
        from stopa.data.migrations import apply_rule_matching_migration

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(_v24_intel_ddl())
        _insert_match(conn, CASE_ID, "ioc-1", "entity")
        _insert_match(conn, CASE_ID, "ioc-2", "file_hash")
        _insert_match(conn, CASE_ID, "ioc-3", "artifact_text")

        apply_rule_matching_migration(conn)

        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='intel_matches'"
        ).fetchone()[0]
        assert "'yara'" in sql and "'sigma'" in sql
        # data + sloupce beze změny
        rows = conn.execute("SELECT ioc_id, match_kind FROM intel_matches ORDER BY id").fetchall()
        assert [(r["ioc_id"], r["match_kind"]) for r in rows] == [
            ("ioc-1", "entity"),
            ("ioc-2", "file_hash"),
            ("ioc-3", "artifact_text"),
        ]
        # index přežil rebuild (po RENAME sledoval starou tabulku → znovu vytvořen)
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='intel_matches'"
        )}
        assert "idx_intel_matches_case" in idx
        # nový CHECK přijímá yara/sigma, cizí hodnotu odmítá
        _insert_match(conn, CASE_ID, "ioc-4", "yara")
        _insert_match(conn, CASE_ID, "ioc-5", "sigma")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_match(conn, CASE_ID, "ioc-6", "bogus")

        # ioc_feed_items: pravidla jako feed itemy (yara_rule/sigma_tpl přijaty, cizí odmítnuty)
        def _feed_item(kind: str) -> None:
            conn.execute(
                "INSERT INTO ioc_feed_items"
                " (id, case_id, kind, value, acquired_at, imported_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("fid-" + kind, CASE_ID, kind, "v", NOW_ISO, NOW_ISO),
            )

        _feed_item("yara_rule")
        _feed_item("sigma_tpl")
        with pytest.raises(sqlite3.IntegrityError):
            _feed_item("ftp")

    def test_migration_idempotent_on_fresh_v25_db(self):
        from stopa.data.migrations import apply_rule_matching_migration
        from stopa.data.schema import SCHEMA

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        _insert_match(conn, CASE_ID, "ioc-1", "yara")  # v25 CHECK už přijímá
        apply_rule_matching_migration(conn)  # early-return — bez chyby
        apply_rule_matching_migration(conn)  # idempotence
        n = conn.execute("SELECT COUNT(*) FROM intel_matches").fetchone()[0]
        assert n == 1

    def test_migration_fail_closed_on_unexpected_check(self):
        from stopa.data.migrations import apply_rule_matching_migration

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE ioc_feed_items (id TEXT PRIMARY KEY, case_id TEXT NOT NULL,"
            " kind TEXT NOT NULL " + V24_FEED_CHECK + ","
            " value TEXT NOT NULL, acquired_at TEXT NOT NULL, imported_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE intel_matches (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " case_id TEXT NOT NULL, ioc_id TEXT NOT NULL, kind TEXT NOT NULL,"
            " value TEXT NOT NULL, match_kind TEXT NOT NULL"
            " CHECK (match_kind IN ('entity')))"
        )
        with pytest.raises(ValueError, match="Neočekávané DDL"):
            apply_rule_matching_migration(conn)


# ── data vrstva: run_intel_match s --yara / --sigma ─────────────────────────

def _has(name: str) -> bool:
    from importlib.util import find_spec

    return find_spec(name) is not None


requires_yara = pytest.mark.skipif(
    not _has("yara"), reason="chybí yara-python (volitelná závislost)"
)


@requires_yara
class TestDataLayerRules:
    def test_yara_match_persists_and_feed_visible(self, db, yara_dir):
        from stopa.data.intel_repository import IntelRepository, run_intel_match

        result = run_intel_match(db, CASE_ID, yara_dir=str(yara_dir))
        assert result["by_match_kind"] == {"yara": 1}
        m = result["matches"][0]
        assert (m["kind"], m["value"], m["match_kind"]) == ("yara_rule", "P35_Needle", "yara")

        repo = IntelRepository(db.conn)
        saved = {x["ioc_id"]: x for x in repo.list_matches(CASE_ID)}
        ev = saved[ioc_id(IoC(kind="yara_rule", value="P35_Needle"))]["evidence"]
        assert ev[0]["rel_path"] == NEEDLE_FILE and ev[0]["source_id"] == "s1"

        # pravidlo viditelné ve feedu: kanonický název + text pravidla v raw_value
        feed = {f["value"]: f for f in repo.list_feed(CASE_ID)}
        assert set(feed) == {"P35_Needle"}
        assert feed["P35_Needle"]["kind"] == "yara_rule"
        assert "needle" in feed["P35_Needle"].get("raw_value", "")
        assert repo.feed_summary(CASE_ID)["by_kind"] == {"yara_rule": 1}

    def test_yara_no_hit_still_visible_in_feed(self, db, tmp_path: Path):
        from stopa.data.intel_repository import run_intel_match

        rdir = tmp_path / "rules"
        rdir.mkdir()
        (rdir / "nohit.yar").write_text(
            'rule P35_NoHit {\n    strings:\n        $a = "zzz_not_here"\n'
            "    condition:\n        any of them\n}\n",
            encoding="utf-8",
        )
        result = run_intel_match(db, CASE_ID, yara_dir=str(rdir))
        assert "yara" not in result["by_match_kind"]  # žádný hit → žádný řádek v intel_matches
        n_feed = db.conn.execute(
            "SELECT COUNT(*) FROM ioc_feed_items WHERE kind='yara_rule'"
        ).fetchone()[0]
        assert n_feed == 1  # ale pravidlo ve feedu viditelné (0 shod)

    def test_yara_deterministic_reorder_of_files(self, db, tmp_path: Path):
        """Pořadí souborů v adresáři neovlivní pořadí výstupu (AK2)."""
        from stopa.data.intel_repository import run_intel_match

        rdir = tmp_path / "rules"
        rdir.mkdir()
        (rdir / "b.yar").write_text(
            'rule Zeta {\n    strings:\n        $a = "needle"\n'
            "    condition:\n        any of them\n}\n",
            encoding="utf-8",
        )
        (rdir / "a.yar").write_text(
            'rule Alpha {\n    strings:\n        $a = "needle"\n'
            "    condition:\n        any of them\n}\n",
            encoding="utf-8",
        )
        result = run_intel_match(db, CASE_ID, yara_dir=str(rdir))
        vals = [m["value"] for m in result["matches"] if m["match_kind"] == "yara"]
        assert vals == ["Alpha", "Zeta"]  # seřazené podle názvu pravidla

    def test_missing_file_on_disk_no_crash(self, db, yara_dir):
        from stopa.data.intel_repository import run_intel_match

        db.conn.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
            " VALUES ('f2', 's1', 'gone.txt', 'gone.txt', 3)"
        )
        db.conn.commit()
        result = run_intel_match(db, CASE_ID, yara_dir=str(yara_dir))
        assert result["by_match_kind"] == {"yara": 1}
        ev = next(m for m in result["matches"] if m["match_kind"] == "yara")
        assert ev["evidence_count"] == 1  # jen a.txt; gone.txt chybí na disku

    def test_rerun_without_flags_clears_rule_matches(self, db, yara_dir):
        from stopa.data.intel_repository import run_intel_match

        first = run_intel_match(db, CASE_ID, yara_dir=str(yara_dir))
        assert "yara" in first["by_match_kind"]
        # re-run bez flags: pravidla zůstávají ve feedu, ale shody se (re)generují jen z vstupu
        second = run_intel_match(db, CASE_ID)
        assert "yara" not in second["by_match_kind"] and second["matches_total"] == 0
        n_feed = db.conn.execute("SELECT COUNT(*) FROM ioc_feed_items").fetchone()[0]
        assert n_feed == 1

    def test_combined_yara_sigma_and_classic_deterministic(self, db, yara_dir, sigma_file):
        from stopa.data.intel_repository import IntelRepository, run_intel_match

        repo = IntelRepository(db.conn)
        repo.import_feed(CASE_ID, [IoC(kind="hash", value=SHA_A)])
        first = run_intel_match(
            db, CASE_ID, yara_dir=str(yara_dir), sigma_file=str(sigma_file)
        )
        assert first["by_match_kind"] == {"entity": 1, "sigma": 1, "yara": 1}
        assert first["matches_total"] == 3
        second = run_intel_match(
            db, CASE_ID, yara_dir=str(yara_dir), sigma_file=str(sigma_file)
        )
        assert second == first  # deterministický re-run (clear + insert)
        n = db.conn.execute("SELECT COUNT(*) FROM intel_matches").fetchone()[0]
        assert n == 3


class TestDataLayerSigma:
    def test_sigma_match_persists_with_event_evidence(self, db, sigma_file):
        from stopa.data.intel_repository import IntelRepository, run_intel_match

        result = run_intel_match(db, CASE_ID, sigma_file=str(sigma_file))
        assert result["by_match_kind"] == {"sigma": 1}
        m = result["matches"][0]
        assert (m["kind"], m["value"], m["match_kind"]) == ("sigma_tpl", "P35_Beacon", "sigma")
        assert m["first_seen"] == m["last_seen"] == NOW_ISO

        repo = IntelRepository(db.conn)
        saved = {x["ioc_id"]: x for x in repo.list_matches(CASE_ID)}
        ev = saved[ioc_id(IoC(kind="sigma_tpl", value="P35_Beacon"))]["evidence"][0]
        event_id = db.conn.execute("SELECT id FROM timeline_events").fetchone()[0]
        assert str(ev["id"]) == str(event_id)
        assert ev["ts_utc"] == NOW_ISO and "beacon" in ev["title"].lower()

    def test_sigma_no_match_no_row(self, db, tmp_path: Path):
        from stopa.data.intel_repository import run_intel_match

        p = tmp_path / "nomatch.json"
        p.write_text(
            json.dumps([{"name": "P35_Never", "detection": {"title_contains": ["neexistujici"]}}]),
            encoding="utf-8",
        )
        result = run_intel_match(db, CASE_ID, sigma_file=str(p))
        assert "sigma" not in result["by_match_kind"]

    def test_sigma_invalid_doc_valueerror(self, db, tmp_path: Path):
        from stopa.data.intel_repository import run_intel_match

        p = tmp_path / "bad.json"
        p.write_text("[{not-json", encoding="utf-8")
        with pytest.raises(ValueError):
            run_intel_match(db, CASE_ID, sigma_file=str(p))


# ── CLI: stopa intel match <case> --yara DIR | --sigma FILE ─────────────────


def _run(cmd, **kw) -> tuple[int, str]:
    """Spuští CLI příkaz s Namespace; vrací (exit_code, stdout + SystemExit zpráva)."""
    import argparse
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cmd(argparse.Namespace(**kw)) or 0
        return int(rc), buf.getvalue()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        msg = str(exc.code) if not isinstance(exc.code, int) else ""
        return code, f"{msg}\n{buf.getvalue()}"


class TestCliMatchRules:
    @requires_yara
    def test_match_yara_json(self, dbdir, yara_dir):
        from stopa.cli.commands.intel import cmd_intel_match

        rc, out = _run(
            cmd_intel_match, case_id=CASE_ID, json=True, yara=str(yara_dir), sigma=None
        )
        assert rc == 0
        body = json.loads(out)
        assert body["by_match_kind"] == {"yara": 1}
        # textový režim: shrnutí na jednom řádku
        rc2, out2 = _run(
            cmd_intel_match, case_id=CASE_ID, json=False, yara=str(yara_dir), sigma=None
        )
        assert rc2 == 0 and "shody: 1" in out2

    def test_match_sigma_json(self, dbdir, sigma_file):
        from stopa.cli.commands.intel import cmd_intel_match

        rc, out = _run(
            cmd_intel_match, case_id=CASE_ID, json=True, yara=None, sigma=str(sigma_file)
        )
        assert rc == 0 and json.loads(out)["by_match_kind"] == {"sigma": 1}

    def test_empty_feed_exit1(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_match

        rc, out = _run(cmd_intel_match, case_id=CASE_ID, json=True, yara=None, sigma=None)
        assert rc == 1 and "feed" in out

    @requires_yara
    def test_bad_yara_dir_exit1(self, dbdir, tmp_path):
        from stopa.cli.commands.intel import cmd_intel_match

        rc, out = _run(
            cmd_intel_match,
            case_id=CASE_ID,
            json=True,
            yara=str(tmp_path / "nope"),
            sigma=None,
        )
        assert rc == 1 and "adresář" in out

    def test_parser_has_new_flags(self):
        from stopa.cli import build_parser

        args = build_parser().parse_args(
            ["intel", "match", CASE_ID, "--yara", "/x", "--sigma", "/y.json"]
        )
        assert args.yara == "/x" and args.sigma == "/y.json"


# ── Web: POST /api/cases/{id}/intel/match s volitelným tělem ────────────────


@pytest.fixture()
def client(dbdir: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app(dbdir))


class TestWebMatchRules:
    @requires_yara
    def test_match_with_yara_body(self, client, yara_dir):
        r = client.post(f"/api/cases/{CASE_ID}/intel/match", json={"yara_dir": str(yara_dir)})
        assert r.status_code == 200 and r.json()["by_match_kind"] == {"yara": 1}

    def test_match_with_sigma_body(self, client, sigma_file):
        r = client.post(f"/api/cases/{CASE_ID}/intel/match", json={"sigma_file": str(sigma_file)})
        assert r.status_code == 200 and r.json()["by_match_kind"] == {"sigma": 1}

    def test_match_no_body_backward_compat(self, client, dbdir):
        """Bez těla = původní chování (klasické IoC matching)."""
        from stopa.data.intel_repository import IntelRepository

        d = CaseDB(dbdir / f"{CASE_ID}.db")
        IntelRepository(d.conn).import_feed(CASE_ID, [IoC(kind="hash", value=SHA_A)])
        d.close()
        r = client.post(f"/api/cases/{CASE_ID}/intel/match")  # žádné tělo
        assert r.status_code == 200 and r.json()["by_match_kind"] == {"entity": 1}

    def test_match_bad_yara_dir_400(self, client):
        r = client.post(f"/api/cases/{CASE_ID}/intel/match", json={"yara_dir": "/nonexistent/xyz"})
        assert r.status_code == 400 and "adresář" in r.json()["detail"]
