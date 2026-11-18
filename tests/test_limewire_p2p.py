"""ETAPA B vlna 3 — testy LimeWire/Limerunner/Luckywire parseru (P2P shared files).

Offline syntetické fixture: JSON pole záznamů i pipe-delimited text. Ověřuje
detekci rodiny (priorita Limerunner > Limewire), parsing obou formátů,
výjimky pro špatný typ a generování shared-file artifactů s rodinným typem.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.limewire_p2p import (
    PARSER_VERSION,
    build_shared_file_artifacts,
    detect_family,
    extract_shared_files_artifacts,
    is_limewire_family_file,
    parse_shared_files,
)

# ── detekce rodiny ──────────────────────────────────────────────────

def test_detect_limewire_by_name() -> None:
    # quality: positive
    assert detect_family(name="LimeWire.dat") == "limewire_shared_file"


def test_detect_limerunner_priority_over_limewire() -> None:
    # quality: positive
    # limerunner obsahuje "limewire"? ne — ale marker je specifický;
    # ověřujeme, že limerunner vyhraje i když by šlo o obecný název
    assert detect_family(name="limerunner_export.txt") == "limerunner_shared_file"


def test_detect_luckywire_by_name() -> None:
    # quality: positive
    assert detect_family(name="LuckyWire.log") == "luckywire_shared_file"


def test_detect_by_content() -> None:
    # quality: positive
    head = b'limewire shared files\nfilename|size|path|hash\na.mp3|123|/x|abc\n'
    assert detect_family(head=head) == "limewire_shared_file"


def test_detect_none() -> None:
    # quality: negative
    assert detect_family(name="notes.txt", head=b"hello world") is None


def test_is_family_file() -> None:
    # quality: positive
    assert is_limewire_family_file("LimeWire.dat") is True
    assert is_limewire_family_file("random.txt") is False


# ── JSON parser ─────────────────────────────────────────────────────

def test_parse_json_list() -> None:
    # quality: positive
    payload = [
        {
            "filename": "song.mp3",
            "size": 123456,
            "path": "/shared/song.mp3",
            "hash": "abc123",
            "date_modified": "2010-01-02 03:04:05",
        },
        {"name": "doc.pdf", "sha1": "def456"},
    ]
    recs = parse_shared_files(json.dumps(payload).encode())
    assert len(recs) == 2
    r = recs[0]
    assert r.filename == "song.mp3"
    assert r.size == 123456
    assert r.hash == "abc123"
    assert isinstance(r.date_modified, datetime)
    assert r.date_modified.astimezone(timezone.utc).year == 2010
    # druhý záznam — aliasy name/sha1
    assert recs[1].filename == "doc.pdf"
    assert recs[1].hash == "def456"


def test_parse_json_transfer_fields() -> None:
    # quality: positive
    payload = [
        {
            "filename": "x.zip",
            "size": 10,
            "downloaded_by": "user_a",
            "downloaded_on": "2010-05-06 07:08:09",
        }
    ]
    recs = parse_shared_files(json.dumps(payload).encode())
    assert len(recs) == 1
    assert recs[0].transfer["downloaded_by"] == "user_a"


def test_parse_json_invalid_raises() -> None:
    # quality: negative
    with pytest.raises(ValueError):
        parse_shared_files(b"[{bad")


def test_parse_json_non_list_raises() -> None:
    # quality: positive
    with pytest.raises(TypeError):
        parse_shared_files(json.dumps({"a": 1}).encode())


# ── pipe-delimited parser ───────────────────────────────────────────

def test_parse_pipe_full() -> None:
    # quality: positive
    data = b"song.mp3|123456|/shared/song.mp3|abc123|2010-01-02 03:04:05\n"
    recs = parse_shared_files(data)
    assert len(recs) == 1
    r = recs[0]
    assert r.filename == "song.mp3"
    assert r.size == 123456
    assert r.path == "/shared/song.mp3"
    assert r.hash == "abc123"
    assert isinstance(r.date_modified, datetime)


def test_parse_pipe_minimal() -> None:
    # quality: boundary
    data = b"doc.pdf|99\n"
    # pipe regex vyžaduje name|size|path|hash — 2 pole nestačí
    recs = parse_shared_files(data)
    assert len(recs) == 0


def test_parse_pipe_skip_comments_and_garbage() -> None:
    # quality: corrupted
    data = (
        "# hlavička\n"
        "song.mp3|123456|/shared/song.mp3|abc123\n"
        "nesmysl bez pipe\n"
    ).encode()
    recs = parse_shared_files(data)
    assert len(recs) == 1


# ── artifacty + entrypoint ─────────────────────────────────────────

def test_build_artifacts_with_family_type() -> None:
    # quality: positive
    data = b"song.mp3|123456|/shared/song.mp3|abc123\n"
    recs = parse_shared_files(data)
    arts = build_shared_file_artifacts(recs, "limewire_shared_file")
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "limewire_shared_file"
    assert a.details["filename"] == "song.mp3"
    assert a.parser_version == PARSER_VERSION


def test_entrypoint_limewire(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "LimeWire.dat"
    p.write_text("song.mp3|123456|/shared/song.mp3|abc123\n")
    arts = extract_shared_files_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "limewire_shared_file"


def test_entrypoint_limerunner(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "limerunner_export.txt"
    p.write_text("doc.pdf|99|/x/doc.pdf|hash1\n")
    arts = extract_shared_files_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "limerunner_shared_file"


def test_entrypoint_luckywire(tmp_path: Path) -> None:
    # quality: positive
    p = tmp_path / "LuckyWire.log"
    p.write_text("vid.avi|55|/y/vid.avi|h2\n")
    arts = extract_shared_files_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "luckywire_shared_file"


def test_entrypoint_unknown_family_returns_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "notes.txt"
    p.write_text("song.mp3|123456|/shared/song.mp3|abc123\n")
    assert extract_shared_files_artifacts(p) == []


def test_entrypoint_empty(tmp_path: Path) -> None:
    # quality: boundary
    p = tmp_path / "LimeWire.dat"
    p.write_bytes(b"")
    assert extract_shared_files_artifacts(p) == []
