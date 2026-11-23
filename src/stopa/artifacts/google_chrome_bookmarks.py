"""ETAPA B vlna 7 — Google Chrome Bookmarks parser (Takeout / warrant return).

AXIOM ekvivalenty: ``GoogleChromeBookmarksWarrantReturnArtifact`` +
``CloudGoogleChromeBookmarksArtifact``.

Podporovaný formát: **Chrome Bookmarks JSON** z Google Takeout nebo warrant
returnu — rekurzivní strom záložek::

    {"roots": {
        "bookmark_bar": {
            "children": [
                {"date_added": "13300000000000000", "id": "1",
                 "name": "Example", "type": "url", "url": "https://example.com"},
                {"children": [...], "date_added": "...", "id": "2",
                 "name": "Folder", "type": "folder"}
            ],
            "date_added": "...", "id": "0", "name": "Bookmarks bar", "type": "folder"
        },
        "other": {...}, "synced": {...}
    }}

   ``date_added`` = µs od Windows epochy 1601 (Chrome konvence). Jeden URL
   záznam = jeden artifact (``browser_bookmark``). Složky se procházejí
   rekurzivně; neznámé pole se ignoruje.

Detekce: **name-based** (``bookmarks``, ``chrome_bookmarks``) + content check
(JSON s ``roots``/``bookmark_bar`` klíči).

Artifact type: ``browser_bookmark`` — jedna záložka = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_chrome_micros
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_BOOKMARKS_PER_FILE = 5_000


@dataclass
class BookmarkRecord:
    """Jeden záznam Chrome Bookmarks (URL záložka)."""

    name: str = ""
    url: str = ""
    date_added_s: float | None = None
    folder_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _chrome_us_to_seconds(value: Any) -> float | None:
    """Chrome ``date_added`` (µs od 1601) → epoch sekundy."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    if v <= 0:
        return None
    try:
        dt = from_chrome_micros(v)
        return dt.timestamp()
    except ValueError:
        return None


def _walk_bookmarks(node: dict[str, Any], folder_path: str, records: list[BookmarkRecord]) -> None:
    """Rekurzivní procházení stromu záložek."""
    if len(records) >= MAX_BOOKMARKS_PER_FILE:
        return

    node_type = str(node.get("type", "")).strip().lower()
    name = str(node.get("name") or "").strip()
    url = str(node.get("url") or "").strip()
    date_added_s = _chrome_us_to_seconds(node.get("date_added"))

    if node_type == "url" and url:
        records.append(
            BookmarkRecord(
                name=name,
                url=url,
                date_added_s=date_added_s,
                folder_path=folder_path,
            )
        )
    elif node_type == "folder":
        # složka — pokračuj do children s rozšířenou cestou
        child_folder = f"{folder_path}/{name}" if name else folder_path
        for child in node.get("children", []):
            if isinstance(child, dict):
                _walk_bookmarks(child, child_folder, records)


def parse_chrome_bookmarks(data: bytes) -> list[BookmarkRecord]:
    """ČISTÝ parser — Chrome Bookmarks JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne objekt s ``roots``.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, dict):
        raise TypeError("Očekáván JSON objekt s 'roots'")

    roots = payload.get("roots")
    if not isinstance(roots, dict):
        # fallback — celý payload je plochý seznam záložek
        if isinstance(payload.get("children"), list):
            records: list[BookmarkRecord] = []
            for child in payload["children"]:
                if isinstance(child, dict):
                    _walk_bookmarks(child, "", records)
            return records
        raise TypeError("Chybí 'roots' objekt")

    records: list[BookmarkRecord] = []
    for root_name, root_node in roots.items():
        if not isinstance(root_node, dict):
            continue
        # kořenová složka — procházet její children
        folder_label = str(root_node.get("name", root_name)).strip()
        for child in root_node.get("children", []):
            if isinstance(child, dict):
                _walk_bookmarks(child, folder_label, records)

    return records


def is_chrome_bookmarks_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Chrome Bookmarks exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("bookmark", "chrome_bookmark")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith(b"{"):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b"roots", b"bookmark_bar", b"date_added")):
            return False
    return True


def build_bookmark_artifacts(records: list[BookmarkRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (browser_bookmark)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.name or r.url[:60] or "záložka"
        title = f"Chrome Bookmark: {label}"

        details: dict[str, Any] = {"engine": "chrome_bookmarks"}
        if r.name:
            details["name"] = r.name
        if r.url:
            details["url"] = r.url
        if r.folder_path:
            details["folder"] = r.folder_path

        ts = None
        if r.date_added_s is not None:
            from stopa.domain.times import from_unix

            ts = from_unix(r.date_added_s)

        artifacts.append(
            Artifact(
                artifact_type="browser_bookmark",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (r.url and r.name) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_bookmarks_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Chrome Bookmarks JSON → browser_bookmark artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ChromeBookmarks %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_chrome_bookmarks(data)
    except (ValueError, TypeError) as e:
        logger.debug("ChromeBookmarks %s: %s", path, e)
        return []

    return build_bookmark_artifacts(records)
