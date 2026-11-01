"""E7 — Windows Event Log (.evtx) parser.

Parsuje Windows Event Log soubory ve formátu EVTX (chunked, BinXML payload).

Podporované varianty:
  - Standardní EVTX: file magic ``EVTX``, chunk magic ``CHUN``
  - ElfFile varianta: file magic ``ElfFile\\0``, chunk magic ``ElfChnk\\0``
    (zjištěno na ground-truth disku — všech 199 souborů)

Struktura::

    File header (proměnná, min 128 B):
        @0x00  magic (4-8 B)
        @0x20  u32 file_header_size
        @0x24  u16 major_version
        @0x26  u16 minor_version

    Chunks (64 KB = 0x10000):
        Chunk header (proměnná, min 128 B):
            @+0x00  chunk magic (4-8 B)
            @+0x08  u32 chunk_number
            @+0x28  u32 chunk_header_size
        Records (od chunk_start + header_size):
            Record header:
                @+0x00  u16 header_size
                @+0x02  u16 record_number
                @+0x04  u32 reserved
                @+0x08  u64 timestamp (FILETIME)
                @+0x10  u64 event_record_id
            BinXML payload (po headeru)

Artifact type: ``event_log_entry`` (AXIOM ``Magnet.Artifacts.Windows.EventLog``)
"""

from __future__ import annotations

import logging
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# File magic varianty
EVTX_MAGIC_STANDARD = b"EVTX"
EVTX_MAGIC_ELF = b"ElfFile\x00"

# Chunk magic varianty
CHUNK_MAGIC_STANDARD = b"CHUN"
CHUNK_MAGIC_ELF = b"ElfChnk\x00"

# Chunk size (64 KB)
CHUNK_SIZE = 0x10000


@dataclass
class EventLogEntry:
    """Jeden záznam z event logu."""

    record_number: int = 0
    timestamp: datetime | None = None
    event_id: int | None = None
    provider: str = ""
    message: str = ""
    level: str = ""


@dataclass
class EvtxFileData:
    """Celý EVTX soubor — metadata + seznam záznamů."""

    magic: bytes = b""
    is_elf_variant: bool = False
    file_header_size: int = 128
    chunk_count: int = 0
    entries: list[EventLogEntry] = field(default_factory=list)


