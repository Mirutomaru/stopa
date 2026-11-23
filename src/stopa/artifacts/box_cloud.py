"""ETAPA B vlna 13 — Box Cloud parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudBoxFilesArtifact`` + ``CloudBoxEnterpriseEventArtifact`` +
``CloudBoxUserEventAuditArtifact`` (``Magnet.Artifacts.Cloud.Box.*``) — soubory,
složky a audit/enterprise eventy z Box cloud storage.

Podporované formáty (defenzivní parsing, auto-detekce)::

    1. Soubory / složky (JSON list nebo wrapper)::

        [{"id": "123", "name": "report.pdf", "size": 4096,
          "type": "file", "path_collection": {"paths": [
              {"id": "1", "name": "root"}, {"id": "2", "name": "docs"}]},
          "created_at": "2024-10-03T09:00:00Z",
          "modified_at": "2024-10-05T10:00:00Z"}, ...]

    2. Audit / enterprise eventy::

        [{"event_type": "file.upload",
          "actor": {"name": "Jan Novák"},
          "created_at": "2024-10-06T08:00:00Z",
          "record_name": "report.pdf"}, ...]

Jeden záznam = jeden artifact (``document_metadata``,
``details.engine='box_cloud'``, ``kind='file'|'folder'|'event'``).
Neznámá pole se ignorují.

Detekce: **name-based** — Box marker + klíčová slova; v dispatchi pre-pass
na celé cestě PŘED basename chainem (generic basenames kolidují s ostatními
detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class BoxCloudRecord:
    """Jeden Box záznam (soubor, složka, komentář nebo event)."""

    kind: str = "file"  # file | folder | comment | event
    name: str | None = None
    size: int | None = None
    path: str | None = None
    created_s: float | None = None
    modified_s: float | None = None
    author: str | None = None
    message: str | None = None
    action: str | None = None  # event: akce (file.upload, item.trash, ...)


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


def _box_path(item: dict[str, Any]) -> str | None:
    """Rekonstruuje cestu z ``path_collection`` (Box API tvar)."""
    pc = item.get("path_collection")
    if isinstance(pc, dict):
        paths = pc.get("paths")
        if isinstance(paths, list) and paths:
            parts = [p.get("name") for p in paths if isinstance(p, dict)]
            parts = [_to_str(x) for x in parts]
            parts = [x for x in parts if x]
            if len(parts) > 1:
                return "/".join(parts[:-1]) or None
    direct = _to_str(item.get("path", item.get("folder_path")))
    return direct


def parse_box_cloud(data: bytes) -> list[BoxCloudRecord]:
    """ČISTÝ parser — Box JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez Box záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[BoxCloudRecord] = []

    def add_item(item: dict[str, Any]) -> None:
        # audit / enterprise event (Box API tvar s event_type)
        action = _to_str(
            item.get("event_type", item.get("action", item.get("type_of_event")))
        )
        if action and "comment" not in action.lower():
            actor_obj = item.get("actor") or item.get("created_by")
            author = None
            if isinstance(actor_obj, dict):
                author = _to_str(
                    actor_obj.get("name", actor_obj.get("login"))
                )
            records.append(
                BoxCloudRecord(
                    kind="event",
                    name=_to_str(
                        item.get("record_name") or item.get("item_name")
                    ),
                    created_s=_to_epoch(
                        item.get("created_at", item.get("created"))
                    ),
                    author=author,
                    action=action,
                )
            )
            return

        name = _to_str(
            item.get("name", item.get("title", item.get("file_name")))
        )
        raw_type = _to_str(item.get("type")) or ""
        is_comment = "comment" in raw_type.lower() or (
            _to_str(item.get("message")) is not None and name is None
        )
        if is_comment:
            author_obj = item.get("created_by")
            author = None
            if isinstance(author_obj, dict):
                author = _to_str(
                    author_obj.get("name", author_obj.get("login"))
                )
            records.append(
                BoxCloudRecord(
                    kind="comment",
                    name=name or _to_str(item.get("item_name")),
                    created_s=_to_epoch(
                        item.get("created_at", item.get("created"))
                    ),
                    author=author,
                    message=_to_str(item.get("message", item.get("text"))),
                )
            )
            return

        kind = "folder" if raw_type.lower() == "folder" else "file"
        records.append(
            BoxCloudRecord(
                kind=kind,
                name=name,
                size=_to_int(item.get("size", item.get("bytes"))),
                path=_box_path(item),
                created_s=_to_epoch(
                    item.get("created_at", item.get("created"))
                ),
                modified_s=_to_epoch(
                    item.get("modified_at", item.get("updated_at"))
                ),
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("entries", "items", "files", "folders", "events"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt s id+name — jeden záznam
        if not items and any(k in payload for k in ("id", "name")):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        add_item(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Box cloud záznamy")
    return records


def build_box_artifacts(records: list[BoxCloudRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z Box záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "box_cloud",
            "kind": r.kind,
        }
        if r.size is not None:
            details["size"] = r.size
        if r.path:
            details["path"] = r.path[:200]
        if r.author:
            details["author"] = r.author
        if r.message:
            details["message"] = r.message[:500]
        if r.action:
            details["action"] = r.action

        name = r.name or "(bez názvu)"
        kind_label = {"file": "File", "folder": "Folder"}.get(r.kind, "Event")
        ts = None
        anchor = r.created_s or r.modified_s
        if anchor is not None:
            try:
                ts = from_unix(anchor)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="document_metadata",
                timestamp=ts,
                title=f"Box {kind_label}: {name}"[:120],
                details=details,
                confidence=0.8 if r.name else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_box_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Box JSON → document_metadata artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("BoxCloud %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_box_cloud(data)
    except (ValueError, TypeError) as e:
        logger.debug("BoxCloud %s: %s", path.name, e)
        return []

    return build_box_artifacts(records)


def is_box_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Box cloud exportu.

    Vyžaduje ``box`` marker v názvu/cestě + klíčová slova files/folders/
    comments — generic ``files.json`` bez markery nepadne, aby se nekradly
    cizí soubory.
    """
    lower = name.lower()
    if "box" not in lower:
        return False
    if not any(k in lower for k in ("file", "folder", "comment", "item", "event")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
