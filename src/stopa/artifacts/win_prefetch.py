"""MS-PREFETCH (MAM) parser — Windows SuperFetch .pf soubory.

Formát: MAM (Modern Application Metadata), verze 30-variant-2 / 31.
Struktura:
  - 8 B header: magic "MAM\\x04" + u32 uncompressed_size
  - LZXPRESS Huffman komprimovaný payload (MS-XCA §2.2.4)

Dekomprimovaný payload:
  @0   u32 version (31 = Win11, 30 = Win10)
  @4   "SCCA" (4 B ASCII)
  @8   u32 unknown
  @12  u32 filename_string_size (v charách)
  @16  UTF-16LE filename (fixed 60 B slot, null-padded)
  @76  ...padding/unknown...
  @84  file_information (scca_file_information_v30_2):
       +0   u32 metrics_array_offset
       +4   u32 n_metrics_entries
       +8   u32 trace_chain_array_offset
       +12  u32 n_trace_chains
       +16  u32 filename_strings_offset
       +20  u32 filename_strings_size
       +24  u32 volumes_information_offset
       +28  u32 n_volumes
       +32  u32 volumes_info_size
       +36  8 B unknown
       +44  8×FILETIME last_run_times (64 B)
       +108 8 B unknown
       +116 u32 run_count

Volume entry:
  @+0   u32 device_path_string_offset (relativní k volume entry startu)
  @+4   u32 n_chars (device path, UTF-16LE)
  @+8   FILETIME created_time
  @+16  u32 volume_serial_number

Ověřeno byte-for-byte na 286 reálných .pf souborech z Windows 11 image.
LZXPRESS Huffman port: SecurityRonin/xpress-huffman (Rust) → Python.
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.win_prefetch")

PARSER_VERSION = "1.0"

MAM_MAGIC = b"MAM\x04"
SCCA_SIGNATURE = b"SCCA"
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

# LZXPRESS Huffman konstanty (MS-XCA §2.2.4)
_TABLE_LEN = 256  # 512 symbolů × 4-bit code lengths
_BLOCK_SIZE = 1 << 16  # každý blok dekóduje max 64 KiB


def _filetime_to_iso(ft: int) -> str | None:
    """FILETIME (100-ns ticks od 1601) → ISO 8601 UTC."""
    if ft <= 0 or ft > 0x7FFFFFFFFFFFFFFF:
        return None
    try:
        dt = FILETIME_EPOCH + timedelta(microseconds=ft // 10)
        return dt.isoformat()
    except OverflowError:
        return None


# ──────────────────────────────────────────────────────────────────────
# LZXPRESS Huffman dekomprese (MS-XCA §2.2.4)
# Port z SecurityRonin/xpress-huffman (Rust), ověřeno byte-for-byte.
# ──────────────────────────────────────────────────────────────────────


class XpressHuffmanError(ValueError):
    """Chyba LZXPRESS Huffman dekomprese."""


def _build_tree(buf: bytes) -> list[list]:
    """Kanonickej Huffman decode tree z 256 B code-length tabulky.

    Vrací seznam uzlů [left_child, right_child, symbol|None].
    """
    NONE = -1
    nodes: list[list] = [[NONE, NONE, None]] * 1024
    symbols: list[tuple[int, int]] = []
    for i in range(_TABLE_LEN):
        c = buf[i]
        symbols.append((c & 0x0F, i * 2))
        symbols.append((c >> 4, i * 2 + 1))
    symbols.sort()

    start = 0
    while start < len(symbols) and symbols[start][0] == 0:
        start += 1

    mask = 0
    bits = 1
    tree_index = 1

    for length, symbol in symbols[start : start + 512]:
        if tree_index >= 1024:
            raise XpressHuffmanError("invalid Huffman table (over-subscribed)")
        nodes[tree_index] = [NONE, NONE, symbol]
        shift = length - bits
        if shift > 0:
            mask = (mask << shift) & 0xFFFFFFFF
        elif shift < 0:
            mask >>= (-shift) & 31
        bits = length
        # add_leaf
        cur = 0
        i = tree_index + 1
        b = bits
        while b > 1:
            b -= 1
            childidx = (mask >> b) & 1
            if nodes[cur][childidx] == NONE:
                if i >= 1024:
                    raise XpressHuffmanError("invalid Huffman table (arena overflow)")
                nodes[i] = [NONE, NONE, None]
                nodes[cur][childidx] = i
                i += 1
            cur = nodes[cur][childidx]
        if i >= 1024:
            raise XpressHuffmanError("invalid Huffman table (arena overflow)")
        nodes[cur][mask & 1] = tree_index
        tree_index = i
        mask = (mask + 1) & 0xFFFFFFFF

    return nodes


class _BitStream:
    """32-bit okno, refill po 16 bitech LE; byte kurzor sdílen s extended reads."""

    __slots__ = ("bits", "data", "mask", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.mask = 0
        self.bits = 0

    def read16(self) -> int:
        avail = max(0, len(self.data) - self.pos)
        if avail == 0:
            v = 0
        elif avail == 1:
            v = (self.data[self.pos] << 8) & 0xFFFFFFFF
        else:
            v = self.data[self.pos] | (self.data[self.pos + 1] << 8)
        self.pos += min(avail, 2)
        return v

    def init(self) -> None:
        self.mask = ((self.read16() << 16) + self.read16()) & 0xFFFFFFFF
        self.bits = 32

    def lookup(self, n: int) -> int:
        if n == 0:
            return 0
        return (self.mask >> (32 - n)) & ((1 << n) - 1)

    def skip(self, n: int) -> None:
        self.mask = (self.mask << n) & 0xFFFFFFFF
        self.bits -= n
        if self.bits < 16:
            self.mask = (self.mask + (self.read16() << (16 - self.bits))) & 0xFFFFFFFF
            self.bits += 16

    def read_byte(self) -> int:
        b = self.data[self.pos] if self.pos < len(self.data) else 0
        self.pos += 1
        return b

    def match_length(self, nibble: int) -> int:
        length = nibble
        if length == 15:
            length = self.read_byte() + 15
            if length == 270:
                length = self.read16()
        return length + 3

    def decode(self, nodes: list) -> int:
        node = 0
        while nodes[node][2] is None:
            bit = self.lookup(1)
            self.skip(1)
            nxt = nodes[node][bit]
            if nxt == -1:
                return 0
            node = nxt
        return nodes[node][2]


def xpress_huffman_decompress(compressed: bytes, decompressed_size: int) -> bytes:
    """Dekomprimuje LZXPRESS Huffman stream do `decompressed_size` bajtů."""
    dst = bytearray()
    bs = _BitStream(compressed)

    while bs.pos < len(compressed) and len(dst) < decompressed_size:
        table = compressed[bs.pos : bs.pos + _TABLE_LEN]
        if len(table) < _TABLE_LEN:
            raise XpressHuffmanError("truncated Huffman table")
        tree = _build_tree(table)
        bs.pos += _TABLE_LEN
        bs.init()

        produced = 0
        while produced < _BLOCK_SIZE and len(dst) < decompressed_size:
            # Pravý EOF: žádné souborové byty zbývají a v okně je méně než
            # 8 bitů (1 symbol). Bez této kontroly by podmínka `bs.pos < len`
            # ukončila blok příliš brzy — init() načte 32-bit okno, takže na
            # konci streamu zbývá v okně až 31 bitů (≤3 symboly), které se
            # jinak ztratí. Reálné MAM soubory mají za payloadem padding,
            # proto je bug viditelný jen u přesně ukončených syntetických streamů.
            if bs.pos >= len(compressed) and bs.bits < 8:
                break
            symbol = bs.decode(tree)
            if symbol < 256:
                dst.append(symbol)
                produced += 1
                continue
            sym = symbol - 256
            offset_bits = (sym >> 4) & 0x0F
            offset = (1 << offset_bits) + bs.lookup(offset_bits)
            length = bs.match_length(sym & 0x0F)
            bs.skip(offset_bits)

            if offset == 0 or offset > len(dst):
                raise XpressHuffmanError("bad match offset")
            remaining = length
            while remaining > 0:
                n = min(remaining, offset)
                start = len(dst) - offset
                dst.extend(dst[start : start + n])
                remaining -= n
            produced += length

    return bytes(dst[:decompressed_size])


# ──────────────────────────────────────────────────────────────────────
# Hlavní parser
# ──────────────────────────────────────────────────────────────────────


def is_mam_prefetch(data: bytes) -> bool:
    """Detekuje MAM prefetch soubor podle magiky."""
    return data[:4] == MAM_MAGIC


def parse_prefetch(data: bytes) -> dict | None:
    """Parsoje MAM .pf soubor.

    Returns:
        Dict s klíči: program, version, run_count, last_run_times,
        volume_serial, device_path, n_metrics, loaded_files.
        Nebo None při selhání.
    """
    if len(data) < 8 or data[:4] != MAM_MAGIC:
        return None

    uncompressed_size = struct.unpack_from("<I", data, 4)[0]
    compressed = data[8:]

    try:
        plain = xpress_huffman_decompress(compressed, uncompressed_size)
    except XpressHuffmanError as e:
        log.debug("LZXPRESS decompress failed: %s", e)
        return None

    if len(plain) < 84:
        return None

    version = struct.unpack_from("<I", plain, 0)[0]
    if plain[4:8] != SCCA_SIGNATURE:
        log.debug("missing SCCA signature at @4")
        return None

    # Filename (UTF-16LE, fixed 60 B slot od @16)
    name_raw = plain[16:76]
    program_name = name_raw.decode("utf-16-le", "replace").rstrip("\x00")

    # File information @84
    fi = plain[84:]
    if len(fi) < 120:
        return None

    n_metrics = struct.unpack_from("<I", fi, 4)[0]
    fname_str_off = struct.unpack_from("<I", fi, 16)[0]
    fname_str_size = struct.unpack_from("<I", fi, 20)[0]
    vol_off = struct.unpack_from("<I", fi, 24)[0]
    n_vols = struct.unpack_from("<I", fi, 28)[0]

    # Last run times (8 × FILETIME @ fi+44)
    last_runs: list[str] = []
    for i in range(8):
        ft_val = struct.unpack_from("<Q", fi, 44 + 8 * i)[0]
        iso = _filetime_to_iso(ft_val)
        if iso:
            last_runs.append(iso)

    # Run count @ fi+116 (v30_2 layout — potvrzené z libscca zdrojového kódu)
    run_count = struct.unpack_from("<I", fi, 116)[0]

    # Volume info
    volume_serial: int | None = None
    device_path: str | None = None
    if 0 < vol_off < len(plain) and n_vols > 0:
        ve = plain[vol_off:]
        if len(ve) >= 20:
            dev_str_off = struct.unpack_from("<I", ve, 0)[0]
            n_chars = struct.unpack_from("<I", ve, 4)[0]
            volume_serial = struct.unpack_from("<I", ve, 16)[0]

            if 0 < dev_str_off and n_chars > 0:
                spos = dev_str_off
                if spos + n_chars * 2 <= len(ve):
                    device_path = (
                        ve[spos : spos + n_chars * 2].decode("utf-16-le", "replace").rstrip("\x00")
                    )

    # Loaded files (z filename strings) — defenzivně
    loaded_files: list[str] = []
    if 0 < fname_str_off and fname_str_size > 0:
        fs_start = fname_str_off
        fs_end = min(fs_start + fname_str_size, len(plain))
        fs_data = plain[fs_start:fs_end]
        loaded_files = _iter_utf16_strings(fs_data)

    return {
        "program": program_name,
        "version": version,
        "run_count": run_count,
        "last_run_times": last_runs,
        "volume_serial": volume_serial,
        "device_path": device_path,
        "n_metrics": n_metrics,
        "loaded_files": loaded_files[:50],
    }


def _iter_utf16_strings(data: bytes) -> list[str]:
    """Extrahuje null-terminated UTF-16LE stringy z binárního bufferu."""
    results: list[str] = []
    i = 0
    while i + 2 <= len(data):
        ch = struct.unpack_from("<H", data, i)[0]
        if 32 <= ch < 127 or ch > 0x400:
            end = i
            while end + 2 <= len(data):
                c = struct.unpack_from("<H", data, end)[0]
                if c == 0:
                    break
                end += 2
            length = (end - i) // 2
            if length >= 3:
                s = data[i:end].decode("utf-16-le", "replace")
                results.append(s)
                i = end + 2
            else:
                i += 2
        else:
            i += 2
    return results


def build_prefetch_artifacts(path: Path, parsed: dict) -> list[Artifact]:
    """Vytvoří Artifact záznamy z parsovaného .pf souboru."""
    arts: list[Artifact] = []
    program = parsed.get("program", "")

    details: dict = {
        "run_count": parsed.get("run_count"),
        "last_run_times": parsed.get("last_run_times", []),
        "volume_serial": (
            f"0x{parsed['volume_serial']:08X}" if parsed.get("volume_serial") else None
        ),
        "device_path": parsed.get("device_path"),
        "n_loaded_files": len(parsed.get("loaded_files", [])),
        "loaded_files_sample": parsed.get("loaded_files", [])[:10],
    }

    last_runs = parsed.get("last_run_times", [])
    ts_str = last_runs[0] if last_runs else None
    ts: datetime | None = None
    if ts_str:
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            pass

    arts.append(
        Artifact(
            artifact_type="win_prefetch",
            timestamp=ts,
            title=f"Prefetch: {program} (run_count={parsed.get('run_count', '?')})",
            details=details,
            parser_version=PARSER_VERSION,
        )
    )

    return arts


def extract_prefetch_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — parsoje .pf soubor a vrátí artefakty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        log.warning("Prefetch read %s: %s", path, e)
        return []

    parsed = parse_prefetch(data)
    if parsed is None:
        return []

    try:
        return build_prefetch_artifacts(path, parsed)
    except Exception as e:  # noqa: BLE001 — defenzivní
        log.warning("Prefetch extract %s: %s", path, e)
        return []
