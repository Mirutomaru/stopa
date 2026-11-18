"""ETAPA B vlna 2 — Google Search History parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.google_search_history import (
    build_google_search_artifacts,
    extract_google_search_artifacts,
    is_google_search_history_file,
    parse_google_search_history,
)


def _sample() -> list[dict]:
    return [
        {
            "key": "webSearch",
            "time": {"timestamp": "1625097600", "displayTime": "Jul 1, 2021, 8:00 AM"},
            "title": "python asyncio tutorial",
            "url": "https://www.google.com/search?q=python+asyncio+tutorial",
        },
        {
            "key": "webSearch",
            "time": {"timestamp": "1625097660"},
            "title": "forenzní workbench",
            "url": "",
        },
    ]


def test_parse_basic(tmp_path: Path) -> None:
    # quality: positive
    data = json.dumps(_sample()).encode()
    entries = parse_google_search_history(data)
    assert len(entries) == 2
    assert entries[0].query == "python asyncio tutorial"
    assert entries[0].timestamp == 1625097600
    assert entries[0].display_time == "Jul 1, 2021, 8:00 AM"
    assert entries[0].url.startswith("https://www.google.com/")
    assert entries[1].query == "forenzní workbench"
    assert entries[1].timestamp == 1625097660


def test_parse_skips_non_search_items() -> None:
    # quality: positive
    payload = [
        {"key": "youtubeWatch", "time": {"timestamp": "1"}, "title": "", "url": ""},
        {"key": "webSearch", "title": "dotaz", "time": {}},
    ]
    entries = parse_google_search_history(json.dumps(payload).encode())
    assert len(entries) == 1
    assert entries[0].query == "dotaz"


def test_parse_invalid_json_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_google_search_history(b"{nejson")


def test_parse_non_list_raises() -> None:
    # quality: positive
    with pytest.raises(TypeError):
        parse_google_search_history(json.dumps({"a": 1}).encode())


def test_timestamp_variants() -> None:
    # quality: positive
    payload = [
        {"key": "webSearch", "title": "q1", "time": {"timestamp": 1625097600}},
        {"key": "webSearch", "title": "q2", "time": {"timestamp": "1625097601"}},
        {"key": "webSearch", "title": "q3", "time": {"timestamp": "xx"}},
    ]
    entries = parse_google_search_history(json.dumps(payload).encode())
    assert entries[0].timestamp == 1625097600
    assert entries[1].timestamp == 1625097601
    assert entries[2].timestamp is None


def test_artifacts() -> None:
    # quality: positive
    data = json.dumps(_sample()).encode()
    arts = build_google_search_artifacts(parse_google_search_history(data))
    assert len(arts) == 2
    a = arts[0]
    assert a.artifact_type == "google_search"
    assert a.timestamp is not None
    # epoch 1625097600 = 2021-07-01T00:00Z (displayTime je lokální)
    assert a.timestamp == datetime(2021, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert "python asyncio tutorial" in a.title
    assert a.details["engine"] == "google_takeout"
    assert a.confidence == 0.9


def test_artifact_without_query_lower_confidence() -> None:
    # quality: positive
    payload = [{"key": "webSearch", "title": "", "url": "https://x.cz/stranka"}]
    arts = build_google_search_artifacts(parse_google_search_history(json.dumps(payload).encode()))
    assert len(arts) == 1
    assert arts[0].confidence == 0.75
    assert arts[0].timestamp is None


def test_detection() -> None:
    # quality: positive
    head = json.dumps(_sample())[:2048].encode()
    assert is_google_search_history_file("My Activity.json", head)
    assert is_google_search_history_file("search_history.json")
    assert not is_google_search_history_file("other.json", head)
    # content check — hlavička bez očekávaných markerů
    assert not is_google_search_history_file("My Activity.json", b"random text here")


def test_extract_end_to_end(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "search_history.json"
    p.write_text(json.dumps(_sample()))
    arts = extract_google_search_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_search" for a in arts)


def test_extract_missing_file(tmp_path: Path) -> None:
    # quality: negative
    assert extract_google_search_artifacts(tmp_path / "chybi.json") == []


def test_extract_invalid_content(tmp_path: Path) -> None:
    # quality: negative
    p = tmp_path / "search_history.json"
    p.write_text("tohle není json")
    assert extract_google_search_artifacts(p) == []
