"""P1-1 quality — vlna 17 (capstone): posledních 9 parserů / 27 buněk.

Uzavírá P1-1 Parser Quality Framework na category coverage **100 %**
(624/624 parser×kategorie, plně pokryto 78/78).

Kontrakty per parser:
- allowlisted_websites (encoding, locale, size, tz): JSON seznam domén;
  čtení utf-8 errors=replace → U+FFFD; bez horního limitu — stabilita na
  velkém souboru; snapshot bez času → artifact.timestamp is None.
- mailru_agent (encoding, locale, size, tz): chat log ``ts | direction | id
  | name : msg``; naive ts → aware UTC (přesnost minuty → :00);
  MAX_LINES_PER_FILE = 20_000; message [:500], title [:80].
- openoffice_base (encoding, locale, size, tz): ODF ZIP; ElementTree
  respektuje deklaraci encoding v XML hlavičce (iso-8859-1); dc:date:
  Z/±hh:mm → astimezone(UTC), naive → UTC; title [:120].
- sim_tpdu (corrupted, encoding, locale, size, tz): AT+CPBR + volné páry;
  decode utf-8 → latin-1 fallback (nikdy neshodí); jméno s podílem tisknutelných
  < 0.9 → ""; dedup first-wins; MAX_CONTACTS_PER_DUMP = 2_000; timestamp=None.
- apple_cloud, gmail_messages, maps_labeled_places, whatsapp_cloud
  (locale, negative): diakritika verbatim v poli recordu; platné JSON bez
  záznamů → TypeError s přesnou zprávou.
- drive_activity (corrupted, locale): neplatné JSON → ValueError „Neplatné
  JSON"; fileName/actor verbatim.

Marker konvence: jeden čistý ``# quality:`` řádek nad každým testem; atribuce
je na úrovni souboru — každý parser, který má tento soubor v test_files,
dostává všechny kategorie uvedené v tomto souboru.
"""

from __future__ import annotations

import json
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.allowlisted_websites import (
    extract_allowlisted_websites_artifacts,
)
from stopa.artifacts.apple_cloud import parse_apple_cloud
from stopa.artifacts.drive_activity import parse_drive_activity
from stopa.artifacts.gmail_messages import parse_gmail_messages
from stopa.artifacts.mailru_agent import (
    MAX_LINES_PER_FILE,
    build_mailru_artifacts,
    parse_mailru_chat_log,
)
from stopa.artifacts.maps_labeled_places import parse_maps_labeled_places
from stopa.artifacts.openoffice_base import extract_openoffice_base_artifacts
from stopa.artifacts.sim_tpdu import (
    MAX_CONTACTS_PER_DUMP,
    build_tpdu_artifacts,
    extract_tpdu_artifacts,
    parse_tpdu_text,
)
from stopa.artifacts.whatsapp_cloud import parse_whatsapp_cloud


def _make_odb(
    path: Path,
    title: str,
    date: str | None = None,
    creator: str | None = None,
    xml_encoding: str = "utf-8",
) -> Path:
    """Sestaví minimální .odb ZIP s content.xml (ODF metadata)."""
    parts = [f"<dc:title>{title}</dc:title>"]
    if creator is not None:
        parts.append(f"<dc:creator>{creator}</dc:creator>")
    if date is not None:
        parts.append(f"<dc:date>{date}</dc:date>")
    decl = "iso-8859-1" if xml_encoding == "latin-1" else "utf-8"
    xml = (
        '<?xml version="1.0" encoding="' + decl + '"?>'
        '<office:document '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">'
        + "".join(parts)
        + "</office:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.base")
        zf.writestr("content.xml", xml.encode(xml_encoding))
    return path


# ---------------------------------------------------------------------------
# allowlisted_websites — encoding / locale / size / tz
# ---------------------------------------------------------------------------


def test_locale_allowlisted_websites(tmp_path: Path) -> None:
    # quality: locale
    p = tmp_path / "allowlist.json"
    p.write_text(
        json.dumps(["příliš-žluťoučký.example", "*žluťouček.cz"]), encoding="utf-8"
    )
    arts = extract_allowlisted_websites_artifacts(p)
    assert len(arts) == 2
    domains = [a.details.get("domain") for a in arts]
    assert "příliš-žluťoučký.example" in domains
    # wildcard prefix se ořezává, diakritika zůstává verbatim
    assert "žluťouček.cz" in domains


def test_encoding_allowlisted_websites(tmp_path: Path) -> None:
    # quality: encoding
    p = tmp_path / "allowlist.json"
    # 0xFF/0xFE jsou v UTF-8 neplatné → errors=replace → U+FFFD
    p.write_bytes(b'["\xff\xfe-priklad.cz"]')
    arts = extract_allowlisted_websites_artifacts(p)
    assert len(arts) == 1
    assert arts[0].details.get("domain") == "\ufffd\ufffd-priklad.cz"


