"""STOPA P2-5 Wave 2 — Threat Intelligence Workspace: data vrstva + CLI + Web.

Doménová coverage (kanonizace, stáří hranice, STIX roundtrip, matching determinita)
je v ``tests/test_p25_threat_intel_domain.py`` (Wave 1); tady je hrana:

- ``IntelRepository``: idempotentní import feedu (stejný UUIDv5 ID → 1 řádek),
  feed s klasifikací stáří, re-run matching = clear + insert (bez duplicit);
- CLI ``stopa intel import|match <case> [--json]`` — exit kódy a JSON výstup;
- Web ``/api/cases/{id}/intel/*`` — 404 neznámý případ / 400 semantika / 201 import.

Offline a deterministické: dočasná CaseDB ve standardním layoutu {db_dir}/{case}.db;
FastAPI TestClient bez spuštění serveru (jako P2-3/P2-4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.threat_intel import IoC, export_bundle, ioc_id

CASE_ID = "p25-case"
NOW_ISO = "2026-11-18T12:00:00+00:00"
SHA_A = "a" * 64


# ── fixture: case DB s artefakty pro matching ───────────────────────────────


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch):
    d = tmp_path / "cases"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    # case DB s artefakty už existuje na disku (CLI/Web otevírají vlastní spojení)
    seeded = CaseDB(d / f"{CASE_ID}.db")
    _seed_case(seeded)
    seeded.close()
    return d


def _seed_case(d: CaseDB) -> None:
    """Minimální případ se 3 artefakty — každý pro jiný druh IoC matchingu.

    - art-hash: generic_log s SHA-256 v titulu (generický sken → hash entity);
    - art-web: browser_history s URL v titulu (normalize_url_host → url_host);
    - art-ip: generic_log s IP v details.note (svobodný text → artifact_text).
    """
    c = d.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)", (CASE_ID, "P2-5", NOW_ISO))
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', '/tmp/p25', ?)",
        (CASE_ID, NOW_ISO),
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, artifact_type, title)"
        f" VALUES ('art-hash', 's1', 'generic_log', 'found file sha256 {SHA_A}')"
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, artifact_type, title)"
        " VALUES ('art-web', 's1', 'browser_history', 'https://c2.example.net/payload?x=1')"
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, artifact_type, title, details_json)"
        " VALUES ('art-ip', 's1', 'generic_log', 'conn', ?)",
        (json.dumps({"note": "connect to 10.0.0.1 port 443"}),),
    )
    c.commit()


@pytest.fixture()
def db(dbdir: Path):
    d = CaseDB(dbdir / f"{CASE_ID}.db")
    yield d
    d.close()


def _ioc(kind: str, value: str, **kw) -> IoC:
    return IoC(kind=kind, value=value, acquired_at=datetime(2026, 11, 18, tzinfo=timezone.utc), **kw)


# ── data vrstva: IntelRepository + run_intel_match ─────────────────────────


class TestRepoData:
    def test_import_feed_idempotent(self, db):
        from stopa.data.intel_repository import IntelRepository

        repo = IntelRepository(db.conn)
        iocs = [_ioc("domain", "c2.example.net"), _ioc("hash", SHA_A), _ioc("ip", "10.0.0.1")]
        assert repo.import_feed(CASE_ID, iocs) == 3
        # re-import stejného feedu → stále přesně 3 řádky (stejný UUIDv5 ID)
        assert repo.import_feed(CASE_ID, list(reversed(iocs))) == 3
        n = db.conn.execute("SELECT COUNT(*) FROM ioc_feed_items").fetchone()[0]
        assert n == 3

    def test_list_feed_sorted_with_age(self, db):
        from stopa.data.intel_repository import IntelRepository

        repo = IntelRepository(db.conn)
        old = IoC(kind="ip", value="1.2.3.4", acquired_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        fresh = _ioc("domain", "a.b.c")
        repo.import_feed(CASE_ID, [old, fresh])
        feed = repo.list_feed(CASE_ID)
        assert len(feed) == 2
        by_val = {f["value"]: f for f in feed}
        assert by_val["1.2.3.4"]["age"] == "old"  # ~10,5 měsíce > 90 dnů
        assert by_val["a.b.c"]["age"] == "fresh"
        keys = [(f["kind"], f["value"]) for f in feed]
        assert keys == sorted(keys)

    def test_feed_summary_counts_and_kinds(self, db):
        from stopa.data.intel_repository import IntelRepository

        repo = IntelRepository(db.conn)
        repo.import_feed(CASE_ID, [_ioc("domain", "x.y.z"), _ioc("ip", "9.9.9.9")])
        s = repo.feed_summary(CASE_ID)
        assert s["total"] == 2
        assert s["by_kind"] == {"domain": 1, "ip": 1}
        assert s["by_age"]["fresh"] == 2

    def test_run_match_persists_and_rerun_stable(self, db):
        from stopa.data.intel_repository import IntelRepository, run_intel_match

        repo = IntelRepository(db.conn)
        hash_ioc = _ioc("hash", SHA_A)
        dom_ioc = _ioc("domain", "c2.example.net")
        ip_ioc = _ioc("ip", "10.0.0.1")
        repo.import_feed(CASE_ID, [hash_ioc, dom_ioc, ip_ioc])

        first = run_intel_match(db, CASE_ID)
        assert first["matches_total"] == 3
        # každý druh matchingu je reprezentován podle artefaktů v seedu
        assert set(first["by_match_kind"]) <= {"entity", "file_hash", "artifact_text"}
        second = run_intel_match(db, CASE_ID)
        assert second == first  # deterministický re-run (clear + insert → stejný stav)
        n = db.conn.execute("SELECT COUNT(*) FROM intel_matches").fetchone()[0]
        assert n == 3  # re-run bez duplicit

        saved = {m["ioc_id"]: m for m in repo.list_matches(CASE_ID)}
        assert set(saved) == {ioc_id(hash_ioc), ioc_id(dom_ioc), ioc_id(ip_ioc)}
        # hash hit: entity výskyt z art-hash (evidence roundtrip přes DB)
        assert saved[ioc_id(hash_ioc)]["match_kind"] == "entity"
        assert saved[ioc_id(hash_ioc)]["evidence"][0]["artifact_id"] == "art-hash"
        # domain hit: url_host z browser_history art-web
        assert saved[ioc_id(dom_ioc)]["match_kind"] == "entity"
        assert saved[ioc_id(dom_ioc)]["evidence"][0]["artifact_id"] == "art-web"
        # ip hit: svobodný text (details.note) z art-ip
        assert saved[ioc_id(ip_ioc)]["match_kind"] == "artifact_text"
        assert saved[ioc_id(ip_ioc)]["evidence"][0]["artifact_id"] == "art-ip"

    def test_run_match_empty_feed_raises(self, db):
        from stopa.data.intel_repository import run_intel_match

        with pytest.raises(ValueError, match="feed"):
            run_intel_match(db, CASE_ID)


# ── CLI: stopa intel import|match <case> [--json] ───────────────────────────


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


class TestCliImport:
    def test_import_multiple_ioc_json(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_import

        rc, out = _run(
            cmd_intel_import,
            case_id=CASE_ID,
            stix=None,
            ioc=f"domain:c2.example.net,hash:{SHA_A}",
            tlp="AMBER",
            source="feed-a",
            json=True,
        )
        assert rc == 0
        body = json.loads(out)
        assert body["imported"] == 2
        check = CaseDB(dbdir / f"{CASE_ID}.db")
        n = check.conn.execute("SELECT COUNT(*) FROM ioc_feed_items").fetchone()[0]
        check.close()
        assert n == 2

    def test_import_invalid_spec_exit1(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_import

        rc, out = _run(
            cmd_intel_import,
            case_id=CASE_ID,
            stix=None,
            ioc="bez-dvojteckata",
            tlp="GREEN",
            source="",
            json=True,
        )
        assert rc == 1 and "druh:hodnota" in out

    def test_import_unknown_case_exit1(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_import

        rc, out = _run(
            cmd_intel_import,
            case_id="p25-missing",
            stix=None,
            ioc="domain:a.b.c",
            tlp="GREEN",
            source="",
            json=True,
        )
        assert rc == 1 and "nenalezen" in out

    def test_import_stix_file(self, dbdir, tmp_path):
        from stopa.cli.commands.intel import cmd_intel_import

        bundle = export_bundle([_ioc("ip", "10.0.0.1"), _ioc("domain", "c2.example.net")])
        stix_path = tmp_path / "feed.stix.json"
        stix_path.write_text(bundle, encoding="utf-8")
        rc, out = _run(
            cmd_intel_import,
            case_id=CASE_ID,
            stix=str(stix_path),
            ioc=None,
            tlp="GREEN",
            source="",
            json=True,
        )
        assert rc == 0 and json.loads(out)["imported"] == 2

    def test_import_no_source_exit1(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_import

        rc, out = _run(
            cmd_intel_import,
            case_id=CASE_ID,
            stix=None,
            ioc=None,
            tlp="GREEN",
            source="",
            json=True,
        )
        assert rc == 1 and "--stix" in out


class TestCliMatch:
    def test_match_empty_feed_exit1(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_match

        rc, out = _run(cmd_intel_match, case_id=CASE_ID, json=True)
        assert rc == 1 and "feed" in out

    def test_match_with_hits_json(self, dbdir):
        from stopa.cli.commands.intel import cmd_intel_match
        from stopa.data.intel_repository import IntelRepository

        d = CaseDB(dbdir / f"{CASE_ID}.db")
        IntelRepository(d.conn).import_feed(
            CASE_ID, [_ioc("hash", SHA_A), _ioc("domain", "c2.example.net"), _ioc("ip", "10.0.0.1")]
        )
        d.close()

        rc, out = _run(cmd_intel_match, case_id=CASE_ID, json=True)
        assert rc == 0
        body = json.loads(out)
        assert body["matches_total"] == 3
        assert len(body["matches"]) == 3
        # textový režim: shrnutí na jednom řádku
        rc2, out2 = _run(cmd_intel_match, case_id=CASE_ID, json=False)
        assert rc2 == 0 and "shody: 3" in out2


# ── Web: /api/cases/{id}/intel/* ────────────────────────────────────────────


@pytest.fixture()
def client(dbdir: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app(dbdir))


class TestWebIntel:
    def test_feed_unknown_case_404(self, client):
        r = client.get("/api/cases/p25-missing/intel/feed")
        assert r.status_code == 404

    def test_import_then_feed_visible_with_age(self, client):
        r = client.post(
            f"/api/cases/{CASE_ID}/intel/import",
            json={"iocs": [{"kind": "domain", "value": "c2.example.net"}, {"kind": "hash", "value": SHA_A}]},
        )
        assert r.status_code == 201 and r.json()["imported"] == 2

        r = client.get(f"/api/cases/{CASE_ID}/intel/feed")
        assert r.status_code == 200
        body = r.json()
        assert len(body["feed"]) == 2
        by_val = {f["value"]: f for f in body["feed"]}
        assert set(by_val) == {"c2.example.net", SHA_A}
        assert all(f["age"] in ("fresh", "stale", "old") for f in body["feed"])
        assert body["summary"]["total"] == 2

    def test_import_invalid_kind_400(self, client):
        r = client.post(
            f"/api/cases/{CASE_ID}/intel/import",
            json={"iocs": [{"kind": "ftp", "value": "ftp.example.com"}]},
        )
        assert r.status_code == 400 and "IoC" in r.json()["detail"]

    def test_match_empty_feed_400(self, client):
        r = client.post(f"/api/cases/{CASE_ID}/intel/match")
        assert r.status_code == 400 and "feed" in r.json()["detail"]

    def test_match_with_hits_200(self, client, dbdir):
        from stopa.data.intel_repository import IntelRepository

        d = CaseDB(dbdir / f"{CASE_ID}.db")
        IntelRepository(d.conn).import_feed(
            CASE_ID, [_ioc("hash", SHA_A), _ioc("domain", "c2.example.net"), _ioc("ip", "10.0.0.1")]
        )
        d.close()

        r = client.post(f"/api/cases/{CASE_ID}/intel/match")
        assert r.status_code == 200
        body = r.json()
        assert body["matches_total"] == 3
        assert set(body["by_match_kind"]) <= {"entity", "file_hash", "artifact_text"}

    def test_import_idempotent_across_calls(self, client):
        payload = {"iocs": [{"kind": "ip", "value": "10.0.0.1"}]}
        assert client.post(f"/api/cases/{CASE_ID}/intel/import", json=payload).status_code == 201
        r = client.post(f"/api/cases/{CASE_ID}/intel/import", json=payload)
        assert r.status_code == 201 and r.json()["imported"] == 1
        feed = client.get(f"/api/cases/{CASE_ID}/intel/feed").json()
        assert len(feed["feed"]) == 1  # stejný UUIDv5 ID → bez duplicit
