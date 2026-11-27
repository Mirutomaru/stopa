"""STP-073 — deterministická build fixture Chrome History (pilot vlna 1, design §6.1).

Vytvoří anonymizovanou ``chrome_history.db`` se schématem reálné Chrome/Edge
History DB (``urls`` + ``visits``; prázdná ``search_terms`` — bonus GoogleBar
se musí čistě vyhodnotit na nula artifactů).

Determinismus: pevné ID, pevné celosekundové timestampy (Chrome µs =
 ``(unix_s + 11_644_473_600) * 1_000_000`` — přesné celé číslo), žádné
podsekundové frakce. Byte-for-byte stability souboru se fixuje SHA-256 pinem v
``manifest.json`` (guard test ``tests/test_stp073.py``); při rebuildu na jiné
verzi SQLite se hash obnoví a manifest aktualizuje (dokumentovaný postup).

Použití::

    .venv/bin/python tests/reference_datasets/sqlite/chrome_history/build_fixture.py [CILEST]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Vlastní konstanta reference (nezávislá na stopa.domain.times) — 1970−1601 v sekundách.
CHROME_UNIX_OFFSET_S = 11_644_473_600

#: urls(id, url, title) — pátý záznam s NULL titulkem testuje None≠"" (§3.3).
ROWS_URLS: list[tuple[int, str, str | None]] = [
    (1, "https://example.com/", "Example Domain"),
    (2, "file:///home/user/report.pdf", "report.pdf"),
    (3, "https://github.com/Mirutomaru/stopa", "STOPA — forenzní workbench"),
    (4, "http://intranet.local/wiki?strana=1&reze=2", "Interní wiki"),
    (5, "https://example.org/empty-title", None),
]

#: Celosekundové unix timestampy visity (jedinečné URL → join key url je jednoznačný).
VISIT_UNIX_SECONDS: list[int] = [
    1_700_000_000,
    1_700_003_600,
    1_700_007_200,
    1_700_010_800,
    1_700_014_400,
]


def build(path: Path) -> None:
    """Vytvoří fixture DB (přepíše existující soubor)."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE urls ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "url TEXT NOT NULL, title TEXT, "
            "visit_count INTEGER DEFAULT 0 UNIQUE)"
        )
        conn.execute(
            "CREATE TABLE visits ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "url INTEGER NOT NULL REFERENCES urls(id), "
            "visit_time INTEGER NOT NULL, "
            "from_visit INTEGER DEFAULT 0, transition INTEGER DEFAULT 0)"
        )
        # prázdná search_terms s požadovanými sloupci → GoogleBar bonus = [] bez výjimky
        conn.execute(
            "CREATE TABLE search_terms ("
            "term TEXT NOT NULL, time_last_used INTEGER, "
            "weight REAL DEFAULT 0, source TEXT)"
        )
        # UNIQUE(visit_count) v reálném schématu → rozlišné počty (deterministicky uid-based)
        for uid, url, title in ROWS_URLS:
            conn.execute(
                "INSERT INTO urls (id, url, title, visit_count) VALUES (?, ?, ?, ?)",
                (uid, url, title, 10 + uid),
            )
        for i, sec in enumerate(VISIT_UNIX_SECONDS):
            chrome_us = (sec + CHROME_UNIX_OFFSET_S) * 1_000_000
            conn.execute(
                "INSERT INTO visits (url, visit_time, from_visit, transition) "
                "VALUES (?, ?, 0, 0)",
                (i + 1, chrome_us),
            )
        # edge case: visit_time = 0 — filtr ``visit_time > 0`` ho musí vynechat
        # na OBĚCH stranách (STOPA extraktor i referenční dotaz)
        conn.execute(
            "INSERT INTO visits (url, visit_time, from_visit, transition) VALUES (?, 0, 0, 0)",
            (3,),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "chrome_history.db"
    build(target)
    print(f"fixture: {target}")
