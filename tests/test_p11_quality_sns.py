"""P1-1 Parser Quality Framework — vlna 6: sociální rodina (w11, 4 parsery).

Parseri (sdílený test soubor ``tests/test_w11_parsers.py``):
``twitter_posts``, ``twitter_messages``, ``twitter_users``, ``facebook_wr``.

Doplněné kategorie: ``tz`` / ``encoding`` / ``corrupted`` / ``boundary`` / ``size``.

Kontrakty doložené probe (``probe_w11.py``):
- ISO 8601 s offsety (+02:00/-05:30/+05:30) → exaktní epochy ve všech časových
  polích (`created_at`, `date`, `timestamp`, `created_time`) — tolerantní
  `_to_epoch` (int s/ms/ISO).
- UTF-8 BOM → ValueError „Neplatné JSON“ u všech parserů (sdílený loader).
- Prázdné kolekce → TypeError „Nenalezeny/Nenalezeni …“ (dokumentovaný kontrakt):
  posts/messages/users `[]`, facebook messages `[]`, friends `{}`, timeline `{}`.

Data jsou syntetická a anonymizovaná. Plně offline, deterministicky.
"""

from __future__ import annotations

import calendar
import json

import pytest

from stopa.artifacts.facebook_wr import (
    parse_facebook_friends,
    parse_facebook_messages,
    parse_facebook_timeline,
)
from stopa.artifacts.twitter_messages import parse_twitter_messages
from stopa.artifacts.twitter_posts import parse_twitter_posts
from stopa.artifacts.twitter_users import parse_twitter_users

BOM = b"\xef\xbb\xbf"


def _epoch(y: int, m: int, d: int, h: int = 0, min_: int = 0) -> int:
    """Nezávislý epoch výpočet (bez stopa.domain.times)."""
    return calendar.timegm((y, m, d, h, min_, 0, 0, 0, 0))


# ── tz: exaktní konverze časových značek ─────────────────────────────────────


def test_iso_offsets_exact_epochs():
    # quality: tz
    """ISO offsety +02:00 / -05:30 / +05:30 → exaktní epochy ve všech polích."""
    noon = _epoch(2024, 10, 3, 12)

    posts = json.dumps([{"author": "u", "text": "t",
                         "created_at": "2024-10-03T14:00:00+02:00"}]).encode()
    assert parse_twitter_posts(posts)[0].timestamp == noon

    warrant = json.dumps([{"tweet_id": "t", "from_user": "u", "body": "x",
                           "date": "2024-10-03T09:30:00-05:30"}]).encode()
    # UTC = lokální − offset → 09:30 + 05:30 = 15:00Z
    assert parse_twitter_posts(warrant)[0].timestamp == _epoch(2024, 10, 3, 15)

    msgs = json.dumps([{"sender": "a", "recipient": "b", "text": "t",
                        "timestamp": "2024-10-03T14:00:00+02:00"}]).encode()
    assert parse_twitter_messages(msgs)[0].timestamp == noon

    fb = json.dumps({"timeline": [{"author": "a", "text": "p",
                                   "created_time": "2024-10-03T16:00:00+05:30"}]}).encode()
    # UTC = lokální − offset → 16:00 − 05:30 = 10:30Z
    assert parse_facebook_timeline(fb)[0].timestamp == _epoch(2024, 10, 3, 10, 30)


def test_int_and_ms_equivalence():
    # quality: tz
    """Int epoch s a ms heuristika dávají stejný výsledek (twitter posts)."""
    target = _epoch(2024, 10, 3, 12)
    as_s = parse_twitter_posts(json.dumps([{"author": "u", "text": "t",
                                            "created_at": target}]).encode())
    as_ms = parse_twitter_posts(json.dumps([{"author": "u", "text": "t",
                                             "created_at": target * 1000 + 499}]).encode())
    assert as_s[0].timestamp == target
    assert as_ms[0].timestamp == target


# ── encoding: UTF-8 / diakritika ────────────────────────────────────────────


def test_czech_roundtrip_sns():
    # quality: encoding
    """Diakritika přežije všechny 4 parsery bez ztrát."""
    posts = json.dumps([{"author": "uživatel", "text": "Příliš žluťoučký kůň"}]).encode()
    assert parse_twitter_posts(posts)[0].text == "Příliš žluťoučký kůň"

    msgs = json.dumps([{"sender": "a", "recipient": "b",
                        "text": "Ahoj, jak se máš?"}]).encode()
    assert parse_twitter_messages(msgs)[0].text == "Ahoj, jak se máš?"

    users = json.dumps([{"screen_name": "u", "name": "Jan Novák"}]).encode()
    assert parse_twitter_users(users)[0].full_name == "Jan Novák"

    fb = json.dumps({"friends": [{"name": "Petr Dvořák", "username": "pd"}]}).encode()
    assert parse_facebook_friends(fb)[0].full_name == "Petr Dvořák"


