"""STP-079 — deterministická build fixture Android calllog.db (vlna 6, design §7).

Vytvoří anonymizovanou ``calllog.db`` se schématem reálné Android CallLog DB
(tabulka ``calls``; STOPA čte jen ``number`` + ``date``, volitelně ``duration``/
``type``, viz ``stopa.artifacts.sqlite_extract._is_call_log`` — matcher vyžaduje
tabulku ``calls`` se sloupci {number, date}). Ostatní sloupce (new/read/name/
geocode/account_number/velocity) jsou deterministické konstanty = schématická
reálie bez vlivu na extrakci.

Determinismus: pevné ID, pevné timestampy v unix ms (celosekundové hodnoty ×
1000; jeden řádek s podsekundovou frakcí .500 testuje shodu STOPA float cesty
``ms / 1000.0`` + floor normalizace a referenční celočíselné ``// 1_000``,
stejný princip jako STP-076/STP-077). Byte-for-byte stabilita se fixuje SHA-256
pinem v ``manifest.json`` (guard test ``tests/test_stp079.py``). Headerové pole
„SQLite Library Version Number“ (offset 96–99) se po buildu normalizuje na nulu
→ hash je stabilní i při rebuildu jinou verzí SQLite, která toto informační
pole zapíše jinak (čteči od něj nezávisí; stejný guard jako STP-073/STP-076).

Edge sémantiky v datech:
* řádek 1+2 sdílí ``number`` I sekundu po flooru (řádek 2 má frakci .500 s) —
  duplicitní join key [number, ts] na obou stranách; pořadí řadí deterministický
  stabilní klíč (§3.2), ne zdrojové pořadí;
* řádek 3 s ``date = 0`` — filtr ``> 0`` ho musí vynechat na OBĚCH stranách
  (STOPA extraktor i referenční dotaz);
* řádek 4 s NBSP (U+00A0) v čísle + NULL duration/type — NFKC normalizace str
  polí na obou stranách (§3.3: NBSP → mezera) a explicitní None == None parity;
* řádky 1/2/8 sdílejí ``number`` s odlišnými sekundami, řádky 5/6 jiný tvar
  téhož čísla (+420… vs. 420…) v po sobě jdoucích sekundách — join key musí být
  [number, ts] (jen number by kolizovalo, jen ts taky);
* NULL ``number`` se v fixture neobjevuje: STOPA title = f"Hovor — {number}"
  by NULL vykreslil jako text „None" a referenční SQL vrátil None → parity
  porušená; navíc make_join_key fail-fast (§3.4) nedopouští None klíč.

Použití::

    .venv/bin/python tests/reference_datasets/sqlite/android_calllog/build_fixture.py [CILEST]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

#: calls(_id, number, date_ms, duration, type) — pevné ID a timestampy;
#: řádek 2 s frakcí .500 s (duplicitní [number, ts] s řádkem 1), řádek 3 s
#: date = 0 (WHERE parity), řádek 4 s NBSP + NULL duration/type.
ROWS_CALLS: list[tuple[int, str, int, int | None, int | None]] = [
    # příchozí hovor, základní sekunda T0
    (1, "+420777123456", 1_750_000_000 * 1_000, 123, 1),
    # odchozí hovor ve STEJNÉ sekundě po flooru (frakce .500 s) — duplicitní join key
    (2, "+420777123456", 1_750_000_000 * 1_000 + 500, 456, 2),
    # date = 0 — vynechá filtr ``> 0`` na obou stranách
    (3, "+491****5678", 0, 10, 1),
    # NBSP (U+00A0) v čísle + NULL duration/type — NFKC + None==None parity
    (4, "+420\u00a0777 123 456", 1_750_000_123 * 1_000, None, None),
    # zmeškaný hovor (type=3), nulová délka; číslo bez "+" prefixu
    (5, "420777123456", 1_750_000_200 * 1_000, 0, 3),
    # stejná číslice jako řádek 5 (jiný tvar záznamu), druhá sekunda
    (6, "420777123456", 1_750_000_201 * 1_000, 89, 2),
    # mezinárodní tvar s vedoucím „00", dlouhý hovor
    (7, "00420223456789", 1_750_000_300 * 1_000, 2468, 1),
    # třetí záznam se stejným number jako řádky 1/2 (jiná sekunda) — [number, ts]
    (8, "+420777123456", 1_750_000_400 * 1_000, 55, 2),
]

#: Offset pole „SQLite Library Version Number“ v DB headeru (big-endian, 4 B).
_SQLITE_VERSION_FIELD_OFFSET = 96


def _normalize_writer_version(db_path: Path) -> None:
    """Znuluje verzi píšící knihovny v headeru → byte-stabilita napříč verzemi.

    Pole je informační (verze SQLite, která soubor naposledy psala); čteči od
    něj nezávisí. Bez normalizace rebuild jinou verzí SQLite změní 2–4 bajty a
    poruší SHA pin v ``manifest.json`` (guard test ``tests/test_stp079.py``).
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
            "CREATE TABLE calls ("
            "_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "number TEXT, date INTEGER DEFAULT 0, duration INTEGER, "
            "new INTEGER DEFAULT 0, read INTEGER DEFAULT 0, type INTEGER, "
            "name TEXT, geocode TEXT, account_number TEXT, velocity REAL)"
        )
        for uid, number, date_ms, duration, call_type in ROWS_CALLS:
            conn.execute(
                "INSERT INTO calls (_id, number, date, duration, new, read, type, "
                "name, geocode, account_number, velocity) VALUES (?, ?, ?, ?, 0, 0, ?, NULL, NULL, NULL, NULL)",
                (uid, number, date_ms, duration, call_type),
            )
        conn.commit()
    finally:
        conn.close()
    # Header normalizace PO close (SQLite už soubor nedotkne) → SHA stabilní i
    # při rebuildu jinou verzí SQLite (CI ubuntu-latest má odlišné libsqlite3).
    _normalize_writer_version(path)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "calllog.db"
    build(target)
    print(f"fixture: {target}")
