"""ETAPA B vlna 2 — Google Search History parser (lokální profil / Takeout).

AXIOM ekvivalent: ``GoogleSearchHistoryArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.GoogleSearchHistoryArtifact``).

Podporovaný formát: **JSON export** z My Activity / Google Takeout
(``My Activity.json``, ``search_history.json``) — pole objektů::

    [{"key": "webSearch",
      "time": {"timestamp": "1625097600", "displayTime": "..."},
      "title": "hledaný dotaz",
      "url": "https://www.google.com/search?q=..."}]

Detekce: **name-based** (``my activity``, ``search_history``,
``searchhistory``) + content check (JSON pole s klíčem ``webSearch``/``title``).

Artifact type: ``google_search`` — jeden dotaz = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class GoogleSearchEntry:
    """Jeden záznam Google Search History."""

    query: str = ""
    timestamp: int | None = None
    display_time: str = ""
    url: str = ""
    key: str = ""


def _to_int(value: Any) -> int | None:
    """Timestamp pole (int/str/float) → epoch sekundy; neplatné → None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def parse_google_search_history(data: bytes) -> list[GoogleSearchEntry]:
    """ČISTÝ parser — Google Search History JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole záznamů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole záznamů")

    entries: list[GoogleSearchEntry] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        time_obj = item.get("time") or {}
        ts_raw = time_obj.get("timestamp") if isinstance(time_obj, dict) else None
        display = str(time_obj.get("displayTime", "")) if isinstance(time_obj, dict) else ""

        query = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        key = str(item.get("key") or "").strip()

        # bez dotazu i URL to není search záznam (jiný typ aktivity)
        if not query and not url:
            continue

        entries.append(
            GoogleSearchEntry(
                query=query,
                timestamp=_to_int(ts_raw),
                display_time=display,
                url=url,
                key=key,
            )
        )

    return entries


def is_google_search_history_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Search History exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("my activity", "search_history", "searchhistory")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not (h.startswith(b"[") or b"webservice" in h or b"title" in h):
            return False
    return True


def build_google_search_artifacts(entries: list[GoogleSearchEntry]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (google_search)."""
    artifacts: list[Artifact] = []
    for e in entries:
        title = e.query or e.url or "(prázdný dotaz)"
        details: dict[str, Any] = {
            "engine": "google_takeout",
            "query": e.query,
            "url": e.url,
            "key": e.key,
        }
        if e.display_time:
            details["display_time"] = e.display_time

        artifacts.append(
            Artifact(
                artifact_type="google_search",
                timestamp=from_unix(e.timestamp) if e.timestamp is not None else None,
                title=f"Google search: {title[:120]}",
                details=details,
                confidence=0.9 if e.query else 0.75,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_google_search_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Search History JSON → google_search artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GoogleSearch %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        entries = parse_google_search_history(data)
    except (ValueError, TypeError) as e:
        logger.debug("GoogleSearch %s: %s", path, e)
        return []

    return build_google_search_artifacts(entries)
