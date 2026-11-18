"""P1-1 pilot — quality sada pro parser ``sqlite`` (všech 8 kategorií).

Konvence markeru: řádek ``# quality: <kategorie>`` deklaruje pokrytí testu.
Syntetická data přes ``stopa.data.synthetic_factory`` (deterministické per seed)
+ malé inline DB se známými razítky pro exaktní tz asercce (nezávislý výpočet,
ne odvozený z vnitřností factory).
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import datetime

from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts
from stopa.data.synthetic_factory import (
    make_chrome_history_db,
    make_firefox_places_db,
    make_imessage_db,
)


def _epoch(dt: datetime | None) -> float | None:
    """Robustní epoch srovnání bez ohledu na tz-aware/naive razítko."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.timestamp()
    return calendar.timegm(dt.utctimetuple())


# quality: positive
def test_positive_chrome_history(tmp_path):
    """Validní Chrome history DB → artefakty s URL z anonymizovaných domén."""
    db = make_chrome_history_db(tmp_path / "History", seed=1, n_visits=25)
    arts = extract_sqlite_artifacts(db)
    assert len(arts) > 0
    blob = " ".join(str(a.title or "") + str(a.details) for a in arts)
    assert "example" in blob


# quality: positive
def test_positive_firefox_places(tmp_path):
    db = make_firefox_places_db(tmp_path / "places.sqlite", seed=2, n_places=12)
    arts = extract_sqlite_artifacts(db)
    assert len(arts) > 0


# quality: positive
def test_positive_imessage(tmp_path):
    db = make_imessage_db(tmp_path / "chat.db", seed=3, n_messages=14)
    arts = extract_sqlite_artifacts(db)
    assert any(a.artifact_type == "imessage" for a in arts)


# quality: negative
def test_negative_non_sqlite_file(tmp_path):
    """Soubor, který není SQLite vůbec → prázdný výsledek, ne výjimka."""
    p = tmp_path / "not-sqlite.db"
    p.write_bytes(b"this is just a plain text file, not sqlite magic\n")
    assert extract_sqlite_artifacts(p) == []


# quality: negative
def test_negative_unrelated_schema(tmp_path):
    """DB se souvisejícím shape (generic extractor) nepadne."""
    p = tmp_path / "generic.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE random_table (x TEXT)")
    conn.execute("INSERT INTO random_table VALUES ('a')")
    conn.commit()
    conn.close()
    arts = extract_sqlite_artifacts(p)  # bez výjimky
    assert isinstance(arts, list)


# quality: boundary
def test_boundary_single_visit(tmp_path):
    db = make_chrome_history_db(tmp_path / "h.db", seed=5, n_visits=1)
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 1


# quality: boundary
def test_boundary_empty_table(tmp_path):
    """moz_places se 0 řádky → prázdný výsledek bez chyby."""
    p = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT,"
        " title TEXT, last_visit_date INTEGER)"
    )
    conn.commit()
    conn.close()
    assert extract_sqlite_artifacts(p) == []


# quality: corrupted
def test_corrupted_truncated_db(tmp_path):
    """Oříznutí souboru na polovinu → bez výjimky (prázdný či částečný výsledek)."""
    full = make_chrome_history_db(tmp_path / "full.db", seed=9, n_visits=30)
    data = full.read_bytes()
    cut = tmp_path / "cut.db"
    cut.write_bytes(data[: len(data) // 2])
    arts = extract_sqlite_artifacts(cut)
    assert isinstance(arts, list)


# quality: corrupted
def test_corrupted_zero_visit_time_skipped(tmp_path):
    """visit_time=0 (factory: každých 17. visita) se přeskočí bez výjimky."""
    db = make_chrome_history_db(tmp_path / "h.db", seed=1, n_visits=34)
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 34 - 2  # i=17 a i=34 mají visit_time=0


# quality: tz
def test_tz_chrome_micros_conversion(tmp_path):
    """Chrome µs od Windows epochy → exaktní UTC převod (nezávislý výpočet)."""
    p = tmp_path / "tz.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
        " visit_time INTEGER, from_visit INTEGER)"
    )
    unix_ts = 1_700_000_123
    chrome_us = (unix_ts + 11_644_473_600) * 1_000_000
    conn.execute("INSERT INTO urls VALUES (1, 'https://tz.example/x', 'TZ test')")
    conn.execute("INSERT INTO visits (url, visit_time) VALUES (1, ?)", (chrome_us,))
    conn.commit()
    conn.close()
    arts = extract_sqlite_artifacts(p)
    assert len(arts) == 1
    assert abs((_epoch(arts[0].timestamp) or -1.0) - unix_ts) < 0.01


# quality: tz
def test_tz_firefox_ms_conversion(tmp_path):
    p = tmp_path / "tz_ff.sqlite"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT,"
        " title TEXT, last_visit_date INTEGER)"
    )
    ms = 1_700_000_456_789
    conn.execute(
        "INSERT INTO moz_places (url, title, last_visit_date) VALUES (?, ?, ?)",
        ("https://ff.example/y", "FF TZ", ms),
    )
    conn.commit()
    conn.close()
    arts = extract_sqlite_artifacts(p)
    assert len(arts) == 1
    assert abs((_epoch(arts[0].timestamp) or -1.0) - (ms / 1000.0)) < 0.01


# quality: tz
def test_tz_imessage_cfabsolute(tmp_path):
    """Apple CFAbsoluteTime (od 2001) → exaktní UTC převod."""
    p = tmp_path / "tz_chat.db"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE message (_id INTEGER PRIMARY KEY, handle_id INTEGER,"
        " text TEXT, date REAL)"
    )
    unix_ts = 1_700_000_234
    apple_ts = float(unix_ts - 978_307_200)
    conn.execute(
        "INSERT INTO message (handle_id, text, date) VALUES (1, 'tz zpráva', ?)",
        (apple_ts,),
    )
    conn.commit()
    conn.close()
    arts = extract_sqlite_artifacts(p)
    assert len(arts) == 1
    assert abs((_epoch(arts[0].timestamp) or -1.0) - unix_ts) < 0.01


# quality: encoding locale
def test_encoding_unicode_values(tmp_path):
    """Česká diakritika + emoji v hodnotách roundtrip bez ztráty."""
    p = tmp_path / "enc.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
        " visit_time INTEGER, from_visit INTEGER)"
    )
    title = "Šňůrka žluťoučká 🎯 café"
    conn.execute("INSERT INTO urls VALUES (1, 'https://enc.example/snurka', ?)", (title,))
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (1, ?)",
        ((1_700_000_500 + 11_644_473_600) * 1_000_000,),
    )
    conn.commit()
    conn.close()
    arts = extract_sqlite_artifacts(p)
    assert len(arts) == 1
    blob = str(arts[0].title) + str(arts[0].details)
    assert "Šňůrka" in blob and "🎯" in blob


# quality: size
def test_size_limit_2000_visits(tmp_path):
    """Limitní velikost — 2000 visit se extrahuje bez ztráty řádků."""
    db = make_chrome_history_db(tmp_path / "big.db", seed=11, n_visits=2000)
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 2000 - (2000 // 17)  # i%17==0 → visit_time=0
