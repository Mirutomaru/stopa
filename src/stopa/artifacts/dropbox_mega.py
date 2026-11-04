"""ETAPA B vlna 13 — Dropbox + Mega cloud storage parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudDropboxArtifact`` + ``CloudMegaArtifact``
(``Magnet.Artifacts.Cloud.Dropbox.*`` / ``...Mega.*``) — soubory a metadata
z Dropbox a Mega cloud účtů.

Podporované formáty (defenzivní parsing, auto-detekce)::

    1. Dropbox (JSON list nebo wrapper)::

        [{"name": "report.pdf", "path_lower": "/docs/report.pdf",
          "bytes": 4096, "is_dir": false,
          "server_modified": "2024-10-05T10:00:00Z"}, ...]

    2. Mega (JSON list)::

        [{"name": "photo.jpg", "size": 2048, "type": "file",
          "modified": 1728136800}, ...]

Jeden záznam = jeden artifact (``document_metadata``,
``details.engine='dropbox_mega'``, ``kind='file'|'folder'``,
``provider='dropbox'|'mega'``). Neznámá pole se ignorují.

Detekce: **name-based** — dropbox/mega marker + klíčová slova; v dispatchi
pre-pass na celé cestě PŘED basename chainem (generic basenames kolidují s
ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class DropboxMegaRecord:
    """Jeden Dropbox/Mega záznam (soubor nebo složka)."""

    provider: str = "dropbox"  # dropbox | mega
    kind: str = "file"  # file | folder
    name: str | None = None
    size: int | None = None
    path: str | None = None
    modified_s: float | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na nezáporné celé číslo."""
    try:
        num = int(float(value))
    except (ValueError, TypeError):
        return None
    return num if num >= 0 else None


def _to_epoch(value: Any) -> float | None:
    """Tolerantní konverze času na epoch sekundy.

    Podporuje: int/float (sekundy i milisekundy), ISO 8601 stringy
    (s ``Z`` i offsetem). Neznámé tvary → None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        text = _to_str(value)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
    if abs(num) >= 10**12:
        num /= 1000.0
    return num if num > 0 else None


def _detect_provider(name: str, item: dict[str, Any]) -> str:
    """Určí provider podle cesty/názvu + tvaru položky."""
    lower = name.lower()
    if "mega" in lower:
        return "mega"
    if "dropbox" in lower:
        return "dropbox"
    # fallback podle klíčů (Dropbox API má path_lower/bytes, Mega size/type)
    if any(k in item for k in ("path_lower", "server_modified")):
        return "dropbox"
    return "mega"


def parse_dropbox_mega(data: bytes, provider_hint: str = "") -> list[DropboxMegaRecord]:
    """ČISTÝ parser — Dropbox/Mega JSON → záznamy.

    Args:
        data: Obsah souboru (JSON).
        provider_hint: Volitelný hint z cesty ("dropbox"/"mega"); prázdně = auto.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez Dropbox/Mega záznamů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[DropboxMegaRecord] = []

    def add_item(item: dict[str, Any], provider: str) -> None:
        name = _to_str(
            item.get("name", item.get("title", item.get("file_name")))
        )
        if not name:
            return
        is_dir_raw = item.get("is_dir")
        raw_type = (_to_str(item.get("type")) or "").lower()
        if isinstance(is_dir_raw, bool):
            kind = "folder" if is_dir_raw else "file"
        elif raw_type in ("folder", "dir"):
            kind = "folder"
        elif raw_type == "file":
            kind = "file"
        else:
            kind = "file"

        path = _to_str(
            item.get("path_lower", item.get("path", item.get("full_path")))
        )
        size = _to_int(item.get("bytes", item.get("size")))
        modified_s = _to_epoch(
            item.get("server_modified", item.get("modified", item.get("updated_at")))
        )

        records.append(
            DropboxMegaRecord(
                provider=provider,
                kind=kind,
                name=name,
                size=size if kind == "file" else None,
                path=path,
                modified_s=modified_s,
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("entries", "items", "files", "metadatas"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt s name — jeden záznam
        if not items and _to_str(payload.get("name")):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        provider = (
            provider_hint
            if provider_hint in ("dropbox", "mega")
            else _detect_provider("", item)
        )
        add_item(item, provider)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Dropbox/Mega záznamy")
    return records


def build_dropbox_mega_artifacts(
    records: list[DropboxMegaRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: z Dropbox/Mega záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "dropbox_mega",
            "provider": r.provider,
            "kind": r.kind,
        }
        if r.size is not None:
            details["size"] = r.size
        if r.path:
            details["path"] = r.path[:200]

        name = r.name or "(bez názvu)"
        kind_label = "Folder" if r.kind == "folder" else "File"
        ts = None
        if r.modified_s is not None:
            try:
                ts = from_unix(r.modified_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="document_metadata",
                timestamp=ts,
                title=f"{r.provider.capitalize()} {kind_label}: {name}"[:120],
                details=details,
                confidence=0.8 if r.name else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_dropbox_mega_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Dropbox/Mega JSON → document_metadata artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("DropboxMega %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    # provider hint z cesty (detektor už marker ověřil)
    lower = str(path).lower()
    hint = "dropbox" if "dropbox" in lower else ("mega" if "mega" in lower else "")

    try:
        records = parse_dropbox_mega(data, provider_hint=hint)
    except (ValueError, TypeError) as e:
        logger.debug("DropboxMega %s: %s", path.name, e)
        return []

    return build_dropbox_mega_artifacts(records)


def is_dropbox_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Dropbox cloud exportu.

    Vyžaduje ``dropbox`` marker v názvu/cestě — generic ``files.json`` bez
    markery nepadne, aby se nekradly cizí soubory.
    """
    lower = name.lower()
    if "dropbox" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True


def is_mega_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Mega cloud exportu.

    Vyžaduje ``mega`` marker v názvu/cestě — generic ``files.json`` bez
    markery nepadne, aby se nekradly cizí soubory.
    """
    lower = name.lower()
    if "mega" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
