"""P1-1 Parser Quality Framework — vlna 7: cloud SNS (w10, 4 parsery).

Parseri (sdílený test soubor ``tests/test_w10_parsers.py``):
``instagram_messages``, ``instagram_posts``, ``instagram_account``, ``snapchat_wr``.

Doplněné kategorie: ``tz`` / ``encoding`` / ``corrupted`` / ``boundary`` / ``size``.

Kontrakty doložené probe (``probe_w10.py``):
- Timestampy = **int epoch seconds** (numerický string se konvertuje na int);
  ISO string → graceful degradace na ``None`` (dokumentovaná limitem parseru).
- UTF-8 BOM → ValueError „Neplatné JSON“ u všech vstupních bodů.
- Prázdné vstupy → TypeError „Nenalezeny …“ (dokumentovaný kontrakt):
  messages/posts/account/snapchat `[]`, contacts `{}`, geolocation `[]`, ip `{}`.

Data jsou syntetická a anonymizovaná. Plně offline, deterministicky.
"""

from __future__ import annotations

import json

import pytest

from stopa.artifacts.instagram_account import parse_instagram_account
from stopa.artifacts.instagram_messages import parse_instagram_messages
from stopa.artifacts.instagram_posts import parse_instagram_posts
from stopa.artifacts.snapchat_wr import (
    parse_snapchat_contacts,
    parse_snapchat_geolocation,
    parse_snapchat_ip_history,
    parse_snapchat_messages,
)

BOM = b"\xef\xbb\xbf"


# ── tz: epoch konvence a degradace ───────────────────────────────────────────


def test_int_epoch_passthrough_all_entrypoints():
    # quality: tz
    """Int epoch s → exaktní propustění ve všech časových polích."""
    target = 1_728_000_000

    recs = parse_instagram_messages(
        json.dumps([{"from": "a", "body": "x", "time": target}]).encode()
    )
    assert recs[0].timestamp == target

    posts, comments = parse_instagram_posts(json.dumps([{
        "id": "p", "caption": "c", "timestamp": target,
        "comments": [{"user": "u", "text": "t", "time": target + 60}],
    }]).encode())
    assert posts[0].timestamp == target
    assert comments[0].timestamp == target + 60

    events, _ = parse_instagram_account(
        json.dumps([{"type": "login", "time": target}]).encode()
    )
    assert events[0].timestamp == target

    sc = parse_snapchat_messages(
        json.dumps([{"from": "a", "body": "x", "time": target}]).encode()
    )
    assert sc[0].timestamp == target


def test_numeric_string_and_iso_degradation():
    # quality: tz
    """Numerický string == int epoch; ISO string → None (dokumentovaná degradace)."""
    as_int = parse_instagram_messages(
        json.dumps([{"from": "a", "body": "x", "time": 1_728_000_000}]).encode()
    )
    as_str = parse_instagram_messages(
        json.dumps([{"from": "a", "body": "x", "time": "1728000000"}]).encode()
    )
    assert as_int[0].timestamp == as_str[0].timestamp == 1_728_000_000

    iso = parse_instagram_messages(
        json.dumps([{"from": "a", "body": "x", "time": "2024-10-03T14:00:00+02:00"}]).encode()
    )
    assert iso[0].timestamp is None  # int-only konvence — degradace, ne výjimka


# ── encoding: UTF-8 / diakritika ────────────────────────────────────────────


def test_czech_roundtrip_instagram_snapchat():
    # quality: encoding
    """Diakritika přežije všechny 4 parsery bez ztrát."""
    recs = parse_instagram_messages(
        json.dumps([{"from": "a", "body": "Příliš žluťoučký kůň"}]).encode()
    )
    assert recs[0].text == "Příliš žluťoučký kůň"

    posts, _ = parse_instagram_posts(
        json.dumps([{"id": "p", "caption": "Víkend u jezera"}]).encode()
    )
    assert posts[0].caption == "Víkend u jezera"

    _, users = parse_instagram_account(json.dumps({
        "followers": [{"username": "f1", "full_name": "Jan Novák"}],
    }).encode())
    assert users[0].full_name == "Jan Novák"

    sc = parse_snapchat_contacts(
        json.dumps({"friends": [{"username": "f1", "full_name": "Petr Dvořák"}]}).encode()
    )
    assert sc[0].full_name == "Petr Dvořák"


