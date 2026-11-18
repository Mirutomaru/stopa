"""ETAPA B vlna 2 — MSN/Messenger chat log parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stopa.artifacts.msn_messenger import (
    build_msn_artifacts,
    extract_msn_artifacts,
    is_msn_chat_file,
    parse_msn_chat_log,
)

CHATLOG = """Microsoft® Windows Live™ Messenger 8.5.0.134
Chat started on 2/14/2010 at 10:23 AM
----------------------------------------
jan@example.com (Jan Novák): Ahoj!
petra@example.com (Petra): Jsi to ty?
jan@example.com: Ano, jak se máš?
"""


def test_parse_basic() -> None:
    # quality: positive
    msgs = parse_msn_chat_log(CHATLOG.encode())
    assert len(msgs) == 3
    m = msgs[0]
    assert m.sender == "jan@example.com"
    assert m.display_name == "Jan Novák"
    assert m.text == "Ahoj!"
    # zpráva bez display name
    assert msgs[2].sender == "jan@example.com"
    assert msgs[2].display_name == ""
    assert msgs[2].text == "Ano, jak se máš?"


def test_parse_text_with_colon() -> None:
    # quality: positive
    data = (
        "Windows Live Messenger 8.1\n"
        "Chat started on 1/1/2010 at 9:00 AM\n"
        "a@b.cz: Čas je 10:30, pojdeme?\n"
    )
    msgs = parse_msn_chat_log(data.encode())
    assert len(msgs) == 1
    assert msgs[0].text == "Čas je 10:30, pojdeme?"


def test_parse_skips_header_lines() -> None:
    # quality: positive
    data = (
        "Microsoft Messenger 8.5\n"
        "Chat started on 2/14/2010 at 10:23 AM\n"
        "----------------------------------------\n"
        "x@y.cz: text\n"
    )
    msgs = parse_msn_chat_log(data.encode())
    assert len(msgs) == 1
    assert msgs[0].sender == "x@y.cz"


def test_parse_noise_filter() -> None:
    # quality: positive
    # sender >40 znaků bez tečky ani @ = šum
    data = (
        "Messenger 8.5\n"
        "Chat started on 1/1/2010 at 9:00 AM\n"
        "tohle je velmi dlouha radek ktery nema tecku ani zavinac v sobe: text\n"
        "ok@cz.cz: dobrý řádek\n"
    )
    msgs = parse_msn_chat_log(data.encode())
    assert len(msgs) == 1
    assert msgs[0].sender == "ok@cz.cz"


def test_parse_invalid_header_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_msn_chat_log(b"random text bez nadpisu\n")


def test_artifacts() -> None:
    # quality: positive
    msgs = parse_msn_chat_log(CHATLOG.encode())
    arts = build_msn_artifacts(msgs)
    assert len(arts) == 3
    a = arts[0]
    assert a.artifact_type == "messenger_message"
    assert a.timestamp is None
    # title používá display name, pokud existuje
    assert "Jan Novák" in a.title
    assert a.details["sender"] == "jan@example.com"
    assert a.details["engine"] == "msn_messenger"
    assert a.confidence == 0.8


def test_detection() -> None:
    # quality: positive
    head = CHATLOG.encode()[:4096]
    assert is_msn_chat_file("chatlog.txt", head)
    assert is_msn_chat_file("MSN_export.txt")
    assert not is_msn_chat_file("other.txt", head)
    # content check — hlavička bez markerů
    assert not is_msn_chat_file("msn.txt", b"random text here")


def test_extract_end_to_end(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "chatlog.txt"
    p.write_text(CHATLOG, encoding="utf-8")
    arts = extract_msn_artifacts(p)
    assert len(arts) == 3
    assert all(a.artifact_type == "messenger_message" for a in arts)


def test_extract_invalid_content(tmp_path: Path) -> None:
    # quality: negative
    p = tmp_path / "msn.txt"
    p.write_text("tohle není chat log")
    assert extract_msn_artifacts(p) == []


def test_extract_missing_file(tmp_path: Path) -> None:
    # quality: negative
    assert extract_msn_artifacts(tmp_path / "chybi.txt") == []
