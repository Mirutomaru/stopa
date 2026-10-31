"""Apple iCloud Messages extraktor — cloud varianta iMessage (warrant return).

AXIOM `CloudAppleIMessageArtifact` / `Magnet.Artifacts.Cloud.Apple.IMessage.*`:
iCloud „Messages in iCloud“ sync export z Apple warrant/production returnu.
Soubor `[Apple_Request]-MESSAGESINICLOUD-[N].zip` obsahuje `MessagesInICloud.csv`,
který ve skutečnosti bývá XLSX (tabulka s metadatami nad hlavičkou) nebo
delimited text — magic bytes nestačí, detekce je podle NÁZVU souboru.

Formát (ground truth: RLEAPP `icloudMsgsInCloud.py`, Magnet blog):
- XLSX: openpyxl read_only, hlavička na prvním řádku s ≥2 známými sloupci
  (Apple export má nad ní metadata — pevný offset nefunguje univerzálně)
- delimited text: tab nebo comma, hlavička stejně detekována obsahem

Sloupce se mapují fuzzy (normalizace na lowercase alfanumeriku + aliasy),
protože Apple neudržuje stabilní schéma exportu. Časové hodnoty: datetime
objekt (openpyxl), ISO text nebo epoch číslo (heuristická konverze).

IO je jen v `extract_icloud_messages()`; parser a mapování jsou čisté funkce.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

from stopa.domain.times import detect_and_convert
from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.imessage_cloud")

# E1: verze parseru — eviduje se v audit logu (reprodukovatelnost analýzy)
PARSER_VERSION = "1.0"

# detekce podle názvu — AXIOM Hunter pattern (case-insensitive)
NAME_MARKER = "messagesinicloud"

MAX_HEADER_SCAN_ROWS = 15  # metadata řádky nad hlavičkou (Apple export)

# aliasy sloupců → normalizované (lowercase, jen alfanumerika)
_TEXT_ALIASES = ("text", "message", "body", "content")
_DATE_ALIASES = ("date", "timestamp", "time")
_DIRECTION_ALIASES = ("isfromme", "direction", "sender", "sentby")
_HANDLE_ALIASES = ("handle", "address", "recipient", "chatidentifier", "guid", "contact")

# ISO formáty, které Apple exporty skutečně používají
_ISO_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)


def is_icloud_messages_file(name: str) -> bool:
    """Detekce iCloud Messages exportu podle názvu souboru (case-insensitive).

    Magic bytes nestačí — XLSX je generic OOXML a delimited text žádnou
    signaturu nemá. AXIOM `CloudAppleIMessageArtifact` Hunter pracuje stejně.
    """
    return NAME_MARKER in name.lower()


def _normalize_header(cell: object) -> str:
    """Normalizace hlavičky — lowercase, jen alfanumerika ('IsFromMe' → 'isfromme')."""
    return "".join(ch for ch in str(cell).lower() if ch.isalnum())


def _find_column(headers: list[str], aliases: tuple[str, ...]) -> int | None:
    """Najde sloupec podle aliasů — nejdřív přesná shoda, pak substring."""
    norm = [_normalize_header(h) for h in headers]
    for alias in aliases:
        if alias in norm:
            return norm.index(alias)
    for alias in aliases:  # fallback: alias je podřetězec hlavičky (např. 'sentdate')
        for i, n in enumerate(norm):
            if n and alias in n:
                return i
    return None


def _parse_timestamp(value: object) -> datetime | None:
    """Časová hodnota exportu → aware UTC datetime; neznámý formát → None.

    openpyxl vrací datetime objekty (naivní → předpokládá se UTC), textové
    buňky ISO formáty, numerické epochy (sekundy/milisekundy) přes heuristiku.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # epoch číslo (unix s/ms) — heuristická konverze podle velikosti
    try:
        return detect_and_convert(float(text))
    except (ValueError, OverflowError):
        log.debug("iCloud Messages čas nerozpoznán: %r", value)
        return None


def _cell(row: list[str], idx: int | None) -> str | None:
    """Bezpečný přístup na buňku řádku (None index / krátký řádek → None)."""
    if idx is None or idx >= len(row):
        return None
    value = row[idx].strip()
    return value or None


