"""ETAPA B vlna 12 — SharePoint parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudSharePointContentArtifact``,
``CloudSharePointDocumentsArtifact``, ``CloudSharePointSitePagesArtifact``
(``Magnet.Artifacts.Cloud.SharePoint.*``) — obsah, dokumenty a stránky
webů z Microsoft SharePoint.

Podporovaný formát: **JSON export** s auto-detekcí sekcí (defenzivní)::

    Dokumenty/soubory → ``cloud_file``::

        [{"name": "smlouva.pdf", "size": 1024,
          "url": "https://corp.sharepoint.com/..."}]

    Webové stránky → ``web_page``::

        {"pages": [{"title": "Domů", "content": "...",
                    "url": "https://corp.sharepoint.com/sites/x"}]}

Jeden záznam = jeden artifact (``details.engine='sharepoint_wr'``,
``mimetype='ms:sharepoint'``). Neznámá pole se ignoruje.

Detekce: **name-based** — SharePoint marker v názvu/cestě; v dispatchi
pre-pass na celé cestě PŘED basename chainem (generic basenames
``Documents.json`` / ``Pages.json`` kolidují s ostatními detektory).
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
class SharePointItem:
    """Jeden SharePoint záznam (dokument/soubor nebo webová stránka)."""

    kind: str  # "document" | "page"
    name: str | None = None
    url: str | None = None
    size_bytes: int | None = None
    modified_s: float | None = None
    content: str | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    """Normalizuje pole / scalar / None na list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na non-negative int."""
    try:
        num = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
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


def parse_sharepoint(data: bytes) -> list[SharePointItem]:
    """ČISTÝ parser — SharePoint JSON → záznamy (auto-detekce sekcí).

    Rozpozná dokumenty/soubory i webové stránky; sekce se hledají v
    top-level klíčích (``documents``, ``files``, ``pages``, ``value``,
    ``items``) i v plochém seznamu.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez SharePoint záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items: list[SharePointItem] = []

    def add_document(item: dict[str, Any]) -> None:
        name = _to_str(
            item.get("name", item.get("fileName", item.get("title")))
        )
        url = _to_str(item.get("url", item.get("webUrl", item.get("link"))))
        size = _to_int(
            item.get("size", item.get("fileSize", item.get("length")))
        )
        modified_s = _to_epoch(
            item.get(
                "lastModifiedDateTime",
                item.get("modified", item.get("lastModified")),
            )
        )
        if not name and not url:
            return
        items.append(
            SharePointItem(
                kind="document",
                name=name,
                url=url,
                size_bytes=size,
                modified_s=modified_s,
            )
        )

    def add_page(item: dict[str, Any]) -> None:
        title = _to_str(item.get("title", item.get("name")))
        content = _to_str(
            item.get("content", item.get("body", item.get("html")))
        )
        url = _to_str(item.get("url", item.get("webUrl", item.get("link"))))
        modified_s = _to_epoch(
            item.get("lastModifiedDateTime", item.get("modified"))
        )
        if not title and not content:
            return
        items.append(
            SharePointItem(
                kind="page",
                name=title,
                url=url,
                content=content,
                modified_s=modified_s,
            )
        )

    def handle(obj: Any) -> None:
        if isinstance(obj, dict):
            # explicitní sekce stránky?
            pages = obj.get("pages") or obj.get("sitePages")
            if isinstance(pages, list):
                for p in pages:
                    if isinstance(p, dict):
                        add_page(p)
            docs = (
                obj.get("documents")
                or obj.get("files")
                or obj.get("items")
                or obj.get("value")
            )
            if isinstance(docs, list):
                for d in docs:
                    if isinstance(d, dict):
                        add_document(d)
            elif any(
                k in obj
                for k in ("name", "fileName", "title", "url", "webUrl")
            ):
                # samotný dokument / stránka
                if _to_str(obj.get("content", obj.get("body"))):
                    add_page(obj)
                else:
                    add_document(obj)
        elif isinstance(obj, list):
            for item in obj:
                handle(item)

    handle(payload)

    items = items[:MAX_ITEMS_PER_FILE]
    if not items:
        raise TypeError("Nenalezeny SharePoint záznamy")
    return items


def build_sharepoint_artifacts(items: list[SharePointItem]) -> list[Artifact]:
    """ČISTÁ funkce: ze SharePoint záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for it in items:
        details: dict[str, Any] = {
            "engine": "sharepoint_wr",
            "mimetype": "ms:sharepoint",
        }
        if it.url:
            details["url"] = it.url
        ts = None
        if it.modified_s is not None:
            try:
                ts = from_unix(it.modified_s)
            except ValueError:
                ts = None

        if it.kind == "page":
            if it.content:
                details["content"] = it.content[:500]
            title = f"SharePoint Page: {it.name or '(bez názvu)'}"
            artifacts.append(
                Artifact(
                    artifact_type="web_page",
                    timestamp=ts,
                    title=title[:120],
                    details=details,
                    confidence=0.8 if it.content else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )
        else:
            if it.size_bytes is not None:
                details["size"] = it.size_bytes
            title = f"SharePoint Document: {it.name or '(bez názvu)'}"
            artifacts.append(
                Artifact(
                    artifact_type="cloud_file",
                    timestamp=ts,
                    title=title[:120],
                    details=details,
                    confidence=0.8 if it.size_bytes is not None else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )
    return artifacts


def extract_sharepoint_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — SharePoint JSON → cloud_file/web_page artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("SharePoint %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        items = parse_sharepoint(data)
    except (ValueError, TypeError) as e:
        logger.debug("SharePoint %s: %s", path.name, e)
        return []

    return build_sharepoint_artifacts(items)


def is_sharepoint_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce SharePoint exportu.

    Vyžaduje ``sharepoint`` marker v názvu/cestě — generic
    ``Documents.json`` / ``Pages.json`` bez markery nepadnou, aby se
    nekradly cizí dokumenty.
    """
    lower = name.lower()
    if "sharepoint" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
