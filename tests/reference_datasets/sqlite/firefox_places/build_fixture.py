"""STP-076 — deterministická build fixture Firefox places.sqlite (vlna 3, design §7).

Vytvoří anonymizovanou ``places.sqlite`` se schématem reálné Firefox Places DB
(``moz_places`` + ``moz_historyvisits``; STOPA čte jen ``moz_places``, viz
``stopa.artifacts.sqlite_extract._is_firefox_history`` — matcher vyžaduje
sloupce ``url`` + ``last_visit_date``).

Determinismus: pevné ID, pevné timestampy v unix ms (celosekundové hodnoty ×
1000; jeden řádek s podsekundovou frakcí .123 testuje shodu STOPA float cesty
``ms / 1000.0`` + floor normalizace a referenční celočíselné ``// 1_000``).
Byte-for-byte stabilita se fixuje SHA-256 pinem v ``manifest.json`` (guard test
``tests/test_stp076.py``). Headerové pole „SQLite Library Version Number“
(offset 96–99) se po buildu normalizuje na nulu → hash je stabilní i při
rebuildu jinou verzí SQLite, která toto informační pole zapíše jinak (čteči od
něj nezávisí; stejný guard jako STP-073 chrome_history).

Edge sémantiky v datech:
* řádek 4 s ``last_visit_date = 0`` — filtr ``> 0`` ho musí vynechat na OBĚCH
  stranách (STOPA extraktor i referenční dotaz);
* řádek 3 s NULL ``title`` — ``page_title=None`` explicitní (None ≠ "", §3.3);
* řádek 5 s frakcí .123 s — přesnost epoch konverze (viz výše);
* řádek 6 s URL přesně 499 znaků — pod limitem STOPA ``url[:500]``, bez truncace.

Použití::

    .venv/bin/python tests/reference_datasets/sqlite/firefox_places/build_fixture.py [CILEST]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

#: moz_places(id, url, title, last_visit_date) — ostatní sloupce deterministické
#: konstanty. URL jsou jedinečné → join key ``url`` je jednoznačný (moz_places
#: drží jeden řádek na místo; duplicitní URL fixture záměrně neobsahuje).
ROWS_PLACES: list[tuple[int, str, str | None, int]] = [
    (1, "https://example.com/", "Example Domain", 1_700_000_000 * 1_000),
    # česká diakritika v URL i titulu — NFKC normalizace na obou stranách (§3.3)
    (2, "http://intranet.local/podpora/hlášení?rok=2026", "Interní hlášení", 1_700_036_000 * 1_000),
    # NULL titulek → page_title=None na obou stranách (None ≠ "")
    (3, "https://github.com/Mirutomaru/stopa", None, 1_700_072_000 * 1_000),
    # last_visit_date = 0 — vynechá filtr ``> 0`` na obou stranách
    (4, "https://example.org/excluded-zero", "Návštěva bez času", 0),
    # podsekundová frakce .123 s — STOPA float ms/1000.0 + floor ≡ reference //1_000
    (5, "https://example.org/subsecond-precision", "Subsekundová přesnost", 1_700_108_000 * 1_000 + 123),
]

#: URL přesně 499 znaků — pod limitem STOPA ``url[:500]`` (bez truncace).
_LONG_URL = "https://example.org/dlouha-" + ("a" * (499 - len("https://example.org/dlouha-")))
assert len(_LONG_URL) == 499, f"hraniční URL musí mít přesně 499 znaků, má {len(_LONG_URL)}"

#: moz_historyvisits(id, place_id, visit_time) — schématická reálie; ani STOPA
#: extraktor ani referenční dotaz ji nečtou (STOPA: „Firefox neukládá
#: jednotlivé visity“ — čte moz_places.last_visit_date).
VISITS: list[tuple[int, int, int]] = [
    (1, 1, 1_700_000_000 * 1_000),
    (2, 2, 1_700_036_000 * 1_000),
    (3, 3, 1_700_072_000 * 1_000),
    (4, 5, 1_700_108_000 * 1_000 + 123),
    (5, 6, 1_700_144_000 * 1_000),
]

#: Offset pole „SQLite Library Version Number“ v DB headeru (big-endian, 4 B).
_SQLITE_VERSION_FIELD_OFFSET = 96


def _normalize_writer_version(db_path: Path) -> None:
    """Znuluje verzi píšící knihovny v headeru → byte-stabilita napříč verzemi.

    Pole je informační (verze SQLite, která soubor naposledy psala); čteči od
    něj nezávisí. Bez normalizace rebuild jinou verzí SQLite změní 2–4 bajty a
    poruší SHA pin v ``manifest.json`` (guard test ``tests/test_stp076.py``).
    """
    data = bytearray(db_path.read_bytes())
    field_end = _SQLITE_VERSION_FIELD_OFFSET + 4
    data[_SQLITE_VERSION_FIELD_OFFSET:field_end] = b"\x00" * 4
    db_path.write_bytes(bytes(data))


def build(path: Path) -> None:
    """Vytvoří fixture DB (přepíše existující soubor)."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE moz_places ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "url TEXT NOT NULL, title TEXT, "
            "revkey BLOB, type INTEGER DEFAULT 0, "
            "visit_count INTEGER DEFAULT 1, last_visit_date INTEGER DEFAULT 0, "
            "hidden INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE moz_historyvisits ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "place_id INTEGER NOT NULL REFERENCES moz_places(id), "
            "from_visit INTEGER DEFAULT 0, visit_time INTEGER NOT NULL, "
            "visit_type INTEGER DEFAULT 2)"
        )
        for uid, url, title, ms in ROWS_PLACES:
            conn.execute(
                "INSERT INTO moz_places (id, url, title, revkey, type, visit_count, last_visit_date, hidden) "
                "VALUES (?, ?, ?, ?, 0, ?, ?, 0)",
                (uid, url, title, bytes([uid] * 16), 1 + uid, ms),
            )
        # hraniční řádek: URL přesně 499 znaků pod STOPA limitem [:500]
        conn.execute(
            "INSERT INTO moz_places (id, url, title, revkey, type, visit_count, last_visit_date, hidden) "
            "VALUES (?, ?, ?, ?, 0, ?, ?, 0)",
            (6, _LONG_URL, "Dlouhá URL pod limitem", bytes([6] * 16), 7, 1_700_144_000 * 1_000),
        )
        for vid, place_id, ms in VISITS:
            conn.execute(
                "INSERT INTO moz_historyvisits (id, place_id, from_visit, visit_time, visit_type) "
                "VALUES (?, ?, 0, ?, 2)",
                (vid, place_id, ms),
            )
        conn.commit()
    finally:
        conn.close()
    # Header normalizace PO close (SQLite už soubor nedotkne) → SHA stabilní i
    # při rebuildu jinou verzí SQLite (CI ubuntu-latest má odlišné libsqlite3).
    _normalize_writer_version(path)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "places.sqlite"
    build(target)
    print(f"fixture: {target}")
