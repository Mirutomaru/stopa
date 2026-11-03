"""ETAPA B vlna 2 — Google Account Info parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.google_account_info import (
    build_account_artifacts,
    extract_account_artifacts,
    is_account_info_file,
    parse_account_info,
)


def test_parse_basic() -> None:
    payload = {
        "name": "Jan Novák",
        "emailAddress": "jan@example.com",
        "phoneNumber": "+420123456789",
        "countryCode": "CZ",
    }
    info = parse_account_info(json.dumps(payload).encode())
    assert info is not None
    assert info.name == "Jan Novák"
    assert info.email == "jan@example.com"
    assert info.phone == "+420123456789"
    # neznámá pole do extra
    assert info.extra.get("countrycode") == "CZ"


def test_parse_key_normalization() -> None:
    payload = {"Email Address": "a@b.cz", "Phone Number": "123"}
    info = parse_account_info(json.dumps(payload).encode())
    assert info is not None
    assert info.email == "a@b.cz"
    assert info.phone == "123"


def test_parse_empty_returns_none() -> None:
    # bez identifikátorů (name/email/phone) → None
    assert parse_account_info(json.dumps({"foo": 1}).encode()) is None


def test_parse_invalid_raises() -> None:
    with pytest.raises(TypeError):
        parse_account_info(b"[1,2]")
    with pytest.raises(ValueError):
        parse_account_info(b"xx")


def test_artifacts() -> None:
    payload = {"name": "Jan Novák", "emailAddress": "jan@example.com"}
    info = parse_account_info(json.dumps(payload).encode())
    assert info is not None
    arts = build_account_artifacts(info)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_account"
    assert a.timestamp is None
    assert "Jan Novák" in a.title
    assert a.details["email"] == "jan@example.com"
    assert a.confidence == 0.9


def test_detection() -> None:
    head = json.dumps({"name": "X", "emailAddress": "a@b.cz"})[:2048].encode()
    assert is_account_info_file("account_info.json", head)
    assert not is_account_info_file("other.json", head)
    # content check — JSON bez markerů
    assert not is_account_info_file("account_info.json", b'{"foo": 1}')


def test_extract_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "account_info.json"
    p.write_text(json.dumps({"name": "Petr", "emailAddress": "p@x.cz"}))
    arts = extract_account_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "google_account"


def test_extract_empty_content(tmp_path: Path) -> None:
    p = tmp_path / "account_info.json"
    p.write_text(json.dumps({"foo": 1}))
    assert extract_account_artifacts(p) == []


def test_extract_missing_file(tmp_path: Path) -> None:
    assert extract_account_artifacts(tmp_path / "chybi.json") == []
