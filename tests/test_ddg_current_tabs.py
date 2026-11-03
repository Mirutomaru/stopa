"""ETAPA B vlna 2 — DuckDuckGo Current Tabs parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.ddg_current_tabs import (
    build_tab_artifacts,
    extract_current_tabs_artifacts,
    is_current_tabs_file,
    parse_current_tabs_json,
)


def _json_sample() -> list[dict]:
    return [
        {"url": "https://example.com/stranka", "title": "Příklad"},
        {"url": "https://cnews.cz/clanek", "title": ""},
        {"title": "bez url"},
    ]


def test_parse_json_basic() -> None:
    tabs = parse_current_tabs_json(json.dumps(_json_sample()).encode())
    assert len(tabs) == 2
    assert tabs[0].url == "https://example.com/stranka"
    assert tabs[0].title == "Příklad"
    assert tabs[1].url == "https://cnews.cz/clanek"


def test_parse_json_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_current_tabs_json(b"{")
    with pytest.raises(TypeError):
        parse_current_tabs_json(json.dumps("scalar").encode())


TEXT_SAMPLE = """https://example.com/stranka
https://cnews.cz/clanek
https://example.com/stranka
"""


def test_parse_text_basic() -> None:
    from stopa.artifacts.ddg_current_tabs import parse_current_tabs_text

    tabs = parse_current_tabs_text(TEXT_SAMPLE.encode())
    # dedupe URL
    assert len(tabs) == 2
    assert all(t.title == "" for t in tabs)


def test_artifacts() -> None:
    tabs = parse_current_tabs_json(json.dumps(_json_sample()).encode())
    arts = build_tab_artifacts(tabs)
    assert len(arts) == 2
    a = arts[0]
    assert a.artifact_type == "browser_tab"
    assert a.timestamp is None
    assert "Příklad" in a.title
    assert a.details["url"] == "https://example.com/stranka"
    assert a.confidence == 0.8


def test_detection() -> None:
    head_json = json.dumps(_json_sample())[:2048].encode()
    assert is_current_tabs_file("current_tabs.json", head_json)
    # textový export — jméno obsahuje ddg, content check přes URL marker
    assert is_current_tabs_file("ddg_tabs.txt", TEXT_SAMPLE.encode())
    assert not is_current_tabs_file("other.json", head_json)
    # content check — JSON bez markerů
    assert not is_current_tabs_file("current_tabs.json", b'{"foo": 1}')


def test_extract_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "current_tabs.json"
    p.write_text(json.dumps(_json_sample()))
    arts = extract_current_tabs_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "browser_tab" for a in arts)


def test_extract_missing_file(tmp_path: Path) -> None:
    assert extract_current_tabs_artifacts(tmp_path / "chybi.json") == []