def test_size_allowlisted_websites(tmp_path: Path) -> None:
    # quality: size
    p = tmp_path / "allowlist.json"
    domains = [f"firma-{i}.priklad.cz" for i in range(5_000)]
    p.write_text(json.dumps(domains), encoding="utf-8")
    arts = extract_allowlisted_websites_artifacts(p)
    # parser nemá horní limit — soubor se zpracuje stabilně a kompletně
    assert len(arts) == 5_000
    first_title = arts[0].title
    assert first_title is not None and "firma-0.priklad.cz" in first_title


def test_tz_allowlisted_websites(tmp_path: Path) -> None:
    # quality: tz
    p = tmp_path / "allowlist.json"
    p.write_text(json.dumps(["a.cz", "b.example"]), encoding="utf-8")
    arts = extract_allowlisted_websites_artifacts(p)
    assert len(arts) == 2
    # snapshot bez času — deterministicky None (ne odhadované „now")
    for a in arts:
        assert a.timestamp is None


# ---------------------------------------------------------------------------
# mailru_agent — encoding / locale / size / tz
# ---------------------------------------------------------------------------

_MAILRU_CZ_LINE = (
    "2015-03-14 10:23:45 | IN | 777123456 | Příliš Žluťouček : "
    "Ahoj, jak se máš žluťoučký kůň?"
)


def test_locale_mailru_agent() -> None:
    # quality: locale
    recs = parse_mailru_chat_log(_MAILRU_CZ_LINE.encode("utf-8"))
    assert len(recs) == 1
    assert recs[0].display_name == "Příliš Žluťouček"
    assert recs[0].message == "Ahoj, jak se máš žluťoučký kůň?"
    arts = build_mailru_artifacts(recs, [])
    title = arts[0].title
    expected = (
        "Mail.ru Příliš Žluťouček: Ahoj, jak se máš žluťoučký kůň?"
    )
    assert title is not None and title == expected


def test_encoding_mailru_agent() -> None:
    # quality: encoding
    # latin-1 0xDA (Ú) + raw 0x9A — v UTF-8 neplatné → errors=replace
    raw = (
        "2015-03-14 10:23:45 | IN | u1 | J : Ahoj Ú ".encode("latin-1")
        + b"\x9a"
        + " svitěte".encode()
    )
    recs = parse_mailru_chat_log(raw)
    assert len(recs) == 1
    assert "\ufffd" in recs[0].message


def test_size_mailru_agent() -> None:
    # quality: size
    parts: list[str] = []
    for i in range(20_001):
        msg = "first-msg" if i == 0 else "m"
        parts.append(
            f"2015-03-{i % 28 + 1:02d} {i % 24:02d}:{i % 60:02d}:00"
            f" | IN | u{i} | N : {msg}"
        )
    recs = parse_mailru_chat_log("\n".join(parts).encode("utf-8"))
    assert len(recs) == MAX_LINES_PER_FILE
    assert recs[0].message == "first-msg"


def test_tz_mailru_agent() -> None:
    # quality: tz
    raw = (
        b"2015-03-14 10:23:45 | IN | u1 | J : ahoj\n"
        b"2015-03-14 10:24 | IN | u2 | K : b"
    )
    recs = parse_mailru_chat_log(raw)
    assert len(recs) == 2
    # naive timestamp → deterministicky aware UTC; přesnost minuty → :00
    assert recs[0].created_dt == datetime(
        2015, 3, 14, 10, 23, 45, tzinfo=timezone.utc
    )
    assert recs[1].created_dt == datetime(
        2015, 3, 14, 10, 24, 0, tzinfo=timezone.utc
    )
    arts = build_mailru_artifacts(recs, [])
    ts = arts[0].timestamp
    assert ts is not None and ts.tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# openoffice_base — encoding / locale / size / tz
# ---------------------------------------------------------------------------


def test_locale_openoffice_base(tmp_path: Path) -> None:
    # quality: locale
    p = _make_odb(
        tmp_path / "db.odb",
        "Příliš žluťoučký kůň databáze",
        creator="Jan Žluťouček",
    )
    arts = extract_openoffice_base_artifacts(p)
    assert len(arts) == 1
    title = arts[0].title
    assert (
        title is not None
        and title == "OpenOffice Base: Příliš žluťoučký kůň databáze"
    )
    assert arts[0].details.get("creator") == "Jan Žluťouček"


