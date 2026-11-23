"""ETAPA B vlna 7 — Google Chrome History Warrant Return parser.

AXIOM ekvivalent: ``GoogleChromeHistoryWarrantReturnArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.GoogleChromeHistory.*``).

Podporovaný formát: **Chrome History warrant return JSON** — pole záznamů
navštívených URL (ekvivalent tabulky ``urls`` + ``visits``)::

    [{"url": "https://example.com", "title": "Example Domain",
      "visit_time": "13300000000000000", "from_visit": 0,
      "transition_type": 80530640}, ...]

   ``visit_time`` = µs od Windows epochy 1601 (Chrome konvence). Jeden záznam
   = jeden artifact (``browser_history``) — konzistentní s lokálním Chrome
   parserem (``sqlite_extract``), aby se propojilo do browser view.

Detekce: **name-based** (``chrome_history``, ``history.json`` v Chrome kontextu)
+ content check (JSON s ``visit_time``/``url`` klíči).

Artifact type: ``browser_history`` — jedna návštěva = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_chrome_micros, from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class ChromeHistoryRecord:
    """Jeden záznam Chrome History warrant returnu."""

    url: str = ""
    title: str = ""
    visit_time_s: float | None = None
    transition_type: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _chrome_us_to_seconds(value: Any) -> float | None:
    """Chrome ``visit_time`` (µs od 1601) → epoch sekundy."""
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


def parse_chrome_history_wr(data: bytes) -> list[ChromeHistoryRecord]:
    """ČISTÝ parser — Chrome History warrant return JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole/objekt se záznamy.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if isinstance(payload, dict):
        for key in ("history", "visits", "records", "items"):
            v = payload.get(key)
            if isinstance(v, list):
                payload = v
                break
        else:
            # jediný objekt s history klíči → zabal do pole
            if any(k in payload for k in ("visit_time", "url")):
                payload = [payload]
    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole history záznamů")

    records: list[ChromeHistoryRecord] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue

        url = str(item.get("url", item.get("URL")) or "").strip()
        title = str(item.get("title", item.get("Title") or "").strip())
        visit_time_s = _chrome_us_to_seconds(
            item.get("visit_time", item.get("VisitTime", item.get("timestamp")))
        )

        transition: int | None = None
        tt_raw = item.get("transition_type", item.get("TransitionType"))
        if isinstance(tt_raw, (int, float)) and not isinstance(tt_raw, bool):
            transition = int(tt_raw)

        extra: dict[str, Any] = {}
        for key in ("from_visit", "id"):
            v = item.get(key)
            if isinstance(v, (int, str)):
                extra[key] = v

        records.append(
            ChromeHistoryRecord(
                url=url,
                title=title,
                visit_time_s=visit_time_s,
                transition_type=transition,
                extra=extra,
            )
        )
    return records


def is_chrome_history_wr_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Chrome History warrant returnu."""
    lower = name.lower()
    if not any(k in lower for k in ("chrome_history", "history")):
        return False
    # vyhnout se kolizi s lokálním Chrome History DB (SQLite) — ten má .db ext
    if lower.endswith((".db", ".sqlite", ".sqlite3")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"[", b"{")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b"visit_time", b"url")):
            return False
    return True


def build_chrome_history_artifacts(records: list[ChromeHistoryRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (browser_history)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.title or r.url[:60] or "návštěva"
        title = f"Chrome History: {label}"

        details: dict[str, Any] = {"engine": "chrome_history_wr"}
        if r.url:
            details["url"] = r.url
        if r.title:
            details["title"] = r.title
        if r.transition_type is not None:
            details["transition_type"] = r.transition_type
        if r.extra:
            details.update(r.extra)

        ts = from_unix(r.visit_time_s) if r.visit_time_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="browser_history",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (r.url and r.visit_time_s is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_chrome_history_wr_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Chrome History WR JSON → browser_history artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ChromeHistoryWR %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_chrome_history_wr(data)
    except (ValueError, TypeError) as e:
        logger.debug("ChromeHistoryWR %s: %s", path, e)
        return []

    return build_chrome_history_artifacts(records)