def _filetime_to_dt(value: int) -> datetime | None:
    """Konvertuje FILETIME (u64 100ns od 1601) na datetime."""
    if value <= 0 or value > 10**18:
        return None
    try:
        unix_ts = (value - 116_444_736_000_000_000) / 10_000_000
        if unix_ts < 946_684_800 or unix_ts > 4_102_444_800:  # 2000-2100
            return None
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _extract_binxml_strings(payload: bytes) -> dict[str, str]:
    """Extrahuje klíčová pole z BinXML payloadu (heuristicky).

    BinXML (MS-BINL) není text — element jména i hodnoty jsou v string tabulce /
    binárních sekcích. Heuristika: dekódovat UTF-16LE a hledat známé markery.
      - EventID → číslo události (užší regex, jen control znaky mezi)
      - Provider → nejdelší "name-like" token (bez mezer, s - nebo .)
      - Message → nejdelší tisknutelný řetězec ≥30 B (ne URL, ne provider)

    Level se NEextrahuje — v BinXML je to enum číslo, text 'Error' ve string
    tabulce dává falešné kladivo.
    """
    result: dict[str, str] = {}

    try:
        text = payload.decode("utf-16-le", errors="replace")
    except Exception:  # noqa: BLE001
        return result

    m = re.search(r"EventID[\x00-\x1f\x7f]{0,4}(\d{1,5})", text)
    if m:
        result["event_id"] = m.group(1)

    # Provider — prioritizuj jednoznačné Windows provider vzorce (BinXML string
    # tabulka sdílí element jména i hodnoty, takže "nejdelší token" chytá
    # počítačová jména / pole). Řád preferencí:
    #   1. Microsoft-Windows-* / Microsoft.*  (nejjednoznačnější)
    #   2. .NET-style typ s tečkou (např. NVDisplay.ContainerLocalSystem)
    #   3. ostatní name-like tokeny (bez mezer, ne v known_elements)
    runs = re.findall(r"[\x20-\x7E]{4,}", text)
    known_elements = {
        "Event", "System", "Provider", "Name", "EventID", "Version", "Task",
        "Keywords", "SystemTime", "EventRecordID", "TimeCreated", "Channel",
        "Correlation", "Execution", "ProcessId", "ThreadId", "Opcode", "Level",
        "Message", "EventLog", "Qualifier", "Qualifiers", "xmlns", "ActivityID",
        "Related", "Identity", "Domain", "Sid", "Subject", "Object", "Data",
        "Value", "ProcessID", "ThreadID", "CorrelationID", "PackageID",
        "ProviderName", "EventData", "EventUserData", "SystemProperties",
        "UserData", "Computer", "Security", "RelatedActivityID", "Keyword",
        "UserID", "LogonID", "SessionID", "Binary", "Guid", "ServiceName",
    }
    name_like = [
        r for r in runs
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9._\-]*", r) and r not in known_elements
    ]

    ms_win = [r for r in name_like if r.startswith(("Microsoft-Windows-", "Microsoft."))]
    if ms_win:
        result["provider"] = max(ms_win, key=len)
    else:
        dotted = [
            r for r in name_like
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9_.\-]*", r)
        ]
        if dotted:
            result["provider"] = max(dotted, key=len)

    # Message — nejdelší tisknutelný řetězec ≥30 B (ne URL, ne provider)
    prov = result.get("provider", "")
    candidates = [
        r for r in runs
        if len(r) >= 30 and not r.startswith("http") and r != prov
    ]
    if candidates:
        result["message"] = max(candidates, key=len)[:500]

    return result


def _find_chunks(data: bytes) -> list[int]:
    """Najde offsety všech chunků v souboru (scan po magice)."""
    elf_offsets: list[int] = []
    off = 0
    while True:
        idx = data.find(CHUNK_MAGIC_ELF, off)
        if idx == -1:
            break
        elf_offsets.append(idx)
        off = idx + 8

    if elf_offsets:
        return elf_offsets

    std_offsets: list[int] = []
    off = 0
    while True:
        idx = data.find(CHUNK_MAGIC_STANDARD, off)
        if idx == -1:
            break
        std_offsets.append(idx)
        off = idx + 4

    return std_offsets


def _parse_records_in_chunk(
    data: bytes, chunk_start: int, chunk_header_size: int
) -> list[EventLogEntry]:
    """Parsuje records v jednom chunku.

    Primární strategie — content-scan: najde UTF-16LE ``EventID`` markery a
    extrahuje okolní BinXML (nezávislé na přesném header layoutu — funguje pro
    ElfFile variantu i standardní EVTX, kde je element jméno v string tabulce).

    Fallback — header-based walk (MS-EVLOG layout): použije se jen když markery
    nenajde (např. komprimovaný BinXML payload bez textových jmen).
    """
    chunk_end = min(chunk_start + CHUNK_SIZE, len(data))
    markers = _count_eventid_markers(data, chunk_start, chunk_end)

    if markers > 0:
        # Markery existují → content-scan je autoritativní (i když vrátí [],
        # protože všechny záznamy selhaly filtrem — header-scan by v BinXML
        # datech našel falešné "records").
        return _content_scan(data, chunk_start)

    entries = _header_scan(data, chunk_start, chunk_header_size)
    if entries:
        logger.debug("EVTX header-scan (bez markerů): %d záznamů", len(entries))
    return entries


