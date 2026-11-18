"""ETAPA B vlna 2 — Google Login/Sign-in History parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.google_login_history import (
    build_login_artifacts,
    extract_login_artifacts,
    is_login_history_file,
    parse_login_history_csv,
    parse_login_history_json,
)


def _json_sample() -> list[dict]:
    return [
        {
            "time": {"timestamp": "1625097600", "displayTime": "Jul 1, 2021, 8:00 AM"},
            "deviceName": "Chrome on Windows",
            "ipAddress": "83.10.1.2",
            "location": "Prague, Czechia",
        },
        {"time": {}, "deviceName": "Pixel 5", "ipAddress": "", "location": ""},
    ]


def test_parse_json_basic() -> None:
    # quality: positive
    entries = parse_login_history_json(json.dumps(_json_sample()).encode())
    assert len(entries) == 2
    e = entries[0]
    assert e.timestamp_s == 1625097600
    assert e.display_time == "Jul 1, 2021, 8:00 AM"
    assert e.device_name == "Chrome on Windows"
    assert e.ip_address == "83.10.1.2"
    assert e.location == "Prague, Czechia"


def test_parse_json_snake_case_keys() -> None:
    # quality: positive
    payload = [{"time": {"timestamp": 5}, "device_name": "X", "ip_address": "1.2.3.4"}]
    entries = parse_login_history_json(json.dumps(payload).encode())
    assert entries[0].device_name == "X"
    assert entries[0].ip_address == "1.2.3.4"


def test_parse_json_invalid_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_login_history_json(b"[")
    with pytest.raises(TypeError):
        parse_login_history_json(json.dumps("scalar").encode())


CSV_SAMPLE = (
    "Time,Device Name,IP Address,Location\n"
    "1625097600,Chrome on Windows,83.10.1.2,Prague\n"
    "1625097600000,Pixel 5,10.0.0.1,\n"
)


def test_parse_csv_basic() -> None:
    # quality: positive
    entries = parse_login_history_csv(CSV_SAMPLE.encode())
    assert len(entries) == 2
    assert entries[0].timestamp_s == 1625097600
    assert entries[0].device_name == "Chrome on Windows"
    # epoch ms → s
    assert entries[1].timestamp_s == 1625097600


def test_parse_csv_iso_time() -> None:
    # quality: positive
    csv_data = "Time,Device Name\n2021-07-01T08:00:00Z,Phone\n"
    entries = parse_login_history_csv(csv_data.encode())
    assert len(entries) == 1
    assert entries[0].timestamp_s is None
    assert entries[0].display_time == "2021-07-01T08:00:00Z"


def test_parse_csv_missing_columns_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_login_history_csv(b"a,b\n1,2\n")


def test_artifacts() -> None:
    # quality: positive
    entries = parse_login_history_json(json.dumps(_json_sample()).encode())
    arts = build_login_artifacts(entries)
    assert len(arts) == 2
    a = arts[0]
    assert a.artifact_type == "google_login"
    # epoch 1625097600 = 2021-07-01T00:00Z
    assert a.timestamp == datetime(2021, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert "Chrome on Windows" in a.title
    assert a.details["ip_address"] == "83.10.1.2"
    assert a.confidence == 0.85


def test_artifact_without_details_lower_confidence() -> None:
    # quality: positive
    entries = parse_login_history_json(json.dumps([{"time": {}}]).encode())
    arts = build_login_artifacts(entries)
    assert len(arts) == 1
    assert arts[0].confidence == 0.6


def test_detection() -> None:
    # quality: positive
    head_json = json.dumps(_json_sample())[:2048].encode()
    assert is_login_history_file("sign-ins.json", head_json)
    assert is_login_history_file("login_history.csv", CSV_SAMPLE.encode()[:2048])
    assert not is_login_history_file("other.json", head_json)
    assert not is_login_history_file("sign-ins.json", b"random text")


def test_extract_end_to_end(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "sign-ins.json"
    p.write_text(json.dumps(_json_sample()))
    arts = extract_login_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_login" for a in arts)


def test_extract_csv_end_to_end(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "login_history.csv"
    p.write_text(CSV_SAMPLE)
    arts = extract_login_artifacts(p)
    assert len(arts) == 2


def test_extract_missing_file(tmp_path: Path) -> None:
    # quality: negative
    assert extract_login_artifacts(tmp_path / "chybi.json") == []
