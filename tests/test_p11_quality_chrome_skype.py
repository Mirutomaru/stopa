"""P1-1 Parser Quality Framework — vlna 5: browser + Skype rodina (w7, 5 parserů).

Parseri (sdílený test soubor ``tests/test_w7_parsers.py``):
``chrome_bookmarks``, ``chrome_history_wr``, ``contacts_wr``,
``chrome_autofill``, ``skype_warrant_return``.

Doplněné kategorie: ``tz`` / ``encoding`` / ``corrupted`` / ``boundary`` / ``size``.

Kontrakty doložené probe (``probe_w7.py``):
- Chrome ``date_added``/``visit_time`` = µs od Windows epochy 1601 — exaktní
  konverze ověřena nezávislým výpočtem (offset 11_644_473_600 s).
- Skype ``composetime`` přijímá ISO 8601 i epoch ms/s; offsety fungují.
- UTF-8 BOM → ValueError „Neplatné JSON“ u všech pěti parserů (sdílený loader,
  dokumentovaná limitace).
- Prázdné kolekce: ``{"roots": {}}`` / ``[]`` → 0 záznamů; skype ``[]`` →
  TypeError „Neznámý Skype warrant subtyp“ (detekce subtypu potřebuje markery).

Data jsou syntetická a anonymizovaná. Plně offline, deterministicky.
"""

from __future__ import annotations

import calendar
import json

import pytest

from stopa.artifacts.google_chrome_autofill import parse_chrome_autofill
from stopa.artifacts.google_chrome_bookmarks import parse_chrome_bookmarks
from stopa.artifacts.google_chrome_history_wr import parse_chrome_history_wr
from stopa.artifacts.google_contacts_wr import parse_contacts_wr
from stopa.artifacts.skype_warrant_return import parse_skype_warrant

BOM = b"\xef\xbb\xbf"
# Nezávislá konstanta: počet sekund mezi 1601-01-01 a 1970-01-01 UTC.
WINDOWS_OFFSET_S = 11_644_473_600


def _epoch(y: int, m: int, d: int, h: int = 0) -> int:
    """Nezávislý epoch výpočet (bez stopa.domain.times)."""
    return calendar.timegm((y, m, d, h, 0, 0, 0, 0, 0))


def _chrome_us(epoch_s: int) -> str:
    """µs od Windows epochy 1601 — nezávislý výpočet."""
    return str(int((epoch_s + WINDOWS_OFFSET_S) * 1_000_000))


# ── tz: exaktní konverze časových značek ─────────────────────────────────────


def test_chrome_us_exact_epoch():
    # quality: tz
    """Chrome µs od 1601 (bookmarks date_added + history visit_time) → epoch."""
    target = _epoch(2024, 5, 1, 12)  # 2024-05-01T12:00:00Z
    us = _chrome_us(target)
    bm = json.dumps({
        "roots": {"bookmark_bar": {
            "children": [{
                "date_added": us, "id": "1", "name": "X", "type": "url",
                "url": "https://x.cz",
            }],
            "date_added": us, "id": "0", "name": "bar", "type": "folder",
        }}
    }).encode()
    recs = parse_chrome_bookmarks(bm)
    assert len(recs) == 1
    assert recs[0].date_added_s == float(target)

    hist = json.dumps([{"url": "https://y.cz", "visit_time": us}]).encode()
    hrecs = parse_chrome_history_wr(hist)
    assert len(hrecs) == 1
    assert hrecs[0].visit_time_s == float(target)


def test_skype_composetime_offset_and_ms():
    # quality: tz
    """Skype composetime: ISO s offsetem +02:00 a epoch ms → exaktní epocha."""
    midnight = _epoch(2016, 1, 1)  # 2016-01-01T00:00:00Z
    chat = json.dumps([
        {"conversationId": "c1", "from": "8:a", "to": "8:b", "message": "t",
         "composetime": "2016-01-01T02:00:00+02:00"},
        {"conversationId": "c1", "from": "8:a", "to": "8:b", "message": "u",
         "composetime": midnight * 1000},  # epoch ms
    ]).encode()
    recs = parse_skype_warrant(chat)
    assert len(recs) == 2
    assert recs[0].timestamp_s == float(midnight)
    assert recs[1].timestamp_s == float(midnight)


# ── encoding: UTF-8 / diakritika / BOM ───────────────────────────────────────


def test_czech_roundtrip_all_parsers():
    # quality: encoding
    """Diakritika přežije všechny 5 parserů bez ztrát."""
    bm = json.dumps({
        "roots": {"bookmark_bar": {
            "children": [{
                "date_added": _chrome_us(_epoch(2024, 1, 1)), "id": "1",
                "name": "Žluťoučký kůň", "type": "url", "url": "https://k.cz",
            }],
            "date_added": _chrome_us(_epoch(2024, 1, 1)), "id": "0",
            "name": "Složka s diakritikou", "type": "folder",
        }}
    }).encode()
    assert any("Žluťoučký kůň" == r.name for r in parse_chrome_bookmarks(bm))

    hist = json.dumps([{"url": "https://x.cz", "title": "Příliš žluťoučký kůň"}]).encode()
    hrecs = parse_chrome_history_wr(hist)
    assert hrecs[0].title == "Příliš žluťoučký kůň"

    ct = json.dumps([{"name": ["Jan Novák"], "givenName": ["Jan"],
                      "familyName": ["Novák"]}, ]).encode()
    crecs = parse_contacts_wr(ct)
    assert crecs[0].display_name == "Jan Novák"

    af = json.dumps([{"name": "Petr Dvořák", "city": "Hlavní 1"}]).encode()
    arecs = parse_chrome_autofill(af)
    assert arecs[0].name == "Petr Dvořák"
    assert arecs[0].city == "Hlavní 1"

    sk = json.dumps([{"conversationId": "c", "from": "8:a", "to": "8:b",
                      "message": "Ahoj, jak se máš?", "composetime": "2016-01-01T00:00:00Z"}]).encode()
    srecs = parse_skype_warrant(sk)
    assert srecs[0].sub_type == "chat"
    assert srecs[0].title == "Ahoj, jak se máš?"  # text zprávy → title (≤60 znaků)


