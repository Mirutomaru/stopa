"""F2.2 — DuckDB OLAP vrstva: staleness, parity s SQLite, CLI/web wiring, cleanup.

Plnoškálový AK (10M eventů / 1 h < 2 s; agregace < 5 s) běží v
``scripts/bench_f22_analytics.py`` — zde je rychlý proxy na 200k událostech,
aby zůstala suite offline a rychle zelená.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DUCKDB = pytest.importorskip("duckdb")  # F2.2 vyžaduje extra [analytics]


@pytest.fixture()
def case_db(tmp_path: Path) -> tuple[Path, str]:
    """Case DB s případem, zdrojem, timeline událostmi a entitami."""
    from stopa.data.db import CaseDB
    from stopa.models import Case, EvidenceSource

    db_file = tmp_path / "case-f22test.db"
    db = CaseDB(db_file)
    case = Case(id="case-f22test", name="F2.2 Test")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/tmp/seed")
    db.add_source(src)

    base = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    types = ("browser_history", "chat_message", "file_access")
    for i in range(30):
        db.add_timeline_event(
            source_id=src.id,
            ts_utc=base + timedelta(minutes=i * 5),  # rozloženo do ~2,5 h
            event_type=types[i % len(types)],
            rel_path=f"/seed/f{i % 7}.log",
            title=f"ev-{i}",
            confidence=0.8,
        )
    db.upsert_entities(
        "case-f22test",
        [
            ("email", "matus@example.com", None, base.isoformat(), (base + timedelta(hours=1)).isoformat()),
            ("phone", "+420777123456", "+420 777 123 456", base.isoformat(), None),
        ],
    )
    db.commit()
    db.close()
    return db_file, src.id


# ── bulk generátor (SQL series — bez Python loopu) pro perf proxy ──

def _bulk_events(db_file: Path, n: int = 200_000, chunk: int = 50_000) -> None:
    con = sqlite3.connect(db_file)
    try:
        sid = con.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
        con.execute(
            "CREATE TEMP TABLE gen AS WITH RECURSIVE s(n) AS (SELECT 0 UNION ALL"
            " SELECT n+1 FROM s WHERE n < ?) SELECT n FROM s",
            (chunk - 1,),
        )
        base = "2026-11-09T12:00:00Z"
        for c in range((n + chunk - 1) // chunk):
            remaining = min(chunk, n - c * chunk)
            con.execute(
                """INSERT INTO timeline_events (id, source_id, rel_path, event_type, ts_utc, title, confidence, ts_origin)
                   SELECT 'bulk' || (? + g.n), ?, '/seed/f' || (g.n % 40) || '.log',
                          CASE WHEN g.n % 2 = 0 THEN 'browser_history' ELSE 'chat_message' END,
                          strftime('%Y-%m-%dT%H:%M:%SZ', ? , '+' || ((? + g.n) * 3599 / ?) || ' seconds'),
                          'bulk-' || (g.n % 100), 0.9, 'source'
                   FROM gen g WHERE g.n < ?""",
                (c * chunk, sid, base, c * chunk, n, remaining),
            )
        con.commit()
    finally:
        con.close()


# ── staleness / freshness ────────────────────────────────────────

def test_refresh_counts_and_fresh(case_db):
    from stopa.data.analytics import AnalyticsStore

    db_file, _ = case_db
    store = AnalyticsStore(db_file)
    counts = store.refresh()
    assert counts["timeline_events"] == 30
    assert counts["entities"] == 2
    st = store.status()
    assert st["fresh"] is True
    assert st["snapshot"]["timeline_events"] == 30


def test_staleness_auto_refresh_rw(case_db):
    from stopa.data.analytics import AnalyticsStore
    from stopa.data.db import CaseDB

    db_file, sid = case_db
    store = AnalyticsStore(db_file)
    assert store.status()["fresh"] is True

    # mutace z DRUHÉHO procesu (nová konexe) → signatura musí chytit stale
    db2 = CaseDB(db_file)
    base = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    db2.add_timeline_event(source_id=sid, ts_utc=base + timedelta(hours=3), event_type="chat_message", title="late")
    db2.commit()
    db2.close()

    st = store.status()  # RW → auto-refresh
    assert st["fresh"] is True
    assert st["live"]["timeline_events"] == 31


def test_stale_readonly_signals_and_raises(case_db):
    from stopa.data.analytics import AnalyticsError, AnalyticsStore
    from stopa.data.db import CaseDB

    db_file, sid = case_db
    store_rw = AnalyticsStore(db_file)
    assert store_rw.status()["fresh"] is True

    ro = AnalyticsStore(db_file, readonly=True)
    # mutace po open → readonly store musí hlásit stale a odmítnout query
    db2 = CaseDB(db_file)
    base = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    db2.add_timeline_event(source_id=sid, ts_utc=base + timedelta(hours=3), event_type="chat_message", title="late")
    db2.commit()
    db2.close()

    st = ro.status()
    assert st["fresh"] is False
    assert st["readonly"] is True
    with pytest.raises(AnalyticsError):
        ro.timeline_range("2026-11-09T12:00:00+00:00", "2026-11-09T15:00:00+00:00")


def test_readonly_refresh_rejected(case_db):
    from stopa.data.analytics import AnalyticsError, AnalyticsStore

    db_file, _ = case_db
    ro = AnalyticsStore(db_file, readonly=True)
    with pytest.raises(AnalyticsError):
        ro.refresh()


# ── parity s SQLite cestou ────────────────────────────────────────

def test_timeline_range_parity(case_db):
    from stopa.data.analytics import AnalyticsStore
    from stopa.data.db import CaseDB

    db_file, _ = case_db
    store = AnalyticsStore(db_file)
    frm = datetime(2026, 11, 9, 12, 30, tzinfo=timezone.utc).isoformat()
    to = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc).isoformat()

    duck_rows = store.timeline_range(frm, to)
    db = CaseDB(db_file)
    sqlite_rows = db.list_timeline_events(
        from_ts=datetime.fromisoformat(frm), to_ts=datetime.fromisoformat(to)
    )
    db.close()

    assert len(duck_rows) == len(sqlite_rows) > 0
    duck_ids = {r["id"] for r in duck_rows}
    sqlite_ids = {e["id"] for e in sqlite_rows}
    assert duck_ids == sqlite_ids


def test_timeline_range_type_filter_and_limit(case_db):
    from stopa.data.analytics import AnalyticsStore

    db_file, _ = case_db
    store = AnalyticsStore(db_file)
    frm = "2026-11-09T12:00:00+00:00"
    to = "2026-11-09T15:00:00+00:00"

    all_rows = store.timeline_range(frm, to)
    chats = store.timeline_range(frm, to, event_type="chat_message")
    assert len(all_rows) == 30
    assert len(chats) == 10
    assert {r["event_type"] for r in chats} == {"chat_message"}

    limited = store.timeline_range(frm, to, limit=5)
    assert len(limited) == 5


def test_histogram_and_top_types_parity(case_db):
    from stopa.data.analytics import AnalyticsStore

    db_file, _ = case_db
    store = AnalyticsStore(db_file)
    hist = store.hourly_histogram()
    tops = store.top_event_types(limit=10)

    # 30 událostí v rozmezí 12:00–14:15 UTC → 3 hodinové buckety (12, 13, 14)
    assert {h["hour"][:13] for h in hist} == {"2026-11-09T12", "2026-11-09T13", "2026-11-09T14"}
    assert sum(h["events"] for h in hist) == 30

    # typy se střídají → po 10; řazení sestupně, při rovnosti stabilní
    assert [t["count"] for t in tops] == sorted([10, 10, 10], reverse=True)
    assert {t["event_type"] for t in tops} == {"browser_history", "chat_message", "file_access"}

    # okno omezí agregaci
    windowed = store.hourly_histogram(from_ts="2026-11-09T13:00:00+00:00")
    assert sum(h["events"] for h in windowed) < 30


def test_entity_summary(case_db):
    from stopa.data.analytics import AnalyticsStore

    db_file, _ = case_db
    store = AnalyticsStore(db_file)
    summary = {row["kind"]: row for row in store.entity_summary()}
    assert set(summary) == {"email", "phone"}
    assert summary["email"]["count"] == 1
    assert summary["email"]["earliest_first_seen"].startswith("2026-11-09T12:00")


# ── cleanup ───────────────────────────────────────────────────────

def test_drop_case_analytics(case_db):
    from stopa.data.analytics import AnalyticsStore, case_duckdb_path, drop_case_analytics

    db_file, _ = case_db
    store = AnalyticsStore(db_file)
    store.refresh()
    duck_file = case_duckdb_path(db_file)
    assert duck_file.exists()

    assert drop_case_analytics(db_file) is True
    assert not duck_file.exists()
    # dvojitý drop je idempotentní
    assert drop_case_analytics(db_file) is False


def test_missing_db_raises(tmp_path: Path):
    from stopa.data.analytics import AnalyticsError, AnalyticsStore

    with pytest.raises(AnalyticsError):
        AnalyticsStore(tmp_path / "nope.db")


# ── perf proxy (rychlá verze AK; plná škála = bench skript) ───────

def test_perf_200k_range_and_aggregation(case_db, tmp_path: Path):
    import time

    from stopa.data.analytics import AnalyticsStore

    db_file, _ = case_db
    _bulk_events(db_file, n=200_000)
    store = AnalyticsStore(db_file)
    # 200k bulk + 30 z fixture
    assert store.status()["live"]["timeline_events"] == 200_030

    t0 = time.perf_counter()
    rows = store.timeline_range("2026-11-09T12:00:00+00:00", "2026-11-09T13:00:00+00:00", limit=10_000)
    t_range = time.perf_counter() - t0
    assert len(rows) == 10_000
    assert t_range < 2.0, f"AK proxy porušeno: {t_range:.3f}s"

    t0 = time.perf_counter()
    hist = store.hourly_histogram()
    tops = store.top_event_types(limit=20)
    t_agg = time.perf_counter() - t0
    assert sum(h["events"] for h in hist) == 200_030
    assert tops and tops[0]["count"] > 0
    assert t_agg < 5.0, f"AK agregace proxy porušeno: {t_agg:.3f}s"


# ── CLI wiring ────────────────────────────────────────────────────

def test_cli_analytics_json(case_db, tmp_path: Path, monkeypatch, capsys):
    from stopa.cli import main

    db_file, _ = case_db
    cli_dir = tmp_path / "cli_cases"
    cli_dir.mkdir()
    (cli_dir / "case-f22test.db").write_bytes(db_file.read_bytes())
    monkeypatch.setenv("STOPA_DB_DIR", str(cli_dir))

    rc = main(
        [
            "analytics", "case-f22test",
            "--from-ts", "2026-11-09T12:30:00+00:00",
            "--to-ts", "2026-11-09T14:00:00+00:00",
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["case_id"] == "case-f22test"
    assert payload["status"]["fresh"] is True
    assert payload["timeline_window"]["count"] > 0


def test_cli_analytics_no_duckdb(case_db, tmp_path: Path, monkeypatch, capsys):
    from stopa.cli import main

    db_file, _ = case_db
    cli_dir = tmp_path / "cli_cases"
    cli_dir.mkdir()
    (cli_dir / "case-f22test.db").write_bytes(db_file.read_bytes())
    monkeypatch.setenv("STOPA_DB_DIR", str(cli_dir))
    from stopa.data import analytics

    monkeypatch.setattr(analytics, "duckdb_available", lambda: False)

    rc = main(["analytics", "case-f22test"])
    assert rc == 3
    assert "stopa[analytics]" in capsys.readouterr().out


def test_cli_analytics_missing_case(tmp_path: Path, monkeypatch):
    from stopa.cli import main

    cli_dir = tmp_path / "cli_cases"
    cli_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(cli_dir))
    with pytest.raises(SystemExit):
        main(["analytics", "case-neexistuje"])


# ── web wiring ────────────────────────────────────────────────────

def test_web_analytics_endpoint(case_db, tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    db_file, _ = case_db
    app_dir = tmp_path / "web_cases"
    app_dir.mkdir()
    (app_dir / "case-f22test.db").write_bytes(db_file.read_bytes())
    with TestClient(create_app(db_dir=app_dir)) as client:
        r = client.get("/api/cases/case-f22test/analytics")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"]["fresh"] is True
        assert any(t["event_type"] == "browser_history" for t in body["top_event_types"])
        kinds = {e["kind"] for e in body["entity_summary"]}
        assert {"email", "phone"} <= kinds

        r2 = client.get(
            "/api/cases/case-f22test/analytics",
            params={"from_ts": "2026-11-09T12:30:00+00:00", "to_ts": "2026-11-09T14:00:00+00:00"},
        )
        assert r2.status_code == 200, r2.text
        win = r2.json()["timeline_window"]
        assert win["count"] > 0


def test_web_analytics_no_duckdb(case_db, tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from stopa.data import analytics
    from stopa.web.app import create_app

    db_file, _ = case_db
    app_dir = tmp_path / "web_cases"
    app_dir.mkdir()
    (app_dir / "case-f22test.db").write_bytes(db_file.read_bytes())
    monkeypatch.setattr(analytics, "duckdb_available", lambda: False)

    with TestClient(create_app(db_dir=app_dir)) as client:
        r = client.get("/api/cases/case-f22test/analytics")
        assert r.status_code == 503
        assert "[analytics]" in r.json()["detail"]


def test_web_delete_case_drops_analytics(case_db, tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.data.analytics import case_duckdb_path
    from stopa.web.app import create_app

    db_file, _ = case_db
    app_dir = tmp_path / "web_cases"
    app_dir.mkdir()
    (app_dir / "case-f22test.db").write_bytes(db_file.read_bytes())
    duck_file = case_duckdb_path(app_dir / "case-f22test.db")

    with TestClient(create_app(db_dir=app_dir)) as client:
        # materiálovat (přes analytics endpoint — auto-refresh)
        r0 = client.get("/api/cases/case-f22test/analytics")
        assert r0.status_code == 200, r0.text
        assert duck_file.exists()

        r = client.delete("/api/cases/case-f22test")
        assert r.status_code == 200, r.text
    # po smazání případu musí zmizet i odvozený DuckDB stav
    assert not duck_file.exists()


def test_analytics_store_reuses_connection(case_db):
    """Dva store na stejnou DB sdílejí konexi (web = multi-thread)."""
    from stopa.data.analytics import AnalyticsStore

    db_file, _ = case_db
    s1 = AnalyticsStore(db_file)
    s2 = AnalyticsStore(db_file)
    assert s1._con is s2._con


def test_duckdb_available_true():
    from stopa.data.analytics import duckdb_available

    assert duckdb_available() is True
