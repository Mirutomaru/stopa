"""ETAPA B vlna 3 — testy Chatroulette parseru (video chat, text + JSON).

Offline syntetické fixture: textový chat log i JSON pole záznamů. Ověřuje
parsing řádků s časem, plain řádků, JSON formátu, výjimky pro špatný typ a
generování messenger_message artifactů.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.chatroulette import (
    PARSER_VERSION,
    build_chatroulette_artifacts,
    extract_chatroulette_artifacts,
    is_chatroulette_file,
    parse_chatroulette,
)

# ── textový formát ──────────────────────────────────────────────────

def test_parse_typed_line() -> None:
    # quality: positive
    data = b"[2018-05-06 09:30:00] partner_abc said: hi there\n"
    msgs = parse_chatroulette(data)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.partner == "partner_abc"
    assert m.message == "hi there"
    assert isinstance(m.timestamp, datetime)
    assert m.timestamp.astimezone(timezone.utc).year == 2018


def test_parse_plain_line() -> None:
    # quality: positive
    data = b"me: hello!\n"
    msgs = parse_chatroulette(data)
    assert len(msgs) == 1
    assert msgs[0].partner == "me"
    assert msgs[0].message == "hello!"
    assert msgs[0].timestamp is None


def test_parse_mixed_lines() -> None:
    # quality: positive
    data = (
        b"[2018-05-06 09:30:00] partner_abc said: hi there\n"
        b"me: hello!\n"
        b"\n"
    )
    msgs = parse_chatroulette(data)
    assert len(msgs) == 2


# ── JSON formát ─────────────────────────────────────────────────────

def test_parse_json_list() -> None:
    # quality: positive
    payload = [
        {"partner": "p1", "message": "první", "timestamp": 1525563000},
        {"user": "p2", "text": "druhá"},
    ]
    msgs = parse_chatroulette(json.dumps(payload).encode())
    assert len(msgs) == 2
    assert msgs[0].partner == "p1"
    assert msgs[0].message == "první"
    assert isinstance(msgs[0].timestamp, datetime)
    assert msgs[0].timestamp.astimezone(timezone.utc).year == 2018
    assert msgs[1].partner == "p2"
    assert msgs[1].message == "druhá"


def test_parse_json_invalid_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_chatroulette(b"[{bad")


def test_parse_json_non_list_raises() -> None:
    # quality: positive
    with pytest.raises(TypeError):
        parse_chatroulette(json.dumps({"a": 1}).encode())


# ── detekce ─────────────────────────────────────────────────────────

def test_detect_by_name_and_content() -> None:
    # quality: positive
    head = b"[2018-05-06 09:30:00] partner_abc said: hi there\n"
    assert is_chatroulette_file("chatroulette_log.txt", head) is True


def test_detect_by_name_only() -> None:
    # quality: positive
    assert is_chatroulette_file("cr_chat_export.log") is True


def test_reject_wrong_name() -> None:
    # quality: negative
    head = b"[2018-05-06 09:30:00] partner_abc said: hi there\n"
    assert is_chatroulette_file("notes.txt", head) is False


def test_reject_no_content_marker() -> None:
    # quality: negative
    # správný název, ale obsah bez markerů (chatroulette/said:/partner/message)
    assert is_chatroulette_file("cr_chat.txt", b"hello world") is False


# ── artifacty + entrypoint ─────────────────────────────────────────

def test_build_artifacts() -> None:
    # quality: positive
    data = b"[2018-05-06 09:30:00] partner_abc said: hi there\n"
    msgs = parse_chatroulette(data)
    arts = build_chatroulette_artifacts(msgs)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "messenger_message"
    assert a.details["partner"] == "partner_abc"
    assert a.parser_version == PARSER_VERSION


def test_entrypoint_text(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "chatroulette.txt"
    p.write_text("[2018-05-06 09:30:00] partner_abc said: hi there\nme: hello!\n")
    arts = extract_chatroulette_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "messenger_message" for a in arts)


def test_entrypoint_invalid_json_returns_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "cr.json"
    p.write_text("[{bad")
    assert extract_chatroulette_artifacts(p) == []


def test_entrypoint_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "chatroulette.txt"
    p.write_bytes(b"")
    assert extract_chatroulette_artifacts(p) == []
