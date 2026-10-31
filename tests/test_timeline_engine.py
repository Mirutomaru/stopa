"""E2 Timeline Engine — materializovaná timeline, TZ konverze, detekce nesrovnalostí.

Pokrytí (dle DEVELOPMENT_ROADMAP ETAPA 2):
- 3 anomaly pravidla (mtime_before_ctime, out_of_range, duplicate) — čistá logika
- to_local_iso: UTC → lokální čas (Europe/Prague), fallback na neznámé TZ
- DB timeline metody: add/list/clear/window + filtry
- Migrace staré case DB (timezone_name + provenience sloupce)
- Pipeline E2E: materializace timeline + provenience (extracted_at, parser_version)
- Web endpoint /timeline: TZ konverze + filtry + backward-kompatibilní aliasy
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.timeline_anomaly import (
    FLAG_DUPLICATE,
    FLAG_MTIME_BEFORE_CTIME,
    FLAG_OUT_OF_RANGE,
    AnomalyContext,
    check_duplicate,
    check_mtime_before_ctime,
    check_out_of_range,
    detect_anomalies,
)
from stopa.domain.times import to_local_iso
from stopa.models import Case, EvidenceSource

# ── fixtures ───────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


def _chrome_ts(unix_seconds: int) -> int:
    """unix s → Chrome µs od Windows epochy (1601)."""
    return (unix_seconds + 11_644_473_600) * 1_000_000


@pytest.fixture
def chrome_history(tmp_path: Path) -> Path:
    """Syntetická Chrome history DB s známými timestampy."""
    p = tmp_path / "History"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
        " visit_time INTEGER, from_visit INTEGER)"
    )
    # 2024-01-15T10:00:00Z = 1705312800 s
    conn.execute("INSERT INTO urls VALUES (1, 'https://example.com/a', 'Stránka A')")
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (1, ?)", (_chrome_ts(1_705_312_800),)
    )
    # 2024-01-15T11:00:00Z = 1705316400 s
    conn.execute("INSERT INTO urls VALUES (2, 'https://shop.cz/b', 'Obchod B')")
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (2, ?)", (_chrome_ts(1_705_316_400),)
    )
    conn.commit()
    conn.close()
    return p


@pytest.fixture
def evidence_with_history(tmp_path: Path, chrome_history: Path) -> Path:
    """Evidence source s reálnou Chrome history DB (pro pipeline E2E)."""
    root = tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    # zkopíruj History do evidence stromu
    import shutil
    shutil.copy2(chrome_history, root / "History")
    return root


# ── 1. Anomaly pravidla (čistá logika) ─────────────────────────

class TestMtimeBeforeCtime:
    def test_mtime_before_ctime_detected(self):
        mtime = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ctime = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert check_mtime_before_ctime(mtime, ctime) is True

    def test_normal_order_no_flag(self):
        mtime = datetime(2024, 6, 1, tzinfo=timezone.utc)
        ctime = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert check_mtime_before_ctime(mtime, ctime) is False

    def test_equal_times_no_flag(self):
        t = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert check_mtime_before_ctime(t, t) is False

    def test_none_mtime_no_flag(self):
        ctime = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert check_mtime_before_ctime(None, ctime) is False


class TestOutOfRange:
    def _ctx(self, start: datetime, end: datetime) -> AnomalyContext:
        return AnomalyContext(window_start=start, window_end=end)

    def test_within_range_no_flag(self):
        ctx = self._ctx(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        assert check_out_of_range(ts, ctx) is False

    def test_before_window_flagged(self):
        ctx = self._ctx(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)  # rok před oknem
        assert check_out_of_range(ts, ctx) is True

    def test_after_window_flagged(self):
        ctx = self._ctx(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        ts = datetime(2025, 6, 1, tzinfo=timezone.utc)  # rok po okně
        assert check_out_of_range(ts, ctx) is True

    def test_within_tolerance_no_flag(self):
        """V rámci tolerance (30 dní) se nehlásí."""
        ctx = self._ctx(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        ts = datetime(2023, 12, 15, tzinfo=timezone.utc)  # 17 dní před oknem
        assert check_out_of_range(ts, ctx) is False

    def test_no_window_no_flag(self):
        """První extrakce — okno neznámé → pravidlo se nepoužije."""
        ctx = AnomalyContext()
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert check_out_of_range(ts, ctx) is False

    def test_none_ts_no_flag(self):
        ctx = self._ctx(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        assert check_out_of_range(None, ctx) is False


class TestDuplicate:
    def test_same_key_within_1s_flagged(self):
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        seen = [(ts - timedelta(milliseconds=500), "browser_history|Stránka A|History")]
        assert check_duplicate(ts, "browser_history|Stránka A|History", seen) is True

    def test_same_key_different_time_no_flag(self):
        ts = datetime(2024, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
        seen = [(ts - timedelta(seconds=10), "browser_history|Stránka A|History")]
        assert check_duplicate(ts, "browser_history|Stránka A|History", seen) is False

    def test_different_key_no_flag(self):
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        seen = [(ts - timedelta(milliseconds=500), "imessage|Zpráva X|chat.db")]
        assert check_duplicate(ts, "browser_history|Stránka A|History", seen) is False

    def test_none_ts_no_flag(self):
        seen = [(datetime(2024, 1, 1, tzinfo=timezone.utc), "key")]
        assert check_duplicate(None, "key", seen) is False


class TestDetectAnomalies:
    def test_clean_event_no_flags(self):
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        ctx = AnomalyContext(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        flags = detect_anomalies("browser_history", ts, title="A", ctx=ctx)
        assert flags == ()

    def test_mtime_before_ctime_flag(self):
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        ctx = AnomalyContext()
        mtime = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ctime = datetime(2024, 6, 1, tzinfo=timezone.utc)
        flags = detect_anomalies(
            "browser_history", ts, file_mtime=mtime, file_ctime=ctime, ctx=ctx
        )
        assert FLAG_MTIME_BEFORE_CTIME in flags

    def test_out_of_range_flag(self):
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        ctx = AnomalyContext(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        flags = detect_anomalies("browser_history", ts, ctx=ctx)
        assert FLAG_OUT_OF_RANGE in flags

    def test_duplicate_flag(self):
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        key = "browser_history|Stránka A|History"
        ctx = AnomalyContext(seen_timestamps=[(ts - timedelta(milliseconds=100), key)])
        flags = detect_anomalies("browser_history", ts, title="Stránka A", rel_path="History", ctx=ctx)
        assert FLAG_DUPLICATE in flags

    def test_multiple_flags_combined(self):
        """Více pravidel najednou — všechny flagy se hromadí."""
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        key = "browser_history|A|History"
        ctx = AnomalyContext(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2024, 6, 1, tzinfo=timezone.utc),
            seen_timestamps=[(ts - timedelta(milliseconds=50), key)],
        )
        mtime = datetime(2023, 1, 1, tzinfo=timezone.utc)
        ctime = datetime(2024, 6, 1, tzinfo=timezone.utc)
        flags = detect_anomalies(
            "browser_history", ts, title="A", rel_path="History",
            file_mtime=mtime, file_ctime=ctime, ctx=ctx,
        )
        assert FLAG_MTIME_BEFORE_CTIME in flags
        assert FLAG_OUT_OF_RANGE in flags
        assert FLAG_DUPLICATE in flags

    def test_none_ts_only_mtime_rule(self):
        """Bez timestampu — jen mtime/ctime pravidlo může vyhodit flag."""
        ctx = AnomalyContext()
        mtime = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ctime = datetime(2024, 6, 1, tzinfo=timezone.utc)
        flags = detect_anomalies("browser_history", None, file_mtime=mtime, file_ctime=ctime, ctx=ctx)
        assert FLAG_MTIME_BEFORE_CTIME in flags


# ── 2. TZ konverze (to_local_iso) ─────────────────────────────

class TestToLocalIso:
    def test_utc_to_prague_summer(self):
        """Létní čas CEST = UTC+2."""
        dt = datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = to_local_iso(dt, "Europe/Prague")
        assert result is not None
        # 12:00 UTC → 14:00 CEST
        assert "+02:00" in result

    def test_utc_to_prague_winter(self):
        """Zimní čas CET = UTC+1."""
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = to_local_iso(dt, "Europe/Prague")
        assert result is not None
        # 12:00 UTC → 13:00 CET
        assert "+01:00" in result

    def test_utc_to_utc(self):
        dt = datetime(2024, 6, 15, 8, 30, 0, tzinfo=timezone.utc)
        result = to_local_iso(dt, "UTC")
        assert result is not None
        assert "+00:00" in result

    def test_naive_datetime_treated_as_utc(self):
        """Naivní datetime → interpretace jako UTC."""
        dt = datetime(2024, 7, 15, 12, 0, 0)  # bez tzinfo
        result = to_local_iso(dt, "Europe/Prague")
        assert result is not None
        assert "+02:00" in result

    def test_unknown_tz_fallback_to_utc(self):
        """Neznámé TZ → fallback na UTC (bez výjimky)."""
        dt = datetime(2024, 6, 15, 8, 30, 0, tzinfo=timezone.utc)
        result = to_local_iso(dt, "Mars/Olympus_Mons")
        assert result is not None
        # fallback → UTC ISO
        assert "+00:00" in result

    def test_none_returns_none(self):
        assert to_local_iso(None, "Europe/Prague") is None


# ── 3. DB timeline metody ──────────────────────────────────────

class TestTimelineDB:
    def _case_and_source(self, db: CaseDB) -> tuple[str, str]:
        c = Case(name="TL test")
        db.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="folder", path="/tmp/ev")
        db.add_source(s)
        return c.id, s.id

    def test_add_and_list(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        eid = db.add_timeline_event(
            source_id=sid, ts_utc=ts, event_type="browser_history", title="Stránka A"
        )
        assert eid.startswith("tl")

        events = db.list_timeline_events(source_id=sid)
        assert len(events) == 1
        assert events[0]["event_type"] == "browser_history"
        assert events[0]["title"] == "Stránka A"
        assert events[0]["ts_utc"].startswith("2024-03-15T12:00:00")

    def test_list_filter_by_event_type(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="browser_history", title="A")
        db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="imessage", title="B")

        browser = db.list_timeline_events(source_id=sid, event_type="browser_history")
        assert len(browser) == 1
        assert browser[0]["title"] == "A"

    def test_list_filter_by_time_range(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        t1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        t2 = datetime(2024, 6, 15, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid, ts_utc=t1, event_type="x", title="early")
        db.add_timeline_event(source_id=sid, ts_utc=t2, event_type="x", title="late")

        # jen od t1
        from_t1 = db.list_timeline_events(source_id=sid, from_ts=t1)
        assert len(from_t1) == 2  # oba (t1 a t2 jsou >= t1)

        # jen do t1
        to_t1 = db.list_timeline_events(source_id=sid, to_ts=t1)
        assert len(to_t1) == 1
        assert to_t1[0]["title"] == "early"

    def test_list_anomalies_only(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="x", title="clean")
        db.add_timeline_event(
            source_id=sid, ts_utc=ts, event_type="x", title="dirty",
            anomaly_flags=(FLAG_OUT_OF_RANGE,),
        )

        all_events = db.list_timeline_events(source_id=sid)
        assert len(all_events) == 2

        anomalies = db.list_timeline_events(source_id=sid, anomalies_only=True)
        assert len(anomalies) == 1
        assert anomalies[0]["title"] == "dirty"
        assert FLAG_OUT_OF_RANGE in anomalies[0]["anomaly_flags"]

    def test_clear_timeline_events(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="x", title="a")
        db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="x", title="b")
        assert len(db.list_timeline_events(source_id=sid)) == 2

        n = db.clear_timeline_events(source_id=sid)
        assert n == 2
        assert len(db.list_timeline_events(source_id=sid)) == 0

    def test_clear_all_sources(self, db: CaseDB):
        cid, sid1 = self._case_and_source(db)
        s2 = EvidenceSource(case_id=cid, kind="folder", path="/tmp/ev2")
        db.add_source(s2)
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid1, ts_utc=ts, event_type="x", title="a")
        db.add_timeline_event(source_id=s2.id, ts_utc=ts, event_type="x", title="b")

        n = db.clear_timeline_events()  # bez source_id → vše
        assert n == 2
        assert len(db.list_timeline_events()) == 0

    def test_timeline_window(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        t1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        t2 = datetime(2024, 6, 15, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid, ts_utc=t1, event_type="x", title="a")
        db.add_timeline_event(source_id=sid, ts_utc=t2, event_type="x", title="b")

        win = db.timeline_window(source_id=sid)
        assert win["window_start"] is not None
        assert win["window_end"] is not None
        # min/max odpovídají vložným časům
        assert win["window_start"].year == 2024
        assert win["window_start"].month == 1
        assert win["window_end"].month == 6

    def test_timeline_window_empty(self, db: CaseDB):
        _, sid = self._case_and_source(db)
        win = db.timeline_window(source_id=sid)
        assert win["window_start"] is None
        assert win["window_end"] is None


# ── 4. Migrace staré case DB ───────────────────────────────────

class TestMigration:
    def test_old_db_gets_timezone_and_provenance(self, tmp_path: Path):
        """Stará DB (bez E2 sloupců) se po open migruje."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        # minimální schéma — jen cases + artifacts bez E2 sloupců
        conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            "CREATE TABLE artifacts ("
            " id TEXT PRIMARY KEY, source_id TEXT, file_id TEXT,"
            " artifact_type TEXT, title TEXT, timestamp TEXT)"
        )
        conn.close()

        d = CaseDB(p)
        assert d.schema_version() == SCHEMA_VERSION

        # cases.timezone_name existuje
        case_cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(cases)").fetchall()}
        assert "timezone_name" in case_cols

        # artifacts E2 sloupce existují
        art_cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        for col in ("confidence", "parser_version", "extracted_at", "anomaly_flags"):
            assert col in art_cols, f"chybí sloupec {col}"

        # timeline_events tabulka existuje
        tables = {r[0] for r in d.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "timeline_events" in tables
        d.close()


# ── 5. Pipeline E2E — materializace + provenience ─────────────

class TestPipelineE2:
    def test_timeline_materialized_with_provenance(
        self, db: CaseDB, evidence_with_history: Path
    ):
        """Pipeline extrahuje artifacty → timeline events s extracted_at + parser_version."""
        from stopa.pipeline import process_source

        c = Case(name="E2 pipeline")
        db.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="folder", path=str(evidence_with_history))
        db.add_source(s)
        result = process_source(db, s.id, evidence_with_history)
        assert result.files_total > 0

        # timeline events materializovány
        events = db.list_timeline_events(source_id=s.id)
        assert len(events) >= 1, "očekávám alespoň jeden timeline event"

        for e in events:
            # provenience — extracted_at je vyplněn
            assert e["extracted_at"] is not None, "extracted_at musí být vyplněn"
            # parser_version je vyplněn (sqlite extraktor)
            if e["event_type"] == "browser_history":
                assert e["parser_version"] is not None

    def test_reingest_idempotent(self, db: CaseDB, evidence_with_history: Path):
        """Re-ingest stejného zdroje → timeline se vyčistí a znovu naplní (bez duplicit)."""
        from stopa.pipeline import process_source

        c = Case(name="E2 reingest")
        db.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="folder", path=str(evidence_with_history))
        db.add_source(s)

        # první ingest
        process_source(db, s.id, evidence_with_history)
        count1 = len(db.list_timeline_events(source_id=s.id))
        assert count1 >= 1

        # re-ingest (stejný zdroj)
        process_source(db, s.id, evidence_with_history)
        count2 = len(db.list_timeline_events(source_id=s.id))

        # počet se nemění — clear + re-materialize
        assert count2 == count1, f"re-ingest změnil počet: {count1} → {count2}"


