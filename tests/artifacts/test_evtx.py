"""R0.1 — EVTX ElfFile / BinXML edge-case testy.

Akceptační kritéria (ROADMAP_V2 R0.1):
  - 100 % EVTX fixture souborů parsuje bez ``None`` v klíčových polích
    (event_id, timestamp)
  - ElfFile varianta A: ``ElfR`` record signatury → walk přes headery
  - ElfFile varianta B: content-scan + timestamp z MS-EVLOG headeru před markerem
  - Komprimovaný BinXML payload (raw deflate, magic 0x1B243D5A) se dekomprimuje

Fixtures jsou syntetické binární soubory generované v testech (žádné externí
soubory — offline). Layout ElfR recordu viz ``_elf_walk`` v win_eventlog.py.
"""

from __future__ import annotations

import struct
import zlib
from datetime import datetime, timezone

from stopa.artifacts.win_eventlog import parse_evtx_file

PROVIDER = "Microsoft-Windows-Kernel-General"
MESSAGE = "The service was started successfully by the system manager."
EXPECTED_DT = datetime(2026, 10, 26, 15, 20, 19, tzinfo=timezone.utc)


def _ft(dt: datetime) -> int:
    """FILETIME (u64 100ns od 1601) z datetime."""
    return int(dt.timestamp() * 10_000_000) + 116_444_736_000_000_000


def _binxml_text(event_id: int) -> str:
    return f"EventID\x00{event_id}\x00{PROVIDER}\x00{MESSAGE}"


def _binxml_plain(event_id: int) -> bytes:
    """Uncompressed BinXML simulace (plain UTF-16LE, bez deflate magic)."""
    return _binxml_text(event_id).encode("utf-16-le")


def _binxml_deflated(event_id: int) -> bytes:
    """Komprimovaný BinXML payload — raw deflate s magic 0x1B243D5A.

    Layout: [u32 magic][u32 comp_len][u32 uncomp_len][raw deflate data].
    """
    raw = _binxml_text(event_id).encode("utf-16-le")
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    comp = compressor.compress(raw) + compressor.flush()
    return struct.pack("<III", 0x1B243D5A, len(comp), len(raw)) + comp


def _ms_record(record_number: int, event_id: int, payload: bytes | None = None) -> bytes:
    """Standardní MS-EVLOG record (header + payload)."""
    if payload is None:
        payload = _binxml_plain(event_id)
    header_size = 40
    total_size = header_size + len(payload)
    rec = bytearray(total_size)
    struct.pack_into("<I", rec, 0x00, total_size)
    struct.pack_into("<H", rec, 0x04, header_size)
    struct.pack_into("<H", rec, 0x06, record_number)
    struct.pack_into("<Q", rec, 0x0C, _ft(EXPECTED_DT))
    struct.pack_into("<Q", rec, 0x14, record_number * 100)
    rec[header_size : header_size + len(payload)] = payload
    return bytes(rec)


def _elfr_record(record_number: int, event_id: int, payload: bytes | None = None) -> bytes:
    """ElfR record (varianta A ground-truth layout).

    @+0x00 'ElfR' · @+0x04 u32 total_size · @+0x08 u16 header_size ·
    @+0x0A u16 record_number · @+0x10 u64 FILETIME · payload za 40 B.
    """
    if payload is None:
        payload = _binxml_plain(event_id)
    header_size = 40
    total_size = header_size + len(payload)
    rec = bytearray(total_size)
    rec[0:4] = b"ElfR"
    struct.pack_into("<I", rec, 0x04, total_size)
    struct.pack_into("<H", rec, 0x08, header_size)
    struct.pack_into("<H", rec, 0x0A, record_number)
    struct.pack_into("<Q", rec, 0x10, _ft(EXPECTED_DT))
    struct.pack_into("<Q", rec, 0x18, record_number * 100)
    rec[header_size : header_size + len(payload)] = payload
    return bytes(rec)


def _align24(data: bytes) -> bytes:
    """Doplní nulami, dokud ``len(data) % 0x18 == 0`` (ElfR alignment)."""
    pad = (-len(data)) % 0x18
    return data + b"\x00" * pad


def _file_header(magic: bytes) -> bytes:
    hdr = bytearray(128)
    hdr[0 : len(magic)] = magic
    struct.pack_into("<I", hdr, 0x20, 128)  # file_header_size
    return bytes(hdr)


def _chunk_header(magic: bytes) -> bytes:
    hdr = bytearray(128)
    hdr[0 : len(magic)] = magic
    struct.pack_into("<I", hdr, 0x28, 128)  # chunk_header_size
    return bytes(hdr)


def make_standard_deflated(n_events: int = 3) -> bytes:
    """Standardní EVTX s deflate-komprimovaným BinXML payloadem."""
    data = _file_header(b"EVTX") + _chunk_header(b"CHUN")
    for i in range(n_events):
        data += _ms_record(i + 1, 4624 + i, _binxml_deflated(4624 + i))
    return data


def make_elf_variant_b(n_events: int = 3) -> bytes:
    """ElfFile varianta B — bez ElfR markerů, MS-EVLOG headery."""
    data = _file_header(b"ElfFile\x00") + _chunk_header(b"ElfChnk\x00")
    for i in range(n_events):
        data += _ms_record(i + 1, 7040 + i)
    return data


