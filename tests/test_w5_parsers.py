"""ETAPA B vlna 5 — syntetické testy pro 6 nových parserů (plně offline).

Pokrytí:
- google_aggregated_activities (GoogleAggregatedActivitiesArtifact + IdentitySessions)
- google_maps_activity (GoogleMapsActivityArtifact — placeVisit + activitySegment)
- google_chat_family (Chat/Hangouts/PlusChat/Talk — Takeout JSON)
- google_account_meta (AccountChangeHistory + Devices + ExportSummary)
- drive_activity (DriveActivityArtifact)
- samsung_voice_recording (SamsungVoiceRecordingArtifact — SQLite schéma-based)

Vše syntetické fixture, žádné sítě. Spouštět přes ``python -m pytest``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from stopa.artifacts.drive_activity import (
    PARSER_VERSION as DRIVE_VERSION,
)
from stopa.artifacts.drive_activity import (
    build_drive_artifacts,
    extract_drive_activity_artifacts,
    is_drive_activity_file,
    parse_drive_activity,
)
from stopa.artifacts.google_account_meta import (
    PARSER_VERSION as ACCT_META_VERSION,
)
from stopa.artifacts.google_account_meta import (
    build_account_event_artifacts,
    build_device_artifacts,
    build_export_summary_artifacts,
    extract_account_change_history_artifacts,
    extract_export_summary_artifacts,
    extract_linked_devices_artifacts,
    is_account_change_history_file,
    is_export_summary_file,
    is_linked_devices_file,
    parse_account_change_history,
    parse_export_summary,
    parse_linked_devices,
)
from stopa.artifacts.google_aggregated_activities import (
    PARSER_VERSION as AGG_VERSION,
)
from stopa.artifacts.google_aggregated_activities import (
    build_activity_artifacts,
    build_identity_artifacts,
    extract_aggregated_activities_artifacts,
    extract_identity_sessions_artifacts,
    is_aggregated_activities_file,
    is_identity_sessions_file,
    parse_aggregated_activities,
    parse_identity_sessions,
)
from stopa.artifacts.google_chat_family import (
    PARSER_VERSION as CHAT_VERSION,
)
from stopa.artifacts.google_chat_family import (
    build_chat_artifacts,
    extract_google_chat_artifacts,
    is_google_chat_file,
    parse_chat_messages,
)
from stopa.artifacts.google_maps_activity import (
    PARSER_VERSION as MAPS_VERSION,
)
from stopa.artifacts.google_maps_activity import (
    build_maps_artifacts,
    extract_maps_activity_artifacts,
    is_maps_activity_file,
    parse_maps_activity,
)
from stopa.artifacts.samsung_voice_recording import (
    PARSER_VERSION as SAMSUNG_VERSION,
)
from stopa.artifacts.samsung_voice_recording import (
    build_voice_recording_artifacts,
    extract_samsung_voice_recording_artifacts,
    is_samsung_voice_recording_database,
)

# ---------------------------------------------------------------------------
# Google Aggregated Activities
# ---------------------------------------------------------------------------

AGG_FIXTURE = [
    {
        "date": "2024-01-15",
        "activities": [
            {"type": "search", "count": 12},
            {"type": "youtube_watch", "count": 3},
        ],
    },
    {
        "date": "2024-01-16",
        "activities": [{"type": "maps_search", "count": 5}],
    },
]


def test_agg_parse_days():
    days = parse_aggregated_activities(json.dumps(AGG_FIXTURE).encode())
    assert len(days) == 2
    assert days[0].date == "2024-01-15"
    assert days[0].activities[0] == {"type": "search", "count": 12}


def test_agg_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_aggregated_activities(b"{nejson")


def test_agg_parse_not_list():
    with pytest.raises(TypeError):
        parse_aggregated_activities(json.dumps({"a": 1}).encode())


def test_agg_build_artifacts():
    days = parse_aggregated_activities(json.dumps(AGG_FIXTURE).encode())
    arts = build_activity_artifacts(days)
    assert len(arts) == 2
    a0 = arts[0]
    assert a0.artifact_type == "google_activity"
    assert a0.details["date"] == "2024-01-15"
    assert a0.details["activities"][0]["type"] == "search"
    assert a0.timestamp is not None
    assert a0.parser_version == AGG_VERSION


def test_agg_extract_entrypoint(tmp_path: Path):
    p = tmp_path / "aggregated_activities.json"
    p.write_text(json.dumps(AGG_FIXTURE))
    arts = extract_aggregated_activities_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_activity" for a in arts)


def test_agg_detection():
    head = json.dumps(AGG_FIXTURE).encode()[:100]
    assert is_aggregated_activities_file("aggregated_activities.json", head)
    # jiný název → False
    assert not is_aggregated_activities_file("random.txt", b"[")


IDENTITY_FIXTURE = [
    {
        "deviceInfo": {"name": "Pixel 7", "model": "G0E3C"},
        "sessionStartTimestamp": "2024-01-15T08:00:00Z",
        "sessionEndTimestamp": "2024-01-15T09:30:00Z",
    }
]


def test_identity_parse():
    sessions = parse_identity_sessions(json.dumps(IDENTITY_FIXTURE).encode())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.device_name == "Pixel 7"
    assert s.device_model == "G0E3C"
    assert s.start_ts is not None and s.end_ts is not None


def test_identity_build():
    sessions = parse_identity_sessions(json.dumps(IDENTITY_FIXTURE).encode())
    arts = build_identity_artifacts(sessions)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_identity_session"
    assert a.details["device_name"] == "Pixel 7"
    assert a.timestamp is not None


def test_identity_extract(tmp_path: Path):
    p = tmp_path / "identity_sessions.json"
    p.write_text(json.dumps(IDENTITY_FIXTURE))
    arts = extract_identity_sessions_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "google_identity_session"


def test_identity_detection():
    head = json.dumps(IDENTITY_FIXTURE).encode()[:100]
    assert is_identity_sessions_file("identity_sessions.json", head)
    assert not is_identity_sessions_file("other.json", b"[")


# ---------------------------------------------------------------------------
# Google Maps Activity (semantic location history)
# ---------------------------------------------------------------------------

MAPS_FIXTURE = {
    "timelineObjects": [
        {
            "placeVisit": {
                "location": {"latitudeE7": 501048532, "longitudeE7": 144378056},
                "place": {"name": "Staroměstské náměstí", "address": "Praha"},
                "duration": {
                    "startTimestamp": "2024-01-15T10:00:00Z",
                    "endTimestamp": "2024-01-15T11:30:00Z",
                },
            }
        },
        {
            "activitySegment": {
                "startLocation": {"latitudeE7": 501048532, "longitudeE7": 144378056},
                "endLocation": {"latitudeE7": 501100000, "longitudeE7": 144500000},
                "distance": 1250.5,
                "activityType": "WALKING",
                "confidence": "HIGH",
                "duration": {
                    "startTimestamp": "2024-01-15T11:30:00Z",
                    "endTimestamp": "2024-01-15T12:00:00Z",
                },
            }
        },
    ]
}


def test_maps_parse_place_visit():
    objs = parse_maps_activity(json.dumps(MAPS_FIXTURE).encode())
    assert len(objs) == 2
    v = objs[0]
    assert v.kind == "place_visit"
    # E7 → stupně: 501048532 / 1e7 = 50.1048532
    assert abs(v.latitude - 50.1048532) < 1e-9
    assert v.place_name == "Staroměstské náměstí"
    assert v.start_ts is not None


def test_maps_parse_activity_segment():
    objs = parse_maps_activity(json.dumps(MAPS_FIXTURE).encode())
    seg = objs[1]
    assert seg.kind == "activity_segment"
    assert seg.distance_m == 1250
    assert seg.activity_type == "WALKING"
    assert seg.confidence == "HIGH"


def test_maps_parse_invalid():
    with pytest.raises(ValueError):
        parse_maps_activity(b"{x")
    with pytest.raises(TypeError):
        parse_maps_activity(json.dumps([1, 2]).encode())


def test_maps_build():
    objs = parse_maps_activity(json.dumps(MAPS_FIXTURE).encode())
    arts = build_maps_artifacts(objs)
    assert len(arts) == 2
    a0 = arts[0]
    assert a0.artifact_type == "google_maps_activity"
    assert a0.details["kind"] == "place_visit"
    assert a0.details["place_name"] == "Staroměstské náměstí"
    assert a0.timestamp is not None


def test_maps_extract(tmp_path: Path):
    p = tmp_path / "maps_activity.json"
    p.write_text(json.dumps(MAPS_FIXTURE))
    arts = extract_maps_activity_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_maps_activity" for a in arts)


def test_maps_detection():
    head = json.dumps(MAPS_FIXTURE).encode()[:100]
    assert is_maps_activity_file("maps_activity.json", head)
    # pole místo objektu → False (head začíná [)
    assert not is_maps_activity_file("maps_activity.json", b"[")


# ---------------------------------------------------------------------------
# Google Chat family (Hangouts/Chat/PlusChat/Talk)
# ---------------------------------------------------------------------------

CHAT_FIXTURE = {
    "conversations": [
        {
            "conversation": {"conversation_id": {"id": "conv-123"}},
            "events": [
                {
                    "event_type": "CHAT_MESSAGE",
                    "sender_id": {"gaia_id": "user@example.com"},
                    "timestamp": 1705314600,
                    "chat_message": {
                        "message_content": {
                            "segment": [
                                {"type": "TEXT", "text": "Ahoj!"},
                                {"type": "IMAGE", "url": "http://x"},
                            ]
                        }
                    },
                },
                {
                    "event_type": "CHAT_MESSAGE",
                    "sender_id": {"gaia_id": "other@example.com"},
                    "timestamp": 1705314660,
                    "chat_message": {
                        "message_content": {
                            "segment": [{"type": "TEXT", "text": "Jako!"}]
                        }
                    },
                },
            ],
        }
    ]
}


def test_chat_parse_messages():
    msgs = parse_chat_messages(json.dumps(CHAT_FIXTURE).encode())
    assert len(msgs) == 2
    m0 = msgs[0]
    assert m0.conversation_id == "conv-123"
    assert m0.sender_id == "user@example.com"
    assert m0.text == "Ahoj!"
    assert m0.timestamp_s == 1705314600.0


def test_chat_parse_invalid():
    with pytest.raises(ValueError):
        parse_chat_messages(b"{x")
    with pytest.raises(TypeError):
        parse_chat_messages(json.dumps([1]).encode())


def test_chat_build():
    msgs = parse_chat_messages(json.dumps(CHAT_FIXTURE).encode())
    arts = build_chat_artifacts(msgs)
    assert len(arts) == 2
    a0 = arts[0]
    assert a0.artifact_type == "chat_message"
    assert a0.details["conversation_id"] == "conv-123"
    assert a0.details["text"] == "Ahoj!"
    assert a0.timestamp is not None


def test_chat_extract(tmp_path: Path):
    p = tmp_path / "hangouts.json"
    p.write_text(json.dumps(CHAT_FIXTURE))
    arts = extract_google_chat_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "chat_message" for a in arts)


def test_chat_detection():
    head = json.dumps(CHAT_FIXTURE).encode()[:100]
    assert is_google_chat_file("hangouts.json", head)
    assert not is_google_chat_file("notes.txt", b"{")


# ---------------------------------------------------------------------------
# Google Account metadata (change history + devices + export summary)
# ---------------------------------------------------------------------------

ACCT_HISTORY_FIXTURE = [
    {
        "eventType": "PASSWORD_CHANGE",
        "timestamp": "2024-01-15T09:00:00Z",
        "deviceName": "Pixel 7",
        "ipAddress": "1.2.3.4",
    }
]

DEVICES_FIXTURE = [
    {
        "name": "Pixel 7",
        "model": "G0E3C",
        "lastUsedTimestamp": "2024-01-15T09:00:00Z",
        "osVersion": "Android 14",
    }
]

EXPORT_SUMMARY_FIXTURE = {
    "products": ["Search history", "Location history"],
    "createdTime": "2024-01-15T09:00:00Z",
    "email": "user@example.com",
}


def test_acct_history_parse():
    events = parse_account_change_history(json.dumps(ACCT_HISTORY_FIXTURE).encode())
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "PASSWORD_CHANGE"
    assert e.device_name == "Pixel 7"
    assert e.timestamp_s is not None


def test_acct_history_build():
    events = parse_account_change_history(json.dumps(ACCT_HISTORY_FIXTURE).encode())
    arts = build_account_event_artifacts(events)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_account_event"
    assert a.details["event_type"] == "PASSWORD_CHANGE"


def test_acct_history_extract(tmp_path: Path):
    p = tmp_path / "account_change_history.json"
    p.write_text(json.dumps(ACCT_HISTORY_FIXTURE))
    arts = extract_account_change_history_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "google_account_event"


def test_devices_parse():
    devices = parse_linked_devices(json.dumps(DEVICES_FIXTURE).encode())
    assert len(devices) == 1
    d = devices[0]
    assert d.name == "Pixel 7"
    assert d.model == "G0E3C"
    assert d.last_used_s is not None


def test_devices_build():
    devices = parse_linked_devices(json.dumps(DEVICES_FIXTURE).encode())
    arts = build_device_artifacts(devices)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_device"
    assert a.details["name"] == "Pixel 7"


def test_devices_extract(tmp_path: Path):
    p = tmp_path / "linked_devices.json"
    p.write_text(json.dumps(DEVICES_FIXTURE))
    arts = extract_linked_devices_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "google_device"


def test_export_summary_parse():
    summary = parse_export_summary(json.dumps(EXPORT_SUMMARY_FIXTURE).encode())
    assert summary["products"] == ["Search history", "Location history"]


def test_export_summary_build():
    summary = parse_export_summary(json.dumps(EXPORT_SUMMARY_FIXTURE).encode())
    arts = build_export_summary_artifacts(summary)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_export_summary"
    assert a.details["products"] == ["Search history", "Location history"]
    assert a.details["account_email"] == "user@example.com"


def test_export_summary_extract(tmp_path: Path):
    p = tmp_path / "export_summary.json"
    p.write_text(json.dumps(EXPORT_SUMMARY_FIXTURE))
    arts = extract_export_summary_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "google_export_summary"


def test_acct_meta_detection():
    h_head = json.dumps(ACCT_HISTORY_FIXTURE).encode()[:100]
    d_head = json.dumps(DEVICES_FIXTURE).encode()[:100]
    s_head = json.dumps(EXPORT_SUMMARY_FIXTURE).encode()[:100]
    assert is_account_change_history_file("account_change_history.json", h_head)
    assert is_linked_devices_file("linked_devices.json", d_head)
    assert is_export_summary_file("export_summary.json", s_head)


# ---------------------------------------------------------------------------
# Google Drive Activity
# ---------------------------------------------------------------------------

DRIVE_FIXTURE = [
    {
        "fileId": "f-1",
        "fileName": "report.pdf",
        "action": "UPLOAD",
        "timestamp": "2024-01-15T10:00:00Z",
        "actorEmail": "user@example.com",
    },
    {
        "fileId": "f-2",
        "fileName": "notes.txt",
        "action": "SHARE",
        "timestamp": 1705314600,
        "actorEmail": "other@example.com",
    },
]


def test_drive_parse():
    records = parse_drive_activity(json.dumps(DRIVE_FIXTURE).encode())
    assert len(records) == 2
    r0 = records[0]
    assert r0.file_id == "f-1"
    assert r0.file_name == "report.pdf"
    assert r0.action == "UPLOAD"
    assert r0.timestamp_s is not None


def test_drive_parse_wrapped():
    # některé exporty balí pole do objektu s klíčem activities
    wrapped = {"activities": DRIVE_FIXTURE}
    records = parse_drive_activity(json.dumps(wrapped).encode())
    assert len(records) == 2


def test_drive_parse_invalid():
    with pytest.raises(ValueError):
        parse_drive_activity(b"{x")
    with pytest.raises(TypeError):
        parse_drive_activity(json.dumps({"a": 1}).encode())


def test_drive_build():
    records = parse_drive_activity(json.dumps(DRIVE_FIXTURE).encode())
    arts = build_drive_artifacts(records)
    assert len(arts) == 2
    a0 = arts[0]
    assert a0.artifact_type == "drive_activity"
    assert a0.details["file_name"] == "report.pdf"
    assert a0.details["action"] == "UPLOAD"


def test_drive_extract(tmp_path: Path):
    p = tmp_path / "drive_activity.json"
    p.write_text(json.dumps(DRIVE_FIXTURE))
    arts = extract_drive_activity_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "drive_activity" for a in arts)


def test_drive_detection():
    head = json.dumps(DRIVE_FIXTURE).encode()[:100]
    assert is_drive_activity_file("drive_activity.json", head)
    assert not is_drive_activity_file("other.txt", b"[")


# ---------------------------------------------------------------------------
# Samsung Voice Recording (SQLite schéma-based)
# ---------------------------------------------------------------------------

def _make_samsung_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE voicerec ("
        "id INTEGER PRIMARY KEY, name TEXT, path TEXT, duration INTEGER, date INTEGER)"
    )
    # 2024-01-15T10:30:00Z = epoch s 1705314600 → ms 1705314600000
    conn.execute(
        "INSERT INTO voicerec (name, path, duration, date) VALUES (?, ?, ?, ?)",
        ("Nahrávka 1", "/sdcard/Recordings/rec1.m4a", 90_000, 1705314600000),
    )
    conn.execute(
        "INSERT INTO voicerec (name, path, duration, date) VALUES (?, ?, ?, ?)",
        ("Nahrávka 2", "/sdcard/Recordings/rec2.m4a", 30_500, 1705318200000),
    )
    conn.commit()
    return conn


def test_samsung_detection():
    conn = _make_samsung_db()
    assert is_samsung_voice_recording_database(conn)


def test_samsung_detection_negative():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE other (x TEXT)")
    conn.commit()
    assert not is_samsung_voice_recording_database(conn)


def test_samsung_extract():
    conn = _make_samsung_db()
    arts = extract_samsung_voice_recording_artifacts(conn)
    assert len(arts) == 2
    a0 = arts[0]
    assert a0.artifact_type == "voice_recording"
    assert a0.details["name"] == "Nahrávka 1"
    assert a0.details["duration_s"] == 90
    assert a0.timestamp is not None


def test_samsung_build_pure():
    conn = _make_samsung_db()
    rows = conn.execute("SELECT * FROM voicerec").fetchall()
    arts = build_voice_recording_artifacts(rows)
    assert len(arts) == 2
    # délka 30_500 ms → 30 s (heuristika >10_000 = ms)
    assert arts[1].details["duration_s"] == 30


def test_samsung_empty_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE voicerec (name TEXT, path TEXT)")
    conn.commit()
    arts = extract_samsung_voice_recording_artifacts(conn)
    assert arts == []


# ---------------------------------------------------------------------------
# Verze parserů (C3 registry sanity)
# ---------------------------------------------------------------------------

def test_parser_versions():
    for v in (AGG_VERSION, MAPS_VERSION, CHAT_VERSION, ACCT_META_VERSION, DRIVE_VERSION, SAMSUNG_VERSION):
        assert v == "1.0"