# ── corrupted: BOM / oříznuté JSON / smetí ───────────────────────────────────


def test_bom_rejected_all_parsers():
    # quality: corrupted
    """UTF-8 BOM → ValueError „Neplatné JSON“ u všech vstupních bodů."""
    cases = [
        (parse_instagram_messages, json.dumps([{"from": "a", "body": "x"}]).encode()),
        (parse_instagram_posts, json.dumps([{"id": "p", "caption": "c"}]).encode()),
        (parse_instagram_account, json.dumps([{"type": "login"}]).encode()),
        (parse_snapchat_messages, json.dumps([{"from": "a", "body": "x"}]).encode()),
    ]
    for parser, data in cases:
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(BOM + data)


def test_truncated_and_garbage():
    # quality: corrupted
    """Oříznuté JSON a binární smetí → ValueError."""
    truncated = b'[{"from": "a", "body"'
    with pytest.raises(ValueError):
        parse_snapchat_messages(truncated)
    garbage = b"\x00\x01\xff\xfe{bin"
    with pytest.raises(ValueError):
        parse_instagram_account(garbage)


# ── boundary: prázdné a minimální vstupy ─────────────────────────────────────


def test_empty_collections_typeerror_contract():
    # quality: boundary
    """Prázdné vstupy → TypeError „Nenalezeny …“ (dokumentovaný kontrakt)."""
    with pytest.raises(TypeError, match="Nenalezeny Instagram DM zprávy"):
        parse_instagram_messages(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Instagram položky"):
        parse_instagram_posts(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Instagram account záznamy"):
        parse_instagram_account(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Snapchat zprávy"):
        parse_snapchat_messages(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Snapchat kontakty"):
        parse_snapchat_contacts(b"{}")
    with pytest.raises(TypeError, match="Nenalezeny Snapchat geolokační body"):
        parse_snapchat_geolocation(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Snapchat IP záznamy"):
        parse_snapchat_ip_history(b"{}")


def test_single_minimal_record_each():
    # quality: boundary
    """Jeden minimální záznam per vstupní bod → přesně 1 záznam."""
    assert len(parse_instagram_messages(
        json.dumps([{"from": "a", "body": "x"}]).encode())) == 1

    posts, comments = parse_instagram_posts(
        json.dumps([{"id": "p", "caption": "c"}]).encode()
    )
    assert len(posts) == 1 and comments == []

    events, users = parse_instagram_account(
        json.dumps({"followers": [{"username": "f1"}]}).encode()
    )
    assert len(users) == 1 and events == []

    assert len(parse_snapchat_messages(
        json.dumps([{"from": "a", "body": "x"}]).encode())) == 1


# ── size: stresové objemy ─────────────────────────────────────────────────────


def test_stress_many_records():
    # quality: size
    """Stres: stovky záznamů bez výjimky a bez ztráty počtu (pod limity)."""
    conv = [{"id": f"c{i % 10}", "participants": ["a", "b"],
             "messages": [{"sender": "a", "text": f"zpráva {i}"}]} for i in range(30)]
    recs = parse_instagram_messages(json.dumps(conv).encode())
    assert len(recs) == 30

    posts, comments = parse_instagram_posts(json.dumps([
        {"id": f"p{i}", "caption": f"post {i}",
         "comments": [{"user": f"u{j}", "text": f"komentář {j}"} for j in range(2)]}
        for i in range(100)
    ]).encode())
    assert len(posts) == 100 and len(comments) == 200

    events, _ = parse_instagram_account(json.dumps([
        {"type": "login", "time": 1_728_000_000 + i} for i in range(250)
    ]).encode())
    assert len(events) == 250

    geo = [{"latitude": 48.0 + (i % 100) / 100, "longitude": 17.0} for i in range(300)]
    assert len(parse_snapchat_geolocation(json.dumps(geo).encode())) == 300

    ip = {"ip_history": [{"ip_address": f"10.0.{i // 256}.{i % 256}", "time": i}
                         for i in range(200)]}
    assert len(parse_snapchat_ip_history(json.dumps(ip).encode())) == 200
