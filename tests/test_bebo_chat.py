"""ETAPA B vlna 3 — testy Bebo Live Chat parseru (text + JSON).

Offline syntetické fixture: textový chat log i JSON pole záznamů. Ověřuje
parsing řádků s časem, plain řádků, JSON formátu, výjimky pro špatný typ a
generování messenger_message artifactů.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.bebo_chat import (
    PARSER_VERSION,
    build_bebo_artifacts,
    extract_bebo_artifacts,
    is_bebo_chat_file,
    parse_bebo_chat,
)

# ── textový formát ──────────────────────────────────────────────────

def test_parse_typed_line() -> None:
    # quality: positive
    data = b"[2019-03-04 12:00:01] user_a said: ahoj\n"
    msgs = parse_bebo_chat(data)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.user == "user_a"
    assert m.message == "ahoj"
    assert isinstance(m.timestamp, datetime)
    assert m.timestamp.astimezone(timezone.utc).year == 2019


def test_parse_plain_line() -> None:
    # quality: positive
    data = "user_b: jak se máš?\n".encode()
    msgs = parse_bebo_chat(data)
    assert len(msgs) == 1
    assert msgs[0].user == "user_b"
    assert msgs[0].message == "jak se máš?"
    assert msgs[0].timestamp is None


def test_parse_mixed_lines() -> None:
    # quality: positive
    data = (
        "[2019-03-04 12:00:01] user_a said: ahoj\n"
        "user_b: jak se máš?\n"
        "\n"
        "   \n"
    ).encode()
    msgs = parse_bebo_chat(data)
    assert len(msgs) == 2


# ── JSON formát ─────────────────────────────────────────────────────

def test_parse_json_list() -> None:
    # quality: positive
    payload = [
        {"user": "u1", "message": "první", "timestamp": 1551676801},
        {"from": "u2", "text": "druhá"},
    ]
    msgs = parse_bebo_chat(json.dumps(payload).encode())
    assert len(msgs) == 2
    assert msgs[0].user == "u1"
    assert msgs[0].message == "první"
    assert isinstance(msgs[0].timestamp, datetime)
    # epoch s → UTC
    assert msgs[0].timestamp.astimezone(timezone.utc).year == 2019
    assert msgs[1].user == "u2"
    assert msgs[1].message == "druhá"


def test_parse_json_invalid_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_bebo_chat(b"[{bad")


def test_parse_json_non_list_raises() -> None:
    # quality: positive
    with pytest.raises(TypeError):
        parse_bebo_chat(json.dumps({"a": 1}).encode())


# ── detekce ─────────────────────────────────────────────────────────

def test_detect_by_name_and_content() -> None:
    # quality: positive
    head = b"[2019-03-04 12:00:01] user_a said: ahoj\n"
    assert is_bebo_chat_file("bebo_livechat.txt", head) is True


def test_detect_by_name_only() -> None:
    # quality: positive
    # bez head → jen kontrola názvu
    assert is_bebo_chat_file("bebo_export.log") is True


def test_reject_wrong_name() -> None:
    # quality: negative
    head = b"[2019-03-04 12:00:01] user_a said: ahoj\n"
    assert is_bebo_chat_file("notes.txt", head) is False


def test_reject_no_content_marker() -> None:
    # quality: negative
    # správný název, ale obsah bez markerů (bebo/said:/user/message)
    assert is_bebo_chat_file("bebo.txt", b"hello world") is False


# ── artifacty + entrypoint ─────────────────────────────────────────

def test_build_artifacts() -> None:
    # quality: positive
    data = b"[2019-03-04 12:00:01] user_a said: ahoj\n"
    msgs = parse_bebo_chat(data)
    arts = build_bebo_artifacts(msgs)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "messenger_message"
    assert a.details["user"] == "user_a"
    assert a.parser_version == PARSER_VERSION


def test_entrypoint_text(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "bebo_chat.txt"
    p.write_text("[2019-03-04 12:00:01] user_a said: ahoj\nuser_b: jak se máš?\n")
    arts = extract_bebo_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "messenger_message" for a in arts)


def test_entrypoint_invalid_json_returns_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "bebo.json"
    p.write_text("[{neplatné")
    assert extract_bebo_artifacts(p) == []


def test_entrypoint_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "bebo.txt"
    p.write_bytes(b"")
    assert extract_bebo_artifacts(p) == []
