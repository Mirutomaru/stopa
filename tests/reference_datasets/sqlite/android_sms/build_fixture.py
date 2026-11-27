"""STP-077 — deterministická build fixture Android mmssms.db (vlna 4, design §7).

Vytvoří anonymizovanou ``mmssms.db`` se schématem reálné Android SMS databáze
(tabulka ``sms``; STOPA čte jen ``address`` + ``body`` + ``date``, viz
``stopa.artifacts.sqlite_extract._is_android_sms`` — matcher vyžaduje tabulku
``sms``). Ostatní sloupce (person/read/status/type/…) jsou deterministické
konstanty = schématická reálie bez vlivu na extrakci.

Determinismus: pevné ID, pevné timestampy v unix ms (celosekundové hodnoty ×
1000; jeden řádek s podsekundovou frakcí .500 testuje shodu STOPA float cesty
``ms / 1000.0`` + floor normalizace a referenční celočíselné ``// 1_000``,
stejný princip jako STP-076). Byte-for-byte stabilita se fixuje SHA-256 pinem v
``manifest.json`` (guard test ``tests/test_stp077.py``). Headerové pole „SQLite
Library Version Number“ (offset 96–99) se po buildu normalizuje na nulu → hash
je stabilní i při rebuildu jinou verzí SQLite, která toto informační pole
zapíše jinak (čteči od něj nezávisí; stejný guard jako STP-073/STP-076).

Edge sémantiky v datech:
* řádek 5 s ``date = 0`` — filtr ``> 0`` ho musí vynechat na OBĚCH stranách
  (STOPA extraktor i referenční dotaz);
* řádek 6 s NULL ``body`` — filtr ``body IS NOT NULL`` ho musí vynekat na
  obou stranách;
* řádek 3 s frakcí .500 s — přesnost epoch konverze (viz výše);
* řádek 4 s tělem přesně 299 znaků — pod limitem STOPA ``title[:300]``, bez
  truncace (STOPA title = ``body.strip()[:300]``; fixture drží body bez okrajové
  bílé spaces a bez prázdných hodnot → shoda reference surové tělo ≡ STOPA title);
* řádek 8 s ligaturou ﬁ (U+FB01) — NFKC normalizace na obou stranách (§3.3):
  surové body se liší od normalizovaného tvaru, kanonické záznamy jsou shodné;
* řádky 1/2/9 sdílejí ``address`` s odlišnými sekundami — join key
  ``[address, ts]`` musí být oběma komponentami (jen ts by kolizovalo);
* řádek 7 s vnitřním novým řádkem v těle — strip ovlivňuje jen okraje.

Použití::

    .venv/bin/python tests/reference_datasets/sqlite/android_sms/build_fixture.py [CILEST]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

#: sms(_id, address, person, date, read, status, type, reply_path_present,
#: error_code, service_center, canonical_address, body) — sloupce, které STOPA
#: nečte, jsou deterministické konstanty (schématická reálie).
ROWS_SMS: list[tuple[int, str, int, str | None]] = [
    # česká diakritika + em-dash — NFKC na obou stranách (§3.3)
    (1, "+420777123456", -1, "Dobrý den, schůzka v 15:30 — potvrdte prosím."),
    # stejná address jako řádek 1, jiná sekunda → join key [address, ts]
    (2, "+420777123456", -1, "Potvrzuji, uvidíme se!"),
    # podsekundová frakce .500 s — STOPA float ms/1000.0 + floor ≡ reference //1_000
    (3, "12345", -1, "SMS s podsekundovou frakcí."),
    # mezinárodní číslo + tělo přesně 299 znaků — pod limitem STOPA [:300]
    (4, "+14155550132", -1, ""),
    # date = 0 — vynechá filtr ``> 0`` na obou stranách
    (5, "+491512345678", -1, "Vynecháno: date = 0"),
    # NULL body — vynechá filtr ``body IS NOT NULL`` na obou stranách
    (6, "+8135123456", -1, None),
    # vnitřní nový řádek — strip ovlivňuje jen okraje těla
    (7, "+420601112233", -1, "Přijedeme v pátek.\nVezměte prosím rezervaci a doklady."),
    # ligatura ﬁ (U+FB01) — NFKC ekvivalence obou cest
    (8, "+442079460018", -1, "Meeting re: Q3 ﬁnance report"),
    # bohatá diakritika + stejná address jako řádky 1/2 (třetí sekunda)
    (9, "+420777123456", -1, "Ďalší zpráva: ěščřžýáíéůú"),
]

#: Tělo přesně 299 znaků — pod limitem STOPA ``title[:300]`` (bez truncace).
_PREFIX_LONG = "Dlouhá SMS pod limitem: "
assert len(_PREFIX_LONG) < 299, "prefix musí být kratší než 299 znaků"
_PAD_LEN = 299 - len(_PREFIX_LONG)

#: date (unix ms) per _id — pevné hodnoty, řádek 3 s frakcí .500.
DATES_MS: dict[int, int] = {
    1: 1_735_689_600 * 1_000,
    2: 1_735_689_900 * 1_000,
    3: 1_735_690_200 * 1_000 + 500,
    4: 1_735_691_000 * 1_000,
    5: 0,
    6: 1_735_690_500 * 1_000,
    7: 1_735_692_000 * 1_000,
    8: 1_735_693_000 * 1_000,
    9: 1_735_694_000 * 1_000,
}

#: Offset pole „SQLite Library Version Number“ v DB headeru (big-endian, 4 B).
_SQLITE_VERSION_FIELD_OFFSET = 96


def _long_body() -> str:
    body = _PREFIX_LONG + ("a" * _PAD_LEN)
    assert len(body) == 299, f"hraniční tělo musí mít přesně 299 znaků, má {len(body)}"
    return body


def _rows() -> list[tuple[int, str, int, int, str | None]]:
    """(_id, address, person, date_ms, body) — řádek 4 s hraničním tělem."""
    out = []
    for uid, address, person, body in ROWS_SMS:
        if uid == 4:
            body = _long_body()
        out.append((uid, address, person, DATES_MS[uid], body))
    return out


def _normalize_writer_version(db_path: Path) -> None:
    """Znuluje verzi píšící knihovny v headeru → byte-stabilita napříč verzemi.

    Pole je informační (verze SQLite, která soubor naposledy psala); čteči od
    něj nezávisí. Bez normalizace rebuild jinou verzí SQLite změní 2–4 bajty a
    poruší SHA pin v ``manifest.json`` (guard test ``tests/test_stp077.py``).
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
            "CREATE TABLE sms ("
            "_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "address TEXT NOT NULL, person INTEGER DEFAULT -1, date INTEGER DEFAULT 0, "
            "read INTEGER DEFAULT 0, status INTEGER DEFAULT -1, type INTEGER DEFAULT 1, "
            "reply_path_present INTEGER DEFAULT 0, error_code INTEGER DEFAULT 0, "
            "service_center TEXT, canonical_address TEXT, body TEXT)"
        )
        for uid, address, person, date_ms, body in _rows():
            conn.execute(
                "INSERT INTO sms (_id, address, person, date, read, status, type, "
                "reply_path_present, error_code, service_center, canonical_address, body) "
                "VALUES (?, ?, ?, ?, 0, -1, 1, 0, 0, NULL, NULL, ?)",
                (uid, address, person, date_ms, body),
            )
        conn.commit()
    finally:
        conn.close()
    # Header normalizace PO close (SQLite už soubor nedotkne) → SHA stabilní i
    # při rebuildu jinou verzí SQLite (CI ubuntu-latest má odlišné libsqlite3).
    _normalize_writer_version(path)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "mmssms.db"
    build(target)
    print(f"fixture: {target}")
