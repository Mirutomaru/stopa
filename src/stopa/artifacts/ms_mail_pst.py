"""ETAPA B vlna 12 — Microsoft Mail (PST) parser (cloud export / warrant return).

AXIOM ekvivalent: ``CloudMicrosoftMailPstArtifact``
(``Magnet.Artifacts.Cloud.Microsoft.Mail.*``) — e-maily z Outlook PST /
Outlook.com účtu.

Podporovaný formát: **JSON export poštovní schránky** (defenzivní parsing)::

    [{"subject": "Re: faktura", "from": "sender@example.com",
      "to": ["me@example.com"], "body": "text zprávy",
      "sentDateTime": "2024-10-03T12:00:00Z"}]

   nebo warrant return s alternativními klíči::

    {"messages": [{"sender": "...", "recipient": "...", "content": "...",
                   "date": 1727956800}]}

Jeden e-mail = jeden artifact (``email_message``, ``details.engine='ms_mail_pst'``).
Neznámá pole se ignoruje.

Detekce: **name-based** — Microsoft marker + klíčová slova pošty; v dispatchi
pre-pass na celé cestě PŘED basename chainem (generic basenames kolidují s
Google Mail Message Information detektorem).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 5_000


@dataclass
class MsMailRecord:
    """Jeden e-mail z Microsoft poštovní schránky."""

    subject: str | None = None
    sender: str | None = None
    recipients: list[str] = field(default_factory=list)
    body: str | None = None
    timestamp_s: float | None = None


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


def parse_ms_mail_pst(data: bytes) -> list[MsMailRecord]:
    """ČISTÝ parser — Microsoft mail JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez zpráv.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[MsMailRecord] = []

    def add(item: dict[str, Any]) -> None:
        subject = _to_str(
            item.get("subject", item.get("title"))
        )
        sender = _to_str(
            item.get("from", item.get("sender", item.get("fromAddress")))
        )
        recipients: list[str] = []
        for raw in _as_list(
            item.get("to", item.get("recipients", item.get("recipient")))
        ):
            if isinstance(raw, dict):
                addr = _to_str(raw.get("address", raw.get("email")))
            else:
                addr = _to_str(raw)
            if addr:
                recipients.append(addr)
        body = _to_str(
            item.get("body", item.get("content", item.get("text")))
        )
        ts_s = _to_epoch(
            item.get(
                "sentDateTime",
                item.get("date", item.get("timestamp", item.get("receivedDateTime"))),
            )
        )
        if not subject and not sender and not body:
            return
        records.append(
            MsMailRecord(
                subject=subject,
                sender=sender,
                recipients=recipients,
                body=body,
                timestamp_s=ts_s,
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("messages", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                items = [x for x in val if isinstance(x, dict)]
                break
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_MESSAGES_PER_FILE]:
        add(item)

    records = records[:MAX_MESSAGES_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Microsoft e-maily")
    return records


def build_ms_mail_artifacts(records: list[MsMailRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z e-mailů vytvoří artifacty (email_message)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "ms_mail_pst"}
        if r.sender:
            details["from"] = r.sender
        if r.recipients:
            details["to"] = r.recipients
        if r.body:
            details["body"] = r.body[:500]

        title = f"Microsoft Mail: {r.subject or '(bez předmětu)'}"
        ts = None
        if r.timestamp_s is not None:
            try:
                ts = from_unix(r.timestamp_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="email_message",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if r.subject else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_ms_mail_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Microsoft mail JSON → email_message artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MsMailPst %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_ms_mail_pst(data)
    except (ValueError, TypeError) as e:
        logger.debug("MsMailPst %s: %s", path.name, e)
        return []

    return build_ms_mail_artifacts(records)


def is_ms_mail_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Microsoft mail exportu.

    Vyžaduje Microsoft marker (``microsoft``/``outlook``) v názvu/cestě +
    klíčová slova pošty — generic ``messages.json`` bez markery nepadne,
    aby se nekradl Google Mail Message Information.
    """
    lower = name.lower()
    if not any(k in lower for k in ("microsoft", "outlook")):
        return False
    if not any(k in lower for k in ("mail", "pst", "message", "email")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
