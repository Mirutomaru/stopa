"""ETAPA B vlna 1 — Windows Clipboard registry parser.

AXIOM ekvivalent: ``ClipboardArtifact``.

Podporovaný formát: **NTUSER.DAT hive** — klíč
``Software\\Microsoft\\Windows\\CurrentVersion\\Clipboards`` obsahuje
podklíče podle clipboard formátu (jméno = hex ID, např. ``000D`` =
CF_UNICODETEXT) a každý má hodnotu ``Data`` s obsahem schránky.

Sekundární průchod vedle generic registry extraktoru (sdílená ``regf``
magic — pattern jako Amcache/ShimCache v pipeline). Detekce podle cesty
klíče; bez Clipboards klíče → prázdný výsledek.

Artifact type: ``clipboard_entry`` — jeden formát = jeden artifact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_CLIPBOARD_ENTRIES = 50
MAX_DATA_LEN = 2048  # nevtěsnávat obří schránku do detailů

# známé clipboard formáty (Windows CF_* konstanty) — jméno klíče je hex ID
KNOWN_CF_FORMATS: dict[str, str] = {
    "0001": "CF_TEXT",
    "0002": "CF_BITMAP",
    "0003": "CF_METAFILEPICT",
    "0004": "CF_SYLK",
    "0005": "CF_DIF",
    "0006": "CF_TIFF",
    "0007": "CF_OEMTEXT",
    "0008": "CF_DIB",
    "0009": "CF_PALETTE",
    "000A": "CF_PENDATA",
    "000B": "CF_RIFF",
    "000C": "CF_WAVE",
    "000D": "CF_UNICODETEXT",
    "0015": "CF_OWNERDISPLAY",
    "0016": "CF_DIBV5",
}


@dataclass
class ClipboardEntry:
    """Jeden záznam schránky — formát + obsah."""

    format_id: str = ""  # hex ID (jméno klíče)
    format_name: str = ""  # CF_* název, pokud známý
    data_text: str = ""
    is_binary: bool = False
    timestamp: datetime | None = None


def _printable_ratio(s: str) -> float:
    """Podíl tisknutelných znaků v řetězci (prázdný → 0.0)."""
    if not s:
        return 0.0
    sample = s[:64]
    return sum(c.isprintable() or c.isspace() for c in sample) / len(sample)


def _decode_value(value: Any) -> tuple[str, bool]:
    """Registry hodnota → (text, je_binární).

    REG_SZ/REG_EXPAND_SZ (str) → text; bytes → UTF-8 nebo UTF-16LE text
    (detekce podle tisknutelnosti dekodovaného výsledku), jinak hex preview.
    """
    if value is None:
        return "", False
    if isinstance(value, bytes):
        # 1) UTF-8 text — strict decode + >90% tisknutelných znaků
        try:
            s = value.decode("utf-8")
            if _printable_ratio(s) > 0.9:
                return s.strip(), False
        except (UnicodeDecodeError, UnicodeError):
            logger.debug("clipboard: UTF-8 decode selhal (%d B) → zkusím další kódování", len(value))
        # 2) UTF-16LE text — strict decode + >90% tisknutelných znaků
        if len(value) % 2 == 0:
            try:
                s = value.decode("utf-16-le")
                if _printable_ratio(s) > 0.9:
                    return s.strip(), False
            except (UnicodeDecodeError, UnicodeError):
                logger.debug("clipboard: UTF-16LE decode selhal (%d B) → hex preview", len(value))
        # 3) binární — hex preview
        return value.hex()[:MAX_DATA_LEN], True
    return str(value)[:MAX_DATA_LEN], False


def build_clipboard_artifacts(entries: list[ClipboardEntry]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů schránky vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for e in entries[:MAX_CLIPBOARD_ENTRIES]:
        fmt_label = e.format_name or f"CF_{e.format_id}"
        details: dict[str, Any] = {
            "engine": "clipboard",
            "format_id": e.format_id,
            "format": fmt_label,
        }
        if e.data_text:
            details["data"] = e.data_text[:MAX_DATA_LEN]
        if e.is_binary:
            details["binary_hex_preview"] = True

        artifacts.append(
            Artifact(
                artifact_type="clipboard_entry",
                timestamp=e.timestamp,
                title=f"Schránka: {fmt_label}",
                details=details,
                confidence=0.85 if e.data_text else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_clipboard_artifacts(path) -> list[Artifact]:
    """Pipeline entrypoint — NTUSER.DAT hive → clipboard_entry artifacty.

    Sekundární extraktor pro soubory pojmenované ``NTUSER.DAT`` (regf magic) —
    běží vedle generic registry extraktoru. Bez Clipboards klíče → prázdný výsledek.
    """
    from regipy.registry import RegistryHive  # type: ignore[import-untyped]

    try:
        hive = RegistryHive(hive_path=str(path))
    except FileNotFoundError:
        logger.warning("NTUSER.DAT hive nenalezena: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Chyba při otevírání NTUSER.DAT %s: %s", path, exc)
        return []

    entries: list[ClipboardEntry] = []
    for key in hive.recurse_subkeys():
        kpath = (key.path or "").lower().replace("/", "\\")
        # jen klíč Clipboards samotný — ne jeho podklíče (ty řeší 2. smyčka)
        if not kpath.endswith("currentversion\\clipboards"):
            continue
        # podklíč Clipboards — každý subkey je clipboard formát
        for val in key.values or []:
            name = getattr(val, "name", "") or ""
            if name.lower() == "(default)":
                continue
            data_text, is_binary = _decode_value(getattr(val, "value", None))
            entries.append(
                ClipboardEntry(
                    format_id=name.upper(),
                    format_name=KNOWN_CF_FORMATS.get(name.upper(), ""),
                    data_text=data_text[:MAX_DATA_LEN],
                    is_binary=is_binary,
                    timestamp=getattr(key, "timestamp", None),
                )
            )

    # alternativní struktura: Clipboards\\<format_id> podklíče s hodnotou Data
    if not entries:
        for key in hive.recurse_subkeys():
            kpath = (key.path or "").lower().replace("/", "\\")
            if "currentversion\\clipboards\\" not in kpath:
                continue
            fmt_id = kpath.rsplit("\\", 1)[-1].upper()
            for val in key.values or []:
                vname = getattr(val, "name", "") or ""
                if vname.lower() != "data":
                    continue
                data_text, is_binary = _decode_value(getattr(val, "value", None))
                entries.append(
                    ClipboardEntry(
                        format_id=fmt_id,
                        format_name=KNOWN_CF_FORMATS.get(fmt_id, ""),
                        data_text=data_text[:MAX_DATA_LEN],
                        is_binary=is_binary,
                        timestamp=getattr(key, "timestamp", None),
                    )
                )

    logger.debug("Clipboard %s: %d záznamů", path, len(entries))
    return build_clipboard_artifacts(entries)