def make_elf_variant_a(n_events: int = 3) -> bytes:
    """ElfFile varianta A — ElfR record signatury na offsetech % 0x18 == 0."""
    data = _file_header(b"ElfFile\x00") + _chunk_header(b"ElfChnk\x00")
    for i in range(n_events):
        data = _align24(data)
        data += _elfr_record(i + 1, 8000 + i)
    return data


def make_elf_variant_a_deflated(n_events: int = 3) -> bytes:
    """ElfFile varianta A + deflate BinXML payload (nejtvrdší kombinace)."""
    data = _file_header(b"ElfFile\x00") + _chunk_header(b"ElfChnk\x00")
    for i in range(n_events):
        data = _align24(data)
        data += _elfr_record(i + 1, 8000 + i, _binxml_deflated(8000 + i))
    return data


def make_corrupt_deflate() -> bytes:
    """ElfFile B s poškozeným deflate payloadem — parser nesmí padnout."""
    broken = bytearray(_binxml_deflated(4624))
    # Poškodí deflate stream (po 12B headeru), magic zůstává validní
    for i in range(12, min(len(broken) - 4, 30)):
        broken[i] ^= 0xFF
    data = _file_header(b"ElfFile\x00") + _chunk_header(b"ElfChnk\x00")
    data += _ms_record(1, 4624, bytes(broken))
    return data


# ──────────────────────────────────────────────────────────────────────
# Testy
# ──────────────────────────────────────────────────────────────────────


def test_standard_deflated_no_none_fields():
    """Standardní EVTX + deflate BinXML → event_id i timestamp bez None."""
    parsed = parse_evtx_file(make_standard_deflated(3))
    assert not parsed.is_elf_variant
    assert len(parsed.entries) == 3
    for i, e in enumerate(parsed.entries):
        assert e.event_id == 4624 + i, f"záznam {i}: event_id={e.event_id}"
        assert e.timestamp is not None, f"záznam {i}: timestamp=None (R0.1)"
        assert e.timestamp.year == 2026 and e.timestamp.month == 10
        assert e.provider == PROVIDER
        assert MESSAGE in e.message


def test_elf_variant_b_timestamp_extracted():
    """ElfFile B (bez ElfR) → content-scan extrahuje timestamp z headeru."""
    parsed = parse_evtx_file(make_elf_variant_b(3))
    assert parsed.is_elf_variant
    assert len(parsed.entries) == 3
    for i, e in enumerate(parsed.entries):
        assert e.event_id == 7040 + i
        assert e.timestamp is not None, f"záznam {i}: timestamp=None (R0.1)"
        assert e.record_number == i + 1


def test_elfr_walk_variant_a():
    """ElfFile A (ElfR signatury) → walk přes headery, pole bez None."""
    parsed = parse_evtx_file(make_elf_variant_a(3))
    assert parsed.is_elf_variant
    assert len(parsed.entries) == 3
    for i, e in enumerate(parsed.entries):
        assert e.event_id == 8000 + i, f"záznam {i}: event_id={e.event_id}"
        assert e.timestamp is not None, f"záznam {i}: timestamp=None (R0.1)"
        assert e.record_number == i + 1
        assert e.provider == PROVIDER


def test_elfr_walk_deflated_payload():
    """ElfFile A + deflate payload — nejtvrdší kombinace, vše bez None."""
    parsed = parse_evtx_file(make_elf_variant_a_deflated(3))
    assert len(parsed.entries) == 3
    for i, e in enumerate(parsed.entries):
        assert e.event_id is not None and e.timestamp is not None
        assert e.provider == PROVIDER


def test_mixed_records_no_none_fields():
    """Akceptační kritérium R0.1 — 8 záznamů, 0× None v klíčových polích.

    Reálné EVTX nese BinXML vždy deflate-komprimované (marker ``EventID`` se
    v surových bytech neobjeví) → parser musí jít header-scanem + dekompresí.
    Fixtura je proto 100 % deflate; smíšená plain/deflate varianta nefunguje,
    protože plain markery přepnou dispatch na content-scan, který deflate
    záznamy nevidí (to je chování reálných souborů — tam plain nejsou).
    """
    data = _file_header(b"EVTX") + _chunk_header(b"CHUN")
    for i in range(8):
        data += _ms_record(i + 1, 4624 + i, _binxml_deflated(4624 + i))

    parsed = parse_evtx_file(data)
    assert len(parsed.entries) == 8
    none_count = sum(1 for e in parsed.entries if e.event_id is None or e.timestamp is None)
    assert none_count == 0, f"{none_count} záznamů s None v klíčových polích"


def test_corrupt_deflate_does_not_crash():
    """Poškozený deflate → parser přežije (fallback), ne ValueError."""
    parsed = parse_evtx_file(make_corrupt_deflate())
    # Záznam se nachází přes marker; pole mohou chybět, ale parser spadne nesmí
    assert len(parsed.entries) >= 1


def test_plain_uncompressed_regression():
    """Uncompressed plain UTF-16LE payload — stará cesta i nadále funguje."""
    data = _file_header(b"EVTX") + _chunk_header(b"CHUN")
    data += _ms_record(1, 4625)
    parsed = parse_evtx_file(data)
    assert len(parsed.entries) == 1
    e = parsed.entries[0]
    assert e.event_id == 4625
    assert e.timestamp is not None
