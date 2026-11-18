"""P1-1 vlna 2 — quality sada pro rodinu Google Takeout (w5, 8 parserů).

Pokrývá kategorie ``tz`` / ``encoding`` / ``size`` pro:
google_aggregated_activities, google_identity_sessions, google_maps_activity,
google_chat_family, google_account_change_history, google_linked_devices,
google_export_summary, drive_activity.

Vše syntetické a anonymizované; očekávané epochy počítané nezávisle
(``calendar.timegm``), nikoli parserovým kódem. Chování doloženo probytováním
parserů (tz offsety kromě Z fungují, UTF-8 BOM → ValueError = dokumentovaný
limit, chat ISO timestamp string → graceful degradace na None).
"""

from __future__ import annotations

import calendar
import json

import pytest

from stopa.artifacts.drive_activity import parse_drive_activity
from stopa.artifacts.google_account_meta import (
    build_export_summary_artifacts,
    parse_account_change_history,
    parse_export_summary,
    parse_linked_devices,
)
from stopa.artifacts.google_aggregated_activities import (
    parse_aggregated_activities,
    parse_identity_sessions,
)
from stopa.artifacts.google_chat_family import parse_chat_messages
from stopa.artifacts.google_maps_activity import build_maps_artifacts, parse_maps_activity

BOM = b"\xef\xbb\xbf"


