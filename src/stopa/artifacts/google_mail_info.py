"""ETAPA B vlna 6 — Google Mail Message Information parser (lokální profil / takeout).

AXIOM ekvivalent: ``GoogleMailMessageInformationArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.GoogleMailMessageInformation.
GoogleMailMessageInformationArtifact``).

Podporovaný formát: **JSON metadata poštovních zpráv** z Google Takeout „Gmail"
exportu nebo warrant returnu — pole záznamů s identitou a časem zprávy::

    [{"threadId": "abc123",
      "internalDate": "1705314600000000",
      "from": {"emailAddress": "sender@example.com"},
      "to": [{"emailAddress": "rcpt@example.com"}],
      "subject": "Re: Schůzka", "snippet": "Text zprávy…"}, ...]

   Jeden záznam = jeden artifact (``google_mail_info``). ``internalDate`` je µs
   od Unix epochy (Gmail konvence); podporuje se i ISO 8601 / s / ms. Odesílatel
   a příjemci mohou být plain string NEBO objekt ``{"emailAddress": ...}``.

Detekce: **name-based** (``gmail``, ``mail_message_information``,
``messages.json``) + content check (JSON s threadId/internalDate klíči).

Artifact type: ``google_mail_info`` — jedna zpráva = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class MailInfoRecord:
    """Jeden záznam Google Mail Message Information metadata."""

    thread_id: str = ""
    subject: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    snippet: str = ""
    timestamp_s: float | None = None


def _parse_gmail_date(value: Any) -> float | None:
    """Gmail čas → epoch sekundy.

    ``internalDate`` je µs od Unix epochy; tolerantně podporuje i ISO 8601,
    epoch s a ms. Neplatné → None (nikdy výjimka).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # µs od epochy má ~16–19 cifr; ms ~13; s ~10
        if abs(v) > 1e14:
            return v / 1_000_000.0
        if abs(v) > 1e12:
            return v / 1_000.0
        return v
    text = str(value).strip()
    if not text:
        return None
    digits = text.replace(".", "", 1).lstrip("-")
    if digits.isdigit():
        try:
            v = float(text)
        except ValueError:
            return None
        if abs(v) > 1e14:
            return v / 1_000_000.0
        if abs(v) > 1e12:
            return v / 1_000.0
        return v
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _addr(value: Any) -> str:
    """E-mailová adresa z plain stringu NEBO objektu ``{"emailAddress": ...}``."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("emailAddress", "address", "value"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _addrs(value: Any) -> list[str]:
    """Seznam adres z pole / stringu / objektů (tolerantní)."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        a = _addr(item)
        if a and a not in out:
            out.append(a)
    return out


def parse_mail_info(data: bytes) -> list[MailInfoRecord]:
    """ČISTÝ parser — Mail Message Information JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole/objekt se záznamy.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if isinstance(payload, dict):
        for key in ("messages", "items", "records", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                payload = v
                break
        else:
            # jediný objekt s mail klíči → zabal do pole
            if any(k in payload for k in ("threadId", "internalDate", "subject")):
                payload = [payload]
    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole zpráv")

    records: list[MailInfoRecord] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue

        thread_id = str(item.get("threadId", item.get("id") or "")).strip()
        subject = str(item.get("subject") or "").strip()
        sender = _addr(item.get("from"))
        recipients = _addrs(item.get("to")) + [
            a for a in _addrs(item.get("cc")) if a not in _addrs(item.get("to"))
        ]
        snippet = str(item.get("snippet", item.get("body") or "")).strip()[:500]

        ts_raw: Any = item.get("internalDate", item.get("timestamp", item.get("date")))
        ts_s = _parse_gmail_date(ts_raw)

        records.append(
            MailInfoRecord(
                thread_id=thread_id,
                subject=subject,
                sender=sender,
                recipients=recipients,
                snippet=snippet,
                timestamp_s=ts_s,
            )
        )
    return records


def is_mail_info_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Mail Message Information exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("mail_message_information", "gmail")) and not (
        lower.endswith(".json") and "messages" in lower
    ):
        return False
    # content check — JSON s mail klíči (ne binární / jiný export)
    if head:
        h = head[:2048].lstrip()
        if not h.startswith((b"[", b"{")):
            return False
        joined = head[:2048]
        if not any(k in joined for k in (b"threadId", b"internalDate")):
            return False
    return True


def build_mail_info_artifacts(records: list[MailInfoRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (google_mail_info)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.subject or "(bez předmětu)"
        title = f"Google Mail: {label}"

        details: dict[str, Any] = {"engine": "google_mail_info"}
        if r.thread_id:
            details["thread_id"] = r.thread_id
        if r.sender:
            details["from"] = r.sender
        if r.recipients:
            details["to"] = r.recipients
        if r.snippet:
            details["snippet"] = r.snippet

        ts = from_unix(r.timestamp_s) if r.timestamp_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_mail_info",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (r.thread_id and r.timestamp_s is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_mail_info_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Mail Message Information JSON → google_mail_info."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GoogleMailInfo %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_mail_info(data)
    except (ValueError, TypeError) as e:
        logger.debug("GoogleMailInfo %s: %s", path, e)
        return []

    return build_mail_info_artifacts(records)
