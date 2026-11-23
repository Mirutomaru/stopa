"""ETAPA B vlna 14 — Gmail Messages cloud parser (cloud export / warrant return).

AXIOM ekvivalent: ``CloudGmailMessagesArtifact``
(``Magnet.Artifacts.Cloud.Gmail.Messages*``) — e-mailové zprávy z Gmail cloud
exportů (warrant return / Takeout).

Podporovaný formát (defenzivní parsing)::

    [{"subject": "Re: faktura", "from": "a@b.cz", "to": ["c@d.cz"],
      "cc": [], "body": "...", "date": "2024-10-05T10:00:00Z"}, ...]

    nebo wrapper ``{"messages": [...]}``.

Jeden záznam = jeden artifact (``artifact_type='email_message'``,
``details.engine='gmail_messages_cloud'``). Neznámá pole se ignorují.

Detekce: **name-based** — gmail marker + klíčová slova; v dispatchi pre-pass na
celé cestě PŘED basename chainem (generic basenames kolidují s ostatními
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
class GmailMessageRecord:
    """Jeden Gmail cloud e-mail (normalizovaná data)."""

    subject: str | None = None
    sender: str | None = None
    recipient: str | None = None
    cc: str | None = None
    body: str | None = None
    created_s: float | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(*values: Any) -> str | None:
    """První non-empty string z řetězce kandidátů."""
    for v in values:
        s = _to_str(v)
        if s:
            return s
    return None


def _list_of_str(value: Any) -> list[str]:
    """Tolerantní konverze na seznam non-empty stringů."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            s = _to_str(item)
            if s:
                out.append(s)
        return out
    # dict (např. {"value": "x"}) — vezmi 'value'/'address'
    if isinstance(value, dict):
        for key in ("value", "address"):
            s = _to_str(value.get(key))
            if s:
                return [s]
    return []


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


def parse_gmail_messages(data: bytes) -> list[GmailMessageRecord]:
    """ČISTÝ parser — Gmail cloud JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez e-mailových zpráv.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[GmailMessageRecord] = []

    def add_message(item: dict[str, Any]) -> None:
        subject = _to_str(item.get("subject"))
        sender = _first_str(
            item.get("from"), item.get("sender"), item.get("From")
        )
        recipients = _list_of_str(item.get("to", item.get("recipients")))
        cc = _list_of_str(item.get("cc"))
        body = _to_str(item.get("body", item.get("textBody")))
        records.append(
            GmailMessageRecord(
                subject=subject,
                sender=sender,
                recipient=", ".join(recipients)[:200] or None,
                cc=(", ".join(cc)[:200] if cc else None),
                body=(body[:500] if body else None),
                created_s=_to_epoch(item.get("date", item.get("sentDate"))),
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("messages", "entries", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt — jedna zpráva
        if not items and any(
            k in payload for k in ("subject", "from", "body")
        ):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        add_message(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Gmail cloud zprávy")
    return records


def build_gmail_artifacts(records: list[GmailMessageRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z Gmail cloud zpráv vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "gmail_messages_cloud"}

        ts = None
        if r.created_s is not None:
            try:
                ts = from_unix(r.created_s)
            except ValueError:
                ts = None

        title = f"Gmail e-mail: {r.subject or '(bez předmětu)'}"[:120]
        if r.sender:
            details["sender"] = r.sender
        if r.recipient:
            details["recipient"] = r.recipient
        if r.cc:
            details["cc"] = r.cc
        if r.body:
            details["body"] = r.body[:500]

        artifacts.append(
            Artifact(
                artifact_type="email_message",
                timestamp=ts,
                title=title,
                details=details,
                confidence=0.85 if (r.subject and r.sender) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_gmail_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Gmail cloud JSON → artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GmailCloud %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_gmail_messages(data)
    except (ValueError, TypeError) as e:
        logger.debug("GmailCloud %s: %s", path.name, e)
        return []

    return build_gmail_artifacts(records)


def is_gmail_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Gmail cloud exportu.

    Vyžaduje gmail marker v názvu/cestě — generic ``messages.json`` bez markery
    nepadne, aby se nekradly cizí soubory.
    """
    lower = name.lower()
    if "gmail" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
