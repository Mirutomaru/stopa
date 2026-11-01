"""E7 — Windows parsery vlna 2: Event Log (.evtx), Amcache, ShimCache, USN Journal.

Binární fixture se generují přímo v testech (žádné externí soubory):
- EVTX: file header + chunky (standardní "EVTX"/"CHUN" i ground-truth
  "ElfFile\\0"/"ElfChnk\\0") s BinXML payloadem obsahujícím EventID markery
- ShimCache: u32 version + FILETIME last_write + záznamy (ANSI/UTF-16LE) až do konce
- USN Journal: 1024 B header (USN_JOURNAL_DATA_V2) + USN_RECORD_V2 záznamy
- Amcache: čisté funkce _parse_amcache_values / build_amcache_artifacts

E2E testy jdou přes `process_source` (forensic profil) a čtou artifacty z DB.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.win_amcache import (
    _parse_amcache_values,
    build_amcache_artifacts,
)
from stopa.artifacts.win_eventlog import (
    _extract_binxml_strings,
    build_evtx_artifacts,
    extract_evtx_artifacts,
    parse_evtx_file,
)
from stopa.artifacts.win_shimcache import (
    build_shimcache_artifacts,
    parse_shimcache_value,
)
from stopa.artifacts.win_usn import (
    USN_REASON_FILE_CREATE,
    USN_REASON_FILE_DELETE,
    build_usn_artifacts,
    is_usn_journal_file,
    parse_usn_journal,
)
from stopa.data.db import CaseDB
from stopa.domain.signatures import detect_signature
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source


def _ft(year: int, month: int, day: int, hour=0, minute=0, second=0) -> int:
    """FILETIME (u64 100ns od 1601) z datetime."""
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return int(dt.timestamp() * 10_000_000) + 116_444_736_000_000_000


# ──────────────────────────────────────────────────────────────────────
# EVTX fixture generátory
# ──────────────────────────────────────────────────────────────────────

PROVIDER = "Microsoft-Windows-Kernel-General"
MESSAGE = "The service was started successfully by the system manager."


def _evtx_binxml(event_id: int) -> bytes:
    """BinXML payload s EventID markerem + providerem + zprávou (UTF-16LE)."""
    text = f"EventID\x00{event_id}\x00{PROVIDER}\x00{MESSAGE}"
    return text.encode("utf-16-le")


def _evtx_record(record_number: int, event_id: int) -> bytes:
    """Jeden EVTX record (header + BinXML payload)."""
    payload = _evtx_binxml(event_id)
    header_size = 40  # 0x28
    total_size = header_size + len(payload)
    rec = bytearray(total_size)
    struct.pack_into("<I", rec, 0x00, total_size)
    struct.pack_into("<H", rec, 0x04, header_size)
    struct.pack_into("<H", rec, 0x06, record_number)
    struct.pack_into("<I", rec, 0x08, 0)  # reserved
    struct.pack_into("<Q", rec, 0x0C, _ft(2026, 10, 26, 15, 20, 19))
    struct.pack_into("<Q", rec, 0x14, record_number * 100)
    rec[header_size : header_size + len(payload)] = payload
    return bytes(rec)


def make_evtx_standard(n_events: int = 3) -> bytes:
    """Standardní EVTX (magic "EVTX", chunky "CHUN") s n událostmi."""
    hdr = bytearray(128)
    hdr[0:4] = b"EVTX"
    struct.pack_into("<I", hdr, 0x20, 128)  # file_header_size
    struct.pack_into("<H", hdr, 0x24, 3)  # major_version
    struct.pack_into("<H", hdr, 0x26, 0)  # minor_version
    data = bytes(hdr)

    chunk_hdr = bytearray(128)
    chunk_hdr[0:4] = b"CHUN"
    struct.pack_into("<I", chunk_hdr, 0x08, 0)  # chunk_number
    struct.pack_into("<I", chunk_hdr, 0x28, 128)  # chunk_header_size
    data += bytes(chunk_hdr)

    for i in range(n_events):
        data += _evtx_record(i + 1, 4624 + i)
    return data


def make_evtx_elf(n_events: int = 2) -> bytes:
    """ElfFile varianta (magic "ElfFile\\0", chunky "ElfChnk\\0")."""
    hdr = bytearray(128)
    hdr[0:8] = b"ElfFile\x00"
    struct.pack_into("<I", hdr, 0x20, 128)
    data = bytes(hdr)

    chunk_hdr = bytearray(128)
    chunk_hdr[0:8] = b"ElfChnk\x00"
    struct.pack_into("<I", chunk_hdr, 0x08, 0)
    struct.pack_into("<I", chunk_hdr, 0x28, 128)
    data += bytes(chunk_hdr)

    for i in range(n_events):
        data += _evtx_record(i + 1, 7040 + i)
    return data


# ──────────────────────────────────────────────────────────────────────
# ShimCache fixture generátor
# ──────────────────────────────────────────────────────────────────────


def make_shimcache_blob(entries: list[tuple[str, int, bool]], version=0x2B5) -> bytes:
    """ShimCache blob — u32 version + FILETIME + záznamy až do konce dat."""
    blob = struct.pack("<I", version)
    blob += struct.pack("<Q", _ft(2026, 10, 26))
    for filename, size, unicode in entries:
        if unicode:
            blob += struct.pack("<I", (size & 0x7FFFFFFF) | 0x80000000)
            blob += filename.encode("utf-16-le") + b"\x00\x00"
        else:
            blob += struct.pack("<I", size & 0x7FFFFFFF)
            blob += filename.encode("utf-8") + b"\x00"
    return blob


# ──────────────────────────────────────────────────────────────────────
# USN Journal fixture generátor
# ──────────────────────────────────────────────────────────────────────


def make_usn_journal(records: list[tuple[int, int, int, str]]) -> bytes:
    """$UsnJrnl — 1024 B header + USN_RECORD_V2 záznamy.

    records: (usn, timestamp_ft, reason, filename)
    """
    hdr = bytearray(1024)
    struct.pack_into("<I", hdr, 0x00, 2)  # MajorVersion
    struct.pack_into("<I", hdr, 0x04, 0)  # MinorVersion
    struct.pack_into("<Q", hdr, 0x08, 123_456_789)  # UsnJournalID
    struct.pack_into("<Q", hdr, 0x10, 512)  # FirstUsn
    struct.pack_into("<Q", hdr, 0x18, _ft(2026, 1, 1))  # CreationTime
    struct.pack_into("<I", hdr, 0x20, 3)  # FileSystemMajorVersion
    struct.pack_into("<I", hdr, 0x24, 50)  # FileSystemMinorVersion
    struct.pack_into("<Q", hdr, 0x28, 1000)  # Number of Sectors
    struct.pack_into("<I", hdr, 0x30, 1024)  # Allocation Delta
    struct.pack_into("<Q", hdr, 0x38, 512 + len(records))  # Next Usn

    data = bytes(hdr)
    for usn, ts_ft, reason, filename in records:
        fname_bytes = filename.encode("utf-16-le")
        fname_len = len(fname_bytes)
        record_length = 60 + fname_len
        rec = bytearray(record_length)
        struct.pack_into("<H", rec, 0x00, 2)  # MajorVersion
        struct.pack_into("<H", rec, 0x02, 0)  # MinorVersion
        struct.pack_into("<I", rec, 0x04, record_length)  # RecordLength
        struct.pack_into("<Q", rec, 0x08, usn)  # Usn
        struct.pack_into("<Q", rec, 0x10, ts_ft)  # TimeStamp
        struct.pack_into("<I", rec, 0x18, 0x20)  # FileAttributes (archive)
        struct.pack_into("<H", rec, 0x1C, 2)  # MajorVersion dup
        struct.pack_into("<H", rec, 0x1E, 0)  # MinorVersion dup
        struct.pack_into("<Q", rec, 0x20, 0x100)  # ParentFileReferenceNumber
        struct.pack_into("<Q", rec, 0x28, usn & 0xFFFF_FFFF)  # FileReferenceNumber
        struct.pack_into("<I", rec, 0x30, reason)  # Reason
        struct.pack_into("<I", rec, 0x34, 0)  # SourceInfo
        struct.pack_into("<H", rec, 0x38, fname_len)  # FileNameLength
        struct.pack_into("<H", rec, 0x3A, 60)  # FileNameOffset
        rec[60 : 60 + fname_len] = fname_bytes
        data += bytes(rec)
    return data


# ──────────────────────────────────────────────────────────────────────
# EVTX parser (8 testů)
# ──────────────────────────────────────────────────────────────────────


def test_evtx_standard_content_scan():
    """Standardní EVTX s EventID markery → content-scan najde všechny záznamy."""
    data = make_evtx_standard(3)
    parsed = parse_evtx_file(data)
    assert not parsed.is_elf_variant
    assert parsed.chunk_count == 1
    assert len(parsed.entries) == 3
    # provider + message se extrahuje ze sdílené string tabulky chunku
    for e in parsed.entries:
        assert e.provider == PROVIDER
        assert MESSAGE in e.message
        assert e.event_id is not None


def test_evtx_elf_variant_parse():
    """ElfFile varianta (ground-truth) → is_elf_variant + záznamy přes markery."""
    data = make_evtx_elf(2)
    parsed = parse_evtx_file(data)
    assert parsed.is_elf_variant
    assert len(parsed.entries) == 2
    for e in parsed.entries:
        assert e.provider == PROVIDER


def test_evtx_extract_binxml_strings_fields():
    """_extract_binxml_strings — event_id, provider i message přesně."""
    payload = _evtx_binxml(4624)
    fields = _extract_binxml_strings(payload)
    assert fields["event_id"] == "4624"
    assert fields["provider"] == PROVIDER
    assert MESSAGE in fields.get("message", "")


def test_evtx_bad_magic_raises():
    """Neznámá magic → ValueError."""
    with pytest.raises(ValueError, match="Neznámá EVTX magic"):
        parse_evtx_file(b"XXXX" + b"\x00" * 124)


def test_evtx_no_chunks_empty():
    """Validní header bez chunků → 0 záznamů (ne výjimka)."""
    data = make_evtx_standard(3)
    # oříznout na file header + polovinu prvního chunku (bez CHUN magiky)
    truncated = data[:128]
    parsed = parse_evtx_file(truncated)
    assert parsed.chunk_count == 0
    assert parsed.entries == []


def test_evtx_artifacts_title_and_details():
    """build_evtx_artifacts — title s providerem + ID, details kompletní."""
    parsed = parse_evtx_file(make_evtx_standard(2))
    arts = build_evtx_artifacts(parsed)
    assert len(arts) == 2
    art = arts[0]
    assert art.artifact_type == "event_log_entry"
    assert PROVIDER in art.title
    assert "ID" in art.title
    assert art.details["engine"] == "evtx"
    assert art.details["variant"] == "standard"
    assert art.parser_version == "1.0"


def test_evtx_signature_detection():
    """detect_signature na EVTX magice → typ 'evtx' (i ElfFile varianta)."""
    sig = detect_signature(make_evtx_standard(1))
    assert sig is not None and sig[0] == "evtx" and sig[1] == "windows"
    sig_elf = detect_signature(make_evtx_elf(1))
    assert sig_elf is not None and sig_elf[0] == "evtx"


def test_evtx_extract_from_file(tmp_path: Path):
    """extract_evtx_artifacts — IO wrapper nad souborem ve fs."""
    p = tmp_path / "System.evtx"
    p.write_bytes(make_evtx_standard(2))
    arts = extract_evtx_artifacts(p)
    assert len(arts) == 2
    assert arts[0].artifact_type == "event_log_entry"


# ──────────────────────────────────────────────────────────────────────
# ShimCache parser (4 testy)
# ──────────────────────────────────────────────────────────────────────


def test_shimcache_parse_ansi_entries():
    """ANSI záznamy (bit 31 nečistý) → filename + file_size správně."""
    blob = make_shimcache_blob(
        [("C:\\Windows\\System32\\notepad.exe", 45678, False), ("C:\\app.dll", 999, False)]
    )
    parsed = parse_shimcache_value(blob)
    assert parsed.version == 0x2B5
    assert len(parsed.entries) == 2
    assert parsed.entries[0].filename == "C:\\Windows\\System32\\notepad.exe"
    assert parsed.entries[0].file_size == 45678
    assert not parsed.entries[0].is_unicode
    assert parsed.last_write is not None and parsed.last_write.year == 2026


def test_shimcache_parse_unicode_entries():
    """UTF-16LE záznamy (bit 31 čistý) → filename dekódováno, unicode=True."""
    blob = make_shimcache_blob([("C:\\Program Files\\App\\x.exe", 12345, True)])
    parsed = parse_shimcache_value(blob)
    assert len(parsed.entries) == 1
    assert parsed.entries[0].filename == "C:\\Program Files\\App\\x.exe"
    assert parsed.entries[0].is_unicode
    assert parsed.entries[0].file_size == 12345


def test_shimcache_too_short_raises():
    """Blob < 12 B (bez headeru) → ValueError."""
    with pytest.raises(ValueError, match="příliš krátký"):
        parse_shimcache_value(b"\x00" * 8)


def test_shimcache_artifacts_per_entry():
    """build_shimcache_artifacts — jeden artifact na záznam, path v details."""
    parsed = parse_shimcache_value(
        make_shimcache_blob([("C:\\a.exe", 100, False), ("C:\\b.dll", 200, False)])
    )
    arts = build_shimcache_artifacts(parsed)
    assert len(arts) == 2
    for i, art in enumerate(arts):
        assert art.artifact_type == "app_execution"
        assert art.details["engine"] == "shimcache"
        assert art.details["version"] == "0x2b5"
        assert art.timestamp is not None and art.timestamp.year == 2026
    assert arts[0].details["path"] == "C:\\a.exe"
    assert arts[1].details["file_size"] == 200


# ──────────────────────────────────────────────────────────────────────
# USN Journal parser (4 testy)
# ──────────────────────────────────────────────────────────────────────


def test_usn_parse_journal_records():
    """Header + 2 záznamy → entries s usn, reason, filename správně."""
    data = make_usn_journal(
        [
            (513, _ft(2026, 3, 1, 10), USN_REASON_FILE_CREATE, "newfile.txt"),
            (514, _ft(2026, 3, 1, 11), USN_REASON_FILE_DELETE, "oldfile.bin"),
        ]
    )
    parsed = parse_usn_journal(data)
    assert parsed.major_version == 2
    assert len(parsed.entries) == 2
    e0, e1 = parsed.entries
    assert e0.usn == 513 and e0.filename == "newfile.txt"
    assert e0.reason == USN_REASON_FILE_CREATE
    assert e0.timestamp is not None and e0.timestamp.year == 2026
    assert e1.usn == 514 and e1.filename == "oldfile.bin"
    assert e1.reason == USN_REASON_FILE_DELETE


def test_usn_is_journal_file_name_based():
    """Name-based detektor — $UsnJrnl ano, ostatní ne."""
    assert is_usn_journal_file("$UsnJrnl")
    assert is_usn_journal_file("$USNJRNL_0002")  # case-insensitive + rotace
    assert not is_usn_journal_file("System.evtx")
    assert not is_usn_journal_file("usnjrnl.txt")


def test_usn_too_short_raises():
    """Data < 1024 B (bez headeru) → ValueError."""
    with pytest.raises(ValueError, match="příliš krátký"):
        parse_usn_journal(b"\x00" * 512)


def test_usn_artifacts_per_record():
    """build_usn_artifacts — jeden artifact na záznam, reason v details/title."""
    parsed = parse_usn_journal(
        make_usn_journal([(513, _ft(2026, 3, 1), USN_REASON_FILE_CREATE, "a.txt")])
    )
    arts = build_usn_artifacts(parsed)
    assert len(arts) == 1
    art = arts[0]
    assert art.artifact_type == "usn_record"
    assert art.details["engine"] == "usn_journal"
    assert art.details["reason"] == "create"
    assert "a.txt" in art.title
    assert art.timestamp is not None and art.timestamp.year == 2026


# ──────────────────────────────────────────────────────────────────────
# Amcache parser (3 testy) — čisté funkce, bez regipy
# ──────────────────────────────────────────────────────────────────────


def test_amcache_parse_values_classic():
    """Klasický AppCompatCache — Name/Version/Publisher/Size/TimeStamps."""
    values = {
        "Name": "VLC media player",
        "Version": "3.0.23",
        "Publisher": "VideoLAN",
        "Size": 123456789,
        "LastModified": _ft(2026, 5, 10),
    }
    entry = _parse_amcache_values(r"\AppCompatCache\abc123", values)
    assert entry is not None
    assert entry.app_name == "VLC media player"
    assert entry.version == "3.0.23"
    assert entry.publisher == "VideoLAN"
    assert entry.size_bytes == 123456789
    assert entry.last_modified is not None and entry.last_modified.year == 2026


def test_amcache_parse_values_inventory():
    """Win11 Inventory styl — Name/Version/Publisher (bez Size)."""
    values = {
        "Name": "Magnet AXIOM",
        "Version": "2024.1",
        "Publisher": "Magnet Forensics",
    }
    entry = _parse_amcache_values(r"\Root\InventoryApplication\xyz", values)
    assert entry is not None
    assert entry.app_name == "Magnet AXIOM"
    assert entry.version == "2024.1"
    assert entry.size_bytes is None


def test_amcache_artifacts_per_entry():
    """build_amcache_artifacts — title s aplikací, details s verzi/publisherem."""
    from stopa.artifacts.win_amcache import AmcacheEntry

    entries = [
        AmcacheEntry(
            app_name="VLC media player",
            version="3.0.23",
            publisher="VideoLAN",
            size_bytes=123,
            last_modified=datetime(2026, 5, 10, tzinfo=timezone.utc),
            key_path=r"\AppCompatCache\abc",
        )
    ]
    arts = build_amcache_artifacts(entries)
    assert len(arts) == 1
    art = arts[0]
    assert art.artifact_type == "app_execution"
    assert "VLC media player" in art.title
    assert art.details["engine"] == "amcache"
    assert art.details["version"] == "3.0.23"
    assert art.timestamp is not None and art.timestamp.year == 2026


# ──────────────────────────────────────────────────────────────────────
# E2E pipeline (2 testy) — process_source → DB artifacts
# ──────────────────────────────────────────────────────────────────────

CASE_ID = "case-e7"


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "case.db")
    db.add_case(Case(id=CASE_ID, name="E7 test"))
    return db


def _add_source(db: CaseDB, root: Path) -> EvidenceSource:
    src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(root))
    db.add_source(src)
    return src


def test_e2e_evtx_pipeline(tmp_path: Path, case_db: CaseDB):
    """EVTX soubor v evidence stromu → event_log_entry artifacty v DB."""
    (tmp_path / "winevt").mkdir()
    (tmp_path / "winevt" / "System.evtx").write_bytes(make_evtx_standard(2))
    src = _add_source(case_db, tmp_path)
    process_source(case_db, src.id, tmp_path, "forensic")

    arts = case_db.list_artifacts(source_id=src.id, artifact_type="event_log_entry")
    assert len(arts) == 2
    assert PROVIDER in arts[0].title
    assert arts[0].file_id is not None


def test_e2e_usn_pipeline(tmp_path: Path, case_db: CaseDB):
    """$UsnJrnl v evidence stromu → usn_record artifacty v DB.

    Name-based dispatch — soubor nemá spolehlivou magic, detekce podle názvu.
    """
    (tmp_path / "$Extend").mkdir()
    journal = make_usn_journal(
        [(513, _ft(2026, 3, 1), USN_REASON_FILE_CREATE, "secret.docx")]
    )
    (tmp_path / "$Extend" / "$UsnJrnl").write_bytes(journal)
    src = _add_source(case_db, tmp_path)
    process_source(case_db, src.id, tmp_path, "forensic")

    arts = case_db.list_artifacts(source_id=src.id, artifact_type="usn_record")
    assert len(arts) == 1
    assert "secret.docx" in arts[0].title
    assert arts[0].details["reason"] == "create"