def _rows_to_artifacts(rows: list[list[str]], headers: list[str]) -> list[Artifact]:
    """Data řádky → iMessage artifacty (čistá funkce, bez IO)."""
    text_col = _find_column(headers, _TEXT_ALIASES)
    date_col = _find_column(headers, _DATE_ALIASES)
    dir_col = _find_column(headers, _DIRECTION_ALIASES)
    handle_col = _find_column(headers, _HANDLE_ALIASES)

    # bez textového sloupce není co extrahovat (defenzivně — jiný layout exportu)
    if text_col is None:
        log.debug("iCloud Messages — žádný textový sloupec v hlavičce %r", headers)
        return []

    out: list[Artifact] = []
    for row in rows:
        if not any(cell.strip() for cell in row):  # prázdný řádek
            continue
        text = _cell(row, text_col) or ""
        ts = _parse_timestamp(_cell(row, date_col)) if date_col is not None else None
        out.append(
            Artifact(
                artifact_type="imessage",
                timestamp=ts,
                title=text[:300] or "(prázdná zpráva)",
                details={
                    "handle": _cell(row, handle_col),
                    "direction": _cell(row, dir_col),
                    "engine": "icloud_messages",
                },
            )
        )
    return out


def _find_header_row(lines: list[str]) -> tuple[int, str] | None:
    """První řádek s ≥2 známými sloupci → (index, delimiter).

    Apple export má nad hlavičkou metadata (RLEAPP používá pevný offset 6 —
    univerzálně to nefunguje), proto detekce obsahem. Delimiter se odvodí
    z kandidátského řádku (tab vs comma).
    """
    for i, line in enumerate(lines[:MAX_HEADER_SCAN_ROWS]):
        if not line.strip():
            continue
        tabs = line.count("\t")
        commas = line.count(",")
        delim = "\t" if tabs >= commas and tabs > 0 else ","
        try:
            cells = next(csv.reader(io.StringIO(line), delimiter=delim))
        except (csv.Error, StopIteration):
            continue
        norm = [_normalize_header(c) for c in cells]
        known = sum(1 for a in _TEXT_ALIASES + _DATE_ALIASES if a in norm)
        if known >= 2:
            return i, delim
    return None


def _extract_delimited_text(path: Path) -> list[Artifact]:
    """Delimited text (TSV/CSV) varianta exportu — stdlib csv, bez závislostí."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        log.warning("iCloud Messages čtení %s: %s", path, e)
        return []
    text = raw.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines()]
    found = _find_header_row(lines)
    if found is None:
        log.debug("iCloud Messages — hlavička nenalezena v %s", path.name)
        return []
    header_idx, delim = found
    try:
        parsed = list(csv.reader(io.StringIO("\n".join(lines[header_idx:])), delimiter=delim))
    except csv.Error as e:
        log.warning("iCloud Messages CSV parse %s: %s", path, e)
        return []
    if len(parsed) < 2:
        return []
    return _rows_to_artifacts(parsed[1:], parsed[0])


def _extract_xlsx(path: Path) -> list[Artifact]:
    """XLSX varianta exportu — openpyxl (volitelná závislost `[xlsx]`).

    iCloud export má XLSX obsah s příponou `.csv` → openpyxl odmítne cestu
    (kontroluje ext), proto čtení přes BytesIO (obsah, ne název).
    """
    try:
        from openpyxl import load_workbook  # lazy — volitelné extra
    except ImportError:
        log.debug("iCloud Messages XLSX — chybí openpyxl (extra [xlsx])")
        return []

    try:
        data = path.read_bytes()
    except OSError as e:
        log.warning("iCloud Messages XLSX čtení %s: %s", path, e)
        return []

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 — poškozený xlsx nesmí potopit pipeline
        log.warning("iCloud Messages XLSX open %s: %s", path, e)
        return []

    try:
        sheet = workbook.worksheets[0]
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            rows.append(cells)
    except Exception as e:  # noqa: BLE001 — read_only sheet může selhat na korupci
        log.warning("iCloud Messages XLSX čtení %s: %s", path, e)
        return []
    finally:
        workbook.close()

    if not rows:
        return []
    # hlavička = první řádek s ≥2 známými sloupci (metadata nad ní se přeskočí)
    for i, row in enumerate(rows[:MAX_HEADER_SCAN_ROWS]):
        norm = [_normalize_header(c) for c in row]
        known = sum(1 for a in _TEXT_ALIASES + _DATE_ALIASES if a in norm)
        if known >= 2:
            return _rows_to_artifacts(rows[i + 1 :], row)
    log.debug("iCloud Messages XLSX — hlavička nenalezena v %s", path.name)
    return []


def extract_icloud_messages(path: Path) -> list[Artifact]:
    """Extrahuje iCloud Messages zprávy (cloud varianta iMessage).

    Vrací Artifacty BEZ source_id/file_id (ty doplní pipeline). Rozhodnutí
    XLSX vs delimited text podle magic `PK\\x03\\x04` — název souboru už
    detekce potvrdil. Chyby → log + prázdný výsledek, nikdy ne výjimka nahoru.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError as e:
        log.warning("iCloud Messages čtení %s: %s", path, e)
        return []

    if head == b"PK\x03\x04":  # OOXML (xlsx) — i když má příponu .csv
        return _extract_xlsx(path)
    return _extract_delimited_text(path)
