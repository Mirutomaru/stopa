"""ETAPA B vlna 1 — testy email mbox/EML parseru.

ČISTÉ funkce (parse_email_message / split_mbox / build_email_artifacts) +
IO entrypoint (extract_email_artifacts přes tmp_path). Žádný regipy, žádné sítě.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from stopa.artifacts.email_mbox import (
    PARSER_VERSION,
    build_email_artifacts,
    extract_email_artifacts,
    is_email_file,
    parse_email_message,
    split_mbox,
)

# ── syntetické fixtures ────────────────────────────────────────────────

EML_SINGLE = (
    b"From: Alice <alice@example.com>\r\n"
    b"To: Bob <bob@example.com>, Carol <carol@example.com>\r\n"
    b"Subject: Hello World\r\n"
    b"Date: Mon, 02 Nov 2026 10:30:00 +0100\r\n"
    b"Message-ID: <abc123@example.com>\r\n"
    b"\r\n"
    b"Body line one.\r\n"
    b"Body line two.\r\n"
)

MBOX_TWO = (
    b"From alice@example.com Mon Nov 02 10:30:00 2026\r\n"
    b"From: Alice <alice@example.com>\r\n"
    b"To: bob@example.com\r\n"
    b"Subject: First message\r\n"
    b"Date: Mon, 02 Nov 2026 10:30:00 +0100\r\n"
    b"\r\n"
    b"First body.\r\n"
    b"\r\n"
    b"From bob@example.com Tue Nov 03 09:00:00 2026\r\n"
    b"From: Bob <bob@example.com>\r\n"
    b"To: alice@example.com\r\n"
    b"Subject: Re: First message\r\n"
    b"Date: Tue, 03 Nov 2026 09:00:00 +0100\r\n"
    b"\r\n"
    b"Second body.\r\n"
)


# ── is_email_file (name-based detekce) ────────────────────────────────

@pytest.mark.parametrize(
    "name,expected",
    [
        ("message.eml", True),
        ("mailbox.mbox", True),
        ("inbox.MBOX", True),
        ("mail.emlx", False),  # .emlx není v seznamu
        ("notes.txt", False),
        ("photo.jpg", False),
    ],
)
def test_is_email_file(name: str, expected: bool):
    assert is_email_file(name) is expected


# ── parse_email_message (čistá funkce) ────────────────────────────────

def test_parse_single_eml():
    msg = parse_email_message(EML_SINGLE)
    assert msg is not None
    assert "alice@example.com" in msg.sender.lower()
    assert any("bob@example.com" in r for r in msg.recipients)
    assert any("carol@example.com" in r for r in msg.recipients)
    assert msg.subject == "Hello World"
    assert msg.message_id == "<abc123@example.com>"
    assert isinstance(msg.date, datetime)
    assert msg.date.year == 2026 and msg.date.month == 11 and msg.date.day == 2


def test_parse_eml_no_date():
    raw = b"From: x@y.z\r\nSubject: NoDate\r\n\r\nbody"
    msg = parse_email_message(raw)
    assert msg is not None
    assert msg.subject == "NoDate"
    assert msg.date is None


def test_parse_eml_empty():
    assert parse_email_message(b"") is None


# ── split_mbox (čistá funkce) ─────────────────────────────────────────

def test_split_mbox_two_messages():
    segments = split_mbox(MBOX_TWO)
    # 2 zprávy + případně prázdný segment — odfiltrujeme prázdné
    non_empty = [s for s in segments if b"Subject:" in s]
    assert len(non_empty) == 2


def test_split_mbox_single_is_one():
    # jednotlivý EML bez From-oddělovače → jeden segment
    segments = split_mbox(EML_SINGLE)
    non_empty = [s for s in segments if b"Subject:" in s]
    assert len(non_empty) == 1


# ── build_email_artifacts (čistá funkce) ──────────────────────────────

def test_build_artifacts_from_message():
    msg = parse_email_message(EML_SINGLE)
    assert msg is not None
    arts = build_email_artifacts([msg])
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "email_message"
    assert a.parser_version == PARSER_VERSION
    assert "alice@example.com" in (a.details.get("from") or "").lower()
    assert a.timestamp is not None


def test_build_artifacts_empty():
    assert build_email_artifacts([]) == []


# ── extract_email_artifacts (IO přes tmp_path) ────────────────────────

def test_extract_eml_file(tmp_path: Path):
    p = tmp_path / "msg.eml"
    p.write_bytes(EML_SINGLE)
    arts = extract_email_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "email_message"


def test_extract_mbox_file(tmp_path: Path):
    p = tmp_path / "mailbox.mbox"
    p.write_bytes(MBOX_TWO)
    arts = extract_email_artifacts(p)
    # 2 zprávy → 2 artifacty
    assert len(arts) == 2


def test_extract_missing_file(tmp_path: Path):
    assert extract_email_artifacts(tmp_path / "nope.eml") == []


def test_extract_empty_file(tmp_path: Path):
    p = tmp_path / "empty.mbox"
    p.write_bytes(b"")
    assert extract_email_artifacts(p) == []
