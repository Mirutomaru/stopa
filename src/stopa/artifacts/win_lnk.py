"""Windows Shell Link (.LNK) extraktor — MS-LNK formát [MS-LNK].

AXIOM-style Windows artifact: každý soubor se signaturou `lnk` projde čistým
Python parserem. Hlavička 76 B (cbLinkHeaderSize@0, CLSID IShellLink@4,
dwLinkFlags@20, FILETIMEs@28/36/44) + volitelné bloky podle flags v kanonickém
pořadí: IDList → LinkInfo → LocalBasePath → RelativePath → Name → WorkingDir →
CommandLine → IconLocation.

**Encoding stringů** (ověřeno na reálných souborech):
- Path stringy (LocalBasePath, RelativePath, WorkingDir, CommandLine,
  IconLocation): null-terminated **ANSI/CP1252** (single-byte).
- **Name**: null-terminated **UTF-16LE** (WCHAR) — obsahuje diakritiku!
- Volume label v LinkInfo: UTF-16LE.
- SHITEMID abid v IDList: UTF-16LE.

**Robustní block walk**: reálné LNK soubory mají komplexní IDListy
(CLSID-based items, proměnná délka) → kanonický SHITEMID walk selhává.
Používáme hybridní přístup:
  1) Sken od @76 po první plausibilní ANSI path string (`[A-Z]:\\` nebo `%var%`)
     → to je LocalBasePath (flag 0x100) nebo RelativePath (flag 0x02).
  2) Od konce nalezeného stringu čteme zbývající bloky sekvenčně v kanonickém
     pořadí s korektním encodingem per pole.
  3) LinkInfo (volume serial/label) hledáme skenem po LSIN magic v rozsahu
     mezi @76 a začátkem prvního path stringu.

ČISTÁ funkce `parse_lnk()` pracuje nad bajty — testy nepotřebují IO.
IO je jen v `extract_lnk_artifacts()`. Chyby → log + prázdný výsledek, nikdy ne výjimka.
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.lnk")

# E1: verze parseru — eviduje se v audit logu (reprodukovatelnost analýzy)
PARSER_VERSION = "2.0"

HEADER_SIZE = 76  # cbLinkHeaderSize — hlavička končí za Reserved1, bloky od @76

# IShellLink CLSID {00021401-0000-0000-C000-000000000046} (little-endian storage)
_ISHELLLINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")

# LinkFlags (MS-LNK §2.1) — ověřeno na reálných souborech
HAS_LINKINFO = 0x0001
HAS_RELATIVE_PATH = 0x0002
HAS_NAME = 0x0004
HAS_WORKING_DIR = 0x0008
HAS_COMMAND_LINE = 0x0010
_HAS_ICON = 0x0020
_HAS_ICON_ENV = 0x0040
HAS_IDLIST = 0x0080
HAS_LOCAL_BASE_PATH = 0x0100

# FILETIME epocha — 100 ns intervaly od 1601-01-01 UTC
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def filetime_to_datetime(ft: int) -> datetime | None:
    """FILETIME (100 ns od 1601) → aware datetime UTC. 0/přetečení → None."""
    if ft <= 0 or ft > 0x7FFFFFFFFFFFFFFF:
        return None
    try:
        return _FILETIME_EPOCH + timedelta(microseconds=ft // 10)
    except OverflowError:
        return None


def _read_ansi_null(data: bytes, offset: int) -> tuple[str, int]:
    """Čte null-terminated ANSI (CP1252) string. Vrací ("", offset) pokud je garbage."""
    if offset >= len(data):
        return "", offset
    # Sanity: první byte musí být tisknutelný ASCII/CP1252 (ne kontrolní znak)
    first = data[offset]
    if first < 0x20 and first != 0x09:  # tab je OK, ostatní control chars ne
        return "", offset + 1
    end = data.find(b"\x00", offset)
    if end == -1:
        raw = data[offset:]
        return raw.decode("cp1252", errors="replace"), len(data)
    raw = data[offset:end]
    return raw.decode("cp1252", errors="replace"), end + 1


def _read_utf16_null(data: bytes, offset: int) -> tuple[str, int]:
    """Čte null-terminated UTF-16LE string. Vrací (text, nový_offset za nulou).

    Terminátor `\x00\x00` se hledá na **sudém** offsetu relativně k `offset` —
    jinak by ASCII poslední znak (high byte 0x00) + první terminátorová nula
    vytvořily falešný `\x00\x00` o 1 byte dřív a string ztratil poslední znak.
    """
    i = offset
    while i + 2 <= len(data):
        if data[i] == 0 and data[i + 1] == 0:
            raw = data[offset:i]
            return raw.decode("utf-16-le", errors="replace"), i + 2
        i += 2
    # bez terminátoru — dekóduj do konce (lichý byte doplnit nulou)
    raw = data[offset:]
    if len(raw) % 2:
        raw += b"\x00"
    return raw.decode("utf-16-le", errors="replace"), len(data)


def _looks_like_env_var(data: bytes, pos: int) -> bool:
    """Zkontroluje, že na `pos` je `%varname%` pattern (env var reference)."""
    close = data.find(b"%", pos + 1)
    if close == -1 or close > pos + 32:
        return False
    name_len = close - pos - 1
    if name_len < 1:
        return False
    for j in range(pos + 1, close):
        b = data[j]
        if not (32 <= b < 127 and (chr(b).isalnum() or b == ord("_"))):
            return False
    return True


def _scan_for_ansi_path(data: bytes, start: int, max_scan: int = 4096) -> tuple[int, str] | None:
    """Skenuje od `start` po první plausibilní ANSI Windows path string.

    Hledá pattern `[A-Z]:\\` nebo `%var%` na začátku null-terminated stringu.
    Vrací (offset_začátku, text) nebo None pokud nenalezeno.
    """
    end = min(start + max_scan, len(data))
    i = start
    while i < end:
        head3 = data[i : i + 3]
        if (
            head3 in (b"C:\\", b"D:\\", b"..\\")
            or data[i : i + 2] == b".\\"
            or (data[i : i + 1] == b"%" and _looks_like_env_var(data, i))
        ):
            nul = data.find(b"\x00", i)
            if nul != -1 and 3 < (nul - i) < 512:
                chunk = data[i:nul]
                if all(32 <= b < 127 for b in chunk):
                    text = chunk.decode("cp1252", errors="replace")
                    return i, text
        i += 1
    return None


def _find_linkinfo(data: bytes, start: int, end_limit: int) -> dict:
    """Najde a parsuje LinkInfo blok (scan po LSIN magic v rozsahu [start, end_limit)).

    Vrací dict s volume_serial/volume_label. Pokud nenalezeno → prázdné hodnoty.
    """
    info: dict = {"volume_serial": None, "volume_label": None}
    i = start
    while i + 12 <= min(end_limit, len(data)):
        if data[i : i + 4] == b"LSIN":
            size_of_header = struct.unpack_from("<I", data, i)[0]
            vol_flags = struct.unpack_from("<I", data, i + 8)[0]
            # Validace: size_of_header musí být rozumné (12..512)
            if 12 <= size_of_header <= 512 and i + size_of_header <= len(data):
                vi = i + size_of_header
                # VOLUME_ID_DOS (0x01): VolumeSerial(4)+CreationTime(8)+VolumeSize(8)=20B
                if vol_flags & 0x01 and vi + 20 <= len(data):
                    info["volume_serial"] = struct.unpack_from("<I", data, vi)[0]
                    vi += 20
                # VOLUME_ID_WIN32 (0x02): FileSystemType(4)+VolumeLabelLength(4)+label(UTF-16)
                if vol_flags & 0x02 and vi + 8 <= len(data):
                    _fs_type, label_len = struct.unpack_from("<II", data, vi)
                    vi += 8
                    if 0 < label_len <= 256 and vi + label_len * 2 <= len(data):
                        raw = data[vi : vi + label_len * 2]
                        text = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
                        info["volume_label"] = text or None
                return info
        i += 1
    return info


def parse_lnk(data: bytes) -> dict:
    """ČISTÁ funkce: parsuje MS-LNK bajty → dict polí.

    Vrací klíče: `target_path`, `relative_path`, `name`, `working_dir`,
    `command_line`, `icon_location`, `creation_time`, `access_time`,
    `write_time`, `file_size`, `volume_serial`, `volume_label`, `flags`.
    Volitelná pole = None pokud nejsou přítomna.

    Raises: ValueError při špatné signatuře / příliš krátkém souboru.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"LNK too short: {len(data)} B (min {HEADER_SIZE})")

    cb_header = struct.unpack_from("<I", data, 0)[0]
    # CLSID @4 musí být IShellLink — validace signatury
    if data[4:20] != _ISHELLLINK_CLSID:
        raise ValueError(f"bad LNK CLSID: {data[4:20].hex()}")

    flags = struct.unpack_from("<I", data, 20)[0] & 0xFFFF
    file_attributes = struct.unpack_from("<I", data, 24)[0]
    creation_ft, access_ft, write_ft = struct.unpack_from("<QQQ", data, 28)
    file_size = struct.unpack_from("<q", data, 52)[0]

    out: dict = {
        "flags": flags,
        "file_attributes": file_attributes,
        "creation_time": filetime_to_datetime(creation_ft),
        "access_time": filetime_to_datetime(access_ft),
        "write_time": filetime_to_datetime(write_ft),
        "file_size": file_size if 0 < file_size <= 0x7FFFFFFFFFFFFFFF else None,
        "target_path": None,
        "relative_path": None,
        "name": None,
        "working_dir": None,
        "command_line": None,
        "icon_location": None,
        "volume_serial": None,
        "volume_label": None,
    }

    blocks_start = cb_header if 0 < cb_header <= len(data) else HEADER_SIZE

    # ── Krok 1: Najdi první plausibilní ANSI path string (target/relative) ──
    first_path_result = _scan_for_ansi_path(data, blocks_start)
    if first_path_result is None:
        return out  # žádný path nalezen — jen hlavička

    first_path_offset, first_path_text = first_path_result

    # Urči, co je první path: LocalBasePath (0x100) nebo RelativePath (0x02)?
    if flags & HAS_LOCAL_BASE_PATH:
        out["target_path"] = first_path_text
    elif flags & HAS_RELATIVE_PATH:
        out["relative_path"] = first_path_text
    else:
        # Žádný z obou flagů — přesto to je cíl (neznámý typ)
        out["target_path"] = first_path_text

    # ── Krok 2: LinkInfo scan v rozsahu [blocks_start, first_path_offset) ──
    if flags & HAS_LINKINFO:
        vol_info = _find_linkinfo(data, blocks_start, first_path_offset)
        out["volume_serial"] = vol_info.get("volume_serial")
        out["volume_label"] = vol_info.get("volume_label")

    # ── Krok 3: Sekvenční čtení zbývajících bloků od konce prvního path ──
    # Offset za nulovým terminátorem prvního path stringu
    offset = first_path_offset + len(first_path_text.encode("cp1252", errors="replace")) + 1

    # Urči, které bloky ještě zbývají (v kanonickém pořadí [MS-LNK] §2.2)
    # Pořadí: LocalBasePath → RelativePath → Name(UTF-16LE!) → WorkingDir → CommandLine → IconLocation
    remaining_blocks: list[tuple[str, bool]] = []  # (key, is_utf16)

    # Pokud první path byl LocalBasePath a je i RelativePath → čti RELPATH
    if out["target_path"] and flags & HAS_RELATIVE_PATH:
        remaining_blocks.append(("relative_path", False))
    # Pokud první path byl RelativePath a je i LocalBasePath → čti LOCALBASE (málo časté)
    elif out["relative_path"] and flags & HAS_LOCAL_BASE_PATH:
        remaining_blocks.append(("target_path", False))

    if flags & HAS_NAME:
        remaining_blocks.append(("name", True))  # UTF-16LE!
    if flags & HAS_WORKING_DIR:
        remaining_blocks.append(("working_dir", False))
    if flags & HAS_COMMAND_LINE:
        remaining_blocks.append(("command_line", False))
    if flags & _HAS_ICON:
        remaining_blocks.append(("icon_location", False))

    for key, is_utf16 in remaining_blocks:
        if offset + 2 > len(data):
            break
        if is_utf16:
            # Stray null byte mezi ANSI a UTF-16LE sekcí (Windows quirk) —
            # pokud data[offset]==0x00 ale data[offset+1]!=0x00, není to
            # UTF-16LE null terminator (\x00\x00), jen padding → skip 1 B.
            if offset + 1 < len(data) and data[offset] == 0x00 and data[offset + 1] != 0x00:
                offset += 1
            text, offset = _read_utf16_null(data, offset)
        else:
            text, offset = _read_ansi_null(data, offset)
        out[key] = text or None

    return out


