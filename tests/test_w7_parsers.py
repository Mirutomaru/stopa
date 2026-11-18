"""ETAPA B vlna 7 — syntetické offline testy (5 parserů / 12 AXIOM typů).

Pokrývá:
- ``google_chrome_bookmarks`` — Chrome Bookmarks JSON (roots/date_added µs/1601)
- ``google_chrome_history_wr`` — Chrome History warrant return JSON (visit_time)
- ``google_contacts_wr`` — Google Contacts Takeout/warrant JSON
- ``google_chrome_autofill`` — Chrome Autofill / Contact Info JSON
- ``skype_warrant_return`` — Skype warrant return JSON (4 subtypy, auto-detekce)

Vše plně offline: syntetické fixtures, žádné sítě.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.google_chrome_autofill import (
    build_autofill_artifacts,
    extract_chrome_autofill_artifacts,
    is_chrome_autofill_file,
    parse_chrome_autofill,
)
from stopa.artifacts.google_chrome_bookmarks import (
    build_bookmark_artifacts,
    extract_bookmarks_artifacts,
    is_chrome_bookmarks_file,
    parse_chrome_bookmarks,
)
from stopa.artifacts.google_chrome_history_wr import (
    build_chrome_history_artifacts,
    extract_chrome_history_wr_artifacts,
    is_chrome_history_wr_file,
    parse_chrome_history_wr,
)
from stopa.artifacts.google_contacts_wr import (
    build_contact_artifacts,
    extract_contacts_wr_artifacts,
    is_contacts_wr_file,
    parse_contacts_wr,
)
from stopa.artifacts.skype_warrant_return import (
    build_skype_artifacts,
    extract_skype_artifacts,
    is_skype_warrant_file,
    parse_skype_warrant,
)
from stopa.domain.times import to_chrome_micros

# ── Chrome Bookmarks ────────────────────────────────────────────────────────


def _bookmarks_json() -> bytes:
    dt = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    us = to_chrome_micros(dt)
    return json.dumps(
        {
            "roots": {
                "bookmark_bar": {
                    "children": [
                        {
                            "date_added": str(us),
                            "id": "1",
                            "name": "Example",
                            "type": "url",
                            "url": "https://example.com",
                        },
                        {
                            "children": [
                                {
                                    "date_added": str(us),
                                    "id": "3",
                                    "name": "Podstránka",
                                    "type": "url",
                                    "url": "https://pod.example.cz",
                                }
                            ],
                            "date_added": str(us),
                            "id": "2",
                            "name": "Složka",
                            "type": "folder",
                        },
                    ],
                    "date_added": str(us),
                    "id": "0",
                    "name": "Bookmarks bar",
                    "type": "folder",
                }
            }
        }
    ).encode()


def test_bookmarks_parse_takeout():
    # quality: positive
    records = parse_chrome_bookmarks(_bookmarks_json())
    assert len(records) == 2
    r0 = records[0]
    assert r0.name == "Example"
    assert r0.url == "https://example.com"
    assert r0.date_added_s is not None
    # µs od 1601 → epoch s — zpětná konverze musí dát stejný čas
    from stopa.domain.times import from_unix

    back = from_unix(r0.date_added_s)
    assert (back.year, back.month, back.day) == (2024, 5, 1)


def test_bookmarks_nested_folder_path():
    # quality: positive
    records = parse_chrome_bookmarks(_bookmarks_json())
    nested = [r for r in records if "Podstránka" in r.name]
    assert len(nested) == 1
    assert "Složka" in nested[0].folder_path


def test_bookmarks_invalid_json():
    # quality: negative
    with pytest.raises(ValueError):
        parse_chrome_bookmarks(b"{nejson")


def test_bookmarks_not_dict():
    # quality: positive
    with pytest.raises(TypeError):
        parse_chrome_bookmarks(json.dumps([1, 2]).encode())


def test_bookmarks_missing_roots():
    # quality: negative
    with pytest.raises(TypeError):
        parse_chrome_bookmarks(json.dumps({"foo": "bar"}).encode())


def test_bookmarks_detect():
    # quality: positive
    head = b'{"roots": {"bookmark_bar": {"date_added": "1"}}}'
    assert is_chrome_bookmarks_file("Bookmarks", head)
    assert is_chrome_bookmarks_file("chrome_bookmarks.json")
    # bez bookmark v názvu → False
    assert not is_chrome_bookmarks_file("random.txt", head)
    # nesprávný obsah (bez roots markeru) → False
    assert not is_chrome_bookmarks_file("Bookmarks", b'{"foo": 1}')


def test_bookmarks_artifacts():
    # quality: positive
    records = parse_chrome_bookmarks(_bookmarks_json())
    artifacts = build_bookmark_artifacts(records)
    assert len(artifacts) == 2
    a0 = artifacts[0]
    assert a0.artifact_type == "browser_bookmark"
    assert a0.details["url"] == "https://example.com"
    assert a0.details["engine"] == "chrome_bookmarks"
    assert a0.timestamp is not None


def test_bookmarks_extract_io(tmp_path: Path):
    # quality: positive
    p = tmp_path / "Bookmarks"
    p.write_bytes(_bookmarks_json())
    artifacts = extract_bookmarks_artifacts(p)
    assert len(artifacts) == 2
    # chybějící soubor → [] (defenzivní IO)
    assert extract_bookmarks_artifacts(tmp_path / "chybi") == []


# ── Chrome History Warrant Return ───────────────────────────────────────────


def _history_wr_json() -> bytes:
    dt = datetime(2024, 6, 15, 8, 30, tzinfo=timezone.utc)
    us = to_chrome_micros(dt)
    return json.dumps(
        [
            {
                "url": "https://news.example.com/article",
                "title": "Článek",
                "visit_time": str(us),
                "transition_type": 80530640,
            },
            {"url": "https://example.org", "visit_time": None},
        ]
    ).encode()


def test_history_wr_parse_list():
    # quality: positive
    records = parse_chrome_history_wr(_history_wr_json())
    assert len(records) == 2
    r0 = records[0]
    assert r0.url == "https://news.example.com/article"
    assert r0.title == "Článek"
    assert r0.visit_time_s is not None
    from stopa.domain.times import from_unix

    back = from_unix(r0.visit_time_s)
    assert (back.year, back.month, back.day) == (2024, 6, 15)


def test_history_wr_dict_wrapper():
    # quality: positive
    data = json.dumps({"history": [{"url": "https://x.cz", "visit_time": "1"}]}).encode()
    records = parse_chrome_history_wr(data)
    assert len(records) == 1
    assert records[0].url == "https://x.cz"


def test_history_wr_invalid_json():
    # quality: negative
    with pytest.raises(ValueError):
        parse_chrome_history_wr(b"[{")


def test_history_wr_not_list():
    # quality: positive
    with pytest.raises(TypeError):
        parse_chrome_history_wr(json.dumps({"a": 1}).encode())


def test_history_wr_detect():
    # quality: positive
    head = b'[{"url": "https://x", "visit_time": "1"}]'
    assert is_chrome_history_wr_file("chrome_history.json", head)
    # lokální Chrome History DB (SQLite) → False
    assert not is_chrome_history_wr_file("History.db")
    # bez visit_time/url markeru → False
    assert not is_chrome_history_wr_file("history.json", b'{"foo": 1}')


def test_history_wr_artifacts():
    # quality: positive
    records = parse_chrome_history_wr(_history_wr_json())
    artifacts = build_chrome_history_artifacts(records)
    assert len(artifacts) == 2
    a0 = artifacts[0]
    assert a0.artifact_type == "browser_history"
    assert a0.details["url"] == "https://news.example.com/article"
    assert a0.timestamp is not None


def test_history_wr_extract_io(tmp_path: Path):
    # quality: positive
    p = tmp_path / "chrome_history.json"
    p.write_bytes(_history_wr_json())
    artifacts = extract_chrome_history_wr_artifacts(p)
    assert len(artifacts) == 2
    assert extract_chrome_history_wr_artifacts(tmp_path / "chybi") == []


# ── Google Contacts Warrant Return ──────────────────────────────────────────


def _contacts_json() -> bytes:
    return json.dumps(
        [
            {
                "name": ["Jan Novák"],
                "givenName": ["Jan"],
                "familyName": ["Novák"],
                "emails": [{"label": ["home"], "value": "jan@example.com"}],
                "phoneNumbers": [{"label": ["mobile"], "value": "+420123456789"}],
            },
            {
                # People API varianta — objekty s displayName
                "names": [{"displayName": "Petr Svoboda"}],
                "emailAddresses": [{"value": "petr@example.cz"}],
            },
        ]
    ).encode()


def test_contacts_parse_takeout():
    # quality: positive
    records = parse_contacts_wr(_contacts_json())
    assert len(records) == 2
    r0 = records[0]
    assert r0.display_name == "Jan Novák"
    assert r0.given_name == "Jan"
    assert r0.family_name == "Novák"
    assert r0.emails == ["jan@example.com"]
    assert r0.phones == ["+420123456789"]


def test_contacts_people_api_fallback():
    # quality: positive
    records = parse_contacts_wr(_contacts_json())
    r1 = records[1]
    # names[0].displayName fallback
    assert r1.display_name == "Petr Svoboda"
    assert r1.emails == ["petr@example.cz"]


def test_contacts_invalid_json():
    # quality: negative
    with pytest.raises(ValueError):
        parse_contacts_wr(b"[{")


def test_contacts_not_list():
    # quality: positive
    with pytest.raises(TypeError):
        parse_contacts_wr(json.dumps({"x": 1}).encode())


def test_contacts_detect():
    # quality: positive
    head = b'[{"givenName": ["A"], "emails": []}]'
    assert is_contacts_wr_file("contacts.json", head)
    # lokální contacts2.db (Android) → False
    assert not is_contacts_wr_file("contacts2.db")
    # bez contact markeru v obsahu → False
    assert not is_contacts_wr_file("google_contacts.json", b'{"foo": 1}')


def test_contacts_artifacts():
    # quality: positive
    records = parse_contacts_wr(_contacts_json())
    artifacts = build_contact_artifacts(records)
    assert len(artifacts) == 2
    a0 = artifacts[0]
    assert a0.artifact_type == "contact"
    assert a0.details["emails"] == ["jan@example.com"]
    assert a0.details["phones"] == ["+420123456789"]


def test_contacts_extract_io(tmp_path: Path):
    # quality: positive
    p = tmp_path / "contacts.json"
    p.write_bytes(_contacts_json())
    artifacts = extract_contacts_wr_artifacts(p)
    assert len(artifacts) == 2
    assert extract_contacts_wr_artifacts(tmp_path / "chybi") == []


# ── Chrome Autofill / Contact Info ──────────────────────────────────────────


def _autofill_json() -> bytes:
    return json.dumps(
        [
            {
                "name": "Jan Novák",
                "email": "jan@example.com",
                "phoneNumber": "+420123456789",
                "addressLine1": "Hlavní 1",
                "city": "Brno",
                "countryCode": "CZ",
            },
            {"email": "jenmail@example.cz"},
            # prázdný záznam (bez jména i e-mailu) → vynechat
            {"phoneNumber": "+420999888777"},
        ]
    ).encode()


def test_autofill_parse_list():
    # quality: positive
    records = parse_chrome_autofill(_autofill_json())
    assert len(records) == 2  # prázdný záznam vynechan
    r0 = records[0]
    assert r0.name == "Jan Novák"
    assert r0.email == "jan@example.com"
    assert r0.phone == "+420123456789"
    assert r0.city == "Brno"


def test_autofill_empty_skipped():
    # quality: boundary
    records = parse_chrome_autofill(_autofill_json())
    emails = [r.email for r in records]
    assert "jenmail@example.cz" in emails
    # záznam s jen telefonem (bez jména i e-mailu) není v seznamu
    assert all(r.name or r.email for r in records)


def test_autofill_invalid_json():
    # quality: negative
    with pytest.raises(ValueError):
        parse_chrome_autofill(b"{")


def test_autofill_not_list():
    # quality: positive
    with pytest.raises(TypeError):
        parse_chrome_autofill(json.dumps({"a": 1}).encode())


def test_autofill_detect():
    # quality: positive
    head = b'[{"name": "A", "phoneNumber": "+420"}]'
    assert is_chrome_autofill_file("autofill.json", head)
    assert is_chrome_autofill_file("ContactInfo.json")
    # bez autofill klíčového slova → False
    assert not is_chrome_autofill_file("random.json", head)


def test_autofill_artifacts():
    # quality: positive
    records = parse_chrome_autofill(_autofill_json())
    artifacts = build_autofill_artifacts(records)
    assert len(artifacts) == 2
    a0 = artifacts[0]
    assert a0.artifact_type == "autofill_entry"
    assert a0.details["email"] == "jan@example.com"
    assert a0.details["city"] == "Brno"


def test_autofill_extract_io(tmp_path: Path):
    # quality: positive
    p = tmp_path / "autofill.json"
    p.write_bytes(_autofill_json())
    artifacts = extract_chrome_autofill_artifacts(p)
    assert len(artifacts) == 2
    assert extract_chrome_autofill_artifacts(tmp_path / "chybi") == []


# ── Skype Warrant Return (4 subtypy, auto-detekce) ──────────────────────────


def _skype_account_json() -> bytes:
    return json.dumps(
        {
            "account": "skype:user123",
            "email": "user@example.com",
            "displayName": "User One",
        }
    ).encode()


def _skype_chat_json() -> bytes:
    return json.dumps(
        [
            {
                "conversationId": "conv-1",
                "from": "8:user123",
                "to": "8:buddy456",
                "message": "Ahoj, jak se máš?",
                "composetime": "2016-01-01T00:00:00.000Z",
            },
            {
                "conversationId": "conv-1",
                "from": "8:buddy456",
                "to": "8:user123",
                "message": "Dobrě, díky!",
                "composetime": 1700000000000,  # epoch ms
            },
        ]
    ).encode()


def _skype_connection_json() -> bytes:
    return json.dumps(
        [
            {
                "contact": "8:buddy456",
                "status": "accepted",
                "dateAdded": "2015-06-15T10:00:00.000Z",
            }
        ]
    ).encode()


def _skype_contacts_json() -> bytes:
    return json.dumps(
        [
            {
                "displayName": "Buddy 456",
                "msnId": "8:buddy456",
                "email": "buddy@example.com",
            }
        ]
    ).encode()


def test_skype_account_details():
    # quality: positive
    records = parse_skype_warrant(_skype_account_json())
    assert len(records) == 1
    r0 = records[0]
    assert r0.sub_type == "account"
    assert r0.details["account"] == "skype:user123"
    assert r0.details["email"] == "user@example.com"


def test_skype_chat_history():
    # quality: positive
    records = parse_skype_warrant(_skype_chat_json())
    assert len(records) == 2
    r0 = records[0]
    assert r0.sub_type == "chat"
    assert r0.details["sender"] == "8:user123"
    assert r0.timestamp_s is not None
    # ISO 8601 s Z → epoch (2016-01-01T00:00:00Z = 1451606400)
    assert abs(r0.timestamp_s - 1451606400.0) < 1.0


def test_skype_chat_epoch_ms():
    # quality: positive
    records = parse_skype_warrant(_skype_chat_json())
    r1 = records[1]
    # epoch ms → s
    assert abs(r1.timestamp_s - 1700000000.0) < 0.001


def test_skype_connection_history():
    # quality: positive
    records = parse_skype_warrant(_skype_connection_json())
    assert len(records) == 1
    r0 = records[0]
    assert r0.sub_type == "connection"
    assert r0.details["status"] == "accepted"
    assert r0.timestamp_s is not None


def test_skype_contacts():
    # quality: positive
    records = parse_skype_warrant(_skype_contacts_json())
    assert len(records) == 1
    r0 = records[0]
    assert r0.sub_type == "contact"
    assert r0.details["msn_id"] == "8:buddy456"
    assert r0.details["email"] == "buddy@example.com"


def test_skype_invalid_json():
    # quality: negative
    with pytest.raises(ValueError):
        parse_skype_warrant(b"[{")


def test_skype_unknown_subtype():
    # quality: negative
    # pole bez známých markerů → neznámý subtyp
    with pytest.raises(TypeError):
        parse_skype_warrant(json.dumps([{"foo": 1}]).encode())


def test_skype_detect():
    # quality: positive
    head = b'[{"msnId": "8:x", "displayName": "X"}]'
    assert is_skype_warrant_file("skype_contacts.json", head)
    # skype v názvu + JSON → True (parser auto-detekuje subtyp)
    assert is_skype_warrant_file("skype_export.json", b"[]")
    # bez skype v názvu a bez silného markeru → False
    assert not is_skype_warrant_file("random.json", b'{"foo": 1}')


def test_skype_artifacts_by_subtype():
    # quality: positive
    chat = build_skype_artifacts(parse_skype_warrant(_skype_chat_json()))
    assert all(a.artifact_type == "messenger_message" for a in chat)
    contacts = build_skype_artifacts(parse_skype_warrant(_skype_contacts_json()))
    assert all(a.artifact_type == "contact" for a in contacts)
    account = build_skype_artifacts(parse_skype_warrant(_skype_account_json()))
    assert all(a.artifact_type == "skype_account" for a in account)


def test_skype_extract_io(tmp_path: Path):
    # quality: positive
    p = tmp_path / "skype_chat.json"
    p.write_bytes(_skype_chat_json())
    artifacts = extract_skype_artifacts(p)
    assert len(artifacts) == 2
    assert all(a.artifact_type == "messenger_message" for a in artifacts)
    assert extract_skype_artifacts(tmp_path / "chybi") == []