# ── 6. Web endpoint /timeline ─────────────────────────────────

class TestTimelineEndpoint:
    @pytest.fixture
    def client(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        app = create_app(db_dir=tmp_path)
        with TestClient(app) as c:
            yield c

    def _make_case(self, client) -> str:
        r = client.post("/api/cases", json={"name": "TL endpoint"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_empty_timeline_returns_list(self, client):
        cid = self._make_case(client)
        r = client.get(f"/api/cases/{cid}/timeline")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def _seed_source(self, tmp_path: Path, cid: str) -> tuple[CaseDB, str]:
        """Otevře case DB a vytvoří reálný zdroj (FK pro timeline_events)."""
        db_path = tmp_path / f"{cid}.db"
        d = CaseDB(db_path)
        s = EvidenceSource(case_id=cid, kind="folder", path="/tmp/seed")
        d.add_source(s)
        return d, s.id

    def test_timeline_with_seeded_events(self, client, tmp_path: Path):
        """Seed timeline events přímo do DB → endpoint vrací s ts_local + aliasy."""
        cid = self._make_case(client)

        # seed events přímo do case DB (reálný zdroj pro FK)
        d, sid = self._seed_source(tmp_path, cid)
        ts = datetime(2024, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
        d.add_timeline_event(
            source_id=sid, ts_utc=ts, event_type="browser_history", title="Stránka A"
        )
        d.commit()
        d.close()

        r = client.get(f"/api/cases/{cid}/timeline")
        assert r.status_code == 200
        events = r.json()
        assert len(events) >= 1

        e = events[0]
        # UTC čas je kanonický
        assert "ts_utc" in e
        assert e["ts_utc"].startswith("2024-07-15T12:00:00")
        # lokální čas (Europe/Prague, léto → CEST +2)
        assert "ts_local" in e
        assert "+02:00" in e["ts_local"]
        # backward-kompatibilní aliasy pro staré GUI
        assert e.get("artifact_type") == "browser_history"
        assert e.get("timestamp") is not None

    def test_timeline_filter_by_type(self, client, tmp_path: Path):
        cid = self._make_case(client)
        d, sid = self._seed_source(tmp_path, cid)
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        d.add_timeline_event(source_id=sid, ts_utc=ts, event_type="browser_history", title="A")
        d.add_timeline_event(source_id=sid, ts_utc=ts, event_type="imessage", title="B")
        d.commit()
        d.close()

        r = client.get(f"/api/cases/{cid}/timeline", params={"type": "browser_history"})
        assert r.status_code == 200
        events = r.json()
        assert len(events) == 1
        assert events[0]["event_type"] == "browser_history"

    def test_timeline_anomalies_only(self, client, tmp_path: Path):
        cid = self._make_case(client)
        d, sid = self._seed_source(tmp_path, cid)
        ts = datetime(2024, 3, 15, tzinfo=timezone.utc)
        d.add_timeline_event(source_id=sid, ts_utc=ts, event_type="x", title="clean")
        d.add_timeline_event(
            source_id=sid, ts_utc=ts, event_type="x", title="dirty",
            anomaly_flags=(FLAG_OUT_OF_RANGE,),
        )
        d.commit()
        d.close()

        r = client.get(f"/api/cases/{cid}/timeline", params={"anomalies_only": "true"})
        assert r.status_code == 200
        events = r.json()
        assert len(events) == 1
        assert events[0]["title"] == "dirty"
