"""Windows Jump Lists parser — .customDestinations-ms kontejnery.

Formát: custom binární kontejner (NE OLE2) pod
`%AppData%\\Microsoft\\Windows\\Recent\\CustomDestinations\\`.

Struktura (empiricky ověřeno na 16 reálných souborech z Win11 image):
  - 20 B container header: u32 version (=2), u32 unknown, ...
  - N× entry: vložený MS-LNK soubor (cbLinkHeaderSize=76 + CLSID {00021401-...})

Detekce embedded LNK: sken po `4c 00 00 00` (cbLinkHeaderSize=76) následované
LNK CLSID na offsetu +4. Každý nalezený start je začátek jednoho entry;
entry končí na dalším LNK startu nebo konci souboru.

Každé entry se parsoje standardním `win_lnk.parse_lnk()` — cíl, relativní cesta,
název a FILETIME časové značky.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

from stopa.artifacts.win_lnk import parse_lnk
from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.win_jumplist")

PARSER_VERSION = "1.0"

# LNK CLSID {00021401-5CD6-101A-B86B-00AA003BA97C} — little-endian wire form
LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")
LNK_HEADER_SIZE = 76  # cbLinkHeaderSize — první u32 LNK souboru

MAX_ENTRIES_PER_LIST = 50


def is_jump_list_container(data: bytes) -> bool:
    """Detekuje Jump List kontejner (version=2 v prvních 4 bytech)."""
    if len(data) < 8:
        return False
    version = struct.unpack_from("<I", data, 0)[0]
    return version == 2


def is_jump_list_file(name: str) -> bool:
    """Detekce Jump List souboru podle názvu (case-insensitive).

    Magic bytes nestačí — kontejnerová hlavička je jen u32 version a koluje
    s jinými formáty. AXIOM Hunter pattern: detekce podle názvu souboru
    `.customDestinations-ms` (včetně variant s `-<hash>` příponou).
    """
    return name.lower().endswith(".customdestinations-ms") or (
        ".customdestinations-" in name.lower() and name.lower().endswith(".ms")
    )


def find_embedded_lnk_starts(data: bytes) -> list[int]:
    """Najde offsety všech embedded LNK souborů v kontejneru.

    Heuristika: `4c 00 00 00` (cbLinkHeaderSize=76) + LNK CLSID na +4,
    hledání od offsetu 16 (za container headerem).
    """
    starts: list[int] = []
    i = 16
    while True:
        j = data.find(b"\x4c\x00\x00\x00", i)
        if j < 0 or j + 20 > len(data):
            break
        if data[j + 4 : j + 20] == LNK_CLSID:
            starts.append(j)
        i = j + 1
    return starts


def parse_jump_list(data: bytes) -> list[dict]:
    """Parsoje Jump List kontejner → seznam entry (každé je výsledek parse_lnk).

    Returns:
        Seznam dictů z `parse_lnk()` pro každé embedded LNK entry.
        Prázdný seznam při selhání nebo bez entry.
    """
    if len(data) < 20 or not is_jump_list_container(data):
        return []

    starts = find_embedded_lnk_starts(data)
    entries: list[dict] = []
    for k, s in enumerate(starts[:MAX_ENTRIES_PER_LIST]):
        end = starts[k + 1] if k + 1 < len(starts) else len(data)
        chunk = data[s:end]
        try:
            parsed = parse_lnk(chunk)
        except Exception as e:  # noqa: BLE001 — jedno poškozené entry nesmí potopit list
            log.debug("JumpList LNK @%d parse failed: %s", s, e)
            continue
        if parsed is not None:
            entries.append(parsed)

    return entries


def build_jump_list_artifacts(path: Path, entries: list[dict]) -> list[Artifact]:
    """Vytvoří Artifact záznamy pro každé Jump List entry."""
    arts: list[Artifact] = []
    # GUID je v názvu souboru (bez .customDestinations[-*].ms přípony)
    guid = path.name.split(".")[0]

    for idx, e in enumerate(entries):
        target = e.get("target_path") or e.get("relative_path") or ""
        name = e.get("name") or ""
        ts = _as_dt(e.get("access_time")) or _as_dt(e.get("write_time")) or _as_dt(
            e.get("creation_time")
        )

        title_parts = []
        if target:
            title_parts.append(target)
        elif name:
            title_parts.append(name)
        else:
            title_parts.append(f"entry #{idx}")

        arts.append(
            Artifact(
                artifact_type="win_jumplist",
                timestamp=ts,
                title=f"Jump List [{guid}]: {title_parts[0]}",
                details={
                    "jump_list_guid": guid,
                    "entry_index": idx,
                    "target_path": e.get("target_path"),
                    "relative_path": e.get("relative_path"),
                    "name": name or None,
                    "working_dir": e.get("working_dir"),
                    "command_line": e.get("command_line"),
                    "access_time": _iso_or_none(e.get("access_time")),
                    "write_time": _iso_or_none(e.get("write_time")),
                    "creation_time": _iso_or_none(e.get("creation_time")),
                },
                parser_version=PARSER_VERSION,
            )
        )

    return arts


def _as_dt(value):
    """datetime objekt nebo ISO string → datetime (None-safe)."""
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _iso_or_none(value) -> str | None:
    """datetime/ISO string → ISO 8601 string pro details JSON."""
    dt = _as_dt(value)
    return dt.isoformat() if dt else None


def extract_jump_list_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — parsoje Jump List kontejner a vrátí artefakty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        log.warning("JumpList read %s: %s", path, e)
        return []

    entries = parse_jump_list(data)
    if not entries:
        return []

    try:
        return build_jump_list_artifacts(path, entries)
    except Exception as e:  # noqa: BLE001 — defenzivní
        log.warning("JumpList extract %s: %s", path, e)
        return []
