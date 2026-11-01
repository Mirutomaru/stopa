"""E7 — NTFS USN Journal ($UsnJrnl) parser.

Parsuje NTFS USN Journal a extrahuje záznamy o změnách souborového systému
(vytvoření, smazání, přejmenování, změna atributů).

USN Journal se nachází v: ``$Extend\\$UsnJrnl`` (NTFS metadata file) —
detekce name-based (soubor nemá spolehlivou magic; header verze 2 je
kontextově ověřen parserem).

Formát::

    Header (1024 B) — USN_JOURNAL_DATA_V2::
        @0x00  u32     MajorVersion       # 2 pro v2 formát
        @0x04  u32     MinorVersion       # 0
        @0x08  i64     UsnJournalID
        @0x10  i64     FirstUsn
        @0x18  FILETIME CreationTime      # u64, 100ns od 1601
        @0x20  u32     FileSystemMajorVersion   # např. 3 (NTFS)
        @0x24  u32     FileSystemMinorVersion   # např. 50
        @0x28  i64     Number of Sectors
        @0x30  u32     Allocation Delta         # obvykle 1024
        @0x38  i64     Next Usn

    Records (od offsetu 1024) — USN_RECORD_V2:
        u16     MajorVersion       # 2 pro v2 záznamy
        u16     MinorVersion       # 0
        u32     RecordLength       # celková délka tohoto záznamu
        u64     Usn                # unikátní sekvence číslo
        FILETIME TimeStamp         # u64, 100ns od 1601
        u32     FileAttributes
        u32     MajorVersion (dup) / MinorVersion (dup)
        u64    ParentFileReferenceNumber
        u64     FileReferenceNumber
        u16     FileNameLength     # délka filename v bytech
        UTF-16LE Filename

Artifact type: ``usn_record`` (AXIOM ``Magnet.Artifacts.NTFS.USNJournal``)
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"


def is_usn_journal_file(name: str) -> bool:
    """Name-based detekce NTFS USN Journal ($UsnJrnl, $UsnJrnl_000X).

    Soubor nemá spolehlivou magic (header verze 2 je kontextově ověřen
    parserem) → AXIOM Hunter pattern jako Jump Lists.
    """
    stem = name.lower().lstrip("$")
    return stem == "usnjrnl" or stem.startswith("usnjrnl_")


# USN reason kódy (bitmaska) — MS-NTFS §2.4.3
USN_REASON_DATA_OVERWRITE = 0x00000001
USN_REASON_DATA_EXTEND = 0x00000002
USN_REASON_DATA_TRUNCATION = 0x00000004
USN_REASON_NA_DATA_CHANGE = 0x00000008
USN_REASON_FILE_CREATE = 0x00000100
USN_REASON_FILE_DELETE = 0x00000200
USN_REASON_RENAME_OLD_NAME = 0x00001000
USN_REASON_RENAME_NEW_NAME = 0x00002000
USN_REASON_FILE_CREATE_OVERWRITE = 0x00004000


@dataclass
class UsnRecord:
    """Jeden záznam z USN Journal."""

    usn: int = 0
    timestamp: datetime | None = None
    record_length: int = 0
    file_attributes: int = 0
    reason: int = 0
    filename: str = ""
    parent_file_reference: int = 0
    file_reference: int = 0


@dataclass
class UsnJournalData:
    """Celý USN Journal — header + seznam záznamů."""

    major_version: int = 0
    minor_version: int = 0
    journal_id: int = 0
    first_usn: int = 0
    creation_time: datetime | None = None
    fs_major_version: int = 0
    fs_minor_version: int = 0
    next_usn: int = 0
    entries: list[UsnRecord] = field(default_factory=list)


def _filetime_to_dt(value: int) -> datetime | None:
    """Konvertuje FILETIME (u64 100ns od 1601) na datetime."""
    if value <= 0 or value > 10**18:
        return None
    try:
        unix_ts = (value - 116_444_736_000_000_000) / 10_000_000
        if unix_ts < 0 or unix_ts > 4_102_444_800:
            return None
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _reason_to_str(reason: int) -> str:
    """Konvertuje USN reason bitmasku na čitelný string."""
    parts = []
    if reason & USN_REASON_FILE_CREATE:
        parts.append("create")
    if reason & USN_REASON_FILE_DELETE:
        parts.append("delete")
    if reason & USN_REASON_RENAME_OLD_NAME:
        parts.append("rename_old")
    if reason & USN_REASON_RENAME_NEW_NAME:
        parts.append("rename_new")
    if reason & USN_REASON_DATA_OVERWRITE:
        parts.append("data_overwrite")
    if reason & USN_REASON_DATA_EXTEND:
        parts.append("data_extend")
    if reason & USN_REASON_DATA_TRUNCATION:
        parts.append("data_truncation")
    return ",".join(parts) if parts else f"0x{reason:x}"


def parse_usn_journal(data: bytes) -> UsnJournalData:
    """Čistý parser — parsuje $UsnJrnl binární blob.

    Raises:
        ValueError: Neplatná verze nebo poškozené data.
    """
    if len(data) < 1024:
        raise ValueError(f"USN Journal příliš krátký: {len(data)} B (min 1024)")

    major_version, minor_version = struct.unpack_from("<II", data, 0)
    journal_id, first_usn = struct.unpack_from("<QQ", data, 8)
    creation_time_ft, = struct.unpack_from("<Q", data, 24)   # @0x18
    fs_major, fs_minor = struct.unpack_from("<II", data, 32)  # @0x20/0x24
    next_usn, = struct.unpack_from("<Q", data, 56)          # @0x38

    result = UsnJournalData(
        major_version=major_version,
        minor_version=minor_version,
        journal_id=journal_id,
        first_usn=first_usn,
        creation_time=_filetime_to_dt(creation_time_ft),
        fs_major_version=fs_major,
        fs_minor_version=fs_minor,
        next_usn=next_usn,
    )

    if major_version not in (1, 2):
        logger.warning("Neobvyklá USN Journal verze: %d", major_version)

    # Records od offsetu 1024 — USN_RECORD_V2 layout (MS-NTFS §2.4.3)::
    #   +0x00 u16 MajorVersion, +0x02 u16 MinorVersion
    #   +0x04 u32 RecordLength
    #   +0x08 i64 Usn
    #   +0x10 FILETIME TimeStamp (u64)
    #   +0x18 u32 FileAttributes
    #   +0x1C u16 MajorVersion (dup), +0x1E u16 MinorVersion (dup)
    #   +0x20 i64 ParentFileReferenceNumber
    #   +0x28 i64 FileReferenceNumber
    #   +0x30 u32 Reason, +0x34 u32 SourceInfo
    #   +0x38 u16 FileNameLength, +0x3A u16 FileNameOffset
    #   +0x3C UTF-16LE Filename[]
    off = 1024
    while off + 60 <= len(data):
        rec_major, _rec_minor = struct.unpack_from("<HH", data, off)
        record_length, = struct.unpack_from("<I", data, off + 4)

        if rec_major not in (1, 2) or record_length < 60:
            logger.warning(
                "USN: neplatný záznam na offsetu %s (major=%d len=%d)",
                hex(off),
                rec_major,
                record_length,
            )
            break
        if off + record_length > len(data):
            logger.warning("USN: RecordLength přesahuje konec dat")
            break

        usn, = struct.unpack_from("<Q", data, off + 8)
        timestamp_ft, = struct.unpack_from("<Q", data, off + 16)   # @0x10
        file_attributes, = struct.unpack_from("<I", data, off + 24)  # @0x18
        parent_ref, file_ref = struct.unpack_from("<QQ", data, off + 32)  # @0x20/0x28
        reason, _source_info = struct.unpack_from("<II", data, off + 48)  # @0x30/0x34
        fname_len, fname_off = struct.unpack_from("<HH", data, off + 56)  # @0x38/0x3A

        filename = ""
        if fname_len > 0:
            name_start = off + (fname_off if fname_off else 60)
            raw_name = data[name_start : name_start + fname_len]
            try:
                filename = raw_name.decode("utf-16-le", errors="replace")
            except Exception:  # noqa: BLE001
                filename = repr(raw_name)

        result.entries.append(
            UsnRecord(
                usn=usn,
                timestamp=_filetime_to_dt(timestamp_ft),
                record_length=record_length,
                file_attributes=file_attributes,
                reason=reason,
                filename=filename,
                parent_file_reference=parent_ref,
                file_reference=file_ref,
            )
        )

        off += record_length

    logger.debug("USN Journal: %d záznamů", len(result.entries))
    return result


def build_usn_artifacts(parsed: UsnJournalData) -> list[Artifact]:
    """ČISTÁ funkce: z UsnJournalData vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for e in parsed.entries:
        if not e.filename and e.usn == 0:
            continue

        details: dict[str, Any] = {
            "engine": "usn_journal",
            "reason": _reason_to_str(e.reason),
            "file_attributes": hex(e.file_attributes),
        }
        if e.parent_file_reference:
            details["parent_ref"] = e.parent_file_reference
        if e.file_reference:
            details["file_ref"] = e.file_reference

        title = f"USN {e.usn}: {_reason_to_str(e.reason)}"
        if e.filename:
            title += f" — {e.filename}"

        artifacts.append(
            Artifact(
                artifact_type="usn_record",
                timestamp=e.timestamp,
                title=title,
                details=details,
                confidence=0.9,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_usn_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — parsoje $UsnJrnl soubor a vrátí artefakty."""
    try:
        data = path.read_bytes()
        parsed = parse_usn_journal(data)
        return build_usn_artifacts(parsed)
    except FileNotFoundError:
        logger.warning("USN Journal nenalezen: %s", path)
        return []
    except ValueError as exc:
        logger.error("Chyba při parsingu USN Journal %s: %s", path, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Neočekávaná chyba při parsingu USN Journal %s: %s", path, exc)
        return []
