"""ETAPA B vlna 13 — syntetické offline testy cloud-export parserů.

Pokrývá 4 nové parsery (Google Calendar/Keep, Box, Dropbox/Mega) +
dispatch pre-pass routing. Všechny fixture jsou syntetické JSON bez
externích závislostí.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.box_cloud import (
    build_box_artifacts,
    extract_box_artifacts,
    is_box_file,
    parse_box_cloud,
)
from stopa.artifacts.dropbox_mega import (
    build_dropbox_mega_artifacts,
    extract_dropbox_mega_artifacts,
    is_dropbox_file,
    is_mega_file,
    parse_dropbox_mega,
)
from stopa.artifacts.google_calendar_events import (
    build_google_calendar_artifacts,
    extract_google_calendar_artifacts,
    is_google_calendar_file,
    parse_google_calendar_events,
)
from stopa.artifacts.google_keep_tasks import (
    build_google_keep_artifacts,
    extract_google_keep_artifacts,
    is_google_keep_file,
    parse_google_keep_tasks,
)

# ---------------------------------------------------------------------------
# Google Calendar Events
# ---------------------------------------------------------------------------


class TestGoogleCalendarEvents:
    def test_parse_takeout_list(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "summary": "Schůzka s klientem",
                    "start": {"dateTime": "2024-10-03T09:00:00Z"},
                    "end": {"dateTime": "2024-10-03T10:30:00Z"},
                    "organizer": {"displayName": "Jan Novák", "email": "jan@x.cz"},
                    "attendees": [{"email": "petr@y.cz"}],
                    "location": "Kancelář A",
                }
            ]
        ).encode()
        recs = parse_google_calendar_events(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.subject == "Schůzka s klientem"
        assert r.start_s is not None and r.end_s is not None
        assert r.organizer == "Jan Novák"
        assert r.attendees == ["petr@y.cz"]
        assert r.location == "Kancelář A"

    def test_parse_wrapper_events(self):
        # quality: positive
        data = json.dumps(
            {
                "events": [
                    {"summary": "All-day", "start": {"date": "2024-10-05"}, "end": {"date": "2024-10-06"}}
                ]
            }
        ).encode()
        recs = parse_google_calendar_events(data)
        assert len(recs) == 1
        assert recs[0].subject == "All-day"
        # all-day: start/end jako date-only ISO
        assert recs[0].start_s is not None

    def test_parse_empty_raises(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_google_calendar_events(b"[]")

    def test_invalid_json_raises(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_google_calendar_events(b"{nejson")

    def test_build_artifacts(self):
        # quality: positive
        data = json.dumps(
            [{"summary": "X", "start": {"dateTime": "2024-10-03T09:00:00Z"}}]
        ).encode()
        arts = build_google_calendar_artifacts(parse_google_calendar_events(data))
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "calendar_event"
        assert "X" in (a.title or "")
        assert a.details.get("engine") == "google_calendar_events"

    def test_extract_roundtrip(self, tmp_path: Path):
        # quality: positive
        p = tmp_path / "Google_Calendar.json"
        p.write_text(json.dumps([{"summary": "E", "start": {"dateTime": "2024-10-03T09:00:00Z"}}]))
        arts = extract_google_calendar_artifacts(p)
        assert len(arts) == 1

    def test_extract_missing_file(self, tmp_path: Path):
        # quality: negative
        assert extract_google_calendar_artifacts(tmp_path / "absent.json") == []

    def test_detector_positive(self):
        # quality: positive
        assert is_google_calendar_file("Google_Calendar_events.json")
        assert is_google_calendar_file("takeout/calendar/Calendar.json")

    def test_detector_negative_generic(self):
        # quality: positive
        # bez google/takeout markery nepadne (generic events.json)
        assert not is_google_calendar_file("events.json")


# ---------------------------------------------------------------------------
# Google Keep + Tasks
# ---------------------------------------------------------------------------


class TestGoogleKeepTasks:
    def test_parse_keep_notes(self):
        # quality: positive
        data = json.dumps(
            {
                "notes": [
                    {
                        "title": "Nákup",
                        "text": "mléko, chléb",
                        "creationTime": "2024-10-03T09:00:00Z",
                        "modificationTime": "2024-10-03T10:00:00Z",
                        "labels": ["doma"],
                    }
                ]
            }
        ).encode()
        recs = parse_google_keep_tasks(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "keep_note"
        assert r.title == "Nákup"
        assert r.text == "mléko, chléb"
        assert r.created_s is not None
        assert r.labels == ["doma"]

    def test_parse_tasks(self):
        # quality: positive
        data = json.dumps(
            {
                "tasks": [
                    {"title": "Odeslat fakturu", "dueDate": "2024-10-05T17:00:00Z", "completed": False, "listId": "work"}
                ]
            }
        ).encode()
        recs = parse_google_keep_tasks(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "task"
        assert r.title == "Odeslat fakturu"
        assert r.due_s is not None
        assert r.completed is False

    def test_parse_flat_list_mixed(self):
        # quality: positive
        data = json.dumps(
            [
                {"title": "Poznámka", "text": "obsah"},
                {"title": "Úkol", "dueDate": "2024-10-05T17:00:00Z", "completed": True},
            ]
        ).encode()
        recs = parse_google_keep_tasks(data)
        assert len(recs) == 2
        kinds = {r.kind for r in recs}
        assert kinds == {"keep_note", "task"}

    def test_parse_empty_raises(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_google_keep_tasks(b"{}")

    def test_invalid_json_raises(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_google_keep_tasks(b"[x]")

    def test_build_artifacts(self):
        # quality: positive
        data = json.dumps({"notes": [{"title": "T", "text": "X"}]}).encode()
        arts = build_google_keep_artifacts(parse_google_keep_tasks(data))
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "document_metadata"
        assert a.details.get("kind") == "keep_note"

    def test_extract_roundtrip(self, tmp_path: Path):
        # quality: positive
        p = tmp_path / "Keep.json"
        p.write_text(json.dumps({"notes": [{"title": "T"}]}))
        arts = extract_google_keep_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        # quality: positive
        assert is_google_keep_file("takeout/Keep_notes.json")
        assert is_google_keep_file("google_tasks_export.json")

    def test_detector_negative_generic(self):
        # quality: positive
        assert not is_google_keep_file("notes.json")


# ---------------------------------------------------------------------------
# Box Cloud
# ---------------------------------------------------------------------------


class TestBoxCloud:
    def test_parse_files_folders(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "id": "1",
                    "name": "report.pdf",
                    "size": 4096,
                    "type": "file",
                    "path_collection": {"paths": [{"id": "1", "name": "root"}, {"id": "2", "name": "docs"}]},
                    "created_at": "2024-10-03T09:00:00Z",
                    "modified_at": "2024-10-05T10:00:00Z",
                },
                {"id": "2", "name": "docs", "type": "folder"},
            ]
        ).encode()
        recs = parse_box_cloud(data)
        assert len(recs) == 2
        f, d = recs
        assert f.kind == "file" and f.name == "report.pdf"
        assert f.size == 4096
        assert f.path is not None
        assert d.kind == "folder"

    def test_parse_events(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "event_type": "file.upload",
                    "actor": {"name": "Jan Novák"},
                    "created_at": "2024-10-06T08:00:00Z",
                    "record_name": "report.pdf",
                }
            ]
        ).encode()
        recs = parse_box_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "event"
        assert r.action == "file.upload"
        assert r.author == "Jan Novák"

    def test_parse_wrapper_entries(self):
        # quality: positive
        data = json.dumps(
            {"entries": [{"name": "a.txt", "type": "file"}], "events": [{"event_type": "item.trash", "created_at": "2024-10-06T08:00:00Z"}]}
        ).encode()
        recs = parse_box_cloud(data)
        assert len(recs) == 2

    def test_parse_empty_raises(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_box_cloud(b"[]")

    def test_invalid_json_raises(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_box_cloud(b"{bad")

    def test_build_artifacts_event_action(self):
        # quality: positive
        data = json.dumps([{"event_type": "file.upload", "created_at": "2024-10-06T08:00:00Z"}]).encode()
        arts = build_box_artifacts(parse_box_cloud(data))
        assert len(arts) == 1
        a = arts[0]
        assert a.details.get("kind") == "event"
        assert a.details.get("action") == "file.upload"

    def test_extract_roundtrip(self, tmp_path: Path):
        # quality: positive
        p = tmp_path / "box_files.json"
        p.write_text(json.dumps([{"name": "a.pdf", "type": "file"}]))
        arts = extract_box_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        # quality: positive
        assert is_box_file("box_files_export.json")
        assert is_box_file("Box/enterprise_events.json")

    def test_detector_negative_generic(self):
        # quality: positive
        assert not is_box_file("files.json")


# ---------------------------------------------------------------------------
# Dropbox + Mega
# ---------------------------------------------------------------------------


class TestDropboxMega:
    def test_parse_dropbox_list(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "name": "report.pdf",
                    "path_lower": "/docs/report.pdf",
                    "bytes": 4096,
                    "is_dir": False,
                    "server_modified": "2024-10-05T10:00:00Z",
                },
                {"name": "docs", "path_lower": "/docs", "is_dir": True},
            ]
        ).encode()
        recs = parse_dropbox_mega(data, provider_hint="dropbox")
        assert len(recs) == 2
        f, d = recs
        assert f.provider == "dropbox" and f.kind == "file"
        assert f.size == 4096
        assert d.kind == "folder"

    def test_parse_mega_list(self):
        # quality: positive
        data = json.dumps(
            [{"name": "photo.jpg", "size": 2048, "type": "file", "modified": 1728136800}]
        ).encode()
        recs = parse_dropbox_mega(data, provider_hint="mega")
        assert len(recs) == 1
        r = recs[0]
        assert r.provider == "mega" and r.kind == "file"
        assert r.size == 2048
        assert r.modified_s is not None

    def test_parse_auto_provider_dropbox_keys(self):
        # quality: positive
        # bez hintu — auto-detekce podle klíčů (path_lower = Dropbox API)
        data = json.dumps([{"name": "f.pdf", "path_lower": "/f.pdf", "bytes": 10}]).encode()
        recs = parse_dropbox_mega(data)
        assert recs[0].provider == "dropbox"

    def test_parse_empty_raises(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_dropbox_mega(b"[]")

    def test_invalid_json_raises(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_dropbox_mega(b"{nope")

    def test_build_artifacts_provider(self):
        # quality: positive
        data = json.dumps([{"name": "f.pdf", "bytes": 10}]).encode()
        arts = build_dropbox_mega_artifacts(parse_dropbox_mega(data, provider_hint="dropbox"))
        assert len(arts) == 1
        a = arts[0]
        assert a.details.get("provider") == "dropbox"

    def test_extract_roundtrip(self, tmp_path: Path):
        # quality: positive
        p = tmp_path / "dropbox_entries.json"
        p.write_text(json.dumps([{"name": "f.pdf", "bytes": 10}]))
        arts = extract_dropbox_mega_artifacts(p)
        assert len(arts) == 1
        assert arts[0].details.get("provider") == "dropbox"

    def test_extract_mega_hint_from_path(self, tmp_path: Path):
        # quality: positive
        p = tmp_path / "mega_files.json"
        p.write_text(json.dumps([{"name": "p.jpg", "size": 5}]))
        arts = extract_dropbox_mega_artifacts(p)
        assert len(arts) == 1
        assert arts[0].details.get("provider") == "mega"

    def test_detector_positive(self):
        # quality: positive
        assert is_dropbox_file("dropbox_entries.json")
        assert is_mega_file("mega_files_export.json")

    def test_detector_negative_generic(self):
        # quality: positive
        assert not is_dropbox_file("files.json")
        assert not is_mega_file("entries.json")


# ---------------------------------------------------------------------------
# Dispatch pre-pass routing (vlna 13)
# ---------------------------------------------------------------------------


class TestWave13Dispatch:
    @pytest.fixture()
    def pipeline(self):
        from stopa import pipeline

        return pipeline

    def test_calendar_routes(self, pipeline):
        # quality: positive
        r = pipeline._sns_prepass("/case/Google_Calendar_events.json")
        assert r is not None
        assert r[0].__name__ == "extract_google_calendar_artifacts"

    def test_keep_routes(self, pipeline):
        # quality: positive
        r = pipeline._sns_prepass("/case/takeout/Keep_notes.json")
        assert r is not None
        assert r[0].__name__ == "extract_google_keep_artifacts"

    def test_box_routes(self, pipeline):
        # quality: positive
        r = pipeline._sns_prepass("/case/box_files_export.json")
        assert r is not None
        assert r[0].__name__ == "extract_box_artifacts"

    def test_dropbox_routes(self, pipeline):
        # quality: positive
        r = pipeline._sns_prepass("/case/dropbox_entries.json")
        assert r is not None
        assert r[0].__name__ == "extract_dropbox_mega_artifacts"

    def test_mega_routes(self, pipeline):
        # quality: positive
        r = pipeline._sns_prepass("/case/mega_files.json")
        assert r is not None
        assert r[0].__name__ == "extract_dropbox_mega_artifacts"

    def test_generic_basenames_not_stolen(self, pipeline):
        # quality: positive
        # generic basenames bez markery nepadnou do pre-passu
        for name in ("events.json", "notes.json", "files.json"):
            assert pipeline._sns_prepass(f"/case/{name}") is None

    def test_calendar_before_keep_ordering(self, pipeline):
        # quality: positive
        # cesta s calendar markerem jde do calendar i když obsahuje "note"
        r = pipeline._sns_prepass("/case/Google_Calendar_notes_events.json")
        assert r is not None
        assert r[0].__name__ == "extract_google_calendar_artifacts"

    def test_older_waves_keep_order(self, pipeline):
        # quality: positive
        # Twitter (vlna 11) drží pořadí před Google II
        r = pipeline._sns_prepass("/case/twitter_posts.json")
        assert r is not None
        assert r[0].__name__ == "extract_twitter_post_artifacts"
