"""STOPA STP-067 — Interop export historie v UI (re-download z cache).

``GET /api/cases/{case_id}/last-export?what=&format=`` vrací poslední
export daného datasetu+formátu uložený do trvalé cache při ``interop-export``
(``{db_dir}/exports/{case_id}/{what}.{format}`, atomický zápis tmp → rename).
Uživatel si z historie exportů v UI stáhne stejná data, která už jednou
vyexportoval — bez nového exportu. Read-only: bez audit záznamu i integrity
checkpointu (není nový export).

Pokrytí: cache soubor vznikne při exportu a leží na správné cestě; re-download
vrátí stejný obsah + attachment filename; 404 bez cache (případ existuje, nic
neexportováno); 404 neznámý případ; 400 neplatný dataset/formát; druhý export
cache přepíše (poslední výhra); re-download nezapisuje audit. Běží E2E přes
TestClient s reálnou case DB (seed přes sqlite3).
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import pytest

# ── fixtury + seed pomocníci (stejný vzor jako STP-066) ─────────────


@pytest.fixture()
def client(tmp_path: Path):
    import json as _json  # P0.4 — laboratorní WB režim pro tyto testy

    from fastapi.testclient import TestClient

    from stopa.web.app import create_app
    (tmp_path / "settings.json").write_text(
        _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
    )
    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka", encoding="utf-8")
    return ev


def _make_case(client, name: str = "Last export test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client, cid: str, evidence: Path) -> None:
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
    assert r.status_code in (200, 201), r.text


def _db_path(tmp_dir: Path, cid: str) -> Path:
    return tmp_dir / f"{cid}.db"


def _seed_artifacts(dbp: Path, n: int = 3, prefix: str = "art-le") -> None:
    """Ingest nevytvoří artifacts (ty vznikají analýzou) — doplní N řádků."""
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO artifacts (id, source_id, rel_path, artifact_type,"
                " timestamp, title) VALUES (?, ?, ?, 'text', ?, ?)",
                (f"{prefix}-{i}", src[0], f"soubor{i}.txt",
                 f"2026-01-0{ i + 1}T03:04:05Z", f"soubor {i}"),
            )
        con.commit()
    finally:
        con.close()


def _audit_entries(client, cid: str) -> list[dict]:
    r = client.get(f"/api/cases/{cid}/audit?limit=500")
    assert r.status_code == 200, r.text
    return r.json().get("entries", [])


def _audit_count(client, cid: str) -> int:
    return len(_audit_entries(client, cid))


# ── cache vzniká při exportu ────────────────────────────────────────


class TestExportCachesFile:
    def test_export_creates_cache_file(self, client, evidence):
        """interop-export uloží trvalou cache na {db_dir}/exports/{cid}/{what}.{format}."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        r = c.get(f"/api/cases/{cid}/interop-export",
                  params={"what": "artifacts", "format": "csv"})
        assert r.status_code == 200, r.text

        cache = tmp / "exports" / cid / "artifacts.csv"
        assert cache.is_file(), "cache soubor po exportu chybí"
        # obsah cache = obsah odpovědi (stejný serializátor). Binární čtení —
        # read_text() by normalizoval \r\n → \n a falešně nahlásil rozdíl.
        assert cache.read_bytes().decode("utf-8") == r.text

    def test_cache_no_leftover_tmp(self, client, evidence):
        """Atomický zápis nenechá za sebou .tmp soubor."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=1)

        r = c.get(f"/api/cases/{cid}/interop-export",
                  params={"what": "artifacts", "format": "json"})
        assert r.status_code == 200, r.text

        leftovers = list((tmp / "exports" / cid).glob("*.tmp"))
        assert leftovers == [], f"zbylý tmp soubor: {leftovers}"


# ── re-download z cache ─────────────────────────────────────────────


class TestLastExportDownload:
    def test_returns_cached_content(self, client, evidence):
        """Re-download vrátí přesně ten obsah, který export vrátil."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        r1 = c.get(f"/api/cases/{cid}/interop-export",
                   params={"what": "artifacts", "format": "csv"})
        assert r1.status_code == 200, r1.text

        r2 = c.get(f"/api/cases/{cid}/last-export",
                   params={"what": "artifacts", "format": "csv"})
        assert r2.status_code == 200, r2.text
        assert r2.text == r1.text
        assert r2.headers["content-type"].startswith("text/csv")

    def test_attachment_filename(self, client, evidence):
        """Content-Disposition: attachment s {case_id}_{what}.{format}."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=1)

        r = c.get(f"/api/cases/{cid}/interop-export",
                  params={"what": "timeline", "format": "l2tcsv"})
        assert r.status_code == 200, r.text

        dl = c.get(f"/api/cases/{cid}/last-export",
                   params={"what": "timeline", "format": "l2tcsv"})
        assert dl.status_code == 200, dl.text
        cd = dl.headers["content-disposition"]
        assert 'attachment' in cd
        assert f'{case["id"]}_timeline.l2tcsv' in cd

    def test_second_export_overwrites_cache(self, client, evidence):
        """Poslední výhra — druhý export (jiná data) cache přepíše."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        r1 = c.get(f"/api/cases/{cid}/interop-export",
                   params={"what": "artifacts", "format": "csv"})
        assert r1.status_code == 200, r1.text

        # přidat další artifact → export má jiný obsah
        _seed_artifacts(_db_path(tmp, cid), n=1, prefix="art-le-2")
        r2 = c.get(f"/api/cases/{cid}/interop-export",
                   params={"what": "artifacts", "format": "csv"})
        assert r2.status_code == 200, r2.text
        assert r2.text != r1.text

        dl = c.get(f"/api/cases/{cid}/last-export",
                   params={"what": "artifacts", "format": "csv"})
        assert dl.status_code == 200, dl.text
        assert dl.text == r2.text, "cache musí nést poslední export"

    def test_per_dataset_format_isolation(self, client, evidence):
        """Cache je per dataset+formát — jiný formát neovlivní první."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=1)

        r_csv = c.get(f"/api/cases/{cid}/interop-export",
                      params={"what": "artifacts", "format": "csv"})
        assert r_csv.status_code == 200, r_csv.text
        r_json = c.get(f"/api/cases/{cid}/interop-export",
                       params={"what": "artifacts", "format": "json"})
        assert r_json.status_code == 200, r_json.text

        dl_csv = c.get(f"/api/cases/{cid}/last-export",
                       params={"what": "artifacts", "format": "csv"})
        dl_json = c.get(f"/api/cases/{cid}/last-export",
                        params={"what": "artifacts", "format": "json"})
        assert dl_csv.status_code == 200 and dl_csv.text == r_csv.text
        assert dl_json.status_code == 200 and dl_json.text == r_json.text


# ── chybové cesty + read-only sémantika ──────────────────────────────


class TestValidation:
    def test_404_without_cache(self, client, evidence):
        """Případ existuje, ale nic neexportováno → 404."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        r = c.get(f"/api/cases/{cid}/last-export",
                  params={"what": "artifacts", "format": "csv"})
        assert r.status_code == 404

    def test_404_unknown_case(self, client):
        """Neznámý případ → 404 (i kdyby cache náhodou existovala)."""
        c, _tmp = client
        r = c.get("/api/cases/neexistujici-pripad/last-export",
                  params={"what": "artifacts", "format": "csv"})
        assert r.status_code == 404

    def test_invalid_dataset_400(self, client):
        c, _tmp = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/last-export", params={"what": "bogus"})
        assert r.status_code == 400

    def test_invalid_format_400(self, client):
        c, _tmp = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/last-export",
                  params={"what": "artifacts", "format": "pdf"})
        assert r.status_code == 400

    def test_read_only_egress_audit(self, client, evidence):
        """Re-download je read-only — nemění stav případu. Od B3b píše jediný
        egress audit záznam (`export_redownloaded`) za každý stažený formát, aby
        bylo forenzně vidět, kdy data opustila systém. Původní kontrakt STP-067
        („bez auditu — re-download není akcí“) tímto záměrně upraven."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        for fmt in ("csv", "json", "l2tcsv"):  # všechny tři formáty exportovat
            rr = c.get(f"/api/cases/{cid}/interop-export",
                       params={"what": "artifacts", "format": fmt})
            assert rr.status_code == 200, rr.text
        before = _audit_entries(c, cid)
        assert len(before) > 0, "export musí zapsat audit"

        for fmt in ("csv", "json", "l2tcsv"):
            rr = c.get(f"/api/cases/{cid}/last-export",
                       params={"what": "artifacts", "format": fmt})
            assert rr.status_code == 200, rr.text
        after = _audit_entries(c, cid)

        added = (Counter(e.get("action") for e in after)
                 - Counter(e.get("action") for e in before))
        assert dict(added) == {"export_redownloaded": 3}, \
            f"re-download píše přesně 1 egress záznam na formát: {dict(added)}"