def _count_eventid_markers(data: bytes, start: int, end: int) -> int:
    """Počet UTF-16LE ``EventID`` markerů v rozsahu (≈ počet reálných záznamů)."""
    needle = "EventID".encode("utf-16-le")
    count = 0
    off = start
    while True:
        idx = data.find(needle, off, end)
        if idx == -1:
            break
        count += 1
        off = idx + len(needle)
    return count


def _header_scan(
    data: bytes, chunk_start: int, chunk_header_size: int
) -> list[EventLogEntry]:
    """Strategie 1 — postupný walk přes record hlavičky (MS-EVLOG layout).

    Standardní MS-EVLOG record header::

        @+0x00  u32 total_record_size
        @+0x04  u16 header_size (= 0x28)
        @+0x06  u16 record_number
        @+0x08  u32 reserved
        @+0x0C  u64 timestamp (FILETIME)
        @+0x14  u64 event_record_id
    """
    entries: list[EventLogEntry] = []
    records_start = chunk_start + chunk_header_size
    chunk_end = min(chunk_start + CHUNK_SIZE, len(data))

    off = records_start
    while off + 24 <= chunk_end:
        total_size, header_size, record_number = struct.unpack_from(
            "<IHH", data, off
        )

        # Validace: header_size typicky 0x28 (40), total_size v rozumném rozsahu
        if not (32 <= header_size <= 512):
            off += 2
            continue
        if not (header_size + 8 <= total_size <= CHUNK_SIZE) or off + total_size > chunk_end:
            off += 2
            continue

        timestamp_ft, _event_record_id = struct.unpack_from("<QQ", data, off + 0x0C)
        ts_dt = _filetime_to_dt(timestamp_ft)

        if ts_dt is None:
            off += 2
            continue

        payload_start = off + header_size
        payload_end = min(off + total_size, chunk_end)
        payload = data[payload_start:payload_end]

        xml_data = _extract_binxml_strings(payload)

        entry = EventLogEntry(
            record_number=record_number,
            timestamp=ts_dt,
            event_id=int(xml_data["event_id"]) if xml_data.get("event_id") else None,
            provider=xml_data.get("provider", ""),
            message=xml_data.get("message", ""),
            level=xml_data.get("level", ""),
        )
        entries.append(entry)

        off += total_size

    return entries


def _content_scan(data: bytes, chunk_start: int) -> list[EventLogEntry]:
    """Strategie 2 — najde UTF-16LE ``EventID`` markery a extrahuje BinXML.

    Nezávislé na přesném record header layoutu — funguje i pro ElfFile variantu,
    kde je hlavička odlišná. Každý marker = jeden záznam.

    ElfFile varianta používá **sdílenou string tabulku na úrovni chunku**
    (element jména + hodnoty jsou jednou v chunk headeru, records jen odkazují) —
    proto se BinXML extrahuje z celého chunku a sdílí se mezi všechny záznamy.
    """
    entries: list[EventLogEntry] = []
    chunk_end = min(chunk_start + CHUNK_SIZE, len(data))
    needle = "EventID".encode("utf-16-le")

    # Kontext celého chunku (sdílená string tabulka ElfFile varianty)
    chunk_context = _extract_binxml_strings(data[chunk_start:chunk_end])

    off = chunk_start
    while True:
        idx = data.find(needle, off, chunk_end)
        if idx == -1:
            break

        # Lokální payload okolo markera (standardní EVTX — BinXML je v recordu)
        local_start = max(chunk_start, idx - 256)
        local_end = min(idx + 4096, chunk_end)
        local_data = _extract_binxml_strings(data[local_start:local_end])

        # Sloučení: lokální data mají přednost (jsou specifická pro záznam),
        # chybějící pole doplní chunk kontext.
        xml_data = {**chunk_context, **{k: v for k, v in local_data.items() if v}}

        entry = EventLogEntry(
            record_number=len(entries) + 1,
            timestamp=None,
            event_id=int(xml_data["event_id"]) if xml_data.get("event_id") else None,
            provider=xml_data.get("provider", ""),
            message=xml_data.get("message", ""),
            level=xml_data.get("level", ""),
        )
        entries.append(entry)
        off = idx + len(needle)

    return entries


