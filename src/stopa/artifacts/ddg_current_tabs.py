"""ETAPA B vlna 2 — DuckDuckGo Current Tabs parser (lokální profil).

AXIOM ekvivalent: ``CurrentTabsArtifact``
(``Magnet.Artifacts.DuckDuckGo.CurrentTabs.CurrentTabsArtifact``) — aktuálně
otevřené záložky DuckDuckGo prohlížeče.

Podporovaný formát: **JSON** se stavem relace (``current_tabs.json``,
``tabs.json``)::

    [{"title": "Wikipedie", "url": "https://cs.wikipedia.org/", ...}]

nebo jednoduchý text — jeden URL na řádek (export seznamu záložek).

Detekce: **name-based** (``current_tabs``, ``ddg.*tabs``, ``tabs.json``)
+ content check. JSON nemá magic bytes.

Artifact type: ``browser_tab`` — jedna otevřená záložka = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_TABS_PER_FILE = 2_000


@dataclass
class BrowserTab:
    """Jedna otevřená záložka."""

    title: str = ""
    url: str = ""


def parse_current_tabs_json(data: bytes) -> list[BrowserTab]:
    """ČISTÝ parser — JSON pole záložek → taby.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole záložek.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole záložek")

    tabs: list[BrowserTab] = []
    for item in payload[:MAX_TABS_PER_FILE]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url:
            continue
        tabs.append(BrowserTab(title=title, url=url))

    return tabs


def parse_current_tabs_text(data: bytes) -> list[BrowserTab]:
    """ČISTÝ parser — text (jeden URL na řádek) → taby.

    Raises:
        ValueError: Žádný platný URL nenalezen.
    """
    tabs: list[BrowserTab] = []
    seen: set[str] = set()
    for line in data.decode("utf-8", errors="replace").splitlines():
        url = line.strip()
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen or len(tabs) >= MAX_TABS_PER_FILE:
            continue
        seen.add(url)
        tabs.append(BrowserTab(title="", url=url))

    if not tabs:
        raise ValueError("Žádný platný URL nenalezen")

    return tabs


def is_current_tabs_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Current Tabs exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("current_tabs", "currenttabs", "ddg")) and "tabs.json" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        markers = (b"url", b"title", b"http://", b"https://")
        if not any(m in h for m in markers):
            return False
    return True


def build_tab_artifacts(tabs: list[BrowserTab]) -> list[Artifact]:
    """ČISTÁ funkce: ze záložek vytvoří artifacty (browser_tab)."""
    artifacts: list[Artifact] = []
    for t in tabs:
        title = t.title or t.url
        details: dict[str, Any] = {
            "engine": "ddg_current_tabs",
            "title": t.title,
            "url": t.url,
        }
        artifacts.append(
            Artifact(
                artifact_type="browser_tab",
                timestamp=None,  # snapshot otevřených záložek nemá čas
                title=f"Open tab: {title[:100]}",
                details=details,
                confidence=0.8 if t.title else 0.7,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_current_tabs_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Current Tabs → browser_tab artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("CurrentTabs %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    head = data[:2048].lstrip().lower()
    tabs: list[BrowserTab] = []
    try:
        if head.startswith(b"["):
            tabs = parse_current_tabs_json(data)
        else:
            tabs = parse_current_tabs_text(data)
    except (ValueError, TypeError) as e:
        logger.debug("CurrentTabs %s: %s", path, e)
        return []

    return build_tab_artifacts(tabs)
