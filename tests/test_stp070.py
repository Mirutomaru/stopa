"""STOPA STP-070 — Periodický plánovač auto-bundle (oblast Q ★★).

Rozšíření uzavřeného STP-069 (opt-in auto-export po ``process_source``) o
časový interval: web scheduler pravidelně projde případy s zapnutým
auto-expor­tem a vygeneruje bundle, pokud od posledního spuštění uplynul
nastavený interval.

Pokrytí:
- Čistá doménová logika (offline): ``parse_interval_minutes`` (validace
  rozsahu/formátu) + ``is_due`` (rozhodnutí „je čas“).
- Web E2E přes TestClient s reálnou case DB: PATCH nastaví interval,
  persistuje a serializuje v list/detail; explicitní null ho vymaže;
  neplatná hodnota → 422.
- Scheduler tick (``run_auto_export_tick``): due případ dostane deterministický
  ZIP bundle + persistovaný čas spuštění; nedue případ se přeskočí.

Běží offline, deterministicky (explicitní ``now_utc``). Vzor fixtur: STP-069.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ── fixtury + seed pomocníci (stejný vzor jako STP-069) ─────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka", encoding="utf-8")
    return ev


def _make_case(client, name: str = "Scheduler test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client, cid: str, evidence: Path) -> None:
    """Sync ingest (default background=False) — čeká na dokončení process_source."""
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
    assert r.status_code in (200, 201), r.text


def _db_path(tmp_dir: Path, cid: str) -> Path:
    return tmp_dir / f"{cid}.db"


def _seed_artifacts(dbp: Path, n: int = 3) -> None:
    """Ingest nevytvoří artifacts (ty vznikají analýzou) — doplní N řádků."""
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO artifacts (id, source_id, rel_path, artifact_type,"
                " timestamp, title) VALUES (?, ?, ?, 'text', ?, ?)",
                (f"art-s70-{i}", src[0], f"soubor{i}.txt",
                 f"2026-01-0{i + 1}T03:04:05Z", f"soubor {i}"),
            )
        con.commit()
    finally:
        con.close()


def _enable_auto_export(client, cid: str) -> None:
    r = client.patch(f"/api/cases/{cid}", json={"auto_export_enabled": True})
    assert r.status_code == 200, r.text


# ── čistá doménová logika (offline) ────────────────────────────────


class TestParseInterval:
    def test_none_returns_none(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        assert parse_interval_minutes(None) is None

    def test_empty_string_returns_none(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        assert parse_interval_minutes("") is None
        assert parse_interval_minutes("   ") is None

    def test_valid_int(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        assert parse_interval_minutes(60) == 60
        assert parse_interval_minutes(5) == 5          # minimum
        assert parse_interval_minutes(43_200) == 43_200  # maximum (30 dní)

    def test_numeric_string(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        assert parse_interval_minutes("120") == 120
        assert parse_interval_minutes("  90  ") == 90

    def test_below_min_raises(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        with pytest.raises(ValueError):
            parse_interval_minutes(4)

    def test_above_max_raises(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        with pytest.raises(ValueError):
            parse_interval_minutes(43_201)

    def test_non_numeric_string_raises(self):
        from stopa.domain.export_schedule import parse_interval_minutes

        with pytest.raises(ValueError):
            parse_interval_minutes("hodina")


class TestIsDue:
    NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

    def test_never_run_is_due(self):
        from stopa.domain.export_schedule import is_due

        assert is_due(None, self.NOW, 60) is True

    def test_within_interval_not_due(self):
        from stopa.domain.export_schedule import is_due

        last = self.NOW - timedelta(minutes=30)
        assert is_due(last, self.NOW, 60) is False

    def test_exactly_at_interval_is_due(self):
        from stopa.domain.export_schedule import is_due

        last = self.NOW - timedelta(minutes=60)
        assert is_due(last, self.NOW, 60) is True

    def test_past_interval_is_due(self):
        from stopa.domain.export_schedule import is_due

        last = self.NOW - timedelta(hours=3)
        assert is_due(last, self.NOW, 60) is True


# ── web E2E: PATCH interval + persistence + serializace ────────────


class TestIntervalApi:
    def test_default_none(self, client):
        """Nový případ nemá interval nastaven (None)."""
        c, _tmp = client
        case = _make_case(c)

        r = c.get(f"/api/cases/{case['id']}")
        assert r.status_code == 200, r.text
        assert r.json()["auto_export_interval_minutes"] is None

    def test_patch_sets_persists_serializes(self, client):
        """PATCH nastaví interval; persistuje v DB a serializuje v list/detail."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]

        r = c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 120})
        assert r.status_code == 200, r.text
        assert r.json()["auto_export_interval_minutes"] == 120

        # detail + list serializují hodnotu pro UI input
        assert c.get(f"/api/cases/{cid}").json()["auto_export_interval_minutes"] == 120
        listing = c.get("/api/cases").json()
        row = next(x for x in listing if x["id"] == cid)
        assert row["auto_export_interval_minutes"] == 120

        # persistence v DB (přečtení přes sqlite, ne jen API cache)
        raw = sqlite3.connect(_db_path(tmp, cid)).execute(
            "SELECT auto_export_interval_minutes FROM cases WHERE id = ?", (cid,)
        ).fetchone()[0]
        assert raw == 120

    def test_patch_null_clears(self, client):
        """Explicitní null interval vymaže (None)."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 120})

        r = c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": None})
        assert r.status_code == 200, r.text
        assert r.json()["auto_export_interval_minutes"] is None

    def test_patch_invalid_value_422(self, client):
        """Neplatná hodnota (mimo rozsah) → 422."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]

        r = c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 1})
        assert r.status_code == 422, r.text

    def test_patch_other_fields_do_not_touch_interval(self, client):
        """PATCH jiných polí (name) interval nemění."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 90})

        r = c.patch(f"/api/cases/{cid}", json={"name": "Přejmenováno"})
        assert r.status_code == 200, r.text
        assert r.json()["auto_export_interval_minutes"] == 90


# ── scheduler tick: due → bundle + persistovaný čas; nedue → skip ───


class TestSchedulerTick:
    def test_due_case_generates_bundle(self, client, evidence):
        """Due případ (nikdy nespuštěný) dostane ZIP + persistovaný čas."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        # ingest PŘED zapnutím auto-exportu → hook nenastaví last_auto_export_at
        _add_source(c, cid, evidence)
        _enable_auto_export(c, cid)
        c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 60})
        _seed_artifacts(_db_path(tmp, cid), n=3)

        from stopa.web.app import run_auto_export_tick

        now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        results = run_auto_export_tick(tmp, now_utc=now)

        # přesně jeden bundle pro náš case
        assert len(results) == 1, results
        assert results[0]["case_id"] == cid
        out_path = Path(results[0]["path"])
        assert out_path.exists(), "ZIP bundle nebyl uložen"
        assert out_path.stat().st_size > 0

        # persistovaný čas spuštění v DB
        raw = sqlite3.connect(_db_path(tmp, cid)).execute(
            "SELECT last_auto_export_at FROM cases WHERE id = ?", (cid,)
        ).fetchone()[0]
        assert raw == now.isoformat()

    def test_not_due_case_skipped(self, client, evidence):
        """Nedue případ (poslední spuštění v intervalu) se nepřegeneruje."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _enable_auto_export(c, cid)
        c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 60})
        _seed_artifacts(_db_path(tmp, cid), n=3)

        # naplánujme „poslední spuštění“ před 10 min (interval 60 → nedue)
        recent = datetime(2026, 11, 9, 11, 50, tzinfo=timezone.utc)
        con = sqlite3.connect(_db_path(tmp, cid))
        try:
            con.execute(
                "UPDATE cases SET last_auto_export_at = ? WHERE id = ?",
                (recent.isoformat(), cid),
            )
            con.commit()
        finally:
            con.close()

        from stopa.web.app import run_auto_export_tick

        now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        results = run_auto_export_tick(tmp, now_utc=now)

        # náš case se nepřegeneroval (je nedue)
        assert all(r["case_id"] != cid for r in results), results

    def test_disabled_case_skipped(self, client, evidence):
        """Případ s vypnutým auto-exportem se ignoruje i když je due."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        # auto_export_enabled zůstává default False
        _add_source(c, cid, evidence)
        c.patch(f"/api/cases/{cid}", json={"auto_export_interval_minutes": 60})
        _seed_artifacts(_db_path(tmp, cid), n=3)

        from stopa.web.app import run_auto_export_tick

        now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        results = run_auto_export_tick(tmp, now_utc=now)

        assert all(r["case_id"] != cid for r in results), results
