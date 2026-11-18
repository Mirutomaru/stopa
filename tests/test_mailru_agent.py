"""ETAPA B vlna 3 — testy Mail.Ru Agent parseru (chat log + kontakty).

Offline syntetické fixture: textové logy s ``|`` oddělovači. Ověřuje parsing
zpráv (typ/délka z hranatých závorek), kontaktů, detekci podle názvu a
generování artifactů.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from stopa.artifacts.mailru_agent import (
    PARSER_VERSION,
    build_mailru_artifacts,
    extract_mailru_artifacts,
    is_mailru_file,
    parse_mailru_chat_log,
    parse_mailru_contacts,
)

# ── chat log parser ─────────────────────────────────────────────────

def test_parse_text_message() -> None:
    # quality: positive
    data = b"2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n"
    msgs = parse_mailru_chat_log(data)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.remote_id == "user123"
    assert m.display_name == "John Doe"
    assert m.message == "Ahoj!"
    assert m.direction == "IN"
    assert m.msg_type == "Text Message"


def test_parse_voice_call_with_duration() -> None:
    # quality: positive
    data = b"2015-03-14 10:24:01 | OUT | user123 | John Doe : [Voice Call] 120\n"
    msgs = parse_mailru_chat_log(data)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.msg_type == "Voice Call"
    assert m.duration_s == 120


def test_parse_video_call_no_duration() -> None:
    # quality: positive
    data = b"2015-03-14 10:25:00 | IN | u9 | Bob : [Video Call]\n"
    msgs = parse_mailru_chat_log(data)
    assert len(msgs) == 1
    assert msgs[0].msg_type == "Video Call"
    assert msgs[0].duration_s is None


def test_parse_file_transfer() -> None:
    # quality: positive
    data = b"2015-03-14 10:26:00 | OUT | u9 | Bob : [File Transfer] report.pdf\n"
    msgs = parse_mailru_chat_log(data)
    assert len(msgs) == 1
    assert msgs[0].msg_type == "File Transfer"


def test_parse_multiple_lines_and_skip_garbage() -> None:
    # quality: corrupted
    data = (
        "# hlavička logu\n"
        "\n"
        "2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n"
        "nesmysl bez pipe\n"
        "bad-ts | IN | u1 | X : y\n"
    ).encode()
    msgs = parse_mailru_chat_log(data)
    assert len(msgs) == 1
    assert msgs[0].message == "Ahoj!"


def test_timestamp_utc() -> None:
    # quality: positive
    data = b"2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n"
    msgs = parse_mailru_chat_log(data)
    ts = msgs[0].created_dt
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None
    assert ts.astimezone(timezone.utc).year == 2015


# ── kontakty parser ─────────────────────────────────────────────────

def test_parse_contacts() -> None:
    # quality: positive
    data = b"John|Doe|john@example.com|2015-03-14 10:00:00|Czech Republic\n"
    contacts = parse_mailru_contacts(data)
    assert len(contacts) == 1
    c = contacts[0]
    assert c.first_name == "John"
    assert c.last_name == "Doe"
    assert c.email == "john@example.com"
    assert c.locale == "Czech Republic"
    assert isinstance(c.last_seen, datetime)


def test_parse_contacts_minimal() -> None:
    # quality: boundary
    data = b"Jane|Smith\n"
    contacts = parse_mailru_contacts(data)
    # jen 2 pole → < 3 → skip
    assert len(contacts) == 0


# ── detekce ─────────────────────────────────────────────────────────

def test_detect_by_name_chatlog() -> None:
    # quality: positive
    head = b"2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n"
    assert is_mailru_file("mailru_agent_log.txt", head) is True


def test_detect_by_name_contacts() -> None:
    # quality: positive
    head = b"John|Doe|john@mail.ru\n"
    assert is_mailru_file("agent_contacts.txt", head) is True


def test_reject_wrong_name() -> None:
    # quality: negative
    head = b"2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n"
    assert is_mailru_file("notes.txt", head) is False


def test_reject_no_content_marker() -> None:
    # quality: negative
    # správný název, ale obsah bez | a @mail.ru
    assert is_mailru_file("agent_log.txt", b"hello world") is False


# ── artifacty + entrypoint ─────────────────────────────────────────

def test_build_message_artifacts() -> None:
    # quality: positive
    data = b"2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n"
    msgs = parse_mailru_chat_log(data)
    arts = build_mailru_artifacts(msgs, [])
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "messenger_message"
    assert a.details["remote_id"] == "user123"
    assert a.parser_version == PARSER_VERSION


def test_build_contact_artifacts() -> None:
    # quality: positive
    data = b"John|Doe|john@example.com|2015-03-14 10:00:00|Czech Republic\n"
    contacts = parse_mailru_contacts(data)
    arts = build_mailru_artifacts([], contacts)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "contact"
    assert a.details["email"] == "john@example.com"


def test_entrypoint_chat_log(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "mailru_agent.txt"
    p.write_text("2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!\n")
    arts = extract_mailru_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "messenger_message"


def test_entrypoint_contacts(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "mailru_contacts.txt"
    p.write_text("John|Doe|john@example.com|2015-03-14 10:00:00|Czech Republic\n")
    arts = extract_mailru_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "contact"


def test_entrypoint_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "mailru_agent.txt"
    p.write_bytes(b"")
    assert extract_mailru_artifacts(p) == []
