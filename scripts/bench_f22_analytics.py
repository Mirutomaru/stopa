#!/usr/bin/env python3
"""F2.2 AK benchmark — DuckDB OLAP na plné škále (10M timeline eventů v rozmezí 1 h).

Generuje 10M událostí přímo v SQLite (SQL series — bez Python loopu),
materiáluje do DuckDB a měří:
- refresh (one-off cost, informační)
- AK1: timeline_range(1h okno nad 10M) limit 10k < 2 s
- AK2: hourly_histogram + top_event_types < 5 s

Spustit: .venv/bin/python scripts/bench_f22_analytics.py [n_events]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000_000
TMP = Path("/tmp/f22_bench")


def main() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    db_file = TMP / "case-bench.db"
    for suffix in (".db", ".duckdb"):
        p = db_file.with_suffix(suffix)
        if p.exists():
            p.unlink()

    # ── generace case DB s N událostmi v 1 h (SQL series, C engine SQLite) ──
    from stopa.data.db import CaseDB
    from stopa.models import Case, EvidenceSource

    t0 = time.perf_counter()
    db = CaseDB(db_file)
    case = Case(id="case-bench", name="F2.2 Bench")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/tmp/seed")
    db.add_source(src)
    sid = src.id

    con = db.conn
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    chunk = 100_000
    n_chunks = (N + chunk - 1) // chunk
    # series generátor: 0..chunk-1 přes rekurzivní CTE (1×), pak CROSS JOIN range
    con.execute(
        """CREATE TEMP TABLE gen AS
           WITH RECURSIVE s(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM s WHERE n < ?)
           SELECT n FROM s""",
        (chunk - 1,),
    )
    base = "2026-11-09T12:00:00Z"
    # 10M eventů do 3599 s (vše v 1 h okně); sekundová přesnost stačí pro AK
    for c in range(n_chunks):
        remaining = min(chunk, N - c * chunk)
        con.execute(
            """INSERT INTO timeline_events (
                id, source_id, rel_path, event_type, ts_utc, title, confidence, ts_origin
             )
             SELECT 'ev' || (? + g.n), ?, '/seed/f' || (g.n % 50) || '.log',
                    CASE WHEN g.n % 2 = 0 THEN 'browser_history' ELSE 'chat_message' END,
                    strftime('%Y-%m-%dT%H:%M:%SZ', ? , '+' || ((? + g.n) * 3599 / ?) || ' seconds'),
                    'ev' || (g.n % 100), 0.9, 'source'
             FROM gen g WHERE g.n < ?""",
            (c * chunk, sid, base, c * chunk, N, remaining),
        )
    con.execute("COMMIT")
    n_rows = con.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    t_gen = time.perf_counter() - t0
    db.close()

    # ── DuckDB refresh + měření ──
    from stopa.data.analytics import AnalyticsStore

    store = AnalyticsStore(db_file)
    t0 = time.perf_counter()
    counts = store.refresh()
    t_refresh = time.perf_counter() - t0

    # AK1: 1h okno pokrývající všech N událostí, limit 10k (realistická stránka GUI)
    con2 = store._con
    t_range = -1.0
    for attempt in range(3):
        t0 = time.perf_counter()
        con2.execute(
            """SELECT id, ts_utc FROM tl_events
               WHERE ts >= TRY_CAST('2026-11-09T12:00:00Z' AS TIMESTAMP)
                 AND ts <= TRY_CAST('2026-11-09T13:00:00Z' AS TIMESTAMP)
               ORDER BY ts LIMIT 10000"""
        ).fetchall()
        t_range = time.perf_counter() - t0
    # API cesta (přes AnalyticsStore — včetně status/fresh checku)
    t0 = time.perf_counter()
    evs = store.timeline_range(
        "2026-11-09T12:00:00+00:00", "2026-11-09T13:00:00+00:00", limit=10_000
    )
    t_api = time.perf_counter() - t0

    # AK2: agregace
    t0 = time.perf_counter()
    hist = store.hourly_histogram()
    tops = store.top_event_types(limit=20)
    t_agg = time.perf_counter() - t0

    result = {
        "n_events": n_rows,
        "refresh_counts": counts,
        "window_hours": 1.0,
        "gen_seconds": round(t_gen, 2),
        "refresh_seconds": round(t_refresh, 2),
        "range_query_10k_raw_seconds": round(t_range, 3),
        "range_api_10k_seconds": round(t_api, 3),
        "api_range_rows": len(evs),
        "aggregation_seconds": round(t_agg, 3),
        "histogram_buckets": len(hist),
        "top_types": tops[:4],
        "ak1_range_lt_2s": t_api < 2.0,
        "ak2_aggregation_lt_5s": t_agg < 5.0,
    }
    print(json.dumps(result, indent=2))
    (TMP / "result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