def build_lnk_artifacts(parsed: dict, rel_path: str | None = None) -> list[Artifact]:
    """ČISTÁ funkce: z parsed LNK dictu vytvoří artifacty.

    - `shell_link` — cíl + časy + volume (hlavní forenzní artifact)
    """
    target = (
        parsed.get("target_path")
        or parsed.get("relative_path")
        or "(neznámý cíl)"
    )
    vol = ""
    if parsed.get("volume_serial") is not None:
        vol = f", vol {parsed['volume_serial']:#010x}"
    label = f" [{parsed['volume_label']}]" if parsed.get("volume_label") else ""

    access_dt = parsed.get("access_time")
    write_dt = parsed.get("write_time")

    return [
        Artifact(
            artifact_type="shell_link",
            timestamp=parsed.get("creation_time"),
            title=f"LNK → {target}{vol}{label}",
            details={
                "target_path": parsed.get("target_path"),
                "relative_path": parsed.get("relative_path"),
                "name": parsed.get("name"),
                "working_dir": parsed.get("working_dir"),
                "command_line": parsed.get("command_line"),
                "icon_location": parsed.get("icon_location"),
                "file_size": parsed.get("file_size"),
                "volume_serial": parsed.get("volume_serial"),
                "volume_label": parsed.get("volume_label"),
                "access_time": access_dt.isoformat() if access_dt else None,
                "write_time": write_dt.isoformat() if write_dt else None,
                "rel_path": rel_path,
            },
        )
    ]


def extract_lnk_artifacts(path: Path) -> list[Artifact]:
    """Extrahuje artifacty z .LNK souboru. Vrací Artifacty BEZ source_id/file_id
    (ty doplní pipeline). Chyby → log + prázdný výsledek, nikdy ne výjimka."""
    try:
        data = path.read_bytes()
    except OSError as e:
        log.warning("LNK read %s: %s", path, e)
        return []
    try:
        parsed = parse_lnk(data)
    except (ValueError, struct.error) as e:
        log.warning("LNK parse %s: %s", path, e)
        return []
    try:
        return build_lnk_artifacts(parsed, rel_path=str(path))
    except Exception as e:  # noqa: BLE001 — defenzivní
        log.warning("LNK artifacts %s: %s", path, e)
        return []