def test_encoding_openoffice_base(tmp_path: Path) -> None:
    # quality: encoding
    # XML deklarace iso-8859-1 — ElementTree dekoduje dle deklarace,
    # bez U+FFFD (úplně jiná cesta než utf-8 errors=replace)
    p = _make_odb(
        tmp_path / "latin1.odb",
        "ÚROKOVÁ DATABÁZE ÚÉÍÓ",
        xml_encoding="latin-1",
    )
    arts = extract_openoffice_base_artifacts(p)
    assert len(arts) == 1
    title = arts[0].title
    assert (
        title is not None and "ÚROKOVÁ DATABÁZE" in title and "\ufffd" not in title
    )


def test_size_openoffice_base(tmp_path: Path) -> None:
    # quality: size
    long_title = ("Příliš žluťoučký kůň užíval hloušť. " * 5)[:150]
    assert len(long_title) == 150
    p = _make_odb(tmp_path / "long.odb", long_title)
    arts = extract_openoffice_base_artifacts(p)
    assert len(arts) == 1
    title = arts[0].title
    expected = "OpenOffice Base: " + long_title[:120]
    assert title is not None and title == expected


def test_tz_openoffice_base(tmp_path: Path) -> None:
    # quality: tz
    p1 = _make_odb(
        tmp_path / "aware.odb", "Úroková databáze", date="2015-03-14T12:23:45+02:00"
    )
    arts = extract_openoffice_base_artifacts(p1)
    assert len(arts) == 1
    # +02:00 → přesný UTC ekvivalent (astimezone), ne „raw hodnota"
    assert arts[0].timestamp == datetime(
        2015, 3, 14, 10, 23, 45, tzinfo=timezone.utc
    )
    # naive dc:date → deterministicky UTC
    p2 = _make_odb(tmp_path / "naive.odb", "Úroková databáze", date="2015-03-14T10:23:45")
    arts2 = extract_openoffice_base_artifacts(p2)
    assert len(arts2) == 1
    assert arts2[0].timestamp == datetime(
        2015, 3, 14, 10, 23, 45, tzinfo=timezone.utc
    )


# ---------------------------------------------------------------------------
# sim_tpdu — corrupted / encoding / locale / size / tz
# ---------------------------------------------------------------------------

_GARBAGE_BYTES = struct.pack("<I", 0xDEADBEEF) * 30 + b"\x89PNG\r\n\x1a\n"


def test_corrupted_sim_tpdu(tmp_path: Path) -> None:
    # quality: corrupted
    p1 = tmp_path / "garbage.tpdu"
    p1.write_bytes(_GARBAGE_BYTES)
    # binární smetí bez číslic → deterministicky prázdný výsledek, ne výjimka
    assert extract_tpdu_artifacts(p1) == []
    # smetí + jeden validní CPBR řádek → celý soubor jde latin-1 fallbackem
    # (binární bajty invalidují UTF-8), ASCII jméno zůstává verbatim
    p2 = tmp_path / "mixed.tpdu"
    p2.write_bytes(b"\x89PNG\r\n\x1a\nAT+CPBR: \"John Doe\",+420555123456,129\n")
    arts = extract_tpdu_artifacts(p2)
    assert len(arts) == 1
    title = arts[0].title
    assert title is not None and title == "John Doe"


def test_encoding_sim_tpdu(tmp_path: Path) -> None:
    # quality: encoding
    # CPBR dump v latin-1 (Á=0xC1, É=0xC9, Í=0xCD — neplatné UTF-8) →
    # fallback dekoduje latin-1 a diakritika zůstává verbatim
    line = 'AT+CPBR: "ÁBECEDNÍK",+420777123456,129'.encode("latin-1")
    p = tmp_path / "dump.cpbr"
    p.write_bytes(line + b"\n")
    arts = extract_tpdu_artifacts(p)
    assert len(arts) == 1
    title = arts[0].title
    assert title is not None and title == "ÁBECEDNÍK"


def test_locale_sim_tpdu() -> None:
    # quality: locale
    text = (
        'AT+CPBR: "Příliš Žluťouček",+420777987654,129\n'
        '  "Žluťouček Kůň","420 555 987 654"\n'
    )
    entries = parse_tpdu_text(text)
    assert {e.name for e in entries} == {"Příliš Žluťouček", "Žluťouček Kůň"}
    arts = build_tpdu_artifacts(entries)
    assert {a.title for a in arts} == {"Příliš Žluťouček", "Žluťouček Kůň"}


def test_size_sim_tpdu() -> None:
    # quality: size
    lines = [
        f'AT+CPBR: "K{i}",+420777{i:07d},129' for i in range(MAX_CONTACTS_PER_DUMP + 1)
    ]
    entries = parse_tpdu_text("\n".join(lines))
    assert len(entries) == MAX_CONTACTS_PER_DUMP
    numbers = {e.number for e in entries}
    # poslední (2001.) záznam odhozen, první zachován
    assert "+4207770000000" in numbers
    assert f"+420777{MAX_CONTACTS_PER_DUMP:07d}" not in numbers


