"""STP-078 — build deterministické iMessage chat.db fixtury (vlna 5, design §7).

Tabulky reálného schématu chat.db (CoreData): ``message(_id, text, date REAL,
handle_id)`` + ``handle(_id, address)``. ``date`` = CFAbsoluteTime v sekundách
od epochy **2001-01-01T00:00Z** (Apple epoch) — nová epochová varianta SQLite
rodiny po unix s (chrome_history), unix ms (firefox_places, android_sms).

Determinismus: pevné _id a timestamps, anonymizovaná data; headerové pole
„SQLite Library Version Number“ (offset 96–99) se nuluje → byte-stabilita i při
rebuildu jinou verzí SQLite (CI má odlišné libsqlite3 než vývoj).

Řádky (9 message, 7 očekávaných záznamů):

* m1/m2: stejná celá sekunda CFAbsoluteTime, **různé handle** — join key
  [handle, ts] musí rozlišit odposílatele;
* m3: frakce .5 s u m1 handle — po floor normalizaci identická sekunda jako m1
  → **duplicitní join key [handle1, ts]** na obou stranách (pořadové párování
  deterministické přes _sort_key s polí);
* m4: NFKC ligatura ﬁ (U+FB01) v těle;
* m5: whitespace-only text → fallback "(prázdná zpráva)" na obou cestách;
* m6: 350 znaků ASCII — parita truncace [:300] (STOPA title[:300]) vs. SQL
  SUBSTR(TRIM(text),1,300); řez bez normalizovatelných znaků u hranice;
* m7: běžná zpráva od handle1 v jiné sekundě;
* m8/m9: vynechané WHERE paritou obou stran (date=0 / NULL text).

Použití::

    python build_fixture.py [out_path]   # default: chat.db vedle sebe
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# CFAbsoluteTime základ — unix 1_750_000_000 (2025-06-15T04:26:40Z) − offset 978_307_200
_BASE_CF = 771_692_800.0

_HANDLES: list[tuple[int, str]] = [
    (1, "+420777123456"),
    (2, "jano.novak@example.cz"),
]

# 350 znaků čistého ASCII (bez normalizovatelných znaků u řezu [:300])
_LONG_BODY = ("The quick brown fox jumps over the lazy dog. " * 8)[:350]
assert len(_LONG_BODY) == 350, f"očekáváno přesně 350 znaků, je {len(_LONG_BODY)}"

_MESSAGES: list[tuple[int, str | None, float, int]] = [
    # (_id, text, date CFAbsoluteTime, handle_id)
    (1, "Ahoj, jak se máš?", _BASE_CF, 1),  # m1 → unix 1_750_000_000
    (2, "Přijď dnes večer na večeři.", _BASE_CF, 2),  # m2 stejná sekunda, jiné handle
    (3, "Dobře, budu tam o 19:30.", _BASE_CF + 0.5, 1),  # m3 .5 s → duplicitní key [h1, ts]
    (4, "Meeting re: Q3 ﬁnance report", _BASE_CF + 200.0, 2),  # m4 NFKC ligatura ﬁ
    (5, "   ", _BASE_CF + 400.0, 1),  # m5 whitespace-only → "(prázdná zpráva)"
    (6, _LONG_BODY, _BASE_CF + 600.0, 2),  # m6 350 znaků → truncace [:300] parita
    (7, "Poslední zpráva dne.", _BASE_CF + 800.0, 1),  # m7 běžná zpráva
    (8, "Vynechaný řádek — date=0", 0.0, 1),  # m8 WHERE: date > 0
    (9, None, _BASE_CF + 1_000.0, 2),  # m9 WHERE: text IS NOT NULL
]


def build(out_path: Path) -> None:
    """Vytvoří chat.db v ``out_path`` (deterministicky)."""
    if out_path.exists():
        out_path.unlink()

    conn = sqlite3.connect(str(out_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE handle ("
            "_id INTEGER PRIMARY KEY, address TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE message ("
            "_id INTEGER PRIMARY KEY, text TEXT, date REAL, handle_id INTEGER,"
            "FOREIGN KEY(handle_id) REFERENCES handle(_id))"
        )
        cur.executemany("INSERT INTO handle VALUES (?, ?)", _HANDLES)
        cur.executemany("INSERT INTO message VALUES (?, ?, ?, ?)", _MESSAGES)
        conn.commit()
    finally:
        conn.close()

    # Headerové pole „SQLite Library Version Number“ (4 B na offsetu 96) → nula,
    # aby rebuild jinou verzí SQLite nezměnil SHA-256 fixtury.
    data = bytearray(out_path.read_bytes())
    field_end = min(len(data), 100)
    if len(data) >= 100:
        data[96:field_end] = b"\x00" * (field_end - 96)
    out_path.write_bytes(bytes(data))


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "chat.db"
    build(target)
    print(f"OK {target} ({target.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