def parse_evtx_file(data: bytes) -> EvtxFileData:
    """Čistý parser — parsuje EVTX soubor a vrací strukturovaná data.

    Podporuje obě varianty (standardní EVTX + ElfFile).

    Raises:
        ValueError: Neplatný formát nebo příliš krátký soubor.
    """
    if len(data) < 128:
        raise ValueError(f"EVTX soubor příliš krátký: {len(data)} B (min 128)")

    is_elf = data.startswith(EVTX_MAGIC_ELF)
    is_standard = data[:4] == EVTX_MAGIC_STANDARD
    if not is_elf and not is_standard:
        raise ValueError(
            f"Neznámá EVTX magic: {data[:8]!r} (očekáváno 'EVTX' nebo 'ElfFile\\0')"
        )

    file_header_size, = struct.unpack_from("<I", data, 0x20)
    if not (64 <= file_header_size <= 1024):
        file_header_size = 128

    result = EvtxFileData(
        magic=data[:8],
        is_elf_variant=is_elf,
        file_header_size=file_header_size,
    )

    chunks = _find_chunks(data)
    result.chunk_count = len(chunks)

    if not chunks:
        logger.debug("EVTX: žádné chunky nalezeny")
        return result

    for chunk_start in chunks:
        if chunk_start + 0x30 <= len(data):
            chunk_header_size, = struct.unpack_from("<I", data, chunk_start + 0x28)
            if not (64 <= chunk_header_size <= 1024):
                chunk_header_size = 128
        else:
            chunk_header_size = 128

        entries = _parse_records_in_chunk(data, chunk_start, chunk_header_size)
        result.entries.extend(entries)

    logger.debug(
        "EVTX: %d záznamů v %d chunkách (varianta: %s)",
        len(result.entries),
        result.chunk_count,
        "ElfFile" if is_elf else "standard",
    )
    return result


def build_evtx_artifacts(parsed: EvtxFileData) -> list[Artifact]:
    """ČISTÁ funkce: z EvtxFileData vytvoří artifacty.

    Záznam se vynechá jen když nemá NIC (žádný timestamp, message, event_id ani
    provider) — ElfFile varianta nemá textové timestamps, takže by přísnější
    filtr zahodil většinu reálných událostí.
    """
    artifacts: list[Artifact] = []
    for e in parsed.entries:
        if e.timestamp is None and not e.message and e.event_id is None and not e.provider:
            continue

        details: dict[str, Any] = {
            "engine": "evtx",
            "record_number": e.record_number,
            "variant": "elf" if parsed.is_elf_variant else "standard",
        }
        if e.event_id is not None:
            details["event_id"] = e.event_id
        if e.provider:
            details["provider"] = e.provider
        if e.level:
            details["level"] = e.level

        title_parts: list[str] = []
        if e.provider:
            title_parts.append(e.provider)
        if e.event_id is not None:
            title_parts.append(f"ID {e.event_id}")
        if e.message and len(title_parts) == 0:
            title_parts.append(e.message[:80])

        title = " ".join(title_parts) or f"EventLog record #{e.record_number}"

        artifacts.append(
            Artifact(
                artifact_type="event_log_entry",
                timestamp=e.timestamp,
                title=title,
                details=details,
                confidence=0.85 if e.message else 0.6,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_evtx_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — parsoje .evtx soubor a vrátí artefakty."""
    try:
        data = path.read_bytes()
        parsed = parse_evtx_file(data)
        return build_evtx_artifacts(parsed)
    except FileNotFoundError:
        logger.warning("EVTX soubor nenalezen: %s", path)
        return []
    except ValueError as exc:
        logger.error("Chyba při parsingu EVTX %s: %s", path, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Neočekávaná chyba při parsingu EVTX %s: %s", path, exc)
        return []