def test_tz_sim_tpdu(tmp_path: Path) -> None:
    # quality: tz
    p = tmp_path / "dump.tpdu"
    p.write_bytes(
        b'AT+CPBR: "A",+420111222333,129\n  "B","420555666777"\n'
    )
    arts = extract_tpdu_artifacts(p)
    assert len(arts) == 2
    # SIM dump nespolehlivě nese čas — deterministicky None, ne „now"
    for a in arts:
        assert a.timestamp is None


# ---------------------------------------------------------------------------
# apple_cloud — locale / negative
# ---------------------------------------------------------------------------


def test_locale_apple_cloud() -> None:
    # quality: locale
    payload = {
        "contacts": [
            {"firstName": "Příliš", "lastName": "Žluťouček",
             "emailAddresses": ["p.z@example.cz"]}
        ]
    }
    recs = parse_apple_cloud(json.dumps(payload).encode("utf-8"))
    assert len(recs) == 1
    assert recs[0].kind == "contact"
    assert recs[0].name == "Příliš Žluťouček"


def test_negative_apple_cloud() -> None:
    # quality: negative
    with pytest.raises(TypeError, match="Nenalezeny Apple Cloud záznamy"):
        parse_apple_cloud(json.dumps({"foo": "bar"}).encode("utf-8"))


# ---------------------------------------------------------------------------
# drive_activity — corrupted / locale
# ---------------------------------------------------------------------------


def test_corrupted_drive_activity() -> None:
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_drive_activity(b"\x89PNG\r\n\x1a\n" + b"\xff" * 32)


def test_locale_drive_activity() -> None:
    # quality: locale
    payload = {
        "activities": [
            {"fileName": "Příliš_žluťoučký_kůň.pdf",
             "action": "upload", "actorEmail": "žena@example.cz"}
        ]
    }
    recs = parse_drive_activity(json.dumps(payload).encode("utf-8"))
    assert len(recs) == 1
    assert recs[0].file_name == "Příliš_žluťoučký_kůň.pdf"
    assert recs[0].actor == "žena@example.cz"


# ---------------------------------------------------------------------------
# gmail_messages — locale / negative
# ---------------------------------------------------------------------------


def test_locale_gmail_messages() -> None:
    # quality: locale
    payload = {
        "messages": [
            {"subject": "Příliš žluťoučký kůň",
             "from": "Jan Žluťouček <z@example.cz>",
             "body": "Těší mě, až se uvidíme."}
        ]
    }
    recs = parse_gmail_messages(json.dumps(payload).encode("utf-8"))
    assert len(recs) == 1
    assert recs[0].subject == "Příliš žluťoučký kůň"
    sender = recs[0].sender or ""
    assert "Jan Žluťouček" in sender


def test_negative_gmail_messages() -> None:
    # quality: negative
    with pytest.raises(TypeError, match="Nenalezeny Gmail cloud zprávy"):
        parse_gmail_messages(json.dumps({"foo": 1}).encode("utf-8"))


# ---------------------------------------------------------------------------
# maps_labeled_places — locale / negative
# ---------------------------------------------------------------------------


def test_locale_maps_labeled_places() -> None:
    # quality: locale
    payload = {
        "places": [
            {"label": "domov", "name": "Příliš žluťoučký dům",
             "latitude": 50.1, "longitude": 14.4}
        ]
    }
    recs = parse_maps_labeled_places(json.dumps(payload).encode("utf-8"))
    assert len(recs) == 1
    assert recs[0].name == "Příliš žluťoučký dům"
    assert recs[0].label == "domov"


def test_negative_maps_labeled_places() -> None:
    # quality: negative
    with pytest.raises(TypeError, match="Nenalezena označená Google Maps místa"):
        parse_maps_labeled_places(json.dumps({"foo": 1}).encode("utf-8"))


# ---------------------------------------------------------------------------
# whatsapp_cloud — locale / negative
# ---------------------------------------------------------------------------


def test_locale_whatsapp_cloud() -> None:
    # quality: locale
    payload = {
        "chats": [
            {"chatName": "Příliš Žluťouček",
             "messages": [{"sender": "Kůň", "text": "Ahoj žluťoučký"}]}
        ]
    }
    recs = parse_whatsapp_cloud(json.dumps(payload).encode("utf-8"))
    assert len(recs) == 1
    assert recs[0].kind == "chat"
    assert recs[0].name == "Příliš Žluťouček"
    assert recs[0].sender == "Kůň"
    assert recs[0].text == "Ahoj žluťoučký"


def test_negative_whatsapp_cloud() -> None:
    # quality: negative
    with pytest.raises(TypeError, match="Nenalezeny WhatsApp cloud záznamy"):
        parse_whatsapp_cloud(json.dumps({"foo": 1}).encode("utf-8"))