def _epoch(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> float:
    """Nezávislý UTC epoch (bez parserového kódu)."""
    return float(calendar.timegm((y, mo, d, h, mi, 0, 0, 0, 0)))


def _chat_one(text: str, ts: int = 1705314600) -> dict:
    """Jeden chat message event (validní minimální tvar)."""
    return {
        "event_type": "CHAT_MESSAGE",
        "sender_id": {"gaia_id": "u@e.com"},
        "timestamp": ts,
        "chat_message": {"message_content": {"segment": [{"type": "TEXT", "text": text}]}},
    }


class TestTimezones:
    def test_identity_sessions_positive_offset(self):
        # quality: tz
        fx = [
            {
                "deviceInfo": {"name": "Pixel", "model": "X"},
                "sessionStartTimestamp": "2024-06-15T12:00:00+02:00",
                "sessionEndTimestamp": "2024-06-15T13:30:00+02:00",
            }
        ]
        s = parse_identity_sessions(json.dumps(fx).encode())
        assert s[0].start_ts == _epoch(2024, 6, 15, 10)  # 12:00+02:00 = 10:00 UTC
        assert s[0].end_ts == _epoch(2024, 6, 15, 11, 30)

    def test_maps_activity_negative_offset(self):
        # quality: tz
        fx = {
            "timelineObjects": [
                {
                    "placeVisit": {
                        "location": {"latitudeE7": 1, "longitudeE7": 2},
                        "duration": {
                            "startTimestamp": "2024-06-15T12:00:00-05:30",
                            "endTimestamp": "2024-06-15T13:00:00-05:30",
                        },
                    }
                }
            ]
        }
        o = parse_maps_activity(json.dumps(fx).encode())
        assert o[0].start_ts == _epoch(2024, 6, 15, 17, 30)  # 12:00-05:30 = 17:30 UTC

    def test_drive_mixed_iso_offset_and_epoch(self):
        # quality: tz
        fx = [
            {"fileId": "f1", "fileName": "a.pdf", "action": "UPLOAD",
             "timestamp": "2024-06-15T17:30:00+05:30"},
            {"fileId": "f2", "fileName": "b.txt", "action": "SHARE", "timestamp": 1718437200},
        ]
        r = parse_drive_activity(json.dumps(fx).encode())
        assert r[0].timestamp_s == _epoch(2024, 6, 15, 12)  # 17:30+05:30 = 12:00 UTC
        assert r[1].timestamp_s == 1718437200.0  # epoch se zachová beze změny

    def test_account_history_and_devices_offset(self):
        # quality: tz
        h = parse_account_change_history(
            json.dumps([{"eventType": "PASSWORD_CHANGE",
                        "timestamp": "2024-06-15T12:00:00+02:00",
                        "deviceName": "P", "ipAddress": "1.2.3.4"}]).encode()
        )
        d = parse_linked_devices(
            json.dumps([{"name": "P", "model": "M",
                         "lastUsedTimestamp": "2024-06-15T12:00:00+02:00"}]).encode()
        )
        assert h[0].timestamp_s == _epoch(2024, 6, 15, 10)
        assert d[0].last_used_s == _epoch(2024, 6, 15, 10)

    def test_chat_iso_timestamp_degrades_to_none(self):
        # quality: tz
        # chat očekává epoch int; ISO string → graceful degradace (None), ne výjimka
        fx = {"conversations": [
            {"conversation": {"conversation_id": {"id": "c"}},
             "events": [_chat_one("x", ts=0)]}]}
        fx["conversations"][0]["events"][0]["timestamp"] = "2024-01-15T10:00:00Z"
        m = parse_chat_messages(json.dumps(fx).encode())
        assert len(m) == 1 and m[0].timestamp_s is None


class TestEncoding:
    def test_czech_utf8_roundtrip(self):
        # quality: encoding
        text = "Příliš žluťoučký kůň úpěl ďábelské ódy"
        fx = {"timelineObjects": [
            {"placeVisit": {
                "location": {"latitudeE7": 1, "longitudeE7": 2},
                "place": {"name": text, "address": "Praha"},
                "duration": {"startTimestamp": "2024-01-15T10:00:00Z",
                             "endTimestamp": "2024-01-15T11:00:00Z"}}}]}
        o = parse_maps_activity(json.dumps(fx, ensure_ascii=False).encode())
        assert o[0].place_name == text

    def test_bom_prefix_raises_valueerror(self):
        # quality: encoding
        # Dokumentovaný limit: UTF-8 BOM se neodstraňuje (json ho odmítá) —
        # chování je deterministické a testované, ne implicitní.
        fx = [{"date": "2024-01-15", "activities": [{"type": "search", "count": 1}]}]
        with pytest.raises(ValueError, match="BOM"):
            parse_aggregated_activities(BOM + json.dumps(fx).encode())
        chat = {"conversations": [
            {"conversation": {"conversation_id": {"id": "c"}},
             "events": [_chat_one("a")]}] }
        with pytest.raises(ValueError, match="BOM"):
            parse_chat_messages(BOM + json.dumps(chat).encode())


class TestSize:
    def test_empty_collections_return_no_artifacts(self):
        # quality: size
        assert parse_aggregated_activities(b"[]") == []
        assert parse_drive_activity(b"[]") == []
        assert parse_maps_activity(json.dumps({"timelineObjects": []}).encode()) == []
        assert parse_chat_messages(json.dumps({"conversations": []}).encode()) == []

    def test_single_record_each_parser(self):
        # quality: size
        h = parse_account_change_history(
            json.dumps([{"eventType": "PASSWORD_CHANGE",
                        "timestamp": "2024-01-15T09:00:00Z",
                        "deviceName": "P", "ipAddress": "1.2.3.4"}]).encode()
        )
        d = parse_linked_devices(
            json.dumps([{"name": "P", "model": "M",
                         "lastUsedTimestamp": "2024-01-15T09:00:00Z"}]).encode()
        )
        s = parse_export_summary(json.dumps({"products": [], "createdTime": "2024-01-15T09:00:00Z",
                                             "email": "u@e.com"}).encode())
        assert len(h) == 1 and len(d) == 1
        # minimální export summary (prázdné products) → přesně 1 artefakt
        assert len(build_export_summary_artifacts(s)) == 1

    def test_stress_200_records(self):
        # quality: size
        base = 1705314600
        drive = [
            {"fileId": f"f-{i}", "fileName": f"file_{i}.txt", "action": "UPLOAD",
             "timestamp": base + i * 60}
            for i in range(200)
        ]
        r = parse_drive_activity(json.dumps(drive).encode())
        assert len(r) == 200
        assert r[199].timestamp_s == float(base + 199 * 60)

        chat = {"conversations": [
            {"conversation": {"conversation_id": {"id": "c"}},
             "events": [_chat_one(f"msg-{i}", ts=base + i * 60) for i in range(200)]}] }
        m = parse_chat_messages(json.dumps(chat).encode())
        assert len(m) == 200
        assert m[0].text == "msg-0" and m[199].timestamp_s == float(base + 199 * 60)

    def test_stress_maps_artifacts_build(self):
        # quality: size
        objs = parse_maps_activity(json.dumps({
            "timelineObjects": [
                {"placeVisit": {
                    "location": {"latitudeE7": i, "longitudeE7": i},
                    "duration": {"startTimestamp": f"2024-01-{(i % 28) + 1:02d}T10:00:00Z",
                                 "endTimestamp": f"2024-01-{(i % 28) + 1:02d}T11:00:00Z"}}}
                for i in range(50)
            ]}).encode())
        assert len(objs) == 50
        arts = build_maps_artifacts(objs)
        assert len(arts) == 50