# ── corrupted: BOM / oříznuté JSON / smetí ───────────────────────────────────


def test_bom_rejected_all_parsers():
    # quality: corrupted
    """UTF-8 BOM → ValueError „Neplatné JSON“ u všech 4 parserů."""
    cases = [
        (parse_twitter_posts, json.dumps([{"author": "u", "text": "t"}]).encode()),
        (parse_twitter_messages, json.dumps([{"sender": "a", "text": "t"}]).encode()),
        (parse_twitter_users, json.dumps([{"screen_name": "u"}]).encode()),
        (parse_facebook_friends, json.dumps({"friends": [{"name": "X"}]}).encode()),
    ]
    for parser, data in cases:
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(BOM + data)


def test_truncated_and_garbage():
    # quality: corrupted
    """Oříznuté JSON a binární smetí → ValueError."""
    truncated = b'[{"author": "u", "text"'
    with pytest.raises(ValueError):
        parse_twitter_posts(truncated)
    garbage = b"\x00\x01\xff\xfe{bin"
    with pytest.raises(ValueError):
        parse_facebook_friends(garbage)


# ── boundary: prázdné a minimální vstupy ─────────────────────────────────────


def test_empty_collections_typeerror_contract():
    # quality: boundary
    """Prázdné kolekce → TypeError „Nenalezeny/Nenalezeni …“ (dokumentovaný kontrakt)."""
    with pytest.raises(TypeError, match="Nenalezeny Twitter/X příspěvky"):
        parse_twitter_posts(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Twitter/X DM zprávy"):
        parse_twitter_messages(b"[]")
    with pytest.raises(TypeError, match="Nenalezeni Twitter/X uživatelé"):
        parse_twitter_users(b"[]")
    with pytest.raises(TypeError, match="Nenalezeny Facebook Messenger zprávy"):
        parse_facebook_messages(b"[]")
    with pytest.raises(TypeError, match="Nenalezeni Facebook přátelé"):
        parse_facebook_friends(b"{}")
    with pytest.raises(TypeError, match="Nenalezeny Facebook timeline příspěvky"):
        parse_facebook_timeline(b"{}")


def test_single_minimal_record_each():
    # quality: boundary
    """Jeden minimální záznam per parser → přesně 1 záznam."""
    posts = json.dumps([{"author": "min"}]).encode()
    assert len(parse_twitter_posts(posts)) == 1

    msgs = json.dumps([{"sender": "a", "text": "t"}]).encode()
    assert len(parse_twitter_messages(msgs)) == 1

    users = json.dumps({"screen_name": "me", "name": "Me"}).encode()
    recs = parse_twitter_users(users)
    assert len(recs) == 1 and recs[0].relationship == "account"

    fb = json.dumps([{"sender": "a", "body": "x"}]).encode()
    assert len(parse_facebook_messages(fb)) == 1


# ── size: stresové objemy ─────────────────────────────────────────────────────


def test_stress_many_records():
    # quality: size
    """Stres: stovky záznamů bez výjimky a bez ztráty počtu (pod limity)."""
    posts = json.dumps([{"author": f"u{i}", "text": f"post {i}"} for i in range(250)]).encode()
    assert len(parse_twitter_posts(posts)) == 250

    conv = [{"id": f"c{i % 10}", "participants": ["a", "b"],
             "messages": [{"sender": "a", "body": f"zpráva {i}"}]} for i in range(15)]
    msgs = json.dumps(conv).encode()
    assert len(parse_twitter_messages(msgs)) == 15

    users = json.dumps({"screen_name": "me",
                        "followers": [{"username": f"f{i}"} for i in range(100)],
                        "following": [{"username": f"fo{i}"} for i in range(100)]}).encode()
    assert len(parse_twitter_users(users)) == 201

    fb = json.dumps({"timeline": [{"author": "a", "text": f"p{i}"} for i in range(120)],
                     "friends": [{"name": f"Přítel {i}"} for i in range(100)]}).encode()
    assert len(parse_facebook_timeline(fb)) == 120
    assert len(parse_facebook_friends(fb)) == 100