def test_bom_rejected_all_parsers():
    # quality: corrupted
    """UTF-8 BOM → ValueError „Neplatné JSON“ u všech 5 parserů (sdílený loader)."""
    cases = [
        (parse_chrome_bookmarks, json.dumps({"roots": {"bookmark_bar": {}}}).encode()),
        (parse_chrome_history_wr, b'[{"url": "https://x.cz"}]'),
        (parse_contacts_wr, b'[{"name": ["A"]}]'),
        (parse_chrome_autofill, b'[{"email": "a@x.cz"}]'),
        (parse_skype_warrant, json.dumps([{"msnId": "8:x", "displayName": "X"}]).encode()),
    ]
    for parser, data in cases:
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(BOM + data)


def test_truncated_and_garbage():
    # quality: corrupted
    """Oříznuté JSON a binární smetí → ValueError."""
    truncated = b'[{"url": "https://x.cz", "visit_time"'
    with pytest.raises(ValueError):
        parse_chrome_history_wr(truncated)
    garbage = b"\x00\x01\xff\xfe{bin"
    with pytest.raises(ValueError):
        parse_chrome_bookmarks(garbage)


# ── boundary: prázdné a minimální vstupy ─────────────────────────────────────


def test_empty_collections_zero_records():
    # quality: boundary
    """Prázdné kolekce → 0 záznamů; skype [] → TypeError (detekce subtypu)."""
    assert parse_chrome_bookmarks(json.dumps({"roots": {}}).encode()) == []
    assert parse_chrome_history_wr(b"[]") == []
    assert parse_contacts_wr(b"[]") == []
    assert parse_chrome_autofill(b"[]") == []
    with pytest.raises(TypeError, match="Neznámý Skype warrant subtyp"):
        parse_skype_warrant(b"[]")


def test_single_minimal_record_each():
    # quality: boundary
    """Jeden minimální záznam per parser → přesně 1 záznam."""
    bm = json.dumps({
        "roots": {"bookmark_bar": {
            "children": [{"id": "1", "name": "Jediná", "type": "url",
                          "url": "https://j.cz"}],
            "id": "0", "name": "bar", "type": "folder",
        }}
    }).encode()
    assert len(parse_chrome_bookmarks(bm)) == 1

    hist = json.dumps([{"url": "https://h.cz"}]).encode()
    hrecs = parse_chrome_history_wr(hist)
    assert len(hrecs) == 1 and hrecs[0].visit_time_s is None

    ct = json.dumps([{"name": ["Minimální"]}, ]).encode()
    crecs = parse_contacts_wr(ct)
    assert len(crecs) == 1 and crecs[0].display_name == "Minimální"

    af = json.dumps([{"email": "min@x.cz"}]).encode()
    arecs = parse_chrome_autofill(af)
    assert len(arecs) == 1 and arecs[0].email == "min@x.cz"

    sk = json.dumps({"account": "skype:min", "displayName": "Min"}).encode()
    srecs = parse_skype_warrant(sk)
    assert len(srecs) == 1 and srecs[0].sub_type == "account"


# ── size: stresové objemy ─────────────────────────────────────────────────────


def test_stress_many_records():
    # quality: size
    """Stres: stovky záznamů bez výjimky a bez ztráty počtu (pod limity)."""
    us = _chrome_us(_epoch(2024, 3, 1))
    children = [{
        "date_added": us, "id": str(i), "name": f"B{i}", "type": "url",
        "url": f"https://x.cz/{i}",
    } for i in range(300)]
    bm = json.dumps({"roots": {"bookmark_bar": {
        "children": children, "id": "0", "name": "bar", "type": "folder"}}}).encode()
    assert len(parse_chrome_bookmarks(bm)) == 300

    hist = json.dumps([{"url": f"https://h.cz/{i}", "visit_time": us}
                       for i in range(250)]).encode()
    assert len(parse_chrome_history_wr(hist)) == 250

    ct = json.dumps([{"name": [f"Osoba {i}"],
                      "emails": [{"value": f"o{i}@x.cz"}]} for i in range(150)]).encode()
    assert len(parse_contacts_wr(ct)) == 150

    af = json.dumps([{"email": f"a{i}@x.cz", "name": f"Uživatel {i}"}
                     for i in range(120)]).encode()
    assert len(parse_chrome_autofill(af)) == 120

    sk = json.dumps([{
        "conversationId": "c", "from": "8:a", "to": "8:b", "message": f"zpráva {i}",
        "composetime": "2016-01-01T00:00:00Z",
    } for i in range(200)]).encode()
    assert len(parse_skype_warrant(sk)) == 200
