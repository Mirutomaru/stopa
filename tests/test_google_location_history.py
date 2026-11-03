"""ETAPA B vlna 2 — Google Location History parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.google_location_history import (
    build_location_artifacts,
    extract_location_artifacts,
    is_location_history_file,
    parse_location_history_csv,
    parse_location_history_json,
)


def _json_sample() -> list[dict]:
    return [
        {
            "latitudeE7": 500934826,
            "longitudeE7": 144270841,
            "timestampMsSinceEpoch": 1625097600000,
            "accuracyHorizontalMeters": 10.0,
            "altitudeMeters": 200.5,
            "deviceID": "dev-1",
        },
        {"latitudeE7": 488635900, "longitudeE7": 233218600},
    ]


def test_parse_json_basic() -> None:
    points = parse_location_history_json(json.dumps(_json_sample()).encode())
    assert len(points) == 2
    p = points[0]
    # E7 → stupně: 500934826 / 1e7 = 50.0934826
    assert abs(p.latitude - 50.0934826) < 1e-9
    assert abs(p.longitude - 14.4270841) < 1e-9
    assert p.timestamp_ms == 1625097600000
    assert p.accuracy_m == 10.0
    assert p.altitude_m == 200.5
    assert p.device_id == "dev-1"


def test_parse_json_skips_without_coords() -> None:
    payload = [{"foo": 1}, {"latitudeE7": 500000000}]
    points = parse_location_history_json(json.dumps(payload).encode())
    assert len(points) == 1
    assert points[0].longitude is None


def test_parse_json_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_location_history_json(b"xx")
    with pytest.raises(TypeError):
        parse_location_history_json(json.dumps({"a": 1}).encode())


CSV_SAMPLE = (
    "Timestamp,Latitude,Longitude,Accuracy,Altitude,DeviceID\n"
    "2021-07-01T08:00:00Z,50.0934826,14.4270841,10,200.5,dev-1\n"
    "1625097600000,48.86359,23.32186,,,dev-2\n"
)


def test_parse_csv_basic() -> None:
    points = parse_location_history_csv(CSV_SAMPLE.encode())
    assert len(points) == 2
    p = points[0]
    assert abs(p.latitude - 50.0934826) < 1e-9
    assert p.accuracy_m == 10.0
    # ISO čas → timestamp_ms=None (parser drží jen epoch)
    assert p.timestamp_ms is None
    # epoch ms řádek
    assert points[1].timestamp_ms == 1625097600000


def test_parse_csv_missing_columns_raises() -> None:
    with pytest.raises(ValueError):
        parse_location_history_csv(b"a,b\n1,2\n")


def test_artifacts() -> None:
    points = parse_location_history_json(json.dumps(_json_sample()).encode())
    arts = build_location_artifacts(points)
    assert len(arts) == 2
    a = arts[0]
    assert a.artifact_type == "google_location"
    # epoch ms 1625097600000 → 2021-07-01T00:00Z
    assert a.timestamp == datetime(2021, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert "50.09348" in a.title
    assert a.details["latitude"] is not None
    assert a.confidence == 0.9


def test_artifact_without_coords_lower_confidence() -> None:
    points = parse_location_history_json(json.dumps([{"longitudeE7": 144270841}]).encode())
    arts = build_location_artifacts(points)
    assert len(arts) == 1
    assert arts[0].confidence == 0.6


def test_detection() -> None:
    head_json = json.dumps(_json_sample())[:2048].encode()
    assert is_location_history_file("location_history.json", head_json)
    assert is_location_history_file("LocationHistory.csv", CSV_SAMPLE.encode()[:2048])
    assert not is_location_history_file("other.json", head_json)
    assert not is_location_history_file("location_history.json", b"random text")


def test_extract_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "location_history.json"
    p.write_text(json.dumps(_json_sample()))
    arts = extract_location_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_location" for a in arts)


def test_extract_csv_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "location_history.csv"
    p.write_text(CSV_SAMPLE)
    arts = extract_location_artifacts(p)
    assert len(arts) == 2


def test_extract_missing_file(tmp_path: Path) -> None:
    assert extract_location_artifacts(tmp_path / "chybi.json") == []
