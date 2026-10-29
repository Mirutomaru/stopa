"""SQLite artifact extraktor — browser history (Chrome/Edge/Firefox) + triage DB.

AXIOM-style: každý soubor se SQLite signaturou projde schema detektorem.
- Chrome/Edge/Opera: tabulky `urls` + `visits`, čas = µs od Windows epochy (1601)
- Firefox: `moz_places`, last_visit_date = ms od Unix epochy (1970)
- ostatní SQLite DB: jeden triage artifact se seznamem tabulek a počty řádků

IO je jen v `extract_sqlite_artifacts()`; schema matchery jsou čisté funkce.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from stopa.domain.times import from_chrome_micros, from_unix
from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.sqlite")

MAX_GENERIC_TABLES = 20  # triage artifact — nevtěsnávat 500 tabulek do detailů


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Read-only SQLite (file:: URI) — nedotýkáme se důkazů, žádné -wal/-shm soubory."""
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r["name"] for r in rows}


def _is_chrome_history(conn: sqlite3.Connection) -> bool:
    """Chrome/Edge/Opera history: `urls`(url,title) + `visits`(visit_time,url)."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"urls", "visits"} <= tables:
        return False
    urls_cols = _table_columns(conn, "urls")
    visits_cols = _table_columns(conn, "visits")
    return {"url", "title"} <= urls_cols and {"visit_time", "url"} <= visits_cols


def _is_firefox_history(conn: sqlite3.Connection) -> bool:
    """Firefox places.sqlite: `moz_places`(url,last_visit_date)."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "moz_places" not in tables:
        return False
    cols = _table_columns(conn, "moz_places")
    return {"url", "last_visit_date"} <= cols


def _extract_chrome_history(conn: sqlite3.Connection) -> list[Artifact]:
    """Každá návštěva (visit) → artifact s URL, titulkem a časem."""
    rows = conn.execute(
        "SELECT v.visit_time, u.url, u.title"
        " FROM visits v JOIN urls u ON u.id = v.url"
        " WHERE v.visit_time > 0 AND u.url IS NOT NULL"
    ).fetchall()
    out: list[Artifact] = []
    for r in rows:
        try:
            ts = from_chrome_micros(r["visit_time"])
        except ValueError as e:
            log.debug("chrome visit %s: %s", r["visit_time"], e)
            continue
        out.append(
            Artifact(
                artifact_type="browser_history",
                timestamp=ts,
                title=r["url"][:500],
                details={"page_title": r["title"], "engine": "chrome/edge"},
            )
        )
    return out


def _extract_firefox_history(conn: sqlite3.Connection) -> list[Artifact]:
    """Každé místo s last_visit_date → artifact (Firefox neukládá jednotlivé visity)."""
    rows = conn.execute(
        "SELECT url, title, last_visit_date FROM moz_places"
        " WHERE last_visit_date > 0 AND url IS NOT NULL"
    ).fetchall()
    out: list[Artifact] = []
    for r in rows:
        try:
            ts = from_unix(r["last_visit_date"] / 1000.0)  # ms → s
        except ValueError as e:
            log.debug("firefox place %s: %s", r["last_visit_date"], e)
            continue
        out.append(
            Artifact(
                artifact_type="browser_history",
                timestamp=ts,
                title=r["url"][:500],
                details={"page_title": r["title"], "engine": "firefox"},
            )
        )
    return out


def _extract_generic_sqlite(conn: sqlite3.Connection) -> list[Artifact]:
    """Triage artifact pro neznámou SQLite DB — tabulky + počty řádků."""
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    row_counts: dict[str, int] = {}
    for t in tables[:MAX_GENERIC_TABLES]:
        try:
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            row_counts[t] = int(n)
        except sqlite3.Error as e:
            log.debug("count %s: %s", t, e)
    return [
        Artifact(
            artifact_type="sqlite_database",
            timestamp=None,
            title=f"SQLite DB — {len(tables)} tabulek",
            details={"tables": row_counts, "truncated": len(tables) > MAX_GENERIC_TABLES},
        )
    ]


def extract_sqlite_artifacts(path: Path) -> list[Artifact]:
    """Extrahuje artifacty ze SQLite souboru. Vrací Artifacty BEZ source_id/file_id
    (ty doplní pipeline — extraktor nezná kontext případu).

    Chyby (poškozená DB, zámek) → log + práznej výsledek, nikdy ne výjimka nahoru.
    """
    try:
        conn = _connect_readonly(path)
    except sqlite3.Error as e:
        log.warning("SQLite open %s: %s", path, e)
        return []

    try:
        if _is_chrome_history(conn):
            arts = _extract_chrome_history(conn)
        elif _is_firefox_history(conn):
            arts = _extract_firefox_history(conn)
        else:
            arts = _extract_generic_sqlite(conn)
        return arts
    except sqlite3.Error as e:
        log.warning("SQLite extract %s: %s", path, e)
        return []
    finally:
        conn.close()
